"""grok-quota 带着走「最近一次真发出请求」与「最近一次请求失败」（2026-10-23 诊断缺口）。

起因：10-23 09:06 grok 续了 token（有效到 15:06），这 6 小时里一次成功读数都没有，sidecar 里只剩最后那次
`token_expired` —— 是「根本没发请求」还是「发了但失败」，事后分不出来。现在：
- 真发了请求 ⇒ 记 `last_sent_at`；失败 ⇒ 记 `last_fail`（原因 / 详情 / HTTP 码 / 时刻）。
- 没发请求的轮次（本地已过期 / 429 退避）**不覆盖**它们，从上一份 sidecar 带过来。
- 采样器比 sidecar 内容时剔掉 `last_sent_at`，否则每 15 s 都算「变了」、两个 webview 跟着空转。
不联网：`fetch` 一律打桩。
"""
try:
    from . import _isolation  # noqa: F401  ★ 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load(fname, name):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / fname))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


GQ = _load("grok-quota", "grok_quota_last_fail_t")


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


ENTRY_OK = {"key": "tok-placeholder", "user_id": "u", "expires_at": _iso(time.time() + 3600)}
ENTRY_EXPIRED = dict(ENTRY_OK, expires_at=_iso(time.time() - 60))


class TheLastFailureSurvivesRoundsThatSendNothing(unittest.TestCase):
    def test_failed_request_is_recorded_then_carried_past_token_expired(self):
        with mock.patch.object(GQ, "fetch", return_value=(None, "http_error", 502, "bad gateway", None)) as f:
            a1 = GQ.scan_account("k", ENTRY_OK, {}, {})
        self.assertTrue(f.called, "已知阳性：token 有效时真发了请求")
        self.assertIsInstance(a1["last_sent_at"], int)
        self.assertEqual({k: a1["last_fail"][k] for k in ("reason", "http_status")}, {"reason": "http_error", "http_status": 502})
        extras = {"last_sent_at": a1["last_sent_at"], "last_fail": a1["last_fail"], "plan": None, "retry_at": None}
        with mock.patch.object(GQ, "fetch", side_effect=AssertionError("过期了不该发请求")):
            a2 = GQ.scan_account("k", ENTRY_EXPIRED, {}, extras)
        self.assertEqual(a2["reason"], "token_expired")
        self.assertEqual(a2["last_fail"], a1["last_fail"], "★ 没发请求的轮次不许冲掉上一次失败的原因")
        self.assertEqual(a2["last_sent_at"], a1["last_sent_at"])

    def test_prev_extras_reads_them_back_from_the_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text(json.dumps({"accounts": [{"account_key": "k", "last_sent_at": 123,
                                                   "last_fail": {"reason": "network_error"}}]}))
            ex = GQ.prev_extras(str(p))
        self.assertEqual((ex["k"]["last_sent_at"], ex["k"]["last_fail"]), (123, {"reason": "network_error"}))

    def test_success_keeps_the_old_failure_and_updates_sent_at(self):
        with mock.patch.object(GQ, "fetch", return_value=({"used_percent": 10}, None, 200, None, None)), \
                mock.patch.object(GQ, "fetch_plan", return_value=None):
            a = GQ.scan_account("k", ENTRY_OK, {}, {"last_fail": {"reason": "http_error"}, "last_sent_at": 1})
        self.assertTrue(a["available"])
        self.assertGreater(a["last_sent_at"], 1)
        self.assertEqual(a["last_fail"], {"reason": "http_error"}, "最近一次失败是历史，成功不抹掉它")


class TheSamplerIgnoresSentAtWhenComparing(unittest.TestCase):
    def test_only_sent_at_changed_means_no_rewrite(self):
        S = _load("grok-quota-sampler", "grok_sampler_last_fail_t")
        with tempfile.TemporaryDirectory() as d:
            S.SIDECAR = Path(d) / ".grok-quota.json"
            snap = {"fetched_at": 1, "accounts": [{"account_key": "k", "quota": {"used_percent": 10}, "last_sent_at": 100}]}
            S._write_sidecar(snap)
            m0 = S.SIDECAR.stat().st_mtime_ns
            S.SIDECAR.write_text("sentinel")
            S._write_sidecar(dict(snap, fetched_at=2, accounts=[dict(snap["accounts"][0], last_sent_at=115)]))
            self.assertEqual(S.SIDECAR.read_text(), "sentinel", "★ 只有 last_sent_at 变了 ⇒ 不重写（不广播）")
            S._write_sidecar(dict(snap, accounts=[dict(snap["accounts"][0], quota={"used_percent": 11})]))
            self.assertNotEqual(S.SIDECAR.read_text(), "sentinel", "已知阳性：额度变了照写")
            self.assertTrue(m0)


class AMissingUsageFieldMeansZero(unittest.TestCase):
    """xAI 账单是 proto3 JSON，省略零值 ⇒ 本周用量 <1% 时 `creditUsagePercent` 与 `productUsage` 一起缺席（2026-10-23 实测，
    用户拍板「剩 ≥99% · 推断」）。只在结构完整、且没有任何分项时推断；推断要标出来，不当实测。"""
    PERIOD = {"type": "USAGE_PERIOD_TYPE_WEEKLY", "start": "2026-10-22T11:34:58+00:00", "end": "2026-10-29T11:34:58+00:00"}

    def test_absent_field_with_intact_structure_is_an_inferred_zero(self):
        q = GQ.parse_quota({"config": {"currentPeriod": self.PERIOD, "isUnifiedBillingUser": True}})
        self.assertIsNotNone(q, "★ 这正是 10-22 重置后一直「读不到」的那份响应")
        self.assertEqual((q["used_percent"], q["used_inferred"]), (0.0, True))

    def test_real_reading_is_not_marked(self):
        q = GQ.parse_quota({"config": {"currentPeriod": self.PERIOD, "creditUsagePercent": 7}})
        self.assertEqual((q["used_percent"], q["used_inferred"]), (7.0, False))

    def test_contradictory_or_broken_payloads_stay_unreadable(self):
        self.assertIsNone(GQ.parse_quota({"config": {"currentPeriod": self.PERIOD,
                                                     "productUsage": [{"product": "GrokBuild", "usagePercent": 3}]}}),
                          "有分项却缺总数 ⇒ 前后矛盾，不推")
        self.assertIsNone(GQ.parse_quota({"config": {}}), "没有周期 ⇒ 结构不全，不推")
        self.assertIsNone(GQ.parse_quota({"config": {"currentPeriod": {}}}))
        self.assertIsNone(GQ.parse_quota({}))

    def test_inferred_flag_survives_into_last_good(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text(json.dumps({"fetched_at": 5, "accounts": [{"account_key": "k", "available": True,
                                     "quota": {"used_percent": 0.0, "used_inferred": True, "period_end": 9}}]}))
            self.assertEqual(GQ.prev_index(str(p))["k"].get("used_inferred"), True)


if __name__ == "__main__":
    unittest.main()
