"""空闲托盘（AICoop P11）的接线：菜单栏 webview → `set_idle_tray`，设置页 → 广播 → 菜单栏重发。

选位逻辑的行为闸在 `test_idle_tray.py`（纯函数）；这里只验「谁来喂它」（verification.md「改完了 ≠ 有人喂它」）：
  · 常驻的菜单栏 webview 启动就把选好的 2–3 家交给 Rust，`set_idle_prefs` 也发一次；
  · 设置改成「文字标题」并广播后，菜单栏重发 `enabled: false`（不广播就收不到：localStorage 跨 webview 不推送）；
  · 设置页「文字标题样式」只在选「文字标题」时出现（P9 S1 显隐联动）；Rust 侧两个命令都进了 invoke_handler。
端到端部分跑在真 bundle 上（harness 3304）；没起 = skip，**skip 不是绿**。
"""
import json
import re
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/"
TRAY_KEYS = {"codex", "claude", "agy", "grok", "kimi", "deepseek"}

TRAP = """(seed) => {
  // harness 自己会在加载时写一份 codexbar_settings —— 合进去而不是先写（先写会被它整份盖掉）
  const origSet = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) {
    if (k === 'codexbar_settings') { try { v = JSON.stringify(Object.assign(JSON.parse(v), seed)); } catch (e) {} }
    return origSet.call(this, k, v);
  };
  localStorage.setItem('codexbar_settings', '{}');
  window.__calls = [];
  let inner;
  Object.defineProperty(window, '__TAURI_INTERNALS__', { configurable: true,
    get() { return inner; },
    set(v) { const orig = v.invoke.bind(v);
      v.invoke = async (c, a, o) => {
        if (c === 'set_idle_tray' || c === 'set_idle_prefs' || c === 'tpshover_dismiss' || c === 'tpshover_resize'
            || (c === 'plugin:event|emit' && a && /^(idle-tray-settings|idle-panel|open-main-page|idle-snooze)$/.test(a.event)))
          window.__calls.push({ c, a: JSON.parse(JSON.stringify(c === 'plugin:event|emit' ? { event: a.event, payload: a.payload ?? null } : a)) });
        return orig(c, a, o); };
      inner = v; } });
}"""


def _open(page, seed, steps=()):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(BASE + page, timeout=2).read(1)
    except Exception:
        return None
    out = []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        ctx = br.new_context(viewport={"width": 1200, "height": 900})
        ctx.add_init_script(script=f"({TRAP})({json.dumps(seed)})")
        pg = ctx.new_page()
        pg.goto(BASE + page, timeout=30000)
        pg.wait_for_timeout(2000)
        out.append(pg.evaluate("() => window.__calls.slice()"))
        for st in steps:
            st(pg)
            pg.wait_for_timeout(500)
            out.append(pg.evaluate("() => ({ calls: window.__calls.slice(), rows: [...document.querySelectorAll('div')]"
                                   ".filter(d => d.childElementCount === 0 && /^(文字标题样式|菜单栏显示几家|打招呼)$/.test(d.textContent))"
                                   ".map(d => d.textContent) })"))
        br.close()
    return out


def _open_with(page, seed, init_js):
    """同 `_open`，但在页面脚本之前多跑一段 `init_js`（模拟上次运行留下的 localStorage）。"""
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(BASE + page, timeout=2).read(1)
    except Exception:
        raise unittest.SkipTest("harness 3304 没起 —— skip 不是绿")
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        ctx = br.new_context(viewport={"width": 1200, "height": 900})
        ctx.add_init_script(script=f"({TRAP})({json.dumps(seed)}); {init_js}")
        pg = ctx.new_page()
        pg.goto(BASE + page, timeout=30000)
        pg.wait_for_timeout(2000)
        out = [pg.evaluate("() => window.__calls.slice()")]
        br.close()
    return out


def last(calls, cmd):
    xs = [c["a"] for c in calls if c["c"] == cmd]
    return xs[-1] if xs else None


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class MenubarFeedsTheTray(unittest.TestCase):
    def _mb(self, seed, steps=()):
        r = _open("harness-menubar.html?w=352", seed, steps)
        if r is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        return r

    def test_default_sends_icons_with_two_or_three_known_platforms(self):
        calls = self._mb({})[0]
        got = last(calls, "set_idle_tray")
        self.assertIsNotNone(got, "★★ 菜单栏 webview 启动后必须把托盘选位交给 Rust —— 否则空闲托盘永远不出现")
        self.assertTrue(got["enabled"], "P11 §7：默认「AI 图标」")
        keys = [s["key"] for s in got["slots"]]
        self.assertTrue(2 <= len(keys) <= 3 and set(keys) <= TRAY_KEYS and len(set(keys)) == len(keys), keys)
        prefs = last(calls, "set_idle_prefs")
        self.assertEqual((prefs["glow"], prefs["hello"]), (True, "daily"))
        self.assertIn("lastHello", prefs, "★ 重启后要接上「上次打招呼」，否则每次部署都再打一次")
        self.assertIsInstance(got.get("cells"), int, "★ 面板格子数随托盘一起交给 Rust（0 格不弹空面板）")

    def test_two_slots_and_text_mode_are_passed_through(self):
        got = last(self._mb({"idleIcons": False, "idleSlots": 2})[0], "set_idle_tray")
        self.assertFalse(got["enabled"], "★ 选「文字标题」⇒ 关掉空闲托盘")
        self.assertLessEqual(len(got["slots"]), 2)

    def test_todays_frozen_residents_survive_a_restart(self):
        """★ 冻结的常驻记在 localStorage：重启 / 部署后同一天不按实时排名重排（三方评审 2026-10-21）。"""
        base = last(self._mb({})[0], "set_idle_tray")
        live = [x["key"] for x in base["slots"][:2]]
        self.assertEqual(len(live), 2, "前提：默认夹具排得出两家常驻")
        frozen = list(reversed(live))
        seed_js = ("(() => { const d = new Date(); const k = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')"
                   " + '-' + String(d.getDate()).padStart(2, '0');"
                   " localStorage.setItem('codexbar_idle_frozen', JSON.stringify({ day: k, keep: %s, sig: '[3,\"tokens\",14,[]]' })); })()"
                   % json.dumps(frozen))
        got = last(_open_with("harness-menubar.html?w=352", {}, seed_js)[0], "set_idle_tray")
        self.assertEqual([x["key"] for x in got["slots"][:2]], frozen, "★★ 今天已冻结的顺序优先于实时排名")

    def test_text_mode_with_bar_only_still_has_cells(self):
        calls = self._mb({"idleIcons": False, "idleHoverScope": "bar"})[0]
        panel = [c["a"]["payload"] for c in calls if c["c"] == "plugin:event|emit" and c["a"]["event"] == "idle-panel"]
        self.assertTrue(panel, "前提：菜单栏发过面板格子")
        self.assertGreater(len(panel[-1]["cells"]), 0, "★ 文字标题下没有「菜单栏里的那几家」⇒ 按「用过的」，不是空面板")

    def test_a_settings_broadcast_makes_the_menubar_resend(self):
        def flip(pg):
            pg.evaluate("() => { const s = JSON.parse(localStorage.getItem('codexbar_settings') || '{}'); s.idleIcons = false;"
                        " localStorage.setItem('codexbar_settings', JSON.stringify(s));"
                        " window.__harnessFire('idle-tray-settings', null); }")
        before, after = self._mb({}, [flip])
        self.assertTrue(last(before, "set_idle_tray")["enabled"])
        self.assertFalse(last(after["calls"], "set_idle_tray")["enabled"],
                         "★★ 设置页改完广播，常驻的菜单栏 webview 必须重读并重发")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class LogoFillIsTheFiveHourWindow(unittest.TestCase):
    """★ 用户 2026-10-22「logo 水位都改成 5h」：Claude 5h 剩 99、周剩 67 ⇒ 托盘画 99，不画最紧的 67。"""
    def test_claude_logo_follows_5h_not_the_tighter_week(self):
        r = _open("harness-menubar.html?w=352&claudeq=weektight", {"idlePinned": ["claude"]}, ())
        if r is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        got = last(r[0], "set_idle_tray")
        cl = [x for x in got["slots"] if x["key"] == "claude"]
        self.assertEqual(len(cl), 1, f"夹具里 Claude 没上托盘 —— 判不了：{got['slots']}")
        self.assertEqual(cl[0]["remaining"], 99, "★ logo 水位应是 5h 剩余 99，不是周 67")


class SettingsRows(unittest.TestCase):
    def test_text_style_row_only_in_text_mode_and_the_change_is_broadcast(self):
        def to_text(pg):
            pg.click("[data-idle-icons] >> text=文字标题")
        r = _open("harness.html?nav=settings&notrans=1", {}, [to_text])
        if r is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        _, after = r
        self.assertIn("文字标题样式", after["rows"], "选「文字标题」后出现「文字标题样式」")
        self.assertNotIn("菜单栏显示几家", after["rows"], "★ 托盘那几行隐藏")
        self.assertTrue(any(c["c"] == "plugin:event|emit" for c in after["calls"]), "★★ 改完必须广播给菜单栏 webview")

    def test_icon_mode_hides_the_text_style_row(self):
        r = _open("harness.html?nav=settings&notrans=1", {}, [lambda pg: None])
        if r is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        rows = r[1]["rows"]
        self.assertIn("菜单栏显示几家", rows, "前提：托盘那几行真的渲染出来了")
        self.assertIn("打招呼", rows)
        self.assertNotIn("文字标题样式", rows)


class RustSide(unittest.TestCase):
    def test_commands_are_registered(self):
        src = (ROOT / "codexbar/src-tauri/src/lib.rs").read_text()
        handler = src[src.index("generate_handler!["):]
        handler = handler[:handler.index("]")]
        for cmd in ("set_idle_tray", "set_idle_prefs"):
            self.assertRegex(handler, r"\b%s\b" % cmd, "★ 命令没注册 ⇒ invoke 静默失败，托盘永远是文字")
            self.assertRegex(src, r"#\[tauri::command\]\s*fn %s\(" % cmd)


# ---------------------------------------------------------------- 空闲额度格子（悬停面板 · P11 §6）

GRID = ROOT / "codexbar/src/idleGridLayout.ts"


def _node(expr):
    import subprocess
    script = ("import('file://%s').then(m => { console.log(JSON.stringify(%s)); });" % (GRID.as_posix(), expr))
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script], capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip()[:1] in "[{\"tfn0123456789-"]
    if not out:
        raise AssertionError("node 没有产出结果：%s" % r.stderr[-600:])
    return json.loads(out[-1])


class GridGeometry(unittest.TestCase):
    def test_board_geometry_at_1x(self):
        g = _node("m.gridLayout(6)")
        # 用户 2026-10-21 选 1.5×：画板 2× 数值 × 0.75
        self.assertAlmostEqual(g["cw"], 100.25, places=2, msg="(435 − 2×8 − 3×6)/4")
        self.assertEqual(g["ch"], 100.5)
        self.assertEqual(g["h"], 8 + 2 * 100.5 + 6 + 8, "两行：内边距 + 2 格 + 间距 + 内边距")
        self.assertEqual(g["pos"][4], {"x": 8, "y": 8 + 100.5 + 6}, "★ 第 5 格换到第二行行首")
        self.assertEqual(_node("[m.PANEL_W, m.RING, m.LOGO]"), [435, 48, 20], "★ 画板 580 / 64 / 26 × 0.75（logo 19.5 吸整）")
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "tps_hover.rs").read_text(encoding="utf-8")
        self.assertIn("pub const IDLE_PANEL_W: f64 = 435.0;", rs, "★ Rust 摆窗口用的宽必须与前端同值")
        self.assertEqual(_node("m.gridLayout(0).h"), 0, "没有格子 ⇒ 面板不出现")

    def test_tray_logos_fly_into_ring_centres_in_tray_order(self):
        lay = {"panel": {"x": 40, "y": 30}, "segments": [
            {"platform": "codex", "logo": {"x": 300, "y": 5, "size": 14}},
            {"platform": "claude", "logo": {"x": 319, "y": 5, "size": 14}}]}
        f = _node("m.planIdleFlights(%s, ['claude','codex','grok'], m.gridLayout(3), 40, 30)" % json.dumps(lay))
        self.assertEqual([x["fromTray"] for x in f], [True, True, False], "★ 托盘以外的那家不飞，原位淡入")
        self.assertEqual(f[0]["pill"], {"x": 319, "y": 5, "s": 1}, "从托盘里那个 logo 的位置起飞")
        cx = 40 + 1 + 8 + 100.25 / 2
        half = int(re.search(r"export const PILL_LOGO = (\d+);", (ROOT / "codexbar/src/idleGridLayout.ts").read_text()).group(1)) / 2
        self.assertAlmostEqual(f[0]["cell"]["x"] + half, cx, places=6, msg="★★ 落在第一格的环心（含面板描边 1）")
        self.assertEqual([f[0]["delay"], f[1]["delay"]], [25, 0], "按托盘顺序错开 25 ms（Codex 在托盘第 1 位先走）")
        self.assertEqual([f[0]["delayBack"], f[1]["delayBack"]], [0, 25], "飞回倒序：最右的先走")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class IdlePanelOnTheRealBundle(unittest.TestCase):
    def _open(self, q, click=None, fire=None):
        try:
            from playwright.sync_api import sync_playwright
            urllib.request.urlopen(BASE + "harness-tpshover.html", timeout=2).read(1)
        except Exception:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        with sync_playwright() as p:
            br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
            ctx = br.new_context(viewport={"width": 380, "height": 260})
            ctx.add_init_script(script=f"({TRAP})({{}})")
            pg = ctx.new_page()
            pg.goto(BASE + "harness-tpshover.html?" + q, timeout=30000)
            pg.wait_for_timeout(1500)
            if click:
                pg.click(f'[data-idle-cell="{click}"]')
                pg.wait_for_timeout(300)
            if fire:
                pg.evaluate(fire)
                pg.wait_for_timeout(400)
            r = pg.evaluate("""() => ({
              cells: [...document.querySelectorAll('[data-idle-cell]')].map(e => ({ k: e.dataset.idleCell, bar: e.dataset.inBar,
                main: e.querySelector('[data-idle-main]').textContent, dot: !!e.querySelector('.ig-dot'),
                reset: (e.querySelector('[data-idle-reset]') || {}).textContent || '' })),
              runShell: getComputedStyle(document.querySelector('[data-hover-panel]')).opacity,
              shell: getComputedStyle(document.querySelector('[data-idle-panel]')).opacity,
              calls: window.__calls.slice() })""")
            br.close()
        return r, None

    def test_idle_open_draws_the_grid_not_the_speed_panel(self):
        r, _ = self._open("hv=idle")
        self.assertEqual([c["k"] for c in r["cells"]], ["codex", "claude", "agy", "grok"], "★ 前提：格子真的渲染出来了")
        self.assertEqual(r["shell"], "1")
        self.assertEqual(r["runShell"], "0", "★★ 空闲打开 ⇒ 速度面板不出现（同一个窗口，两种面板只亮一个）")
        self.assertEqual([c["dot"] for c in r["cells"]], [True, True, True, False], "菜单栏里的那几家才有白点")
        self.assertEqual(r["cells"][2]["main"], "6%")
        self.assertEqual(r["cells"][0]["reset"], "↻ 2h14m")

    def test_unknown_is_a_dash_not_zero(self):
        r, _ = self._open("hv=idle&hvcells=8")
        kimi = next(c for c in r["cells"] if c["k"] == "kimi")
        self.assertEqual((kimi["main"], kimi["reset"]), ("—", ""), "★★ 读不到写 —，不写 0%；按量计费不写重置")

    def test_run_open_still_draws_the_speed_panel(self):
        r, _ = self._open("hv=4")
        self.assertEqual(r["cells"], [], "在跑打开 ⇒ 没有空闲格子")
        self.assertEqual(r["runShell"], "1")

    def test_clicking_a_cell_opens_that_platform_and_dismisses(self):
        r, _ = self._open("hv=idle", click="claude")
        ev = [c["a"]["payload"] for c in r["calls"] if c["c"] == "plugin:event|emit" and c["a"]["event"] == "open-main-page"]
        self.assertEqual(ev[-1:], [{"page": "overview", "platform": "claude"}], "★ 点格子 ⇒ 打开该 AI 总览")
        self.assertTrue(any(c["c"] == "tpshover_dismiss" for c in r["calls"]), "★ 并收起面板")

    def test_idle_cells_never_resize_the_speed_panel(self):
        """★★ 两个面板共用一个窗口高度：在跑面板开着时推来一份空闲格子，不许改窗口高度（评审 2026-10-21 H2）。"""
        cells = [{"key": k, "main": 50, "reset": "", "inBar": False, "low": False, "stale": False}
                 for k in ("codex", "claude", "agy", "grok", "kimi", "deepseek")]
        r, _ = self._open("hv=4", fire="() => window.__harnessFire('idle-panel', %s)" % json.dumps({"cells": cells, "max": 8}))
        hs = [c["a"]["h"] for c in r["calls"] if c["c"] == "tpshover_resize"]
        self.assertTrue(hs, "前提：在跑面板报过高度")
        idle_h = _node("m.gridLayout(6).h")
        self.assertNotIn(idle_h, hs, "★★ 空闲格子（6 格两行）的高度混进了在跑面板的高度上报")


if __name__ == "__main__":
    unittest.main()
