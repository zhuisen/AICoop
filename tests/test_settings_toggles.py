"""设置页三个开关（交接包 2026-10-19 · F6）：外观（日夜）· 刘海屏版本 · 在跑时显示 t/s。

## 守的
1. **三行都在**，默认值与交接包一致：刘海屏版本**关**、在跑时显示 t/s **开**、外观深色。
2. **t/s 开关驱动 Rust**：`set_tps_tray(enabled)`。Rust 的 `tray_pill::ENABLED` 默认 **false**、进程内 atomic ⇒
   默认开**只能**靠 App.tsx 启动时重发（同 `set_tray_style`）。少了这一句，开关显示「开」、托盘永远不出胶囊，
   而什么都不会报错。关掉时 Rust 立刻画回额度标题（`restore_title`）。
3. **刘海旧键兼容**：开关沿用 v1.11.0「刘海额度条」的存储键 `codexbar_settings.notchHud` 与命令 `set_notch_hud`。
   改了名 = 老用户的「开」静默丢失。端到端：塞一份 v1.11.0 形状的设置（只有 `notchHud: true`、没有 `tpsTray`），
   启动时要重发 `set_notch_hud {on:true}`、t/s 按默认开。
4. **日夜切换移进设置**（不是删掉）：标题栏不再有切换；设置里点「浅色」⇒ 写 `codexbar_theme` + 广播 `theme-changed`，
   主窗口当场变浅；菜单栏弹窗 / 悬停面板读同一个键、听同一个事件。

端到端部分跑在真 bundle 上（harness 3304）；没起 = skip，**skip 不是绿**。
IPC 经 init script 截住 `__TAURI_INTERNALS__.invoke` 记账；设置种子经包一层 `localStorage.setItem` 合并
（harness 自己在 bundle 之前写 `codexbar_settings`，直接预写会被它覆盖）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import re
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "codexbar" / "src"
SETTINGS = SRC / "pages" / "SettingsPage.tsx"
APP = SRC / "App.tsx"
MENUBAR = SRC / "MenuBar.tsx"
HOVER = SRC / "TpsHover.tsx"
LIB = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"
PILL = ROOT / "codexbar" / "src-tauri" / "src" / "tray_pill.rs"

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HARNESS = "http://127.0.0.1:3304/harness.html?nav=settings&notrans=1"


def code_only(path):
    """去掉注释再匹配 —— 注释里正写着那些词（verification.md 形态⑫）。"""
    s = path.read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/\"])//[^\n]*", "", s)


def block(code, start, end):
    i = code.index(start)
    return code[i:code.index(end, i)]


class TheThreeRowsExistWithTheirDefaults(unittest.TestCase):
    def setUp(self):
        self.s = code_only(SETTINGS)

    def test_rows(self):
        for lab in ('label="外观"', 'label="显示位置"', 'label="在跑时显示 t/s"'):
            self.assertEqual(self.s.count(lab), 1, lab)
        # 2026-10-24「刘海屏版本」开关换成「显示位置」菜单栏 / 刘海屏二选一（用户：不能同时出现两个）
        for old in ('label="刘海额度条"', 'label="刘海屏版本"'):
            self.assertNotIn(old, self.s, "旧名字已被「显示位置」取代")

    def test_defaults(self):
        d = block(self.s, "const DEFAULTS: Settings = {", "};")
        self.assertRegex(d, r"\bnotchHud:\s*false\b", "刘海屏版本默认关（交接包 DECISIONS）")
        self.assertRegex(d, r"\btpsTray:\s*true\b", "在跑时显示 t/s 默认开（交接包 page 1）")
        lt = block(self.s, "export function loadTheme()", "\n}")
        self.assertIn('return "dark";', lt, "外观默认深色")

    def test_old_notch_key_is_kept(self):
        """★ 改键 = 老用户偏好丢失。键、命令、合并顺序（DEFAULTS 在前、存的在后）三样都钉住。"""
        self.assertIn('const KEY = "codexbar_settings";', self.s)
        iface = block(self.s, "interface Settings {", "}")
        self.assertRegex(iface, r"\bnotchHud:\s*boolean;")
        load = block(self.s, "function load(): Settings {", "\nfunction save(")
        self.assertIn('JSON.parse(localStorage.getItem(KEY) || "{}")', load)
        self.assertIn("return { ...DEFAULTS, ...raw };", load,
                      "存过的值盖默认值 ⇒ 旧设置里没有 tpsTray 时按默认开，有 notchHud 时沿用")
        row = block(self.s, 'label="显示位置"', "</OneLineRow>")
        self.assertIn('invoke<NotchStatus>("set_notch_hud", { on: next })', row)
        self.assertIn("update({ notchHud: next, surfaceNoticed: true })", row, "自己选的 ⇒ 不再发升级提示")


class TheTogglesDriveRust(unittest.TestCase):
    def setUp(self):
        self.s = code_only(SETTINGS)
        self.app = code_only(APP)

    def test_tps_row_calls_the_command_and_persists(self):
        row = block(self.s, 'label="在跑时显示 t/s"', "</OneLineRow>")
        self.assertIn('invoke("set_tps_tray", { enabled: next })', row)
        self.assertIn("update({ tpsTray: next })", row, "写进 localStorage（下次启动重发用）")

    def test_app_resends_both_on_startup(self):
        eff = block(self.app, "const st = getSettings();", "}, []);")
        self.assertIn('invoke("set_tps_tray", { enabled: st.tpsTray })', eff,
                      "★★ Rust 默认关 —— 不重发，开关显示开、托盘永远不出胶囊")
        self.assertIn('if (st.notchHud) invoke<{ active?: boolean }>("set_notch_hud", { on: true })', eff)
        self.assertIn('invoke("set_tray_style"', eff, "同一处、同一个时机")

    def test_rust_side_exists_and_restores_the_title(self):
        lib = LIB.read_text(encoding="utf-8")
        self.assertRegex(lib, r"fn set_tps_tray\(app: AppHandle, enabled: bool\)")
        self.assertRegex(lib, r"generate_handler!\[[\s\S]*\bset_tps_tray\b", "命令要注册，否则 invoke 静默失败")
        pill = PILL.read_text(encoding="utf-8")
        self.assertRegex(pill, r"static ENABLED: AtomicBool = AtomicBool::new\(false\);",
                         "前提：Rust 默认关 —— 这正是启动必须重发的原因；Rust 改成默认开时这条闸要跟着重想")
        body = block(pill, "pub fn set_enabled(", "\n}\n")
        self.assertIn("restore_title(app)", body, "关掉立刻回原额度标题")


class TheThemeMovedIntoSettings(unittest.TestCase):
    def setUp(self):
        self.s = code_only(SETTINGS)
        self.app = code_only(APP)

    def test_title_bar_no_longer_has_the_picker(self):
        self.assertNotIn("data-theme-pick", self.app, "交接包 page 5：标题栏只留隐私眼睛")
        self.assertNotIn("IconSun", self.app)

    def test_settings_writes_the_shared_key_and_broadcasts(self):
        self.assertIn('export const THEME_KEY = "codexbar_theme";', self.s)
        save = block(self.s, "export function saveTheme(", "\n}")
        self.assertIn("localStorage.setItem(THEME_KEY, v)", save)
        self.assertIn('emit("theme-changed", v)', save, "★ 别的 webview 靠它跟着变")
        row = block(self.s, 'label="外观"', "</OneLineRow>")
        self.assertIn("data-theme-pick={v}", row)
        self.assertIn("onTheme(v)", row)

    def test_main_window_reads_and_follows(self):
        self.assertIn("useState<ThemeName>(loadTheme)", self.app, "主窗口启动读同一个键")
        self.assertRegex(self.app, r'listen\("theme-changed", \(\) => setTheme\(loadTheme\(\)\)\)')
        self.assertIn("const changeTheme = (v: ThemeName) => { setTheme(v); saveTheme(v); };", self.app)
        self.assertIn("onTheme={changeTheme}", self.app)

    def test_other_webviews_listen_to_the_same_key(self):
        for p in (MENUBAR, HOVER):
            c = code_only(p)
            self.assertIn('localStorage.getItem("codexbar_theme")', c, p.name)
            self.assertIn('"theme-changed"', c, p.name)


# ---------------------------------------------------------------- 端到端（真 bundle）

TRAP = """(cfg) => {
  window.__calls = [];
  const origSet = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) {
    if (k === 'codexbar_settings' && cfg.seed) {
      try { v = JSON.stringify(Object.assign(JSON.parse(v), cfg.seed)); } catch (e) {}
    }
    return origSet.call(this, k, v);
  };
  let inner;
  Object.defineProperty(window, '__TAURI_INTERNALS__', { configurable: true,
    get() { return inner; },
    set(v) { const orig = v.invoke.bind(v);
      v.invoke = async (c, a, o) => {
        if (c === 'set_tps_tray' || c === 'set_notch_hud' || (c === 'plugin:event|emit' && a && a.event === 'theme-changed'))
          window.__calls.push({ c, a: c === 'plugin:event|emit' ? { event: a.event, payload: a.payload } : a });
        if (c === 'notch_status') return { active: true, reason: null };
        if (c === 'set_notch_hud') return { active: !!(a && a.on), reason: null };
        return orig(c, a, o); };
      inner = v; } });
}"""

PROBE = """() => {
  const knob = (sel) => { const t = document.querySelector(sel); return t ? getComputedStyle(t.firstElementChild).transform : null; };
  const pick = (v) => { const e = document.querySelector('[data-theme-pick="' + v + '"]'); return e ? e.dataset.on : null; };
  const rows = [...document.querySelectorAll('[data-tps-toggle],[data-notch-toggle],[data-theme-row]')]
    .map(e => e.parentElement.firstElementChild.firstElementChild.textContent);
  let st = null; try { st = JSON.parse(localStorage.getItem('codexbar_settings')); } catch (e) {}
  const seg = (sel) => { const t = document.querySelector(sel + ' [aria-pressed="true"]'); return t ? t.dataset.segOpt : null; };
  return { tps: knob('[data-tps-toggle]'), notch: seg('[data-notch-toggle]'), light: pick('light'), dark: pick('dark'),
           rows, calls: window.__calls, settings: st, theme: localStorage.getItem('codexbar_theme'),
           lightRoot: !!document.querySelector('.cb-light'), titlePick: document.querySelectorAll('[data-tauri-drag-region] [data-theme-pick]').length };
}"""

OFF = "matrix(1, 0, 0, 1, 0, 0)"     # translateX(0)
ON = "matrix(1, 0, 0, 1, 16, 0)"     # translateX(16px)


def _run(cfg, clicks=()):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return "skip"
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        ctx = br.new_context(viewport={"width": 1200, "height": 900})
        ctx.add_init_script(script=f"({TRAP})({json.dumps(cfg, ensure_ascii=False)})")
        pg = ctx.new_page()
        pg.goto(HARNESS, timeout=30000)
        pg.wait_for_timeout(1800)
        before = pg.evaluate(PROBE)
        for sel in clicks:
            pg.click(sel)
            pg.wait_for_timeout(400)
        after = pg.evaluate(PROBE) if clicks else None
        br.close()
    return before, after


def calls(r, cmd):
    return [c["a"] for c in r["calls"] if c["c"] == cmd]


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class OnTheRealBundle(unittest.TestCase):
    def _get(self, cfg, clicks=()):
        r = _run(cfg, clicks)
        if r == "skip":
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        before, after = r
        self.assertEqual(sorted(before["rows"]), sorted(["外观", "显示位置", "在跑时显示 t/s"]),
                         "★ 前提：三行真的渲染出来了")
        return before, after

    def test_fresh_install_defaults(self):
        b, _ = self._get({})
        self.assertEqual(b["tps"], ON, "t/s 默认开")
        self.assertEqual(b["notch"], "menubar", "显示位置默认菜单栏（= 刘海关）")
        self.assertEqual((b["light"], b["dark"]), ("0", "1"), "默认深色")
        self.assertEqual(calls(b, "set_tps_tray"), [{"enabled": True}], "★★ 启动重发一次，Rust 才会出胶囊")
        self.assertEqual(calls(b, "set_notch_hud"), [], "默认关 ⇒ 启动不建刘海窗口")
        self.assertEqual(b["titlePick"], 0, "标题栏没有日夜切换")

    def test_a_v1_11_user_keeps_the_notch_on(self):
        b, _ = self._get({"seed": {"notchHud": True}})
        self.assertEqual(b["notch"], "notch", "★ 旧键 notchHud 的「开」沿用 = 显示位置选刘海屏")
        self.assertEqual(calls(b, "set_notch_hud"), [{"on": True}], "启动时替他重新建窗")
        self.assertEqual(calls(b, "set_tps_tray"), [{"enabled": True}], "旧设置里没有 tpsTray ⇒ 默认开")

    def test_a_saved_off_is_resent_as_off(self):
        b, _ = self._get({"seed": {"tpsTray": False}})
        self.assertEqual(b["tps"], OFF)
        self.assertEqual(calls(b, "set_tps_tray"), [{"enabled": False}])

    def test_turning_tps_off_tells_rust_and_persists(self):
        _, a = self._get({}, clicks=("[data-tps-toggle]",))
        self.assertEqual(calls(a, "set_tps_tray"), [{"enabled": True}, {"enabled": False}])
        self.assertEqual(a["tps"], OFF)
        self.assertIs(a["settings"].get("tpsTray"), False, "写进 localStorage，下次启动重发 false")

    def test_light_from_settings_writes_broadcasts_and_repaints(self):
        b, a = self._get({}, clicks=('[data-theme-pick="light"]',))
        self.assertFalse(b["lightRoot"])
        self.assertEqual(a["theme"], "light", "写共用键 codexbar_theme")
        self.assertIn({"c": "plugin:event|emit", "a": {"event": "theme-changed", "payload": "light"}}, a["calls"],
                      "★ 广播给菜单栏弹窗 / 悬停面板")
        self.assertTrue(a["lightRoot"], "主窗口当场变浅")
        self.assertEqual((a["light"], a["dark"]), ("1", "0"))


if __name__ == "__main__":
    unittest.main()
