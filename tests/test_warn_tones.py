"""悬浮堆叠警告的两档颜色 + 空闲面板底部的周额度告警（用户 2026-10-22）。

- 「空闲的时候新增一个悬浮堆叠弹窗，例如周额度低于 10% 就弹出显示，放在最底部」
- 「弱警告黄色，带有透明度；强警告红色，带有透明度」
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_idle_tray_wiring import BASE, CHROME, TRAP, _open, last  # noqa: E402

PURE = ROOT / "codexbar" / "src" / "idleTray.ts"


def _node(expr):
    script = "import('file://%s').then(m => console.log(JSON.stringify(%s)));" % (PURE.as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    return json.loads([l for l in r.stdout.splitlines() if l.strip()][-1])


class WeeklyWarns(unittest.TestCase):
    def test_only_read_values_under_ten_by_the_shown_integer(self):
        got = _node("m.weeklyWarns([{key:'codex',week:9.6,reset:''},{key:'claude',week:4,reset:'2d'},"
                    "{key:'agy',week:null,reset:''},{key:'grok',week:9.4,reset:''}])")
        self.assertEqual([w["key"] for w in got], ["claude", "grok"],
                         "★ 9.6 显示 10 不报；读不到（null）不报；剩得少的在上")
        self.assertEqual(got[0], {"key": "claude", "rem": 4, "reset": "2d"})


def _vars(css, sel):
    """同一选择器可能出现在好几块（`.hv-win[data-theme="dark"]` 在文件里不止一处）⇒ 全部拼起来。"""
    return "\n".join(re.findall(r"(?:^|\n)" + re.escape(sel) + r"\s*\{([^}]*)\}", css))


class TonesAgree(unittest.TestCase):
    def test_strong_tone_is_the_same_in_both_windows(self):
        ov = (ROOT / "codexbar/src/components/ov/overview.css").read_text()
        hv = (ROOT / "codexbar/src/tpsHover.css").read_text()
        for theme, ovsel, hvsel in (("dark", '.ov-xs[data-level="strong"]', '.hv-win[data-theme="dark"]'),
                                    ("light", '.cb-light .ov-xs[data-level="strong"]', '.hv-win[data-theme="light"]')):
            with self.subTest(theme=theme):
                a, b = _vars(ov, ovsel), _vars(hv, hvsel)
                self.assertTrue(a and b, "选择器没找到 —— 判不了")
                pick = lambda s, k: re.search(k + r":\s*([^;]+);", s).group(1).strip()
                self.assertEqual(pick(a, "--xsTx"), pick(b, "--ig-warn-tx"))
                self.assertEqual(pick(a, "--xsLine"), pick(b, "--ig-warn-line"))
                self.assertEqual(pick(a, "--xsBg"), pick(b, "--ig-warn-bg"))
                self.assertIn("transparent", pick(a, "--xsBg"), "★ 要带透明度")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class OnTheRealBundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import urllib.request
            urllib.request.urlopen(BASE + "harness.html", timeout=2).read(1)
        except Exception:
            raise unittest.SkipTest("harness 3304 没起 —— skip 不是绿")
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def _page(self, path, w=1200, h=800):
        ctx = self.br.new_context(viewport={"width": w, "height": h})
        self.addCleanup(ctx.close)
        ctx.add_init_script(script=f"({TRAP})({{}})")
        pg = ctx.new_page()
        pg.goto(BASE + path, timeout=30000)
        pg.wait_for_timeout(1800)
        return pg

    def test_price_stack_is_weak_yellow(self):
        pg = self._page("harness.html?nav=traffic")
        r = pg.evaluate("() => { const e = document.querySelector('[data-price-warn]'); if (!e) return null;"
                        " return { level: e.dataset.level, tx: getComputedStyle(e.querySelector('.ov-xs-chip')).color }; }")
        if r is None:
            self.skipTest("快照里没有价格待核的模型")
        self.assertEqual(r["level"], "weak")
        self.assertEqual(r["tx"], "rgb(250, 204, 21)", "★ 弱警告 = 黄")

    def test_idle_panel_shows_strong_weekly_stack_and_expands_on_the_rust_cursor(self):
        shut_pg = self._page("harness-tpshover.html?hv=idle&hvwarns=3", w=520, h=360)
        shut = shut_pg.evaluate("() => { const w = document.querySelector('[data-idle-warn]'); return { lvl: w.dataset.level,"
                           " under: getComputedStyle(w.querySelectorAll('[data-idle-warn-item]')[1].firstElementChild).opacity }; }")
        self.assertEqual(shut["lvl"], "strong", "★ 周额度见底 = 强警告（红）")
        self.assertEqual(shut["under"], "0", "★ 收着时第二条的内容不能透上来")
        pg = self._page("harness-tpshover.html?hv=idle&hvwarns=3&hvwarncursor=leave", w=520, h=360)
        # 脚本：1 s 时光标进到堆叠上（Rust 坐标通道）⇒ 展开、窗口长高；2 s 时移开 ⇒ 收回
        hs = pg.evaluate("() => window.__calls.filter(c => c.c === 'tpshover_resize').map(c => c.a.h)")
        self.assertTrue(hs and max(hs) > min(hs), f"★ 展开时窗口没长高：{hs}")
        pg.wait_for_timeout(700)
        self.assertEqual(pg.evaluate("() => document.querySelector('[data-idle-warn]').dataset.open"), "0", "光标移开要收回")



@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class MenubarSendsIt(unittest.TestCase):
    def test_menubar_sends_the_weekly_warn(self):
        r = _open("harness-menubar.html?w=352&claudeq=weeklow", {}, ())
        if r is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        panel = [c["a"] for c in r[0] if c["c"] == "plugin:event|emit" and c["a"].get("event") == "idle-panel"]
        got = panel[-1]["payload"]["warns"] if panel else None
        self.assertIsNotNone(got, "★ 面板数据里没有 warns")
        self.assertIn("claude", [w["key"] for w in got], "夹具 Claude 周剩 5 ⇒ 要报")


if __name__ == "__main__":
    unittest.main()
