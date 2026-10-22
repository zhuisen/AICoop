"""定时 keepalive（用户 2026-10-22「#5 也去处理」）。

launchd 每小时拉起 `keepalive 48 --idle-window`：
① 不在空闲时段（本机 22:00–08:00）⇒ 一拉起就退出，**不读 state、不刷任何号**；
② 在空闲时段 ⇒ 只刷非活跃、没判死的号（活跃号永不刷 —— codex 自己的刷新器持有它）。
全部打桩：`_state` / `_refresh_slot` / `_ensure_live_healthy` / `_mutate_state` 换成夹具，不联网、不碰真 state.json。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import contextlib
import importlib.machinery
import importlib.util
import io
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    loader = importlib.machinery.SourceFileLoader("cr_keepalive", str(ROOT / "codex-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


class KeepaliveRunsOnlyWhenIdle(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.calls = []
        st = {"active": "A", "slots": {"A": {"label": "a"}, "B": {"label": "b"}, "C": {"label": "c", "auth_dead": True},
                                       "D": {"label": "d", "rotate_off": True}}}

        def state():
            self.calls.append("state")
            return st
        self.m._state = state
        self.m._refresh_slot = lambda aid, slot, **kw: (self.calls.append("refresh:" + aid), (True, "still valid"))[1]
        self.m._ensure_live_healthy = lambda s, **kw: "live healthy (no rotation)"
        self.m._slot_access_left_h = lambda slot: 100.0     # 读的是号的 auth 文件；夹具里没有
        self.m._mutate_state = lambda f: None

    def run_ka(self, idle, *args):
        self.m._in_idle = lambda *a, **k: idle
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.m.cmd_keepalive(list(args))
        return out.getvalue()

    def test_outside_the_idle_window_it_does_nothing_at_all(self):
        self.assertEqual(self.run_ka(False, "48", "--idle-window"), "")
        self.assertEqual(self.calls, [], "白天被拉起时读了 state 或刷了号")

    def test_inside_the_window_it_refreshes_inactive_live_slots_only(self):
        self.run_ka(True, "48", "--idle-window")
        refreshed = sorted(c for c in self.calls if c.startswith("refresh:"))
        self.assertEqual(refreshed, ["refresh:B", "refresh:D"], "活跃号 A 绝不刷；判死的 C 跳过；停了轮换的 D 也要保活")

    def test_without_the_flag_manual_runs_ignore_the_window(self):
        self.run_ka(False, "48")
        self.assertIn("refresh:B", self.calls, "手动 `keepalive` 不受空闲时段限制")


class TheServiceIsInstalledHourlyWithTheFlag(unittest.TestCase):
    def test_installer_emits_keepalive_hourly_with_idle_window(self):
        sh = (ROOT / "scripts/install-launchd.sh").read_text(encoding="utf-8")
        code = "\n".join(l for l in sh.splitlines() if not l.lstrip().startswith("#"))
        m = re.search(r"emit keepalive \\\n\s*'([^']*)' \\\n\s*\"\$ROT\" keepalive 48 --idle-window", code)
        self.assertIsNotNone(m, "install-launchd.sh 没有按小时装 keepalive --idle-window")
        self.assertIn("<key>StartInterval</key><integer>3600</integer>", m.group(1))
        self.assertNotIn("StartCalendarInterval", m.group(1), "日历键被外部改写丢过一次（runs = 0）")


if __name__ == "__main__":
    unittest.main()
