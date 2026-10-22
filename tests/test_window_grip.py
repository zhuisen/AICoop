"""主窗口拖动 / 缩放手感（用户 2026-10-22 从 demo v2 选 D3 + G3 + S1 + S3 + S4 + M）。

真 bundle + harness：
- D3：内容区顶上一条带里点**空白处** ⇒ `start_dragging`；点在按钮 / 可点的东西上 ⇒ 不拖；带外不拖。
- G3 / S4：抓手平时不画（描边透明），光标进窗口才淡出；按下 ⇒ `grip_resize_start`（尺寸由 Rust 改）。
- S3：Rust 发 `grip-size` ⇒ 胶囊「W × H · 总览 N 列 · 吸住 · 档名」；`null` ⇒ 收起。
S1（松手靠边吸附）与抓手的真缩放在 Rust（`win_chrome.rs` 单测）；WKWebView 真机手感只能人看。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_requests_p3 import CHROME, HARNESS, _harness_up  # noqa: E402

TRAP = """() => {
  window.__calls = [];
  let inner;
  Object.defineProperty(window, '__TAURI_INTERNALS__', { configurable: true, get() { return inner; },
    set(v) { const orig = v.invoke.bind(v);
      v.invoke = async (c, a, o) => { if (/^(grip_resize_start|plugin:window\\|(start_dragging|toggle_maximize))$/.test(c)) window.__calls.push(c);
        return orig(c, a, o); };
      inner = v; } });
}"""


@unittest.skipUnless(_harness_up() and Path(CHROME).exists(), "harness 没在跑 —— skip 不是绿")
class WindowChrome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def page(self, q="nav=traffic"):
        ctx = self.br.new_context(viewport={"width": 1200, "height": 800})
        self.addCleanup(ctx.close)
        ctx.add_init_script(script=f"({TRAP})()")
        pg = ctx.new_page()
        pg.goto(f"{HARNESS}/harness.html?{q}", timeout=30000)
        pg.wait_for_selector("[data-win-grip]", timeout=15000)
        pg.wait_for_timeout(900)
        return pg

    def calls(self, pg):
        return pg.evaluate("() => window.__calls.slice()")

    def test_blank_header_drags_and_controls_do_not(self):
        pg = self.page()
        band = pg.evaluate("() => { const r = document.querySelector('[data-drag-band]').getBoundingClientRect(); return [r.left, r.top, r.right]; }")
        pg.mouse.click(band[2] - 4, band[1] + 6)            # 顶上内边距里的空白
        self.assertIn("plugin:window|start_dragging", self.calls(pg), "★ 点顶上空白处没开始拖窗口")
        pg.evaluate("() => { window.__calls.length = 0; }")
        chip = pg.evaluate("() => { const b = document.querySelector('[role=group][aria-label=按平台筛选] button').getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; }")
        pg.mouse.click(chip[0], chip[1])
        self.assertNotIn("plugin:window|start_dragging", self.calls(pg), "★ 点标题行的胶囊也在拖窗口 —— 控件失灵")
        pg.mouse.click(band[0] + 200, band[1] + 300)          # 带外
        self.assertNotIn("plugin:window|start_dragging", self.calls(pg), "★ 带外也在拖窗口")

    def test_grip_is_hidden_until_the_window_is_hovered_and_press_starts_the_resize(self):
        pg = self.page()
        stroke = "() => getComputedStyle(document.querySelector('[data-win-grip] path')).stroke"
        pg.mouse.move(5, 5)
        pg.evaluate("() => document.querySelector('.cb-root').dispatchEvent(new MouseEvent('mouseout'))")
        pg.mouse.move(1199, 799)
        pg.wait_for_timeout(300)
        box = pg.evaluate("() => { const r = document.querySelector('[data-win-grip]').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }")
        pg.mouse.move(box[0], box[1])
        pg.wait_for_timeout(300)
        self.assertEqual(pg.evaluate(stroke), "rgba(45, 212, 191, 0.9)", "★ 悬停抓手没变青（S4）")
        pg.mouse.down()
        pg.mouse.up()
        self.assertIn("grip_resize_start", self.calls(pg), "★ 按下抓手没交给 Rust 缩放")

    def test_size_pill_follows_rust_and_marks_a_snap(self):
        pg = self.page("nav=home")
        pill = "() => { const e = document.querySelector('[data-win-pill]'); return [getComputedStyle(e).display, e.textContent, e.className]; }"
        self.assertEqual(pg.evaluate(pill)[0], "none", "没在缩放时胶囊不该出现")
        pg.evaluate("() => window.__harnessFire('grip-size', { w: 1200, h: 800, label: '常用', zoom: 1 })")
        pg.wait_for_timeout(100)
        d, text, cls = pg.evaluate(pill)
        self.assertEqual(d, "block")
        self.assertIn("1200 × 800", text)
        self.assertIn("吸住 · 常用", text)
        self.assertRegex(text, r"总览 \d 列", "★ 胶囊没给出总览列数")
        self.assertIn("snapped", cls)
        pg.evaluate("() => window.__harnessFire('grip-size', null)")
        pg.wait_for_timeout(100)
        self.assertEqual(pg.evaluate(pill)[0], "none", "★ 松手后胶囊没收起")


if __name__ == "__main__":
    unittest.main()
