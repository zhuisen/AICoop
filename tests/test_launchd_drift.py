"""launchd 漂移检测（samchen #4 ②；用户 2026-10-24 选「检测 + 设置页一键重装」）。

那台机器上 7 个服务「都在跑」，所以「接入账号池 → 装常驻服务」报已装；实际是 keepalive 还是旧的 04:30 日历版、
agydawn / otel 没装、已退役的 refreshquota 每天 07:00 仍在跑。判据改成**内容**：装着的 plist 与安装器此刻会生成的逐字典比。

守的：
1. 与安装器生成的一致 ⇒ done；任一份内容不同 / 缺 ⇒ todo，并点名是哪个；
2. 逐行美化（别的工具改写过格式）不算漂移，丢了 `CODEX_ROTATE_STORE` 算；
3. 退役的 refreshquota 还装着 ⇒ todo；安装器重装时会卸掉它（清单两边一致）；
4. 安装器生成不出来 ⇒ 不是「一致」（`None`）。
真跑安装器的 `--render`（只写临时目录，不碰 launchctl）；`launchctl` 查询一律打桩。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import os
import plistlib
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import connector

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install-launchd.sh"
LABEL = "com.doushutangmu.codex-rotate."


@unittest.skipUnless(shutil.which("plutil"), "没有 plutil（非 macOS）")
class DriftIsJudgedByContent(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        self.agents, self.store = d / "agents", d / "store"
        self.agents.mkdir(), self.store.mkdir()
        old = os.environ.get("CODEXBAR_LAUNCH_AGENTS")
        os.environ["CODEXBAR_LAUNCH_AGENTS"] = str(self.agents)
        self.addCleanup(lambda: os.environ.__setitem__("CODEXBAR_LAUNCH_AGENTS", old) if old
                        else os.environ.pop("CODEXBAR_LAUNCH_AGENTS", None))
        self._svc = connector._svc_loaded
        connector._svc_loaded = lambda n: False
        self.addCleanup(lambda: setattr(connector, "_svc_loaded", self._svc))
        # 装一份「安装器此刻会生成的」进假的 LaunchAgents
        r = connector.subprocess.run(["bash", str(SCRIPT), "--render", str(self.agents)],
                                     capture_output=True, text=True,
                                     env=dict(os.environ, CODEX_ROTATE_STORE=str(self.store)))
        self.assertEqual(r.returncode, 0, r.stderr)

    def drift(self):
        return connector._launchd_drift(SCRIPT, self.store)

    def f(self, n):
        return self.agents / f"{LABEL}{n}.plist"

    def test_what_the_installer_writes_is_in_sync(self):
        self.assertEqual(sorted(p.name for p in self.agents.iterdir()),
                         sorted(f"{LABEL}{n}.plist" for n in connector.SERVICES), "★ 前提：7 份都生成了")
        self.assertEqual(self.drift(), {"stale": [], "retired": []})

    def test_the_old_calendar_keepalive_is_stale(self):
        d = plistlib.loads(self.f("keepalive").read_bytes())
        d.pop("StartInterval")
        d["StartCalendarInterval"] = {"Hour": 4, "Minute": 30}
        self.f("keepalive").write_bytes(plistlib.dumps(d))
        self.assertEqual(self.drift()["stale"], ["keepalive"])

    def test_a_missing_service_is_stale(self):
        self.f("otel").unlink()
        self.assertEqual(self.drift()["stale"], ["otel"])

    def test_pretty_printing_is_not_drift_but_a_lost_store_is(self):
        d = plistlib.loads(self.f("quotad").read_bytes())
        self.f("quotad").write_bytes(plistlib.dumps(d, sort_keys=False))   # 逐行美化
        self.assertEqual(self.drift()["stale"], [], "只改格式被当成漂移 —— 恒响的闸会被无视")
        d["EnvironmentVariables"] = {}
        self.f("quotad").write_bytes(plistlib.dumps(d))
        self.assertEqual(self.drift()["stale"], ["quotad"], "★ 丢了 CODEX_ROTATE_STORE 却报一致")

    def test_a_retired_service_still_installed_is_reported(self):
        self.f("refreshquota").write_bytes(plistlib.dumps({"Label": LABEL + "refreshquota"}))
        self.assertEqual(self.drift()["retired"], ["refreshquota"])

    def test_an_installer_that_cannot_render_is_not_in_sync(self):
        bad = Path(tempfile.mkdtemp()) / "install-launchd.sh"
        self.addCleanup(shutil.rmtree, bad.parent, True)
        # 全部写出来了、却以非 0 退出（装一半的那种）—— 只有退出码能挡住
        bad.write_text(f'bash "{SCRIPT}" "$@" >/dev/null || exit 1\nexit 3\n')
        self.assertIsNone(connector._launchd_drift(bad, self.store), "生成失败却报了一个结果")


class ThePlanStepSaysWhatDrifted(unittest.TestCase):
    def test_stale_and_retired_make_the_step_todo(self):
        orig = connector._launchd_drift, connector._svc_loaded
        self.addCleanup(lambda: (setattr(connector, "_launchd_drift", orig[0]),
                                 setattr(connector, "_svc_loaded", orig[1])))
        connector._svc_loaded = lambda n: True
        for drift, want in (({"stale": [], "retired": []}, "done"),
                            ({"stale": ["keepalive"], "retired": []}, "todo"),
                            ({"stale": [], "retired": ["refreshquota"]}, "todo")):
            connector._launchd_drift = lambda s, st, d=drift: d
            step = next(x for x in connector.plan(ROOT, ROOT)["steps"] if x["id"] == "services")
            self.assertEqual(step["state"], want, (drift, step["detail"]))
            for n in drift["stale"] + drift["retired"]:
                self.assertIn(n, step["detail"], "要点名是哪个服务")


class TheRetiredListAgrees(unittest.TestCase):
    def test_installer_and_connector_retire_the_same_services(self):
        s = SCRIPT.read_text(encoding="utf-8")
        m = re.search(r"^for n in ([a-z ]+); do\n    if launchctl print", s, re.M)
        self.assertIsNotNone(m, "安装器里卸退役服务的那段不见了")
        self.assertEqual(m.group(1).split(), connector.RETIRED_SERVICES)


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HARNESS = "http://127.0.0.1:3304/harness.html?nav=settings&conn=drift"
TRAP = """() => { window.__applied = []; let inner;
  Object.defineProperty(window, '__TAURI_INTERNALS__', { configurable: true, get() { return inner; },
    set(v) { const orig = v.invoke.bind(v);
      v.invoke = async (c, a, o) => { if (c === 'connector_apply') window.__applied.push(a.steps); return orig(c, a, o); };
      inner = v; } }); }"""


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheSettingsRowOnTheRealBundle(unittest.TestCase):
    def test_drift_shows_one_row_and_the_button_reinstalls_services(self):
        try:
            from playwright.sync_api import sync_playwright
            import urllib.request
            urllib.request.urlopen(HARNESS, timeout=2).read(1)
        except Exception:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        with sync_playwright() as p:
            br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
            pg = br.new_page(viewport={"width": 860, "height": 560})
            pg.add_init_script(script=f"({TRAP})()")
            pg.goto(HARNESS, timeout=30000)
            pg.wait_for_selector("[data-services-drift]", timeout=8000)
            text = pg.inner_text("[data-services-drift]")
            oneclick = pg.query_selector("[data-connector-oneclick]") is not None
            pg.click("[data-services-reinstall]")
            pg.wait_for_timeout(400)
            applied = pg.evaluate("() => window.__applied")
            br.close()
        for n in ("keepalive", "refreshquota", "重装服务"):
            self.assertIn(n, text, "要点名过时的服务")
        self.assertFalse(oneclick, "只是过时（一个不缺）时一键区又报了一项 —— 同一件事两个按钮")
        self.assertEqual(applied, [["runtime", "services"]], "★ 点「重装服务」要真的重装服务")


if __name__ == "__main__":
    unittest.main()
