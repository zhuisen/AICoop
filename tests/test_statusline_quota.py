"""`traffic/statusline_quota.py`：状态栏额度转写（2026-10-19）。

守四件事：
  ① **白名单**：payload 里的 cwd / transcript_path / session_id / email / model 一个键都不落盘；
  ② **只增不减**（CLAUDE.md §7.0b）：这次没给的窗口 / bucket / 子字段沿用旧值，没抓到东西就不写；
  ③ **绝不影响状态栏**：坏 stdin 静默退出 0、无输出、够快；
  ④ `--read` 的来源选择：状态栏账本 vs Claude.app `plan-usage-history.json`，谁新用谁。

全部用临时目录 + `STATUSLINE_LEDGER_DIR` / `CLAUDE_PLAN_USAGE_PATH`，不碰真实账本。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "traffic" / "statusline_quota.py"

_spec = importlib.util.spec_from_file_location("statusline_quota_t", SCRIPT)
sq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sq)

NOW = 1_800_000_000
SECRET_CWD = "/Users/someone/secret-project"

CLAUDE_ALLOWED = {"captured_at", "five_hour", "seven_day", "used_pct", "resets_at"}
AGY_ALLOWED = {"captured_at", "plan_tier", "buckets", "remaining_fraction", "reset_time"}
AGY_BUCKETS = {"gemini-5h", "gemini-weekly", "3p-5h", "3p-weekly"}


def claude_payload(five=None, seven=None, **extra):
    rl = {}
    if five is not None:
        rl["five_hour"] = five
    if seven is not None:
        rl["seven_day"] = seven
    p = {
        "session_id": "sess-123", "transcript_path": SECRET_CWD + "/t.jsonl",
        "cwd": SECRET_CWD, "workspace": {"current_dir": SECRET_CWD},
        "model": {"id": "claude-opus", "display_name": "Opus"},
        "cost": {"total_cost_usd": 1.23}, "version": "2.1.300",
    }
    if rl:
        p["rate_limits"] = rl
    p.update(extra)
    return p


def agy_payload(quota=None, **extra):
    p = {"cwd": SECRET_CWD, "conversation_id": "conv-9", "session_id": "s-9",
         "email": "demo1@example.com", "model": {"display_name": "Gemini 3.7 Flash (High)"},
         "transcript_path": SECRET_CWD + "/x", "terminal_width": 120}
    if quota is not None:
        p["quota"] = quota
    p.update(extra)
    return p


def all_keys(obj, skip_children_of=()):
    """递归收集所有键；`skip_children_of` 里的键，其子键是数据名（bucket 名）不是字段名。"""
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            if k in skip_children_of and isinstance(v, dict):
                for vv in v.values():
                    out |= all_keys(vv, skip_children_of)
            else:
                out |= all_keys(v, skip_children_of)
    elif isinstance(obj, list):
        for v in obj:
            out |= all_keys(v, skip_children_of)
    return out


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="slq-test-")
        self.ldir = os.path.join(self.dir, "ledger")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def ingest(self, platform, payload, now=NOW):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        return sq.ingest(platform, raw, now=now, ldir=self.ldir)

    def ledger(self, platform):
        with open(os.path.join(self.ldir, platform + ".json"), encoding="utf-8") as f:
            return json.load(f)

    def run_cli(self, args, stdin=b"", env_extra=None):
        env = dict(os.environ, STATUSLINE_LEDGER_DIR=self.ldir,
                   CLAUDE_PLAN_USAGE_PATH=os.path.join(self.dir, "plan-usage-history.json"))
        env.update(env_extra or {})
        t0 = time.perf_counter()
        r = subprocess.run([sys.executable, "-I", str(SCRIPT)] + args, input=stdin,
                           capture_output=True, env=env, timeout=20)
        return r, time.perf_counter() - t0


class OnlyWhitelistedFieldsReachDisk(_Tmp):
    def test_claude_ledger_has_no_foreign_key_or_value(self):
        five = {"used_percentage": 42.5, "resets_at": NOW + 3600, "extra_field": "x"}
        seven = {"used_percentage": 10, "resets_at": NOW + 86400}
        self.assertTrue(self.ingest("claude", claude_payload(
            five, seven, rate_limits_extra=1)))
        p = claude_payload(five, seven)
        p["rate_limits"]["spend_limit"] = {"used_percentage": 3, "used_usd": 9.0}
        self.ingest("claude", p, now=NOW + 1)
        d = self.ledger("claude")
        self.assertTrue(all_keys(d) <= CLAUDE_ALLOWED, all_keys(d) - CLAUDE_ALLOWED)
        text = Path(self.ldir, "claude.json").read_text(encoding="utf-8")
        for leak in (SECRET_CWD, "sess-123", "Opus", "2.1.300", "spend_limit", "extra_field"):
            self.assertNotIn(leak, text)
        self.assertEqual(d["five_hour"]["used_pct"], 42.5)
        self.assertEqual(d["five_hour"]["resets_at"], NOW + 3600)

    def test_agy_ledger_has_no_email_cwd_or_conversation(self):
        q = {"gemini-5h": {"remaining_fraction": 0.9, "reset_time": "2027-01-15T08:00:00Z",
                           "reset_in_seconds": 100, "debug": "y"},
             "3p-weekly": {"remaining_fraction": 0.5, "reset_time": "2027-01-20T08:00:00Z"}}
        self.assertTrue(self.ingest("agy", agy_payload(q, plan_tier="Pro")))
        d = self.ledger("agy")
        keys = all_keys(d, skip_children_of=("buckets",))
        self.assertTrue(keys <= AGY_ALLOWED, keys - AGY_ALLOWED)
        self.assertEqual(set(d["buckets"]), {"gemini-5h", "3p-weekly"})
        self.assertEqual(d["plan_tier"], "Pro")
        text = Path(self.ldir, "agy.json").read_text(encoding="utf-8")
        for leak in ("example.com", SECRET_CWD, "conv-9", "Gemini 3.7", "debug", "reset_in_seconds"):
            self.assertNotIn(leak, text)

    def test_a_tampered_old_file_cannot_smuggle_keys_through(self):
        os.makedirs(self.ldir)
        Path(self.ldir, "claude.json").write_text(json.dumps({
            "captured_at": NOW - 10, "cwd": SECRET_CWD,
            "five_hour": {"used_pct": 1, "resets_at": NOW + 10, "email": "demo2@example.com"}}))
        self.ingest("claude", claude_payload(seven={"used_percentage": 5, "resets_at": NOW + 99}))
        d = self.ledger("claude")
        self.assertTrue(all_keys(d) <= CLAUDE_ALLOWED, all_keys(d) - CLAUDE_ALLOWED)
        self.assertEqual(d["five_hour"]["used_pct"], 1)

    def test_a_tampered_old_agy_file_is_cleaned_too(self):
        os.makedirs(self.ldir)
        Path(self.ldir, "agy.json").write_text(json.dumps({
            "email": "demo3@example.com", "plan_tier": "Pro",
            "buckets": {"../x": {"remaining_fraction": 0.1},
                        "gemini-weekly": {"remaining_fraction": 0.2, "cwd": SECRET_CWD}}}))
        self.ingest("agy", agy_payload({"gemini-5h": {"remaining_fraction": 0.9}}))
        d = self.ledger("agy")
        self.assertEqual(set(d["buckets"]), {"gemini-5h", "gemini-weekly"})
        keys = all_keys(d, skip_children_of=("buckets",))
        self.assertTrue(keys <= AGY_ALLOWED, keys - AGY_ALLOWED)

    def test_bucket_names_that_are_not_names_are_dropped(self):
        q = {"../../etc": {"remaining_fraction": 0.1}, "a" * 100: {"remaining_fraction": 0.2},
             "gemini-weekly": {"remaining_fraction": 0.3}}
        self.ingest("agy", agy_payload(q))
        self.assertEqual(set(self.ledger("agy")["buckets"]), {"gemini-weekly"})


class AbsentMeansKeepTheOldValue(_Tmp):
    def test_missing_window_keeps_previous(self):
        self.ingest("claude", claude_payload({"used_percentage": 30, "resets_at": NOW + 3600},
                                             {"used_percentage": 12, "resets_at": NOW + 86400}))
        self.ingest("claude", claude_payload({"used_percentage": 35, "resets_at": NOW + 3600}),
                    now=NOW + 60)
        d = self.ledger("claude")
        self.assertEqual(d["five_hour"]["used_pct"], 35)
        self.assertEqual(d["seven_day"], {"used_pct": 12, "resets_at": NOW + 86400, "captured_at": NOW})
        self.assertEqual(d["captured_at"], NOW + 60)

    def test_payload_without_rate_limits_does_not_touch_the_file(self):
        self.ingest("claude", claude_payload({"used_percentage": 30, "resets_at": NOW + 3600}))
        before = Path(self.ldir, "claude.json").read_bytes()
        self.assertFalse(self.ingest("claude", claude_payload(), now=NOW + 5))
        self.assertFalse(self.ingest("claude", claude_payload({"used_percentage": None}), now=NOW + 6))
        self.assertEqual(before, Path(self.ldir, "claude.json").read_bytes())

    def test_nothing_captured_creates_no_file(self):
        self.assertFalse(self.ingest("claude", claude_payload()))
        self.assertFalse(self.ingest("agy", agy_payload({})))
        self.assertFalse(os.path.exists(self.ldir) and os.listdir(self.ldir))

    def test_agy_missing_bucket_and_subfield_are_carried(self):
        self.ingest("agy", agy_payload({
            "gemini-5h": {"remaining_fraction": 0.8, "reset_time": "2027-01-15T08:00:00Z"},
            "gemini-weekly": {"remaining_fraction": 0.6, "reset_time": "2027-01-20T08:00:00Z"}},
            plan_tier="Pro"))
        self.ingest("agy", agy_payload({"gemini-5h": {"remaining_fraction": 0.7}}), now=NOW + 30)
        d = self.ledger("agy")
        self.assertEqual(d["buckets"]["gemini-5h"]["remaining_fraction"], 0.7)
        self.assertEqual(d["buckets"]["gemini-5h"]["reset_time"], "2027-01-15T08:00:00Z")
        self.assertEqual(d["buckets"]["gemini-weekly"]["remaining_fraction"], 0.6)
        self.assertEqual(d["plan_tier"], "Pro")

    def test_reset_in_seconds_becomes_an_absolute_time(self):
        self.ingest("agy", agy_payload({"gemini-5h": {"remaining_fraction": 0.5,
                                                      "reset_in_seconds": 3600}}))
        exp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW + 3600))
        self.assertEqual(self.ledger("agy")["buckets"]["gemini-5h"]["reset_time"], exp)

    def test_unreadable_old_file_is_not_overwritten(self):
        if os.geteuid() == 0:
            self.skipTest("root 读得到 0000 文件")
        self.ingest("claude", claude_payload({"used_percentage": 30, "resets_at": NOW + 3600}))
        p = Path(self.ldir, "claude.json")
        before = p.read_bytes()
        p.chmod(0)
        try:
            with self.assertRaises(sq._Unreadable):
                self.ingest("claude", claude_payload(seven={"used_percentage": 1, "resets_at": NOW + 9}))
        finally:
            p.chmod(0o644)
        self.assertEqual(before, p.read_bytes())

    def test_no_temp_file_is_left_behind(self):
        for i in range(3):
            self.ingest("claude", claude_payload({"used_percentage": 30 + i, "resets_at": NOW + 3600}),
                        now=NOW + i)
        self.assertEqual(os.listdir(self.ldir), ["claude.json"])


class AnIdleSessionCannotRollTheNumberBack(_Tmp):
    """闲置会话重画状态栏时带的是它自己最后一次响应时的额度。"""

    def setUp(self):
        super().setUp()
        self.ingest("claude", claude_payload({"used_percentage": 60, "resets_at": NOW + 3600}))

    def test_older_window_is_ignored(self):
        self.ingest("claude", claude_payload({"used_percentage": 90, "resets_at": NOW - 14400}),
                    now=NOW + 10)
        self.assertEqual(self.ledger("claude")["five_hour"]["used_pct"], 60)

    def test_lower_reading_in_the_same_window_is_ignored(self):
        self.ingest("claude", claude_payload({"used_percentage": 20, "resets_at": NOW + 3600}),
                    now=NOW + 10)
        self.assertEqual(self.ledger("claude")["five_hour"]["used_pct"], 60)

    def test_newer_window_replaces_even_when_lower(self):
        self.ingest("claude", claude_payload({"used_percentage": 3, "resets_at": NOW + 3600 + 18000}),
                    now=NOW + 3700)
        w = self.ledger("claude")["five_hour"]
        self.assertEqual((w["used_pct"], w["resets_at"]), (3, NOW + 3600 + 18000))


class IngestNeverDisturbsTheStatusLine(_Tmp):
    BAD = [b"", b"not json", b"[1,2,3]", b"null", b"\xff\xfe\x00garbage",
           b'{"rate_limits": "oops"}', b'{"rate_limits": {"five_hour": [1]}}',
           b'{"quota": {"gemini-5h": "x"}}', b"{" * 5000]

    def test_bad_stdin_exits_zero_silently_and_writes_nothing(self):
        for plat in ("claude", "agy", "bogus"):
            for raw in self.BAD:
                with self.subTest(plat=plat, raw=raw[:20]):
                    r, _ = self.run_cli(["--ingest", plat], stdin=raw)
                    self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        self.assertFalse(os.path.exists(self.ldir) and os.listdir(self.ldir))

    def test_unwritable_ledger_dir_still_exits_zero(self):
        blocker = os.path.join(self.dir, "file-not-dir")
        Path(blocker).write_text("x")
        p = json.dumps(claude_payload({"used_percentage": 5, "resets_at": NOW + 9})).encode()
        r, _ = self.run_cli(["--ingest", "claude"], stdin=p,
                            env_extra={"STATUSLINE_LEDGER_DIR": os.path.join(blocker, "sub")})
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))

    def test_good_stdin_writes_and_is_fast(self):
        p = json.dumps(claude_payload({"used_percentage": 5, "resets_at": NOW + 9})).encode()
        times = []
        for _ in range(5):
            r, dt = self.run_cli(["--ingest", "claude"], stdin=p)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
            times.append(dt)
        self.assertEqual(self.ledger("claude")["five_hour"]["used_pct"], 5)
        self.assertLess(min(times), 0.05, f"ingest 太慢：{[round(t * 1000) for t in times]} ms")

    def test_cli_ingest_uses_the_ledger_env(self):
        p = json.dumps(agy_payload({"gemini-5h": {"remaining_fraction": 0.4}})).encode()
        self.run_cli(["--ingest", "agy"], stdin=p)
        self.assertEqual(self.ledger("agy")["buckets"]["gemini-5h"]["remaining_fraction"], 0.4)


class ReadPicksTheFresherSource(_Tmp):
    def plan(self, samples, raw=None):
        path = os.path.join(self.dir, "plan-usage-history.json")
        Path(path).write_text(raw if raw is not None else json.dumps({"version": 2, "samples": samples}))
        return path

    def read(self, now=NOW + 100, plan_path=None):
        return sq.read_all(now=now, ldir=self.ldir,
                           plan_path=plan_path or os.path.join(self.dir, "absent.json"))

    def test_nothing_anywhere_is_none_not_zero(self):
        c = self.read()["claude"]
        self.assertEqual((c["source"], c["five_hour"], c["seven_day"]), ("none", None, None))
        a = self.read()["agy"]
        self.assertEqual((a["source"], a["buckets"]), ("none", {}))

    def test_statusline_missing_falls_back_to_plan_usage(self):
        pp = self.plan([{"t": (NOW - 50) * 1000, "org": "o1", "u": {"fh": 40, "sd": 7}},
                        {"t": (NOW - 500) * 1000, "org": "o1", "u": {"fh": 99, "sd": 99}}])
        c = self.read(plan_path=pp)["claude"]
        self.assertEqual(c["source"], "plan-usage-history")
        self.assertEqual(c["captured_at"], NOW - 50)
        self.assertEqual(c["five_hour"]["used_pct"], 40)
        self.assertIsNone(c["five_hour"]["resets_at"])
        self.assertEqual(c["seven_day"]["used_pct"], 7)

    def test_newer_statusline_wins(self):
        self.ingest("claude", claude_payload({"used_percentage": 33, "resets_at": NOW + 3600}))
        pp = self.plan([{"t": (NOW - 50) * 1000, "org": "o1", "u": {"fh": 40, "sd": 7}}])
        c = self.read(plan_path=pp)["claude"]
        self.assertEqual((c["source"], c["five_hour"]["used_pct"]), ("statusline", 33))
        self.assertEqual(c["five_hour"]["resets_at"], NOW + 3600)
        self.assertIsNone(c["seven_day"])

    def test_older_statusline_loses_to_newer_plan_usage(self):
        self.ingest("claude", claude_payload({"used_percentage": 33, "resets_at": NOW + 3600}))
        pp = self.plan([{"t": (NOW + 50) * 1000, "org": "o1", "u": {"fh": 41, "sd": 8}}])
        c = self.read(plan_path=pp)["claude"]
        self.assertEqual((c["source"], c["five_hour"]["used_pct"]), ("plan-usage-history", 41))

    def test_unknown_plan_usage_shape_is_none(self):
        for raw in ('{"version": 3, "data": "x"}', "not json", '[{"t": 1}]',
                    '{"samples": [{"t": "soon", "u": {"fh": 1}}]}'):
            with self.subTest(raw=raw):
                self.assertEqual(self.read(plan_path=self.plan(None, raw=raw))["claude"]["source"], "none")

    def test_plan_usage_grouped_by_org_is_tolerated(self):
        raw = json.dumps({"o1": [{"t": NOW, "u": {"fh": 12}}]})        # 秒也认
        c = self.read(plan_path=self.plan(None, raw=raw))["claude"]
        self.assertEqual((c["source"], c["captured_at"], c["five_hour"]["used_pct"]),
                         ("plan-usage-history", NOW, 12))
        self.assertIsNone(c["seven_day"])

    def test_plan_usage_older_than_its_window_is_expired(self):
        """Claude.app 记录没有重置时间：比窗口还老的读数一定属于已重置的旧窗口，不能当现值。"""
        pp = self.plan([{"t": NOW * 1000, "org": "o1", "u": {"fh": 62, "sd": 8}}])
        c = self.read(now=NOW + 5 * 3600 - 1, plan_path=pp)["claude"]
        self.assertEqual((c["five_hour"]["expired"], c["seven_day"]["expired"]), (False, False))
        c = self.read(now=NOW + 5 * 3600, plan_path=pp)["claude"]
        self.assertEqual((c["five_hour"]["used_pct"], c["five_hour"]["expired"]), (62, True))
        self.assertFalse(c["seven_day"]["expired"])
        c = self.read(now=NOW + 7 * 86400, plan_path=pp)["claude"]
        self.assertEqual((c["seven_day"]["used_pct"], c["seven_day"]["expired"]), (8, True))

    def test_expired_window_is_flagged_not_zeroed(self):
        self.ingest("claude", claude_payload({"used_percentage": 70, "resets_at": NOW + 60}))
        w = self.read(now=NOW + 61)["claude"]["five_hour"]
        self.assertEqual((w["used_pct"], w["expired"]), (70, True))
        self.assertFalse(self.read(now=NOW + 59)["claude"]["five_hour"]["expired"])

    def test_agy_read(self):
        self.ingest("agy", agy_payload({"gemini-5h": {"remaining_fraction": 0.25}}, plan_tier="Ultra"))
        a = self.read()["agy"]
        self.assertEqual((a["source"], a["plan_tier"], a["captured_at"]), ("statusline", "Ultra", NOW))
        self.assertEqual(a["buckets"]["gemini-5h"]["remaining_fraction"], 0.25)

    def test_cli_read_prints_json(self):
        self.ingest("claude", claude_payload({"used_percentage": 9, "resets_at": NOW + 3600}))
        r, _ = self.run_cli(["--read"])
        self.assertEqual(r.returncode, 0)
        d = json.loads(r.stdout)
        self.assertEqual(set(d), {"claude", "agy"})
        self.assertEqual(d["claude"]["five_hour"]["used_pct"], 9)


class TheFileIsShipped(unittest.TestCase):
    """B77：运行时会加载的文件要同时进 `RUNTIME_FILES` 与 `bundle.resources`。"""

    def test_bundle_resources_and_runtime_files(self):
        conf = json.loads((ROOT / "codexbar/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
        self.assertEqual(conf["bundle"]["resources"].get("../../traffic/statusline_quota.py"),
                         "scripts/traffic/statusline_quota.py")
        spec = importlib.util.spec_from_file_location("connector_t", ROOT / "connector.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertIn("traffic/statusline_quota.py", m.RUNTIME_FILES)


if __name__ == "__main__":
    unittest.main()
