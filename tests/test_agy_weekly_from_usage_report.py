"""Gemini 周额度改由 agy 自己的 `/usage` 报告给当值号（B88，用户 2026-10-17：「gemini 的额度没有更新」）。

## 实测（2026-10-17 22:24–22:39 SGT，零计费）
- 生产 host `cloudcode-pa` 的周（B83 的来源）自 07:12 起不动：剩 38.7%、reset 10-21 09:38Z。
  同一时刻 agy 自己的 `/usage`：剩 98.1%、reset 10-24 01:02Z —— 生产 host 报的是**上一个窗口**。
- `agy -p /usage --output-format json`：约 12s、`usage` 全 0（3 次）。
- `HOME` 指向临时目录 ⇒ 钥匙串查不到（不弹窗）⇒ agy 读临时目录里的 token 文件：2 个号日志身份都对，
  真钥匙串前后逐字相同，当值号读数与直接跑一致。

## 守的
1. 报告解析：snake_case → 摘要的 camelCase；桶在、数缺 ⇒ 读不到；一个数都没有 / 垃圾 ⇒ None。
2. `fetch_quota` 不再碰生产 host。
3. 旧的生产 host 桶不沿用数字（否则错数再撑 24h）。
4. 接线：每个号用自己的凭证跑；归属对得上才替换；对不上 / 认不出 ⇒ 不用、`usage_report.ok=False`；没到期不跑。
   隔离：假 agy 看到的 HOME 不是真 HOME、token 是这个号的、临时目录用完即删。
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


class EachAccountGetsItsOwnReport(unittest.TestCase):
    """行为闸：真调 `cmd_quota`，碰盘 / 碰网 / 碰钥匙串 / 起 agy 的地方全部打桩。"""

    def setUp(self):
        self.cli = cli = _load_cli()
        self.pool = {"accounts": {"A": {"label": "LA", "email": "a@x"}, "B": {"label": "LB", "email": "b@x"}}}
        self.ran = []
        cli.P = types.SimpleNamespace(
            load=lambda: self.pool,
            fetch_quota=lambda token: (json.loads(json.dumps(CLOUD)), ""),
            quota_by_group=P.quota_by_group,
            carry_missing_groups=lambda old, at, new, now=None: new,
            save=lambda p: None, merge_back=lambda snap, before, keys=(): snap,
            _lock=lambda path: open(os.devnull),
            _keyring_on=lambda: False,
            POOL=None,
        )
        self.skews = {}

        def refresh_one(sub, a, pool, skew=120):
            self.skews[sub] = skew
            return {"token": {"access_token": "tok-" + sub}, "sub": sub}, ""
        cli._refresh_one = refresh_one
        cli._mark_live = lambda pool: "A"
        cli._log = lambda msg: None
        cli._note_pool_anchors = lambda *a, **k: None
        cli._maybe_tier = lambda a, cred: None
        cli._usage_report_on = lambda: True
        cli._agy_last_activity = lambda: None
        self.reply = lambda cred: (P.groups_from_usage_report(REPORT), cred["sub"].lower() + "@X", "")

    def run_quota(self):
        def report(cred):
            self.ran.append(cred["sub"])
            return self.reply(cred)
        self.cli._usage_report = report
        with redirect_stdout(io.StringIO()):
            self.cli.cmd_quota(["--json"])
        return self.pool["accounts"]

    def weekly(self, acc):
        for g in acc.get("quota_summary") or []:
            for b in g["buckets"]:
                if b["bucketId"] == "gemini-weekly":
                    return b.get("remainingFraction")
        return None

    def test_every_due_account_is_reported_with_its_own_credential(self):
        accs = self.run_quota()
        self.assertEqual(sorted(self.ran), ["A", "B"], "★★★ 非当值号也要有周 —— 每个号用自己的凭证跑")
        for sub in ("A", "B"):
            with self.subTest(sub=sub):
                self.assertAlmostEqual(self.weekly(accs[sub]), 0.98144, places=4)
                self.assertTrue(accs[sub]["usage_report"]["ok"])

    def test_a_report_that_ran_as_someone_else_is_not_used(self):
        self.reply = lambda cred: (P.groups_from_usage_report(REPORT), "b@x", "")
        accs = self.run_quota()
        self.assertIsNone(self.weekly(accs["A"]), "★★★ 报告是 B 的，不许记在 A 头上")
        self.assertFalse(accs["A"]["usage_report"]["ok"])
        self.assertIn("归属对不上", accs["A"]["usage_report"]["err"])
        self.assertAlmostEqual(self.weekly(accs["B"]), 0.98144, places=4)

    def test_an_unidentified_report_is_not_used(self):
        self.reply = lambda cred: (P.groups_from_usage_report(REPORT), None, "")
        accs = self.run_quota()
        self.assertIsNone(self.weekly(accs["A"]), "★★ 认不出是谁跑的 = 不挂到任何号上")
        self.assertFalse(accs["A"]["usage_report"]["ok"])

    def test_a_failed_report_keeps_the_cloud_reading(self):
        self.reply = lambda cred: (None, None, "超时（45s）")
        accs = self.run_quota()
        self.assertEqual(accs["A"]["quota_summary"], CLOUD, "★ 报告失败不影响云端那份")
        self.assertEqual(accs["A"]["usage_report"]["err"], "超时（45s）")

    def test_the_token_is_made_fresh_before_a_report(self):
        """★★★ agy 拿到快到期的 token 会自己刷新、再写钥匙串 ⇒ 临时 HOME 下弹「Keychain Not Found」（2026-10-18 实测）。"""
        self.run_quota()
        self.assertEqual(self.skews, {"A": self.cli.USAGE_TOKEN_MIN, "B": self.cli.USAGE_TOKEN_MIN})
        self.assertGreaterEqual(self.cli.USAGE_TOKEN_MIN, 15 * 60, "★ 余量太小，agy 仍可能自己刷新")

    def test_no_report_keeps_the_normal_refresh_margin(self):
        now = int(time.time())
        for a in self.pool["accounts"].values():
            a["usage_report"] = {"at": now - 60, "ok": True}
        self.run_quota()
        self.assertEqual(self.skews, {"A": 120, "B": 120}, "不跑报告就别多刷")

    def test_a_keychain_write_stops_reports_for_a_day(self):
        self.reply = lambda cred: (None, "a@x", self.cli.KEYRING_TRIP + "：Failed to save token to keyring")
        self.run_quota()
        self.assertEqual(len(self.ran), 1, "★★ 绊了一次就停，同一轮里别再起下一个 agy 去弹窗")
        self.assertGreater(self.pool.get("usage_report_off_until", 0), time.time() + 23 * 3600)
        self.ran.clear()
        for a in self.pool["accounts"].values():
            a.pop("usage_report", None)
        self.run_quota()
        self.assertEqual(self.ran, [], "★★ 停用期内不再跑")

    def test_a_fresh_report_is_not_rerun(self):
        now = int(time.time())
        for a in self.pool["accounts"].values():
            a["usage_report"] = {"at": now - 60, "ok": True}
        self.run_quota()
        self.assertEqual(self.ran, [], "★ 每 3 分钟给每个号起一次 agy 是纯浪费")


class WhenTheReportIsDue(unittest.TestCase):
    NOW = 2_000_000_000

    def setUp(self):
        self.cli = _load_cli()

    def due(self, at, is_live=False, activity=None):
        a = {"usage_report": {"at": at}} if at is not None else {}
        return self.cli._usage_report_due(a, is_live, activity, now=self.NOW)

    def test_never_reported_is_due(self):
        self.assertTrue(self.due(None))

    def test_a_fresh_report_is_not_due(self):
        self.assertFalse(self.due(self.NOW - 60))

    def test_an_old_report_is_due(self):
        self.assertTrue(self.due(self.NOW - self.cli.USAGE_MAX_AGE))

    def test_local_activity_makes_only_the_live_account_due(self):
        self.assertTrue(self.due(self.NOW - 60, is_live=True, activity=self.NOW - 30), "★★ agy 刚用过，当值号的额度动了")
        self.assertFalse(self.due(self.NOW - 60, is_live=False, activity=self.NOW - 30),
                         "★ 本机活动只花当值号的额度")
        self.assertFalse(self.due(self.NOW - 10, is_live=True, activity=self.NOW - 30), "活动早于上一份报告")


FAKE_AGY = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
home = pathlib.Path(os.environ["HOME"])
d = home / ".gemini" / "antigravity-cli"
tok = json.loads((d / "antigravity-oauth-token").read_text())
pathlib.Path(sys.argv[0] + ".seen").write_text(json.dumps({"home": str(home), "argv": sys.argv[1:],
    "cwd": os.getcwd(), "tok": tok, "mode": oct((d / "antigravity-oauth-token").stat().st_mode & 0o777)}))
(d / "log").mkdir(exist_ok=True)
(d / "log" / "cli-1.log").write_text("I1017 server_oauth.go:224] applyAuthResult: email=%s, authMethod=consumer\n" % tok["email"])
print(json.dumps(__REPORT__))
"""


class TheReportRunsInAnIsolatedHome(unittest.TestCase):
    """真起一个假 agy（脚本），验它看到的环境 —— 这是「不碰真钥匙串」的全部依据。"""

    def setUp(self):
        self.cli = _load_cli()
        self.dir = tempfile.TemporaryDirectory()
        self.agy = Path(self.dir.name) / "agy"
        self.agy.write_text(FAKE_AGY.replace("__REPORT__", repr(REPORT)))
        self.agy.chmod(0o755)
        self.env = mock.patch.dict(os.environ, {"AGY_REAL": str(self.agy)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def test_it_runs_as_the_given_account_without_the_real_home(self):
        cred = {"email": "x@y", "token": {"access_token": "t"}}
        groups, who, err = self.cli._usage_report(cred)
        seen = json.loads(Path(str(self.agy) + ".seen").read_text())
        self.assertEqual(err, "")
        self.assertNotEqual(seen["home"], str(Path.home()), "★★★ 用真 HOME ⇒ agy 读写的是真钥匙串")
        self.assertEqual(seen["tok"], cred, "★★ agy 读到的必须是这个号的凭证")
        self.assertEqual(seen["mode"], "0o600", "★ 临时 token 文件只给自己读")
        self.assertEqual(seen["argv"], ["-p", "/usage", "--output-format", "json"])
        self.assertEqual(who, "x@y", "★ 身份从临时 HOME 的日志读")
        self.assertAlmostEqual(_bucket(groups, "gemini-weekly")["remainingFraction"], 0.98144, places=4)
        self.assertFalse(Path(seen["home"]).exists(), "★★ 临时目录里有 token，用完必须删")

    def test_a_keychain_write_in_the_log_is_reported(self):
        self.agy.write_text(FAKE_AGY.replace("__REPORT__", repr(REPORT)).replace(
            'authMethod=consumer\\n"',
            'authMethod=consumer\\nW1018 composite_token_storage.go:237] Failed to save token to keyring, falling back to file: exit status 154\\n"'))
        groups, who, err = self.cli._usage_report({"email": "x@y", "token": {}})
        self.assertIsNone(groups)
        self.assertTrue(err.startswith(self.cli.KEYRING_TRIP), err)
        self.assertIn("exit status 154", err)

    def test_identity_must_be_unique(self):
        d = Path(self.dir.name) / "log"
        d.mkdir()
        (d / "cli-1.log").write_text("applyAuthResult: email=a@x, m\n")
        self.assertEqual(self.cli._identity_in(d), "a@x")
        (d / "cli-2.log").write_text("applyAuthResult: email=b@x, m\n")
        self.assertIsNone(self.cli._identity_in(d), "★★ 两个身份 = 认不出，不许挑一个")


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
