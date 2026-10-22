"""阶段 E（§10 后端 / 账号池）—— 全方面评审 2026-10-22 的修复闸。逐条对应
`~/Downloads/aicoop_full_review_20261022/SUMMARY.md` §10。

全部在临时目录里跑：代理的 `STATE` / `AUTH_DIR` / `LIVE` / 锁文件逐个改指；agy 池走 `AGY_POOL_STORE`；
grok 用不存在的 `GROK_AUTH_PATH`（读不到 auth 就不发请求）。不联网：OAuth 刷新的 `urlopen` 打桩。
"""
import base64
import importlib.machinery
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

try:
    from . import _isolation  # noqa: F401  ★ 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def _load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    loader.exec_module(m)
    return m


def _jwt(exp):
    body = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return "h." + body + ".s"


class _Proxy(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="stage-e-proxy-"))
        self.px = _load(ROOT / "proxy" / "proxy.py", "proxy_stage_e")
        (self.d / "auth").mkdir()
        for k, v in {"STATE": "state.json", "STATE_LOCK": ".state.lock", "REFRESH_LOCK": ".refresh.lock",
                     "LIVE": "live-auth.json"}.items():
            setattr(self.px, k, self.d / v)
        self.px.AUTH_DIR = self.d / "auth"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)


class ANetworkBlipDoesNotKillAnAccount(_Proxy):
    """§10：强制刷新时网络抖一下 ⇒ 原来返回旧 token，调用方见 `token2 == token` 就 `_mark_dead`。"""

    def setUp(self):
        super().setUp()
        self.old = _jwt(time.time() - 10)
        (self.d / "auth" / "b.json").write_text(json.dumps({"tokens": {
            "access_token": self.old, "refresh_token": "rt", "account_id": "B"}}))
        (self.d / "state.json").write_text(json.dumps({"active": "A", "slots": {"B": {"file": "b.json"}}}))
        self.slot = {"file": "b.json", "label": "b"}

    def refresh_with(self, exc):
        real = self.px.urllib.request.urlopen

        def boom(*_a, **_k):
            raise exc
        self.px.urllib.request.urlopen = boom
        try:
            why = {}
            tok, _ = self.px._slot_token("B", self.slot, force=True, why=why)
        finally:
            self.px.urllib.request.urlopen = real
        return tok, why

    def test_a_network_error_is_transient(self):
        tok, why = self.refresh_with(urllib.error.URLError("timed out"))
        self.assertEqual(tok, self.old)
        self.assertTrue(why.get("transient"), "★ 连不上被当成了凭证判决")

    def test_a_server_5xx_is_transient(self):
        tok, why = self.refresh_with(urllib.error.HTTPError("u", 503, "x", {}, None))
        self.assertTrue(why.get("transient"))

    def test_invalid_grant_is_a_verdict(self):
        """反向：服务端明确拒绝（400 invalid_grant）⇒ 不是抖动，调用方照旧标死。"""
        tok, why = self.refresh_with(urllib.error.HTTPError("u", 400, "invalid_grant", {}, None))
        self.assertFalse(why.get("transient"), "★ 真掉登录被当成抖动，号永远不标死")

    def test_a_switch_race_is_transient(self):
        (self.d / "state.json").write_text(json.dumps({"active": "B", "slots": {"B": {"file": "b.json"}}}))
        tok, why = self.refresh_with(urllib.error.URLError("x"))
        self.assertIsNone(tok)
        self.assertTrue(why.get("transient"), "★ 刚切成当值号的号被标死")

    def test_a_slot_that_is_already_live_is_transient(self):
        """★ 阶段 E 评审两方：切号先写 LIVE 再写 `active`，强刷时命中 `use_live` 快路径 —— 原来不填 transient。"""
        (self.d / "state.json").write_text(json.dumps({"active": "B", "slots": {"B": {"file": "b.json"}}}))
        (self.d / "live-auth.json").write_text(json.dumps({"tokens": {"access_token": self.old, "account_id": "B"}}))
        tok, why = self.refresh_with(urllib.error.URLError("x"))
        self.assertIsNone(tok)
        self.assertTrue(why.get("transient"), "★ 当值号 401 被标死（它的 token 我们只读、从没问过服务端）")

    def test_a_successful_refresh_lands_in_the_state_slot(self):
        """★ 阶段 E 评审 codex：代理刷新只写凭证文件，state 里这个号的 `last_refresh` 一直是旧的。"""
        import contextlib
        new_at = _jwt(time.time() + 3600)

        class R(contextlib.AbstractContextManager):
            def read(self):
                return json.dumps({"access_token": new_at}).encode()

            def __exit__(self, *a):
                return False
        real = self.px.urllib.request.urlopen
        self.px.urllib.request.urlopen = lambda *a, **k: R()
        try:
            tok, _ = self.px._slot_token("B", self.slot, force=True, why={})
        finally:
            self.px.urllib.request.urlopen = real
        self.assertEqual(tok, new_at)
        st = json.loads((self.d / "state.json").read_text())
        auth = json.loads((self.d / "auth" / "b.json").read_text())
        self.assertEqual(st["slots"]["B"].get("last_refresh"), auth["last_refresh"])

    def test_an_older_refresh_never_overwrites_a_newer_one(self):
        """★ 阶段 F 评审 codex：两次强刷以相反顺序拿到 state 锁时，旧时间盖新时间。"""
        (self.d / "state.json").write_text(json.dumps({"active": "A", "slots": {"B": {
            "file": "b.json", "last_refresh": "2999-01-01T00:00:00.000000Z"}}}))
        import contextlib

        class R(contextlib.AbstractContextManager):
            def read(self):
                return json.dumps({"access_token": _jwt(time.time() + 3600)}).encode()

            def __exit__(self, *a):
                return False
        real = self.px.urllib.request.urlopen
        self.px.urllib.request.urlopen = lambda *a, **k: R()
        try:
            self.px._slot_token("B", self.slot, force=True, why={})
        finally:
            self.px.urllib.request.urlopen = real
        st = json.loads((self.d / "state.json").read_text())
        self.assertEqual(st["slots"]["B"]["last_refresh"], "2999-01-01T00:00:00.000000Z")

    def test_the_handler_skips_instead_of_marking_dead(self):
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        i = src.index("token2, account_id2 = _slot_token(aid, slot, force=True, why=why)")
        j = src.index("_mark_dead(aid, (token2 or token)[-16:])", i)
        self.assertRegex(src[i:j], r"if why\.get\(\"transient\"\):\s*\n\s*_plog\([^\n]*\)\s*\n\s*continue",
                         "★ 抖动判断必须在 `_mark_dead` 之前、并直接换号")


class CoolingWaitsForTheSpentWindow(_Proxy):
    """§10：冷却只看 `primary.resets_at`；Plus 周额度用光时 5 h 一过又撞一次 429。"""

    def put(self, quota):
        (self.d / "state.json").write_text(json.dumps({"slots": {"A": {"quota": quota}}}))

    def cooled(self):
        return json.loads((self.d / "state.json").read_text())["slots"]["A"]["cooling_until"]

    def test_weekly_spent_cools_until_the_weekly_reset(self):
        now = time.time()
        wk = now + 3 * 86400
        self.put({"primary": {"used_percent": 20, "resets_at": now + 3600},
                  "secondary": {"used_percent": 100, "resets_at": wk}})
        self.px._cool("A")
        self.assertAlmostEqual(self.cooled(), wk + 60, delta=1)

    def test_still_cooling_after_the_5h_reset_while_the_week_is_spent(self):
        now = time.time()
        sl = {"cooling_until": now + 86400,
              "quota": {"primary": {"used_percent": 20, "resets_at": now - 60},
                        "secondary": {"used_percent": 100, "resets_at": now + 86400}}}
        self.assertTrue(self.px.cooling(sl, now), "★ 5h 先过了重置点就当它回满了")

    def test_a_spent_5h_window_still_caps_at_its_reset(self):
        """反向：5 h 见底、周没满 ⇒ 仍按 5 h 的重置点（别一律拉到周）。"""
        now = time.time()
        r5 = now + 1800
        self.put({"primary": {"used_percent": 100, "resets_at": r5},
                  "secondary": {"used_percent": 40, "resets_at": now + 5 * 86400}})
        self.px._cool("A")
        self.assertAlmostEqual(self.cooled(), r5 + 60, delta=1)

    def test_a_stale_cooling_still_expires(self):
        """反向：没有窗口见底、primary 已过重置点 ⇒ 冷却作废（原判据保留）。"""
        now = time.time()
        sl = {"cooling_until": now + 3600, "quota": {"primary": {"used_percent": 30, "resets_at": now - 60}}}
        self.assertFalse(self.px.cooling(sl, now))



class AFreshReadingWithRoomLiftsTheCooling(_Proxy):
    """用户 2026-10-23：「官方重置的时候也没有取消冻结。识别到 5H 额度不是 0 的，就应该取消冻结」。
    原判据只认「快照里 primary 的重置点已过」；重置后 quotad 读到新快照，`resets_at` 换成下一个窗口（在未来），
    号就一直冻到 `cooling_until`。"""

    def sl(self, used5, captured_off, *, wk=20, cooled=True):
        now = time.time()
        d = {"cooling_until": now + 4 * 3600,
             "quota": {"captured_at": now + captured_off,
                       "primary": {"used_percent": used5, "resets_at": now + 5 * 3600},
                       "secondary": {"used_percent": wk, "resets_at": now + 5 * 86400}}}
        if cooled:
            d["cooled_at"] = now - 600
        return d, now

    def test_after_the_official_reset_a_fresh_reading_unfreezes(self):
        sl, now = self.sl(0, -60)
        self.assertTrue(self.px.usable("A", sl, now), "★ 重置后读到 5h 0%，号仍被冻着")

    def test_a_reading_from_before_the_429_proves_nothing(self):
        sl, now = self.sl(40, -1200)
        self.assertTrue(self.px.cooling(sl, now), "★ 冷却之前拍的快照不能解冻（会立刻再撞 429）")

    def test_still_spent_stays_frozen(self):
        sl, now = self.sl(100, -60)
        self.assertTrue(self.px.cooling(sl, now))
        sl, now = self.sl(10, -60, wk=100)
        self.assertTrue(self.px.cooling(sl, now), "★ 5h 有余量但周见底 ⇒ 仍冷却")

    def test_without_cooled_at_nothing_changes(self):
        """旧数据 / 手动 `cool` 没有 `cooled_at` ⇒ 不判（保持原行为）。"""
        sl, now = self.sl(0, -60, cooled=False)
        self.assertTrue(self.px.cooling(sl, now))

    def test_cool_stamps_cooled_at(self):
        now = time.time()
        (self.d / "state.json").write_text(json.dumps({"slots": {"A": {"quota": {
            "primary": {"used_percent": 100, "resets_at": now + 1800}}}}}))
        self.px._cool("A")
        sl = json.loads((self.d / "state.json").read_text())["slots"]["A"]
        self.assertAlmostEqual(sl["cooled_at"], now, delta=5)


class WritingARecoveredReadingClearsTheCooling(unittest.TestCase):
    """UI / CLI 各处直接比 `cooling_until`；只改代理的读判据，界面仍显示冻结 ⇒ 写额度时就删。"""

    @classmethod
    def setUpClass(cls):
        cls.cr = _load(ROOT / "codex-rotate", "codex_rotate_stage_e_uncool")

    def st(self):
        now = time.time()
        return {"slots": {"A": {"cooling_until": now + 4 * 3600, "cooled_at": now - 600}}}, now

    def q(self, now, used5, wk=20):
        return {"captured_at": now, "primary": {"used_percent": used5, "resets_at": now + 5 * 3600},
                "secondary": {"used_percent": wk, "resets_at": now + 5 * 86400}}

    def test_a_reading_with_room_clears_it(self):
        st, now = self.st()
        self.cr._patch_slot(st, "A", {"quota": self.q(now, 0), "quota_status": "ok"})
        self.assertNotIn("cooling_until", st["slots"]["A"])
        self.assertNotIn("cooled_at", st["slots"]["A"])

    def test_a_spent_reading_keeps_it(self):
        st, now = self.st()
        self.cr._patch_slot(st, "A", {"quota": self.q(now, 100)})
        self.assertIn("cooling_until", st["slots"]["A"])

    def test_other_patches_do_not_touch_it(self):
        st, now = self.st()
        self.cr._patch_slot(st, "A", {"label": "x"})
        self.assertIn("cooling_until", st["slots"]["A"])


class AnUnreadablePoolIsNeverOverwritten(unittest.TestCase):
    """§10：`agy/pool.load()` 读失败返回空池，之后任何 save 都把整池登记抹掉。"""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="stage-e-pool-"))
        self.env = dict(os.environ, AGY_POOL_STORE=str(self.d), AGY_KEYRING="0")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)

    def pool(self):
        os.environ["AGY_POOL_STORE"] = str(self.d)
        try:
            return _load(ROOT / "agy" / "pool.py", "agy_pool_stage_e")
        finally:
            os.environ["AGY_POOL_STORE"] = _isolation_store

    def test_a_corrupt_file_refuses_to_save(self):
        (self.d / ".agy-pool.json").write_text("{ not json")
        P = self.pool()
        p = P.load()
        self.assertEqual(p["accounts"], {})
        self.assertTrue(p.get(P.UNREADABLE))
        with self.assertRaises(P.PoolUnreadable):
            P.save(p)
        self.assertEqual((self.d / ".agy-pool.json").read_text(), "{ not json", "★ 坏文件被空池覆盖")

    def test_a_missing_file_is_an_empty_writable_pool(self):
        """反向：文件不存在 = 确实没有，照常能写（别把「拒绝写」扩到首次使用）。"""
        P = self.pool()
        p = P.load()
        self.assertFalse(p.get(P.UNREADABLE))
        P.save(p)
        self.assertTrue((self.d / ".agy-pool.json").exists())

    def test_the_cli_says_why_and_leaves_the_file(self):
        (self.d / ".agy-pool.json").write_text('{"accounts": []}')
        r = subprocess.run([sys.executable, str(ROOT / "agy-rotate"), "auto-switch", "--off"],
                           capture_output=True, text=True, env=self.env, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertRegex(r.stderr + r.stdout, r"^✗ 读不出 .*形状不对")
        self.assertNotIn("Traceback", r.stderr, "★ 没接住，用户看到的是一串栈")
        self.assertEqual((self.d / ".agy-pool.json").read_text(), '{"accounts": []}')

    def test_the_board_discloses_it(self):
        (self.d / ".agy-pool.json").write_text("{ not json")
        P = self.pool()
        self.assertTrue(P.board(P.load(), None).get("pool_error"), "★ 读不了的池在界面上看着像空池")


_isolation_store = os.environ.get("AGY_POOL_STORE", "")


class GrokCarriesTheLastReadingWithoutAuth(unittest.TestCase):
    """§10：`grok-quota` 读不到 auth 时输出 `last_good: None`，采样器覆盖 sidecar，旧读数丢失。"""

    def test_prev_last_good_survives(self):
        d = Path(tempfile.mkdtemp(prefix="stage-e-grok-"))
        prev = d / "prev.json"
        prev.write_text(json.dumps({"fetched_at": 1000, "accounts": [{
            "account_key": "k1", "available": True, "quota": {"used_percent": 35, "period_end": 2000}}]}))
        env = dict(os.environ, GROK_AUTH_PATH=str(d / "nope.json"), GROK_BILLING_HOST="127.0.0.1:9")
        r = subprocess.run([sys.executable, str(ROOT / "grok-quota"), "--prev", str(prev)],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        accs = json.loads(r.stdout)["accounts"]
        self.assertEqual([a["account_key"] for a in accs], ["k1"])
        self.assertEqual(accs[0]["last_good"]["used_percent"], 35, "★ 读不到 auth 就把上次的读数丢了")
        self.assertIsNone(accs[0]["quota"], "失败态 quota 必须是 None")

    def test_no_prev_still_gives_one_displayable_row(self):
        """反向：没有上一份 ⇒ 仍出一条可展示的失败记录，不是空数组。"""
        d = Path(tempfile.mkdtemp(prefix="stage-e-grok-"))
        env = dict(os.environ, GROK_AUTH_PATH=str(d / "nope.json"), GROK_BILLING_HOST="127.0.0.1:9")
        r = subprocess.run([sys.executable, str(ROOT / "grok-quota")],
                           capture_output=True, text=True, env=env, timeout=60)
        accs = json.loads(r.stdout)["accounts"]
        self.assertEqual(len(accs), 1)
        self.assertFalse(accs[0]["available"])


class SamplersStopHammeringAfterAReset(unittest.TestCase):
    """§10：采样器跨过重置点后读数不变 / 读失败时 `last_write` 不前进，最长 30 分钟按 5 s 一次打上游。"""

    SAMPLERS = [("grok-quota-sampler", "grok_sampler_stage_e"),
                ("traffic/agy_quota_sampler.py", "agy_sampler_stage_e")]

    def test_fast_polling_is_bounded_after_the_reset(self):
        for path, _ in self.SAMPLERS:
            src = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn("crossed = crossed and now - nxt < RESET_FAST_SECS", src, path)

    def test_importing_does_not_install_a_signal_handler(self):
        """★ 原来模块顶层就装 SIGTERM handler：测试进程 import 它之后，被 SIGTERM 时抛 SystemExit（阶段 B 全套
        闸里的一条报错就是这么来的）。只在 `__main__` 里装。"""
        for path, name in self.SAMPLERS:
            before = signal.getsignal(signal.SIGTERM)
            _load(ROOT / path, name)
            self.assertIs(signal.getsignal(signal.SIGTERM), before, path)


class AgyLongCommandsLeaveTheShortLock(unittest.TestCase):
    """§10：`AGY_LOCK` 把 30–120 s 的 probe / dawn-probe 和毫秒级的 live / switch / pin 串在一起。
    拆锁之前必须先把两样兜住，这里各一条闸；拆锁本身由 `cargo test agy_lock` 守。"""

    SRC = (ROOT / "agy-rotate").read_text(encoding="utf-8")

    def fn(self, name):
        i = self.SRC.index("\ndef %s(" % name)
        j = self.SRC.find("\ndef ", i + 1)
        return "\n".join(re.sub(r"#.*", "", ln) for ln in self.SRC[i:j].splitlines())

    def test_switch_is_refused_while_a_probe_holds_the_keychain(self):
        import fcntl
        d = Path(tempfile.mkdtemp(prefix="stage-e-sw-"))
        (d / ".agy-pool.json").write_text(json.dumps({"accounts": {"s1": {"label": "x", "email": "x@y.z"}}}))
        lk = open(d / ".agy-probe.lock", "w")
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            r = subprocess.run([sys.executable, str(ROOT / "agy-rotate"), "switch", "x"], capture_output=True,
                               text=True, env=dict(os.environ, AGY_POOL_STORE=str(d), AGY_KEYRING="0"), timeout=60)
        finally:
            lk.close()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("探针正在跑", r.stderr + r.stdout, "★ 探针临时切号时还能切 ⇒ finally 把你切的号冲掉")

    def test_switch_and_auto_hold_the_probe_lock_around_the_install(self):
        for name in ("cmd_switch", "cmd_auto"):
            b = self.fn(name)
            self.assertIn("lk = _probe_lock()", b, name)
            self.assertLess(b.index("lk = _probe_lock()"), b.index("P.install_live(cred)"), name)
            self.assertIn("lk.close()", b[b.index("P.install_live(cred)"):], name)

    def _pool_dir(self, accounts):
        d = Path(tempfile.mkdtemp(prefix="stage-e-agy-"))
        (d / ".agy-pool.json").write_text(json.dumps({"accounts": accounts}))
        return d, dict(os.environ, AGY_POOL_STORE=str(d), AGY_KEYRING="0")

    def test_remove_is_refused_while_a_probe_holds_the_keychain(self):
        """★ 阶段 E 评审 codex：探针把原号 A 临时换成 B 时删 A，「不是当前号」会放行，探针就装不回去了。"""
        import fcntl
        d, env = self._pool_dir({"s1": {"label": "x"}, "s2": {"label": "y"}})
        lk = open(d / ".agy-probe.lock", "w")
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            r = subprocess.run([sys.executable, str(ROOT / "agy-rotate"), "remove", "x"],
                               capture_output=True, text=True, env=env, timeout=60)
        finally:
            lk.close()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("探针正在跑", r.stderr + r.stdout)
        self.assertIn("s1", json.loads((d / ".agy-pool.json").read_text())["accounts"])

    def test_two_concurrent_rotate_offs_never_empty_the_pool(self):
        """★ 阶段 E 评审 codex（双线程复现）：两个 `rotate --off` 都在锁外看到对方还开着，合并后全池关完。"""
        from concurrent.futures import ThreadPoolExecutor
        for _ in range(4):
            d, env = self._pool_dir({"s1": {"label": "x"}, "s2": {"label": "y"}})
            run = lambda name: subprocess.run([sys.executable, str(ROOT / "agy-rotate"), "rotate", name, "--off"],  # noqa: E731
                                              capture_output=True, text=True, env=env, timeout=60)
            with ThreadPoolExecutor(2) as ex:
                list(ex.map(run, ["x", "y"]))
            accs = json.loads((d / ".agy-pool.json").read_text())["accounts"]
            self.assertTrue(any(not a.get("rotate_off") for a in accs.values()), "★ 两个都关掉了：%s" % accs)

    def test_probe_reads_its_restore_baseline_after_taking_the_lock(self):
        b = self.fn("cmd_probe")
        self.assertLess(b.index("lk = _probe_lock()"), b.index("pool = P.load()"),
                        "★ 先记原号再拿锁 ⇒ 期间别人切了号，探针结束时照样把旧号装回去")
        self.assertLess(b.index("lk = _probe_lock()"), b.index("live = _mark_live(pool)"))

    def test_no_command_saves_a_pool_it_read_outside_the_lock(self):
        """读在锁外、整份 save 在锁内 ⇒ 期间别的进程写的字段被回滚。每个 `P.save(` 之前、同一把锁里必须重读过。"""
        bad = []
        for m in re.finditer(r"\ndef (cmd_\w+)\(", self.SRC):
            b = self.fn(m.group(1))
            for sv in re.finditer(r"P\.save\(", b):
                lock = b.rfind("with P._lock(P.POOL)", 0, sv.start())
                if lock < 0 or "P.load()" not in b[lock:sv.start()]:
                    bad.append(m.group(1))
        self.assertEqual(bad, [], "★ 这些命令用锁外读的池整份 save；改用 `P.merge_back` 或在锁内重读")


class BareCodexIsRecognisedByItsExecutable(unittest.TestCase):
    """§10 存疑（本机核实成立）：`_codex_running()` 只认三种路径片段，npm 版真正在跑的两个进程一个都对不上。"""

    @classmethod
    def setUpClass(cls):
        cls.cr = _load(ROOT / "codex-rotate", "codex_rotate_stage_e")

    def test_the_real_install_shapes_are_seen(self):
        for line in ["123 node /u/.local/npm-global/lib/node_modules/@openai/codex/bin/codex.js resume",
                     "124 /u/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex exec",
                     "125 /opt/homebrew/bin/codex", "126 /bin/bash /u/.local/bin/codex"]:
            self.assertTrue(self.cr._is_bare_codex_line(line), "★ 漏认：" + line)

    def test_what_must_not_count(self):
        for line in ["127 node /u/codex.js --profile rotateproxy resume",          # 代理会话不碰 auth.json
                     "128 /u/vendor/x/bin/codex-code-mode-host",                  # codex 的辅助进程
                     "129 python3 /u/codex-account-rotator/codex-rotate keepalive",
                     "130 vim notes-about-codex.md",
                     "export CODEX_HOME=/u/.codex codex"]:                        # 别的多行命令串的续行
            self.assertFalse(self.cr._is_bare_codex_line(line), "★ 误认：" + line)

    def test_windows_command_lines_have_no_pid(self):
        self.assertTrue(self.cr._is_bare_codex_line('"C:\\Users\\x\\codex.exe" resume', pid_first=False))


class HeadroomIgnoresAWindowThatAlreadyReset(unittest.TestCase):
    """§10 存疑：`_headroom` 不判窗口过期 —— 过了重置点、快照又拍在重置之前，那是上一个窗口的读数。"""

    @classmethod
    def setUpClass(cls):
        cls.cr = _load(ROOT / "codex-rotate", "codex_rotate_stage_e_hr")

    def test_a_stale_spent_window_does_not_pin_headroom_to_zero(self):
        now = time.time()
        sl = {"quota": {"captured_at": now - 7200,
                        "primary": {"window_minutes": 300, "used_percent": 100, "resets_at": now - 600},
                        "secondary": {"window_minutes": 10080, "used_percent": 40, "resets_at": now + 86400}}}
        self.assertEqual(self.cr._headroom(sl), 60.0)

    def test_a_reading_taken_after_the_reset_still_counts(self):
        """反向：快照晚于重置点 ⇒ 读数属于新窗口，照常采信。"""
        now = time.time()
        sl = {"quota": {"captured_at": now - 60,
                        "primary": {"window_minutes": 300, "used_percent": 90, "resets_at": now - 600}}}
        self.assertEqual(self.cr._headroom(sl), 10.0)

    def test_every_window_stale_is_unknown(self):
        now = time.time()
        sl = {"quota": {"captured_at": now - 7200,
                        "primary": {"window_minutes": 300, "used_percent": 100, "resets_at": now - 600}}}
        self.assertIsNone(self.cr._headroom(sl), "★ 全部过期 ⇒ 未知，不是 0")


class AgyPoolWritesAreBroadcast(unittest.TestCase):
    """§10 存疑（核实成立）：`switchTo` / `health` / `probe` 改了池却不广播，另一个 webview 要等下次轮询。"""

    def test_every_pool_write_emits(self):
        src = (ROOT / "codexbar" / "src" / "hooks" / "useAgyPool.ts").read_text(encoding="utf-8")
        src = re.sub(r"/\*[\s\S]*?\*/", "", src)
        src = re.sub(r"(?<![:/\"'])//[^\n]*", "", src)
        for name in ("switchTo", "runThen", "runTagged", "runQuota", "setAuto"):
            i = src.index("const %s = useCallback(" % name)
            j = src.index("]);", i)              # 依赖数组收尾 —— 只看这一个 useCallback
            self.assertIn("emit(POOL_EVT)", src[i:j], "★ %s 写了池却不广播" % name)


if __name__ == "__main__":
    unittest.main()
