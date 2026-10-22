"""阶段 C（轮换 / 日志 + 中转站）—— 全方面评审 2026-10-22 的修复闸。逐条对应
`~/Downloads/aicoop_full_review_20261022/SUMMARY.md` §3 / §4。

全部用临时目录夹具（store / CODEX_HOME / agy 日志目录都指到 tmpdir），不碰真实 `state.json`、`~/.codex`、
`relay/*.local.json`。代理只调 `_relay_upstream()`，不起服务、不发请求。
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import _isolation  # noqa: F401  ★ 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
sys.path.insert(0, str(ROOT / "traffic"))
sys.path.insert(0, str(ROOT))
import agy_rotation as AR  # noqa: E402
from relay import monitor  # noqa: E402
import scan as S  # noqa: E402

_spec = importlib.util.spec_from_file_location("rot_stage_c", ROOT / "traffic" / "rotation.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

HOUR = 3600.0
NOW = time.time()


def code(rel):
    s = (SRC / rel).read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/\"'])//[^\n]*", "", s)


def node(mod, expr):
    script = "import('file://%s').then(m => { console.log(JSON.stringify(%s)); });" % ((SRC / mod).as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    out = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if not out:
        raise AssertionError("node 没有产出：%s" % r.stderr[-600:])
    return json.loads(out[-1])


def _proxy_log(path, now, hours=3):
    out = []
    for i in range(int(hours), 0, -1):
        t = time.localtime(now - i * HOUR)
        out.append(f"[proxy {t.tm_mon:02d}-{t.tm_mday:02d} {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}]"
                   f" → POST /responses [plus5] new prev=-")
    Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")


class CodexLanesSayWhenThePoolWasNotRead(unittest.TestCase):
    """§3「state.json 读不到 ⇒ 每个号都被画成已移除」：读不到池 ≠ 池是空的。"""

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.store = Path(self.d.name)
        (self.store / "proxy").mkdir()
        _proxy_log(self.store / "proxy" / "proxy.log", NOW)
        self.home = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CODEX_HOME": self.home.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.d.cleanup()
        self.home.cleanup()

    def collect(self):
        return R.collect(hours=6, now=NOW, store=str(self.store), use_cache=False)

    def test_unreadable_state_gives_unknown_not_retired(self):
        (self.store / "state.json").write_text("{not json", encoding="utf-8")
        r = self.collect()
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["accounts"], "夹具没切出任何泳道 —— 下面的断言就没打中")
        self.assertEqual({a["retired"] for a in r["accounts"]}, {None}, "★ 读不到池却把号画成「已移除」")
        self.assertTrue(r["coverage"]["state_error"], "读不到 state.json 没进 coverage")

    def test_a_readable_pool_still_says_retired(self):
        """反向：读得到、但号不在池里 ⇒ 仍是 True（防「一律 None」把功能整个关掉）。"""
        (self.store / "state.json").write_text(json.dumps({"slots": {}}), encoding="utf-8")
        r = self.collect()
        self.assertTrue(r["accounts"])
        self.assertEqual({a["retired"] for a in r["accounts"]}, {True})
        self.assertIsNone(r["coverage"]["state_error"])


class CodexLanesReadOnlyTheGivenStore(unittest.TestCase):
    """★ 阶段 C 评审 codex：`_daily()` 读 `pick_order` 走全局 `store_dir()` ⇒ 测试传临时 store 时仍读真 state.json。"""

    def test_no_state_json_outside_the_temp_store_is_opened(self):
        d = tempfile.TemporaryDirectory()
        home = tempfile.TemporaryDirectory()
        store = Path(d.name)
        (store / "proxy").mkdir()
        _proxy_log(store / "proxy" / "proxy.log", NOW)
        (store / "state.json").write_text(json.dumps({"slots": {}, "pick_order": []}), encoding="utf-8")
        seen = []
        real_open, real_load = open, R._load_json

        def spy_open(path, *a, **kw):
            seen.append(str(path))
            return real_open(path, *a, **kw)

        def spy_load(path, *a, **kw):
            seen.append(str(path))
            return real_load(path, *a, **kw)
        try:
            with mock.patch.dict(os.environ, {"CODEX_HOME": home.name}), \
                 mock.patch("builtins.open", spy_open), mock.patch.object(R, "_load_json", spy_load):
                r = R.collect(hours=6, now=NOW, store=str(store), use_cache=False)
        finally:
            d.cleanup()
            home.cleanup()
        self.assertTrue(r["ok"], r)
        states = [p for p in seen if p.endswith("state.json")]
        self.assertTrue(states, "夹具没读到任何 state.json —— 断言没打中")
        self.assertEqual([p for p in states if not p.startswith(str(store))], [], "★ 读到了临时 store 之外的 state.json")


class CompressedRolloutsAreNotDropped(unittest.TestCase):
    """§3「只 glob `.jsonl` ⇒ 压缩过的会话从泳道里静默消失」；解压不了的要计数，不当没有。"""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.sess = Path(self.home.name) / "sessions" / "2026" / "10" / "22"
        self.sess.mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"CODEX_HOME": self.home.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.home.cleanup()

    def test_zst_is_listed_and_a_duplicate_is_not(self):
        (self.sess / "rollout-a.jsonl.zst").write_bytes(b"x")
        (self.sess / "rollout-b.jsonl").write_text("", encoding="utf-8")
        (self.sess / "rollout-b.jsonl.zst").write_bytes(b"x")        # 压缩到一半：两份并存只收 .jsonl
        names = sorted(Path(p).name for p in R._rollout_paths())
        self.assertEqual(names, ["rollout-a.jsonl.zst", "rollout-b.jsonl"])

    def test_an_undecodable_zst_is_counted(self):
        bad = self.sess / "rollout-c.jsonl.zst"
        bad.write_bytes(b"not zstd at all")
        unread = []
        with mock.patch.object(S, "_zstd_text", side_effect=S.ScanReadError("fixture")):
            R.scan_rollouts(NOW - HOUR, NOW, {"resp_x"}, None, NOW, unread)
        self.assertEqual(unread, [str(bad)], "★ 解压不了的会话没进 unreadable ⇒ 界面当它不存在")

    def test_a_readable_zst_is_parsed(self):
        line = json.dumps({"timestamp": "2026-10-22T00:00:00Z", "type": "event_msg", "payload": {}}) + "\n"
        (self.sess / "rollout-d.jsonl.zst").write_bytes(b"x")
        with mock.patch.object(S, "_zstd_text", return_value=line) as z:
            unread = []
            R.scan_rollouts(NOW - HOUR, NOW, {"resp_x"}, None, NOW, unread)
        self.assertTrue(z.called, "★ .zst 根本没走解压")
        self.assertEqual(unread, [])


class RelayPostLinesOfBothFormats(unittest.TestCase):
    """§3 存疑「中转站计数只认 `@relay`」：2026-09-12 之前的行是 `[name] relay conv=…`，本机 proxy.log 里确有。"""

    def test_both_forms_count_and_pool_lines_do_not(self):
        rx = R._RELAY_POST_RE
        self.assertTrue(rx.search("[proxy 10-22 10:00:00] → POST /responses [TokenDun@relay] new prev=-"))
        self.assertTrue(rx.search("[proxy 09-09 10:00:00] → POST /responses [TokenDun] relay conv=abc"))
        self.assertFalse(rx.search("[proxy 10-22 10:00:00] → POST /responses [plus5] new prev=-"))
        self.assertFalse(rx.search("[proxy 10-22 10:00:00] → POST /responses [relayer] new prev=-"))
        self.assertFalse(rx.search("[proxy 10-22 10:00:00] → POST /responses [Yu#03b40e2e] relay conv=x"),
                         "★ 带身份的账号行被当成中转站")


class AgyLanes(unittest.TestCase):
    """§3：agy 日志读不了 ≠ 没运行过；另一个号的进程同时在跑 ≠ 钥匙串漂移。"""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="agyrot-c-"))
        self.logs = self.d / "log"
        self.logs.mkdir()
        (self.d / ".agy-pool.json").write_text(json.dumps({"accounts": {
            "s0": {"label": "A", "email": "a@x.y"}, "s1": {"label": "B", "email": "b@x.y"}}}))
        self.n = 0

    def tearDown(self):
        for f in self.logs.glob("*"):
            os.chmod(f, 0o644)
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)

    def run_(self, a_h, b_h, email, *more):
        """一个 agy 进程：`a_h` 起、`b_h` 止（相对小时），`email` 是起来时的身份；`more` = [(相对小时, email)…]
        这个进程中途身份变了。"""
        stamp = lambda t: time.strftime("%m%d %H:%M:%S.000000", time.localtime(t))  # noqa: E731
        t0 = NOW + a_h * HOUR
        self.n += 1
        f = self.logs / time.strftime("cli-%Y%m%d_%H%M%S.log", time.localtime(t0 + self.n))
        body = "I%s 1 x.go:1] start\nI%s 2 server_oauth.go:196] applyAuthResult: email=%s, authMethod=consumer\n" % (
            stamp(t0), stamp(t0 + 1), email)
        for (h, e) in more:
            body += "I%s 2 server_oauth.go:196] applyAuthResult: email=%s, authMethod=consumer\n" % (stamp(NOW + h * HOUR), e)
        f.write_text(body)
        os.utime(f, (NOW + b_h * HOUR, NOW + b_h * HOUR))
        return f

    def collect(self):
        return AR.collect(24, now=NOW, log_dir=self.logs, store=self.d, gens=[])

    def test_unreadable_logs_are_not_an_empty_lane(self):
        f = self.run_(-3, -2, "a@x.y")
        os.chmod(f, 0)
        if os.access(f, os.R_OK):
            self.skipTest("以 root 跑：chmod 0 挡不住读")
        r = self.collect()
        self.assertFalse(r["ok"], "★ 一份都没读到却画成空泳道")
        self.assertEqual(r["reason"], "unreadable")

    def test_one_unreadable_log_beside_good_ones_is_disclosed(self):
        self.run_(-5, -4, "a@x.y")
        os.chmod(self.run_(-3, -2, "b@x.y"), 0)
        r = self.collect()
        self.assertTrue(r["ok"])
        self.assertEqual(r["coverage"]["logs_unreadable"], 1)

    def test_a_parallel_process_is_not_drift_and_not_a_rotation(self):
        self.run_(-6, -1, "a@x.y")                 # A 从 -6h 跑到 -1h
        self.run_(-4, -3, "b@x.y")                 # B 在 A 还没结束时起来
        r = self.collect()
        reasons = [s["enter_reason"] for s in r["segments"]]
        self.assertIn("parallel", reasons, reasons)
        self.assertNotIn("drift", reasons, reasons)
        self.assertEqual(r["kpi"]["rotations"], 0, "★ 并行进程被算成一次换号")

    def test_a_real_handover_is_still_drift(self):
        """反向：A 结束之后 B 才起来、又没有换号记录 ⇒ 仍是 drift（防「一律 parallel」）。"""
        self.run_(-6, -5, "a@x.y")
        self.run_(-3, -2, "b@x.y")
        r = self.collect()
        self.assertIn("drift", [s["enter_reason"] for s in r["segments"]])
        self.assertEqual(r["kpi"]["rotations"], 1)

    def test_an_identity_change_inside_one_process_is_drift_even_with_others_running(self):
        """★ 阶段 C 评审 codex：同一份日志里 A→B 是这个进程自己换了身份，别处还有进程在跑也不能吞成并行。"""
        (self.d / ".agy-pool.json").write_text(json.dumps({"accounts": {
            "s0": {"label": "A", "email": "a@x.y"}, "s1": {"label": "B", "email": "b@x.y"},
            "s2": {"label": "C", "email": "c@x.y"}}}))
        self.run_(-8, -1, "c@x.y")                 # C 一直在跑
        self.run_(-6, -2, "a@x.y", (-4, "b@x.y"))  # 这个进程 -4h 从 A 变成 B
        r = self.collect()
        b = [s for s in r["segments"] if s["acc"] == "B"]
        self.assertEqual([s["enter_reason"] for s in b], ["drift"], r["segments"])

    def test_an_in_process_change_to_the_account_another_process_just_started_with_is_drift(self):
        """★ 阶段 D 评审两方：P1 以 A 起；P2 以 B 起（并行）；之后 P1 自己变成 B。全局上一段恰好也是 B，
        原来被外层 `prev != acc` 吞成 same、换号数 0。"""
        self.run_(-6, -1, "a@x.y", (-4, "b@x.y"))
        self.run_(-5, -2, "b@x.y")
        r = self.collect()
        reasons = [(s["acc"], s["enter_reason"]) for s in r["segments"]]
        self.assertEqual(reasons, [("A", "window_start"), ("B", "parallel"), ("B", "drift")], reasons)
        self.assertEqual(r["kpi"]["rotations"], 1, "★ 进程内变号没算进换号数")
        drift = [e for e in r["events"] if e.get("reason") == "drift"]
        self.assertEqual([(e["from"], e["to"]) for e in drift], [("A", "B")], "★ drift 的来源要取同一份日志的上一段")

    def test_returning_to_an_account_that_is_still_running_is_not_drift(self):
        """★ 阶段 C 评审 gemini：A 长会话期间 B 短暂并行，之后 A 再开一个进程 —— 不是换号。"""
        self.run_(-6, -1, "a@x.y")
        self.run_(-5, -4.5, "b@x.y")
        self.run_(-4, -3, "a@x.y")
        r = self.collect()
        self.assertNotIn("drift", [s["enter_reason"] for s in r["segments"]], r["segments"])
        self.assertEqual(r["kpi"]["rotations"], 0)

    def test_concurrency_older_than_eight_segments_is_still_seen(self):
        """原来只看最近 8 段：一个长进程开着时，第 9 段之后的异号进程会被误判 drift。"""
        self.run_(-20, -1, "a@x.y")
        for k in range(9):
            self.run_(-19 + k, -18.9 + k, "a@x.y")
        self.run_(-5, -4, "b@x.y")
        r = self.collect()
        self.assertNotIn("drift", [s["enter_reason"] for s in r["segments"]])

    def test_an_unreadable_log_directory_is_not_an_empty_lane(self):
        """★ 阶段 C 评审 codex：`Path.glob()` 把目录权限错误吞成「没有日志」。"""
        self.run_(-3, -2, "a@x.y")
        os.chmod(self.logs, 0)
        try:
            if os.access(self.logs, os.R_OK):
                self.skipTest("以 root 跑：chmod 0 挡不住读")
            r = self.collect()
        finally:
            os.chmod(self.logs, 0o755)
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["reason"], "unreadable")

    def test_a_missing_log_directory_is_just_empty(self):
        """反向：目录不存在 = agy 没装 / 没跑过，那是确实没有，不是读错。"""
        r = AR.collect(24, now=NOW, log_dir=self.d / "nope", store=self.d, gens=[])
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["segments"], [])

    def test_a_corrupt_pool_does_not_blank_the_page(self):
        self.run_(-3, -2, "a@x.y")
        (self.d / ".agy-pool.json").write_text("{bad")
        r = self.collect()
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(r["segments"]), 1)


class LoopbackRelayIsReallyUsed(unittest.TestCase):
    """§4「store 允许回环 http，代理却只认 https ⇒ 界面说走中转站，请求静默走了账号池」。"""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("proxy_stage_c", ROOT / "proxy" / "proxy.py")
        self.px = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.px)
        self.d = tempfile.TemporaryDirectory()
        d = Path(self.d.name)
        self.px.RELAY_ROUTE = d / "route.local.json"
        self.px.RELAY_STORE = d / "relays.local.json"
        self.px.RELAY_ROUTE.write_text(json.dumps({"profile": "local"}))
        self.log = mock.patch.object(self.px, "_plog")
        self.plog = self.log.start()

    def tearDown(self):
        self.log.stop()
        self.d.cleanup()

    def up(self, url):
        self.px.RELAY_STORE.write_text(json.dumps({"relays": [{
            "id": "local", "label": "L", "enabled": True, "base_url": url, "key": "sk-TESTONLY"}]}))
        self.px._relay_cache = {"v": (None, None)}
        return self.px._relay_upstream()

    def test_loopback_http_is_accepted_without_tls(self):
        for url, port in (("http://127.0.0.1:3000/v1", 3000), ("http://localhost/v1", 80)):
            with self.subTest(url=url):
                u = self.up(url)
                self.assertIsNotNone(u, "★ 回环 http 被退回账号池")
                self.assertFalse(u["tls"])
                self.assertEqual(u["port"], port)

    def test_https_keeps_tls(self):
        u = self.up("https://api.example.com/v1")
        self.assertTrue(u["tls"])
        self.assertEqual(u["port"], 443)

    def test_plaintext_to_the_internet_is_refused_and_logged(self):
        self.assertIsNone(self.up("http://api.example.com/v1"), "★ 明文把 key 发出网卡")
        self.assertTrue(any("退回账号池" in str(c) for c in self.plog.call_args_list), "拒绝了却一句不说")

    def test_the_plain_connection_is_only_taken_without_tls(self):
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        m = re.search(r"if up and not up\.get\(\"tls\", True\):\s*\n\s*conn = http\.client\.HTTPConnection\(", src)
        self.assertTrue(m, "★ `tls: False` 没接到 HTTPConnection —— 回环中转站会拿 TLS 去握明文端口")


class RelayNumbersAreNotBools(unittest.TestCase):
    """§4 存疑：`{"balance": true}` 曾被读成余额 1。"""

    def test_bool_is_not_a_balance(self):
        n = monitor.normalize({"balance": True, "usage": {"total": {"actual_cost": False}}})
        self.assertIsNone(n["balance"])

    def test_numbers_still_pass(self):
        self.assertEqual(monitor.normalize({"balance": 0})["balance"], 0)
        self.assertEqual(monitor.normalize({"remaining": 2.5})["balance"], 2.5)


class RelayViewLogic(unittest.TestCase):
    A = [{"date": "2026-10-01", "actual_cost": 10, "requests": 1}, {"date": "2026-10-02", "actual_cost": 10, "requests": 1}]
    B = [{"date": "2026-10-03", "actual_cost": 10, "requests": 1}, {"date": "2026-10-04", "actual_cost": 10, "requests": 1}]
    ALL = [["2026-10-01", "2026-10-04"]]

    def gpd(self, accts):
        return node("relayView.ts", "m.groupPerActiveDay(%s)" % json.dumps(accts))

    def test_group_per_day_sums_by_date_first(self):
        """§4 存疑：两个账户活跃日不重合时，旧算法（各自日均相加）高估。"""
        self.assertEqual(self.gpd([{"daily": self.A, "covered": self.ALL}, {"daily": self.B, "covered": self.ALL}]), 10)

    def test_group_per_day_refuses_a_partial_group(self):
        self.assertIsNone(self.gpd([{"daily": self.A, "covered": self.ALL}, None]))

    def test_a_day_not_seen_for_one_account_is_unknown(self):
        """★ 阶段 C 评审 codex：A 只被观测了今天，前几天它花没花不知道 ⇒ 不能当 0 算成精确续航。"""
        self.assertIsNone(self.gpd([{"daily": self.A, "covered": self.ALL},
                                    {"daily": [], "covered": [["2026-10-04", "2026-10-04"]]}]))

    def test_an_old_snapshot_without_covered_is_unknown(self):
        self.assertIsNone(self.gpd([{"daily": self.A, "covered": self.ALL}, {"daily": self.B}]))

    def test_requests_without_a_cost_are_unknown(self):
        b = [dict(self.B[0], actual_cost=None), self.B[1]]
        self.assertIsNone(self.gpd([{"daily": self.A, "covered": self.ALL}, {"daily": b, "covered": self.ALL}]))

    def test_a_first_failure_has_a_banner(self):
        """§4「第一次就没取到：没有旧数据就没有 stale，横幅一句原因都不说」。"""
        rows = [{"id": "r1", "label": "L", "enabled": True}]
        ents = [{"id": "r1", "ok": False, "detail": "HTTP 401"}]
        b = node("relayView.ts", "m.bannerOf(%s, %s, null)" % (json.dumps(rows), json.dumps(ents)))
        self.assertEqual(b, {"kind": "error", "acc": "L", "why": "HTTP 401"})

    def test_a_disabled_row_has_no_banner(self):
        rows = [{"id": "r1", "label": "L", "enabled": False}]
        ents = [{"id": "r1", "ok": False}]
        self.assertIsNone(node("relayView.ts", "m.bannerOf(%s, %s, null)" % (json.dumps(rows), json.dumps(ents))))


class FrontendShapes(unittest.TestCase):
    def test_logs_page_keeps_old_data_on_a_failed_refresh(self):
        s = code("pages/LogsPage.tsx")
        self.assertRegex(s, r"const fail = \(why: string\) => \{\s*if \(rotKey\.current !== key\)",
                         "★ 刷新失败一律清空 ⇒ 旧数据没了（§7.0b）")
        self.assertIn("data-rot-stale", s)

    def test_logs_page_reads_service_logs_on_every_refresh(self):
        s = code("pages/LogsPage.tsx")
        self.assertRegex(s, r"const refreshAll = useCallback\(\(h: WinH\) => \{ void load\(h\); loadSvc\(\); \}")
        self.assertRegex(s, r"setInterval\(\(\) => \{ refreshAll\(win\); \}, 30_000\)")

    def test_parallel_has_a_label(self):
        self.assertRegex(code("components/rot/RotTimeline.tsx"), r"\bparallel:\s*\"")

    def test_spark_cards_follow_the_theme(self):
        self.assertRegex(code("components/RelayUsage.tsx"), r"<ModelSparkCard\b[^>]*\bt=\{t\}")

    def test_the_spark_tooltip_follows_the_theme(self):
        """★ 阶段 C 评审 codex：浅色下浮层仍是深色半透明底，日期 1.06:1。"""
        s = code("components/relay/ModelSparkCard.tsx")
        m = re.search(r"<div data-model-tip style=\{\{([\s\S]*?)\}\}>", s)
        self.assertTrue(m)
        self.assertRegex(m.group(1), r"background: t\.isDark \? \"rgba\(10,13,16,\.6\)\" : \"rgba\(255,255,255,")
        self.assertIn("color: t.text", m.group(1))

    def test_logs_page_clears_the_old_error_with_the_old_data(self):
        s = code("pages/LogsPage.tsx")
        self.assertIn("if (rotKey.current !== key) { rotKey.current = null; setRot(null); setErr(null); }", s)

    def ring(self, rows, labels, n):
        return node("relayView.ts", "m.ringRatio(%s, %s, %d)" % (json.dumps(rows), json.dumps(labels), n))

    @staticmethod
    def acct(days, state=None, covered=(("2026-10-01", "2026-10-31"),)):
        d = {"daily": [{"date": k, "total_tokens": v, "actual_cost": v / 1000.0, "requests": 1, "cost": 0}
                       for k, v in days.items()],
             "covered": [list(c) for c in covered]}
        return {"state": state, "data": d} if state else {"data": d}

    CUR = ["2026-10-20", "2026-10-21"]

    def test_ring_ratio_uses_the_same_participants_for_both_periods(self):
        """★ 阶段 D 评审 codex：停用账户的旧数据只进上期 ⇒ ↑100% 变 ↓97.9%。两期必须同一组参与者。"""
        on = self.acct({"2026-10-18": 100, "2026-10-20": 200})
        off = self.acct({"2026-10-18": 9000}, state="disabled")
        self.assertEqual(self.ring([on], self.CUR, 2)["tok"]["txt"], "↑100.0%")
        self.assertEqual(self.ring([on, off], self.CUR, 2)["tok"]["txt"], "↑100.0%",
                         "★ 停用账户的旧数据改变了环比")

    def test_ring_ratio_counts_every_enabled_account(self):
        """阶段 C 评审：参与者 = 没停用的账户；启用账户没数据 ⇒ 不比；覆盖要连到当前窗口末日。"""
        on = self.acct({"2026-10-18": 100, "2026-10-20": 200})
        self.assertIsNone(self.ring([on, {"data": None}], self.CUR, 2), "★ 没取到数的启用账户被漏掉")
        short = self.acct({"2026-10-18": 100}, covered=(("2026-10-01", "2026-10-20"),))
        self.assertIsNone(self.ring([on, short], self.CUR, 2), "★ 覆盖没连到当前窗口末日")
        both = self.acct({"2026-10-18": 50, "2026-10-21": 150})
        self.assertEqual(self.ring([on, both], self.CUR, 2)["tok"]["txt"], "↑133.3%")

if __name__ == "__main__":
    unittest.main()
