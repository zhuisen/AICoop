"""Gemini 周额度改由 agy 自己的 `/usage` 报告给当值号（B88，用户 2026-10-17：「gemini 的额度没有更新」）。

## 实测（2026-10-17 22:24–22:39 SGT，零计费）
- 生产 host `cloudcode-pa` 的周（B83 的来源）自 07:12 起不动：剩 38.7%、reset 10-21 09:38Z。
  同一时刻 agy 自己的 `/usage`：剩 98.1%、reset 10-24 01:02Z —— 生产 host 报的是**上一个窗口**。
- `agy -p /usage --output-format json`：约 12s、`usage` 全 0（3 次）；只报钥匙串里此刻那个号。

## 守的
1. 报告解析：snake_case → 摘要的 camelCase；桶在、数缺 ⇒ 读不到；一个数都没有 / 垃圾 ⇒ None。
2. `fetch_quota` 不再碰生产 host。
3. 旧的生产 host 桶不沿用数字（否则错数再撑 24h）。
4. 接线：归属对得上才替换当值号；对不上 / 认不出 ⇒ 不用、`usage_report.ok=False`；没到期不跑。
5. 测试默认不起真 agy（三处 bootstrap 都设 `AGY_USAGE_REPORT=0`）。
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
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agy import pool as P  # noqa: E402

#: 真报告的形状（2026-10-17 实测输出，去掉说明文字）。
REPORT = {"status": "SUCCESS", "usage": {"total_tokens": 0}, "command": {"name": "usage", "data": {"groups": [
    {"name": "Gemini Models", "buckets": [
        {"id": "gemini-weekly", "window": "weekly", "remaining_fraction": 0.9814425706863403,
         "reset_time": "2026-10-24T01:02:00Z"},
        {"id": "gemini-5h", "window": "5h", "remaining_fraction": 0.9724148511886597,
         "reset_time": "2026-10-17T16:03:39Z"}]},
    {"name": "Claude and GPT models", "buckets": [
        {"id": "3p-weekly", "window": "weekly", "remaining_fraction": 1, "reset_time": "2026-10-24T14:30:42Z"},
        {"id": "3p-5h", "window": "5h", "remaining_fraction": 1, "reset_time": "2026-10-17T19:30:42Z"}]}]}}}


def _bucket(groups, bid):
    return next(b for g in groups for b in g["buckets"] if b["bucketId"] == bid)


class TheUsageReportIsParsed(unittest.TestCase):
    def test_the_real_shape_becomes_summary_groups(self):
        g = P.groups_from_usage_report(REPORT)
        self.assertEqual([x["displayName"] for x in g], ["Gemini Models", "Claude and GPT models"])
        wk = _bucket(g, "gemini-weekly")
        self.assertAlmostEqual(wk["remainingFraction"], 0.98144, places=4)
        self.assertEqual(wk["resetTime"], "2026-10-24T01:02:00Z")
        self.assertEqual(wk["window"], "weekly")
        self.assertEqual(wk["source"], "agy-usage", "★ 来源要能认出来 —— 沿用与排错都靠它")
        self.assertEqual(sum(len(x["buckets"]) for x in g), 4)

    def test_downstream_reads_it_as_gemini(self):
        """★ 换成 camelCase 的意义：`quota_by_group` 一行不改就认得。"""
        q = P.quota_by_group(P.groups_from_usage_report(REPORT))
        self.assertAlmostEqual(q["gemini"]["remaining"], 0.9724, places=3)

    def test_a_bucket_without_a_fraction_stays_unknown(self):
        d = json.loads(json.dumps(REPORT))
        del d["command"]["data"]["groups"][0]["buckets"][0]["remaining_fraction"]
        wk = _bucket(P.groups_from_usage_report(d), "gemini-weekly")
        self.assertNotIn("remainingFraction", wk, "★★ 缺的可能正是 0，不能补成任何数")

    def test_no_number_anywhere_is_a_failure_not_an_empty_quota(self):
        d = json.loads(json.dumps(REPORT))
        for g in d["command"]["data"]["groups"]:
            for b in g["buckets"]:
                b.pop("remaining_fraction")
        self.assertIsNone(P.groups_from_usage_report(d), "★★ 空结构会被当成「额度是 0」")

    def test_garbage_gives_none(self):
        for d in (None, {}, {"command": None}, {"command": {"data": {"groups": "x"}}}, [], "x"):
            with self.subTest(d=d):
                self.assertIsNone(P.groups_from_usage_report(d))


class _Resp:
    def __init__(self, body):
        self.status, self._b = 200, json.dumps(body).encode()

    def read(self):
        return self._b


class TheProdHostIsNoLongerAsked(unittest.TestCase):
    def test_fetch_quota_never_connects_to_the_prod_host(self):
        hosts = []
        summary = {"groups": [{"displayName": "Claude and GPT models", "buckets": [
            {"bucketId": "3p-weekly", "window": "weekly", "remainingFraction": 1}]}]}

        class Conn:
            def __init__(self, host, timeout=None):
                hosts.append(host)
                self.path = None

            def request(self, method, path, body=None, headers=None):
                self.path = path

            def getresponse(self):
                return _Resp(summary if self.path == P.QUOTA_SUMMARY_PATH else {"models": {}})

            def close(self):
                pass

        with mock.patch.object(P, "HTTPSConnection", Conn):
            groups, err = P.fetch_quota("tok")
        self.assertEqual(err, "")
        self.assertTrue(hosts, "★ 前提：真的走到了打桩的连接")
        self.assertNotIn(P.API_HOST, hosts, "★★★ 生产 host 的周是上一个窗口的旧账（B88）")


class OldProdBucketsAreNotCarried(unittest.TestCase):
    def test_a_prod_sourced_weekly_loses_its_number_when_carried(self):
        now = time.time()
        old = [{"displayName": "Gemini Models", "buckets": [
            {"bucketId": "gemini-weekly", "window": "weekly", "remainingFraction": 0.387,
             "resetTime": "2099-01-01T00:00:00Z", "source": P.PROD_SOURCE},
            {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 0.9,
             "resetTime": "2099-01-01T00:00:00Z", "source": "agy-usage"}]}]
        out = P.carry_missing_groups(old, now - 60, [], now=now)
        self.assertNotIn("remainingFraction", _bucket(out, "gemini-weekly"),
                         "★★★ 沿用旧窗口的错数 = 把它当「刚读到」再撑 24h")
        self.assertEqual(_bucket(out, "gemini-5h")["remainingFraction"], 0.9,
                         "★ 只拦生产 host 那份；agy 自己报的照常沿用并标龄")


def _load_cli():
    loader = importlib.machinery.SourceFileLoader("agy_rotate_usage_report", str(ROOT / "agy-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


CLOUD = [{"displayName": "Claude and GPT models", "buckets": [
    {"bucketId": "3p-weekly", "window": "weekly", "remainingFraction": 1}]}]


class TheReportIsWiredToTheLiveAccountOnly(unittest.TestCase):
    """行为闸：真调 `cmd_quota`，碰盘 / 碰网 / 碰钥匙串 / 起 agy 的地方全部打桩。"""

    def setUp(self):
        self.cli = cli = _load_cli()
        self.pool = {"accounts": {"A": {"label": "LA", "email": "a@x"}, "B": {"label": "LB", "email": "b@x"}}}
        self.reports = []
        cli.P = types.SimpleNamespace(
            load=lambda: self.pool,
            fetch_quota=lambda token: (json.loads(json.dumps(CLOUD)), ""),
            quota_by_group=P.quota_by_group,
            carry_missing_groups=lambda old, at, new, now=None: new,
            save=lambda p: None,
            _lock=lambda path: open(os.devnull),
            _keyring_on=lambda: False,
            POOL=None,
        )
        cli._refresh_one = lambda sub, a, pool: ({"token": {"access_token": "tok"}}, "")
        cli._mark_live = lambda pool: "A"
        cli._log = lambda msg: None
        cli._note_pool_anchors = lambda *a, **k: None
        cli._maybe_tier = lambda a, cred: None
        cli._usage_report_on = lambda: True
        cli._usage_report_due = lambda pool, live: True

    def run_with(self, report):
        self.cli._usage_report = lambda: (self.reports.append(1), report)[1]
        with redirect_stdout(io.StringIO()):
            self.cli.cmd_quota(["--json"])
        return self.pool["accounts"]

    def weekly(self, acc):
        for g in acc.get("quota_summary") or []:
            for b in g["buckets"]:
                if b["bucketId"] == "gemini-weekly":
                    return b.get("remainingFraction")
        return None

    def test_a_matching_report_replaces_the_live_account(self):
        accs = self.run_with((P.groups_from_usage_report(REPORT), "A@X", ""))
        self.assertAlmostEqual(self.weekly(accs["A"]), 0.98144, places=4, msg="★★ 当值号的周要来自报告")
        self.assertIsNone(self.weekly(accs["B"]), "★★★ 报告只属于当值号，不许写进别的号")
        self.assertTrue(self.pool["usage_report"]["ok"])
        self.assertEqual(self.pool["usage_report"]["sub"], "A")

    def test_a_report_from_another_account_is_not_used(self):
        accs = self.run_with((P.groups_from_usage_report(REPORT), "b@x", ""))
        self.assertIsNone(self.weekly(accs["A"]), "★★★ 钥匙串被别的 agy 抢回去了 —— 那是 B 的数")
        self.assertFalse(self.pool["usage_report"]["ok"])
        self.assertIn("归属对不上", self.pool["usage_report"]["err"])

    def test_an_unidentified_report_is_not_used(self):
        accs = self.run_with((P.groups_from_usage_report(REPORT), None, ""))
        self.assertIsNone(self.weekly(accs["A"]), "★★ 认不出是谁跑的 = 不挂到任何号上")
        self.assertFalse(self.pool["usage_report"]["ok"])

    def test_a_failed_report_keeps_the_cloud_reading(self):
        accs = self.run_with((None, "a@x", "超时（45s）"))
        self.assertEqual(accs["A"]["quota_summary"], CLOUD, "★ 报告失败不影响云端那份")
        self.assertEqual(self.pool["usage_report"]["err"], "超时（45s）")

    def test_not_due_means_not_run(self):
        self.cli._usage_report_due = lambda pool, live: False
        self.run_with((P.groups_from_usage_report(REPORT), "a@x", ""))
        self.assertEqual(self.reports, [], "★ 每 3 分钟都起一次 12s 的 agy 是纯浪费")
        self.assertNotIn("usage_report", self.pool)


class WhenTheReportIsDue(unittest.TestCase):
    def setUp(self):
        self.cli = _load_cli()
        self.dir = tempfile.TemporaryDirectory()
        self.cli.AGY_CONV_DIR = Path(self.dir.name)
        self.now = 2_000_000_000

    def tearDown(self):
        self.dir.cleanup()

    def due(self, last, live="A"):
        return self.cli._usage_report_due({"usage_report": last} if last else {}, live, now=self.now)

    def test_first_time_and_account_change_are_due(self):
        self.assertTrue(self.due(None))
        self.assertTrue(self.due({"sub": "B", "at": self.now - 10}), "★ 换了号，上一份是别人的")

    def test_no_live_account_is_never_due(self):
        self.assertFalse(self.due(None, live=None))

    def test_a_fresh_report_without_activity_is_not_due(self):
        self.assertFalse(self.due({"sub": "A", "at": self.now - 60}))

    def test_an_old_report_is_due(self):
        self.assertTrue(self.due({"sub": "A", "at": self.now - self.cli.USAGE_MAX_AGE}))

    def test_activity_after_the_last_report_is_due(self):
        f = Path(self.dir.name) / "c.db-wal"
        f.write_text("x")
        os.utime(f, (self.now - 30, self.now - 30))
        self.assertTrue(self.due({"sub": "A", "at": self.now - 60}), "★★ agy 刚用过，额度动了")
        self.assertFalse(self.due({"sub": "A", "at": self.now - 10}), "活动早于上一份报告")


class TestsNeverStartARealAgy(unittest.TestCase):
    def test_the_switch_is_off_under_tests(self):
        self.assertEqual(os.environ.get("AGY_USAGE_REPORT"), "0")
        self.assertFalse(_load_cli()._usage_report_on())

    def test_unset_follows_the_keyring_switch(self):
        cli = _load_cli()
        with mock.patch.dict(os.environ):
            os.environ.pop("AGY_USAGE_REPORT")
            cli.P = types.SimpleNamespace(_keyring_on=lambda: False)
            self.assertFalse(cli._usage_report_on())
            cli.P = types.SimpleNamespace(_keyring_on=lambda: True)
            self.assertTrue(cli._usage_report_on())


if __name__ == "__main__":
    unittest.main()
