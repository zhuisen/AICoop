"""真页面实量（harness 3304，真 bundle）：
① 总览卡底栏（用户 2026-10-21「到期日期挡住了」⇒ 短日期 + 短重置卡）在 860 / 1000 / 1200 宽下一个字都不被省略；
② 「快到期」堆叠警告真的渲染了、条目数与角标一致，`?ovxs=1` 展开后条目不越出窗口；
③ 设置页「AI 平台」每一行、固定 chip 每一个都带平台 logo（用户「设置上 AI 平台没有替换对应的 ai svg」）。
harness 没在跑 / 没有 playwright ⇒ skip（不是绿）。"""
import unittest
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HOST = "http://127.0.0.1:3304/harness.html"


def _up():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        urllib.request.urlopen(HOST, timeout=2).read(1)
        return True
    except Exception:  # noqa: BLE001 —— 没环境就 skip
        return False


FOOT_JS = """() => [...document.querySelectorAll('[data-ov-foot] .ov-fdef')].map(f => {
  const kids = [...f.children];
  return { n: kids.length, txt: f.innerText,
           cut: kids.filter(k => k.scrollWidth > k.clientWidth + 0.5).map(k => k.innerText),
           over: f.scrollWidth > f.clientWidth + 0.5 };
})"""


class Rendered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _up():
            raise unittest.SkipTest("没有 playwright 或 harness 静态服务（3304）没在跑")
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close(); cls.pw.stop()

    def page(self, q, w, h):
        pg = self.br.new_page(viewport={"width": w, "height": h})
        pg.goto("%s?%s" % (HOST, q), timeout=30000)
        pg.wait_for_timeout(2600)
        self.addCleanup(pg.close)
        return pg

    def test_footer_never_truncates(self):
        for w in (860, 1000, 1200):
            pg = self.page("nav=home&ovplat=codex&ovoff=1", w, 760)
            feet = pg.evaluate(FOOT_JS)
            self.assertGreaterEqual(len(feet), 3, "@%d 卡片没渲染出来 —— 闸此刻没有判别力" % w)
            self.assertTrue(any("到期" in f["txt"] for f in feet), "@%d 没有一张卡写着到期日" % w)
            self.assertTrue(any("重置卡" in f["txt"] for f in feet), "@%d 没有一张卡带重置卡角标" % w)
            for f in feet:
                self.assertEqual(f["cut"], [], "★★ @%d 底栏被省略：%r" % (w, f["txt"]))
                self.assertFalse(f["over"], "★★ @%d 底栏溢出：%r" % (w, f["txt"]))

    def test_the_expiry_stack_renders_and_fits(self):
        pg = self.page("nav=home&ovplat=codex&ovxs=1", 860, 560)
        st = pg.evaluate("""() => { const s = document.querySelector('[data-ov-expiry]'); if (!s) return null;
          const its = [...s.querySelectorAll('[data-ov-expiry-item]')];
          return { n: +s.dataset.ovExpiry, items: its.length, chip: s.querySelector('.ov-xs-chip').innerText,
                   vis: getComputedStyle(s.querySelector('.ov-xs-pop')).visibility,
                   right: Math.max(...its.map(e => e.getBoundingClientRect().right)),
                   bottom: Math.max(...its.map(e => e.getBoundingClientRect().bottom)),
                   cut: its.filter(e => e.scrollWidth > e.clientWidth + 0.5).length }; }""")
        self.assertIsNotNone(st, "★★ 夹具里有快到期的卡（harness 保证），堆叠警告却没渲染")
        self.assertGreaterEqual(st["n"], 1)
        self.assertEqual(st["items"], st["n"], "角标说的条数与展开的条数不一致")
        self.assertIn("%d 项快到期" % st["n"], st["chip"])
        self.assertEqual(st["vis"], "visible", "`?ovxs=1` 没展开 —— 下面的几何量的是隐藏态")
        self.assertLessEqual(st["right"], 860, "展开的条目越出了窗口右边")
        self.assertLessEqual(st["bottom"], 560, "展开的条目越出了窗口底边")
        self.assertEqual(st["cut"], 0, "条目文字被截断")

    def test_the_stack_is_hidden_until_hovered(self):
        pg = self.page("nav=home&ovplat=codex", 860, 560)
        vis = pg.evaluate("() => { const p = document.querySelector('[data-ov-expiry] .ov-xs-pop'); return p && getComputedStyle(p).visibility; }")
        self.assertEqual(vis, "hidden", "★ 没悬停时展开层就露出来了（会盖住卡片）")

    def test_settings_platform_rows_carry_their_logos(self):
        pg = self.page("nav=settings", 1200, 900)
        got = pg.evaluate("""() => ({ rows: [...document.querySelectorAll('[data-platform-logo]')].map(e => [e.dataset.platformLogo, !!e.querySelector('img,svg')]),
                                       pins: [...document.querySelectorAll('[data-pin]')].map(e => !!e.querySelector('img,svg')) })""")
        self.assertGreaterEqual(len(got["rows"]), 4, "设置页的 AI 平台行没渲染出来")
        known = {"codex", "claude", "agy", "grok", "kimi", "deepseek"}
        for k, has in got["rows"]:
            if k in known:
                self.assertTrue(has, "★★ 「%s」这一行没有平台 logo" % k)
        self.assertTrue(got["pins"] and all(got["pins"]), "★ 固定 chip 有的没带 logo：%r" % got["pins"])


if __name__ == "__main__":
    unittest.main()
