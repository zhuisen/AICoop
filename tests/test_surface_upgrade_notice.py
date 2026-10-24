"""升级提示：原来开着「刘海屏版本」的人，v2.1.2 起托盘会被藏起来（samchen #5 ③）。

用户 2026-10-24 选「保持刘海屏 + 提示一次」：
1. 选的是刘海屏、刘海真的显示出来（`set_notch_hud` 回 `active: true`）、还没说过 ⇒ 发一次系统通知，并记下「说过了」；
2. 说过了 ⇒ 不再发；刘海没显示（没有刘海屏，托盘本来就在）⇒ 不发；
3. 没有通知权限发不出去 ⇒ 打开主窗口停在设置页（图标没了又没人说，用户就找不到 app）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import unittest
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HARNESS = "http://127.0.0.1:3304/harness.html?nav=home"

TRAP = """(cfg) => {
  window.__calls = [];
  // 通知插件走 `window.Notification`（Tauri 在 webview 里换成系统通知），不走 IPC —— 打桩它
  function N(title, opts) { window.__calls.push({ c: 'notify', a: { title: title, body: opts && opts.body } }); }
  N.permission = cfg.permitted ? 'granted' : 'denied';
  N.requestPermission = async () => N.permission;
  Object.defineProperty(window, 'Notification', { configurable: true, get() { return N; } });
  const origSet = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) {
    if (k === 'codexbar_settings' && cfg.seed && !window.__seeded) {
      window.__seeded = true;
      try { v = JSON.stringify(Object.assign(JSON.parse(v), cfg.seed)); } catch (e) {}
    }
    return origSet.call(this, k, v);
  };
  let inner;
  Object.defineProperty(window, '__TAURI_INTERNALS__', { configurable: true,
    get() { return inner; },
    set(v) { const orig = v.invoke.bind(v);
      v.invoke = async (c, a, o) => {
        if (c.startsWith('plugin:notification') || c === 'set_notch_hud' || c === 'set_main_visible') window.__calls.push({ c, a });
        if (c === 'set_notch_hud') return { active: cfg.active, reason: cfg.active ? null : 'no_notch' };
        if (c === 'plugin:notification|is_permission_granted') return cfg.permitted;
        if (c === 'plugin:notification|request_permission') return cfg.permitted ? 'granted' : 'denied';
        if (c.startsWith('plugin:notification')) return null;
        return orig(c, a, o); };
      inner = v; } });
}"""

PROBE = """() => { let st = null; try { st = JSON.parse(localStorage.getItem('codexbar_settings')); } catch (e) {}
  return { calls: window.__calls, noticed: st && st.surfaceNoticed,
           settingsPage: !!document.querySelector('[data-notch-toggle]') }; }"""


def _run(cfg):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        ctx = br.new_context(viewport={"width": 1200, "height": 800})
        ctx.add_init_script(script=f"({TRAP})({json.dumps(cfg)})")
        pg = ctx.new_page()
        pg.goto(HARNESS, timeout=30000)
        pg.wait_for_timeout(2000)
        r = pg.evaluate(PROBE)
        br.close()
    return r


def sent(r):
    return [c for c in r["calls"] if c["c"] == "notify"]


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class OnTheRealBundle(unittest.TestCase):
    def _get(self, cfg):
        r = _run(cfg)
        if r is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        self.assertIn({"c": "set_notch_hud", "a": {"on": True}}, r["calls"], "前提：选的是刘海屏，启动时重发")
        return r

    def test_an_upgrading_notch_user_is_told_once(self):
        r = self._get({"seed": {"notchHud": True}, "active": True, "permitted": True})
        self.assertEqual(len(sent(r)), 1, "★★ 托盘藏起来了却没说一声")
        body = json.dumps(sent(r)[0]["a"], ensure_ascii=False)
        self.assertIn("显示位置", body, "要说清楚去哪改回来")
        self.assertIs(r["noticed"], True, "说过了要记下")
        again = self._get({"seed": {"notchHud": True, "surfaceNoticed": True}, "active": True, "permitted": True})
        self.assertEqual(sent(again), [], "只说一次")

    def test_no_notch_screen_means_nothing_to_say(self):
        r = self._get({"seed": {"notchHud": True}, "active": False, "permitted": True})
        self.assertEqual(sent(r), [], "没有刘海屏时托盘照常在，不用提示")
        self.assertIsNot(r["noticed"], True, "没说就不能记成说过")

    def test_without_notification_permission_the_settings_page_opens(self):
        r = self._get({"seed": {"notchHud": True}, "active": True, "permitted": False})
        self.assertEqual(sent(r), [])
        self.assertIn({"c": "set_main_visible", "a": {"show": True}}, r["calls"], "★ 发不出通知就当面说")
        self.assertTrue(r["settingsPage"], "停在设置页（显示位置那一行在）")


if __name__ == "__main__":
    unittest.main()
