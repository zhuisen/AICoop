"""agy 云端额度摘要的「两套数来回切」去抖（2026-10-26，用户：「能不能根治 agy 额度不准的问题? codex 就很准」）。

## 实测（2026-10-26 15:1x SGT，零计费，`scratch/agy_cloud_consistency_20261026.py`）
每号连读摘要 15 次、间隔 0.5s，期间没用 agy：
- tomyhuohuo：(5h 92.22 / 周 78.95) ×7 与 (5h 92.03 / 周 79.36) ×8 交替，重置时间逐字相同。
- samyhuohuo：(98.07 / 99.43) ×11 与 (98.17 / 98.77) ×4。
- 两套不是一新一旧：一套 5h 低周高，另一套反过来 ⇒ 后端两个副本计数不一致（印证 B81）。
- agy 自己的 statusline 读同一后端，拿到的也是其中一套。

## 守的
1. 每次读 `SUMMARY_READS` 次，每个桶取剩余最低的那次（各桶独立取）。同一时刻结果确定，不再跳。
2. 缺 `remainingFraction` = 0（proto3 省略零值），参与取最低。
3. 部分读失败用成功的；全失败才报错（降级契约不变：失败不返回空结构）。
4. 摘要已给 Gemini 周 ⇒ 不起 B88 的 `agy -p /usage` 子进程；没给 / 读失败 ⇒ 照旧兜底。
5. 跨刷新：同一 resetTime 内回升 < `RISE_TOL`（1pp）沿用上次 —— 3 次读仍可能全落同一副本
   （真跑 8 轮，samyhuohuo 的桶 3/16 次在两套值间跳，副本比例约 11:4）。回升 ≥ 1pp 照常放行，
   所以窗口若其实是滚动恢复的，误差也只在 1pp 内。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import threading
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agy import pool as P  # noqa: E402

RESET_5H, RESET_WK = "2026-10-26T11:35:16Z", "2026-10-31T01:02:00Z"


def summary(f5h, fwk):
    gem = {"bucketId": "gemini-5h", "window": "5h", "resetTime": RESET_5H}
    if f5h is not None:
        gem["remainingFraction"] = f5h
    return {"groups": [
        {"displayName": "Gemini Models", "buckets": [
            gem, {"bucketId": "gemini-weekly", "window": "weekly", "remainingFraction": fwk, "resetTime": RESET_WK}]},
        {"displayName": "Claude and GPT models", "buckets": [
            {"bucketId": "3p-5h", "window": "5h", "remainingFraction": 1, "resetTime": RESET_5H}]}]}


#: 实测的两套副本（tomyhuohuo）。
REPLICA_X = summary(0.9203, 0.7936)
REPLICA_Y = summary(0.9222, 0.7895)


def frac(groups, bid):
    for g in groups:
        for b in g["buckets"]:
            if b["bucketId"] == bid:
                return b.get("remainingFraction", 0)
    raise KeyError(bid)


class _Resp:
    def __init__(self, status, payload):
        self.status = status
        self._b = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._b


def alternating_server(replies):
    """每次连接按顺序取下一份回复（线程安全）；记下打了哪些路径。"""
    lock = threading.Lock()
    state = {"i": 0, "paths": []}

    class Conn:
        def __init__(self, *a, **k):
            pass

        def request(self, method, path, **kw):
            with lock:
                state["paths"].append(path)
                self.r = replies[state["i"] % len(replies)]
                state["i"] += 1

        def getresponse(self):
            return self.r

        def close(self):
            pass
    return Conn, state


class EachBucketTakesTheLowestReading(unittest.TestCase):
    def test_the_measured_replica_pair_merges_bucket_by_bucket(self):
        g = P.merge_min_groups([REPLICA_X["groups"], REPLICA_Y["groups"]])
        self.assertAlmostEqual(frac(g, "gemini-5h"), 0.9203, msg="★★★ 5h 取的不是最低那次")
        self.assertAlmostEqual(frac(g, "gemini-weekly"), 0.7895, msg="★★★ 周取的不是最低那次 —— 各桶要独立取")
        self.assertEqual(frac(g, "3p-5h"), 1)

    def test_order_does_not_matter(self):
        a = P.merge_min_groups([REPLICA_X["groups"], REPLICA_Y["groups"]])
        b = P.merge_min_groups([REPLICA_Y["groups"], REPLICA_X["groups"]])
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_a_missing_fraction_counts_as_zero(self):
        g = P.merge_min_groups([REPLICA_X["groups"], summary(None, 0.79)["groups"]])
        self.assertNotIn("remainingFraction", [b for b in g[0]["buckets"] if b["bucketId"] == "gemini-5h"][0],
                         "★★ proto3 省略零值 —— 缺的那格是 0，比 0.92 低")

    def test_the_inputs_are_not_mutated(self):
        x = json.loads(json.dumps(REPLICA_X["groups"]))
        P.merge_min_groups([x, REPLICA_Y["groups"]])
        self.assertEqual(x, REPLICA_X["groups"])


class FetchQuotaReadsSeveralTimes(unittest.TestCase):
    def fetch(self, replies):
        Conn, state = alternating_server(replies)
        with mock.patch.object(P, "HTTPSConnection", Conn):
            return P.fetch_quota("tok"), state

    def test_it_reads_the_summary_several_times(self):
        self.assertGreaterEqual(P.SUMMARY_READS, 3, "★ 两个副本各半，读 2 次有 1/2 概率两次落同一个")
        (groups, err), st = self.fetch([_Resp(200, REPLICA_X), _Resp(200, REPLICA_Y)])
        self.assertEqual(st["paths"], [P.QUOTA_SUMMARY_PATH] * P.SUMMARY_READS)
        self.assertFalse(err)

    def test_alternating_replicas_give_the_same_answer_every_time(self):
        """★★★ 用户看到的「跳」：同一时刻两次刷新给出不同的数。"""
        seen = set()
        for start in (0, 1):
            replies = [_Resp(200, REPLICA_X), _Resp(200, REPLICA_Y)][start:] + [_Resp(200, REPLICA_X)][:start]
            (groups, err), _ = self.fetch(replies)
            seen.add((frac(groups, "gemini-5h"), frac(groups, "gemini-weekly")))
        self.assertEqual(seen, {(0.9203, 0.7895)})

    def test_a_partial_failure_uses_the_good_reads(self):
        (groups, err), _ = self.fetch([_Resp(500, b"boom"), _Resp(200, REPLICA_Y)])
        self.assertFalse(err, "★ 一次失败不该让整次读数失败")
        self.assertAlmostEqual(frac(groups, "gemini-weekly"), 0.7895)

    def test_all_failing_is_still_a_failure(self):
        (groups, err), _ = self.fetch([_Resp(500, b"boom")])
        self.assertIsNone(groups, "★★ 失败绝不返回空结构")
        self.assertIn("HTTP 500", err)


def _load_cli():
    loader = importlib.machinery.SourceFileLoader("agy_rotate_denoise", str(ROOT / "agy-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TheUsageReportIsOnlyAFallback(unittest.TestCase):
    """行为闸：真调 `cmd_quota`，碰盘 / 碰网 / 碰钥匙串 / 起 agy 的地方全部打桩。"""

    def setUp(self):
        self.cli = cli = _load_cli()
        self.pool = {"accounts": {"A": {"label": "LA", "email": "a@x"}}}
        self.ran, self.skews, self.cloud = [], [], (REPLICA_X["groups"], "")
        cli.P = types.SimpleNamespace(
            load=lambda: self.pool,
            fetch_quota=lambda token: (json.loads(json.dumps(self.cloud[0])) if self.cloud[0] else None, self.cloud[1]),
            has_gemini_weekly=P.has_gemini_weekly,
            quota_by_group=P.quota_by_group,
            carry_missing_groups=lambda old, at, new, now=None: new,
            save=lambda p: None, merge_back=lambda snap, before, keys=(): snap,
            _lock=lambda path: open(os.devnull), _keyring_on=lambda: False, POOL=None)

        def refresh_one(sub, a, pool, skew=120):
            self.skews.append(skew)
            return {"token": {"access_token": "tok"}, "sub": sub}, ""
        cli._refresh_one = refresh_one
        cli._mark_live = lambda pool: "A"
        cli._log = lambda msg: None
        cli._note_pool_anchors = lambda *a, **k: None
        cli._maybe_tier = lambda a, cred: None
        cli._usage_report_on = lambda: True
        cli._agy_last_activity = lambda: None

        def report(cred):
            self.ran.append(cred["sub"])
            return None, None, "不该跑到这里"
        cli._usage_report = report

    def run_quota(self):
        with redirect_stdout(io.StringIO()):
            self.cli.cmd_quota(["--json"])

    def test_no_subprocess_when_the_summary_has_the_weekly(self):
        self.run_quota()
        self.assertEqual(self.ran, [], "★★★ 摘要已有 Gemini 周还起 12s 的 agy 子进程")
        self.assertEqual(self.skews, [120], "★ 不跑报告就别为它多刷 token")

    def test_the_report_still_runs_when_the_summary_lacks_the_weekly(self):
        self.cloud = ([g for g in REPLICA_X["groups"] if not g["displayName"].startswith("Gemini")], "")
        self.run_quota()
        self.assertEqual(self.ran, ["A"], "★★ 兜底被拆掉了 —— 摘要又不回 Gemini 时周就没来源")
        self.assertEqual(self.skews[-1], self.cli.USAGE_TOKEN_MIN, "★★ 跑报告前 token 要刷到够新（否则弹钥匙串窗）")

    def test_the_report_still_runs_when_the_summary_fails(self):
        self.cloud = (None, "额度 HTTP 500: boom")
        self.run_quota()
        self.assertEqual(self.ran, ["A"])


def _wk(groups):
    return frac(groups, "gemini-weekly")


class SmallRisesWithinAWindowAreReplicaNoise(unittest.TestCase):
    NOW = 1_792_990_000

    def carry(self, old, new):
        return P.carry_missing_groups(old["groups"], self.NOW - 180, new["groups"], now=self.NOW)

    def test_the_measured_replica_gap_is_held(self):
        out = self.carry(summary(0.9807, 0.9877), summary(0.9817, 0.9943))
        self.assertAlmostEqual(_wk(out), 0.9877, msg="★★★ 0.66pp 的副本差又让周跳回去了")
        self.assertAlmostEqual(frac(out, "gemini-5h"), 0.9807)

    def test_tolerance_covers_the_measured_gap(self):
        self.assertGreater(P.RISE_TOL, 0.0066)
        self.assertLessEqual(P.RISE_TOL, 0.02, "★ 太宽会吞掉真恢复")

    def test_a_real_recovery_passes(self):
        self.assertAlmostEqual(_wk(self.carry(summary(0.9, 0.70), summary(0.9, 0.75))), 0.75)

    def test_a_drop_passes(self):
        self.assertAlmostEqual(_wk(self.carry(summary(0.9, 0.79), summary(0.9, 0.78))), 0.78)

    def test_a_new_window_passes(self):
        new = summary(0.9, 0.795)
        new["groups"][0]["buckets"][1]["resetTime"] = "2026-11-07T01:02:00Z"
        self.assertAlmostEqual(_wk(self.carry(summary(0.9, 0.79), new)), 0.795, msg="★★ 新窗口的数不许被旧窗口压住")

    def test_an_old_missing_number_does_not_hold(self):
        old = summary(0.9, 0.79)
        old["groups"][0]["buckets"][1].pop("remainingFraction")
        self.assertAlmostEqual(_wk(self.carry(old, summary(0.9, 0.795))), 0.795)

    def test_the_new_reading_is_not_mutated(self):
        new = summary(0.9817, 0.9943)
        self.carry(summary(0.9807, 0.9877), new)
        self.assertEqual(new["groups"][0]["buckets"][1]["remainingFraction"], 0.9943)


class HasGeminiWeekly(unittest.TestCase):
    def test_cases(self):
        self.assertTrue(P.has_gemini_weekly(REPLICA_X["groups"]))
        self.assertFalse(P.has_gemini_weekly(None))
        self.assertFalse(P.has_gemini_weekly([g for g in REPLICA_X["groups"] if g["displayName"] != "Gemini Models"]))
        no_num = json.loads(json.dumps(REPLICA_X["groups"]))
        no_num[0]["buckets"][1].pop("remainingFraction")
        self.assertTrue(P.has_gemini_weekly(no_num), "★ 桶在、数缺 = 0（用光了），也是有周")


if __name__ == "__main__":
    unittest.main(verbosity=2)
