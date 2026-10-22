"""ensure-live（keepalive 尾部 / `ensure-live`）的两条闸（全方面评审 2026-10-22，三方一致）。

① 暂停（`rotate_off`）或判死（`auth_dead`）的号**不许被换进 `~/.codex/auth.json`** ——
   `paused()` 的 docstring 要求「任何让号成为 active 的路径都过这道闸」，这里原来没过。
② 联网探测期间别的进程写进 state 的字段（额度、置顶、冷却……）**不许被整份旧 state 盖掉**；
   探测期间当值号被换过（用户手动 switch）⇒ 放弃，不覆盖用户的选择。

全部在临时 store + 临时 CODEX_HOME 里跑；联网函数（`_token_alive`）与 codex 进程检测打桩。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOUR = 3600


class _Store(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="cbx_ensure_"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        (self.dir / "auth").mkdir()
        (self.dir / "home").mkdir()
        old = {k: os.environ.get(k) for k in ("CODEX_ROTATE_STORE", "CODEX_HOME")}
        os.environ["CODEX_ROTATE_STORE"] = str(self.dir)
        os.environ["CODEX_HOME"] = str(self.dir / "home")
        try:
            loader = importlib.machinery.SourceFileLoader("cr_ensure", str(ROOT / "codex-rotate"))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            self.m = importlib.util.module_from_spec(spec)
            loader.exec_module(self.m)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(self.m.STATE, self.dir / "state.json", "夹具没隔离 —— 会写真 state.json")
        self.assertEqual(self.m.LIVE, self.dir / "home" / "auth.json", "夹具没隔离 —— 会写真 auth.json")
        self.m._codex_running = lambda: False
        self.m._attributable_quota = lambda s: None
        self.m._access_exp = lambda tok: tok.get("exp", 0)
        self.alive = {}
        self.during_probe = None
        self.m._token_alive = self._alive

    def _alive(self, tok, timeout=8):
        if self.during_probe:
            fn, self.during_probe = self.during_probe, None
            fn()
        return self.alive.get(tok.get("account_id"))

    def acct(self, aid, left_h, **slot):
        tok = {"account_id": aid, "access_token": "TESTONLY-" + aid, "exp": time.time() + left_h * HOUR}
        (self.dir / "auth" / f"{aid}.json").write_text(json.dumps({"tokens": tok}))
        return {"label": aid.lower(), "plan": "plus", "file": f"{aid}.json", **slot}

    def write(self, st):
        self.m._save_state(st)

    def disk(self):
        return json.loads((self.dir / "state.json").read_text())

    def live_aid(self):
        p = self.dir / "home" / "auth.json"
        return json.loads(p.read_text())["tokens"]["account_id"] if p.exists() else None

    def setup_pool(self, **extra):
        """A 是当值号且 JWT 只剩 1h（该换了）；B/C 是候选。"""
        slots = {"A": self.acct("A", 1), "B": self.acct("B", 100), "C": self.acct("C", 50)}
        for aid, patch in extra.items():
            slots[aid].update(patch)
        self.write({"active": "A", "active_since": 0, "slots": slots})
        (self.dir / "home" / "auth.json").write_text((self.dir / "auth" / "A.json").read_text())
        self.alive = {"A": True, "B": True, "C": True}


class PausedOrDeadNeverBecomesLive(_Store):
    def test_baseline_picks_the_freshest_candidate(self):
        """已知阳性：不暂停时 B（JWT 最新鲜）被换进来 —— 证明下面两条的「没换 B」是闸给的。"""
        self.setup_pool()
        self.m._ensure_live_healthy(self.m._state(), quiet=True)
        self.assertEqual(self.live_aid(), "B")
        self.assertEqual(self.disk()["active"], "B")

    def test_a_paused_account_is_skipped(self):
        self.setup_pool(B={"rotate_off": True})
        self.m._ensure_live_healthy(self.m._state(), quiet=True)
        self.assertEqual(self.live_aid(), "C", "★ 暂停的 B 被写进了 auth.json")

    def test_a_dead_account_is_skipped(self):
        self.setup_pool(B={"auth_dead": True})
        self.m._ensure_live_healthy(self.m._state(), quiet=True)
        self.assertEqual(self.live_aid(), "C", "★ 判死的 B 被写进了 auth.json")

    def test_nothing_moves_when_every_candidate_is_paused(self):
        self.setup_pool(B={"rotate_off": True}, C={"rotate_off": True})
        msg = self.m._ensure_live_healthy(self.m._state(), quiet=True)
        self.assertEqual(self.live_aid(), "A")
        self.assertTrue(msg.startswith("no server-healthy slot"), msg)

    def test_a_pause_written_during_the_probe_is_honoured(self):
        """★ 探测是几秒到一分钟的联网；期间用户点了「停轮换」⇒ 提交时必须按磁盘上的新状态再核一次。"""
        self.setup_pool()
        self.during_probe = lambda: self.m._mutate_state(
            lambda st: st["slots"]["B"].update(rotate_off=True))
        self.m._ensure_live_healthy(self.m._state(), quiet=True)
        self.assertNotEqual(self.live_aid(), "B", "★ 探测期间暂停的 B 仍被换进 auth.json")
        self.assertTrue(self.disk()["slots"]["B"]["rotate_off"])


class NoLostUpdate(_Store):
    def test_fields_written_during_the_probe_survive(self):
        """★★ 原实现：探测前读的 state 在探测后整份 `_save_state` ⇒ 期间 quotad 写的额度、
        用户点的置顶全被回滚（与 B15 同族）。"""
        self.setup_pool()
        q = {"primary": {"window_minutes": 300, "used_percent": 42, "resets_at": None}}

        def concurrent():
            def f(st):
                st["slots"]["C"]["quota"] = q
                st["pinned"] = ["C"]
                st["slots"]["A"]["cooling_until"] = 123
            self.m._mutate_state(f)
        self.during_probe = concurrent
        self.m._ensure_live_healthy(self.m._state(), quiet=True)
        st = self.disk()
        self.assertEqual(st["slots"]["C"].get("quota"), q, "★ 探测期间写进的额度被旧 state 盖掉")
        self.assertEqual(st.get("pinned"), ["C"], "★ 探测期间的置顶被旧 state 盖掉")
        self.assertEqual(st["slots"]["A"].get("cooling_until"), 123)
        self.assertEqual(st["active"], "B", "换号本身仍要发生")

    def test_a_manual_switch_during_the_probe_wins(self):
        """探测期间用户手动切到 C ⇒ 当值号已不是我们判过死活的那个 ⇒ 放弃，不覆盖。"""
        self.setup_pool()

        def switched():
            (self.dir / "home" / "auth.json").write_text((self.dir / "auth" / "C.json").read_text())
            self.m._mutate_state(lambda st: st.update(active="C"))
        self.during_probe = switched
        msg = self.m._ensure_live_healthy(self.m._state(), quiet=True)
        self.assertEqual(self.live_aid(), "C", "★ 覆盖了用户刚做的切换")
        self.assertEqual(self.disk()["active"], "C")
        self.assertIn("skip", msg)


if __name__ == "__main__":
    unittest.main()
