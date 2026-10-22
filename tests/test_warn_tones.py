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


class Snooze(unittest.TestCase):
    """B1「隐藏到重置」的两个纯函数。"""
    def test_until_is_the_reset_or_a_fallback(self):
        now = 1_800_000_000_000
        got = _node(f"[m.snoozeUntil({now // 1000 + 3600}, {now}, 5), m.snoozeUntil(null, {now}, 5), m.snoozeUntil({now // 1000 - 60}, {now}, 24)]")
        self.assertEqual(got, [now + 3600_000, now + 5 * 3600_000, now + 24 * 3600_000],
                         "★ 有重置时刻就藏到那时；读不到 / 已过 ⇒ 兜底时长（不永久藏）")

    def test_expired_and_bad_entries_are_dropped(self):
        got = _node("m.liveSnoozes({grok: 2000, codex: 500, kimi: 'x', agy: null}, 1000)")
        self.assertEqual(got, {"grok": 2000})


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

    def test_weekly_chip_sits_in_its_own_cell(self):
        """★ A1（用户 2026-10-22「不是要全局都显示，grok 的问题只在 grok 的方块里显示」）：没有底部长条，小红牌在那一家格子里。"""
        pg = self._page("harness-tpshover.html?hv=idle&hvwarns=1", w=520, h=300)
        r = pg.evaluate("""() => ({ chips: [...document.querySelectorAll('[data-idle-week]')].map(e => [e.closest('[data-idle-cell]').dataset.idleCell, e.textContent]),
          bar: document.querySelectorAll('[data-idle-warn], .ig-warns').length,
          gap: (e => e.closest('[data-idle-cell]').querySelector('[data-idle-reset]').getBoundingClientRect().left - e.getBoundingClientRect().right)(document.querySelector('[data-idle-week]')) })""")
        self.assertEqual(r["chips"], [["claude", "周4%"]])
        self.assertEqual(r["bar"], 0, "★ 底部长条不该再有")
        self.assertGreater(r["gap"], 2, "★ 小红牌压到了右上角的倒计时")

    def test_cursor_on_a_cell_shows_the_x_and_clicking_it_snoozes(self):
        """★ B1：面板不是 key 窗口 ⇒ 悬停靠 Rust 光标坐标；× 出现时倒计时让位；点 × 发 `idle-snooze`，不打开总览。"""
        pg = self._page("harness-tpshover.html?hv=idle&hvcellcursor=grok", w=520, h=300)
        r = pg.evaluate("() => ({ x: getComputedStyle(document.querySelector('[data-idle-hide=grok]')).opacity,"
                        " other: getComputedStyle(document.querySelector('[data-idle-hide=codex]')).opacity,"
                        " reset: getComputedStyle(document.querySelector('[data-idle-cell=grok] [data-idle-reset]')).opacity })")
        self.assertEqual((r["x"], r["other"], r["reset"]), ("1", "0", "0"), "★ 只有光标所在那一格出 ×，倒计时让位")
        pg.click("[data-idle-hide=grok]")
        pg.wait_for_timeout(200)
        ev = pg.evaluate("() => window.__calls.filter(c => c.c === 'plugin:event|emit').map(c => [c.a.event, c.a.payload])")
        self.assertIn(["idle-snooze", {"key": "grok", "undo": False}], [list(x) for x in ev])
        self.assertNotIn("open-main-page", [x[0] for x in ev], "★ 点 × 不能顺带打开总览")

    def test_snoozed_line_offers_undo(self):
        pg = self._page("harness-tpshover.html?hv=idle&hvsnoozed=1", w=520, h=300)
        cells = pg.evaluate("() => [...document.querySelectorAll('[data-idle-cell]')].map(e => e.dataset.idleCell)")
        self.assertNotIn("grok", cells)
        self.assertIn("撤销", pg.evaluate("() => document.querySelector('[data-idle-snoozed=grok]').textContent"))
        pg.click("[data-idle-undo=grok]")
        pg.wait_for_timeout(200)
        ev = pg.evaluate("() => window.__calls.filter(c => c.c === 'plugin:event|emit').map(c => [c.a.event, c.a.payload])")
        self.assertIn(["idle-snooze", {"key": "grok", "undo": True}], [list(x) for x in ev])

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


    def test_a_snoozed_platform_leaves_the_tray_and_the_panel(self):
        from test_idle_tray_wiring import _open_with
        js = "localStorage.setItem('codexbar_idle_snooze', JSON.stringify({ grok: Date.now() + 3600e3, codex: Date.now() - 1 }))"
        base = _open("harness-menubar.html?w=352", {"idlePinned": ["grok"]}, ())
        if base is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        self.assertIn("grok", [x["key"] for x in last(base[0], "set_idle_tray")["slots"]], "前提：固定了 grok 它就在托盘上")
        calls = _open_with("harness-menubar.html?w=352", {"idlePinned": ["grok"]}, js)[0]
        self.assertNotIn("grok", [x["key"] for x in last(calls, "set_idle_tray")["slots"]], "★ 藏着的不进托盘（固定了也一样）")
        panel = [c["a"]["payload"] for c in calls if c["c"] == "plugin:event|emit" and c["a"]["event"] == "idle-panel"][-1]
        self.assertNotIn("grok", [c["key"] for c in panel["cells"]])
        self.assertEqual([z["key"] for z in panel["snoozed"]], ["grok"], "★ 过期的（codex）不算")


if __name__ == "__main__":
    unittest.main()
