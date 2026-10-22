"""「消耗」页标题行（用户 2026-10-22）：平台胶囊并进标题行；带名字放不下时只留图标，不在半个胶囊处截断。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_requests_p3 import CHROME, HARNESS, _harness_up

CHIPS = """() => { const g = document.querySelector('[role=group][aria-label=按平台筛选]');
  const row = document.querySelector('[data-range-label]').parentElement;
  return { tight: g.dataset.chipsTight, cw: g.clientWidth, sw: g.scrollWidth, sameRow: row.contains(g),
           named: [...g.querySelectorAll('button')].filter(b => b.textContent.trim()).length,
           n: g.querySelectorAll('button').length }; }"""


@unittest.skipUnless(_harness_up() and Path(CHROME).exists(), "harness 没在跑 —— skip 不是绿")
class ChipsFitTheTitleRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def test_names_drop_to_icons_and_come_back(self):
        pg = self.br.new_page(viewport={"width": 1600, "height": 900})
        self.addCleanup(pg.close)
        pg.goto(f"{HARNESS}/harness.html?nav=traffic")
        pg.wait_for_selector("[data-tk-chart]", timeout=15000)
        pg.wait_for_timeout(600)
        wide = pg.evaluate(CHIPS)
        self.assertTrue(wide["sameRow"], "★ 胶囊不在标题行")
        self.assertEqual((wide["tight"], wide["named"]), ("0", wide["n"]), "宽屏应全带名字")
        pg.set_viewport_size({"width": 1200, "height": 900})
        pg.wait_for_timeout(400)
        mid = pg.evaluate(CHIPS)
        self.assertEqual(mid["tight"], "1", "夹具 6 家在 1200 宽放不下名字 —— 判不了")
        self.assertLessEqual(mid["sw"], mid["cw"] + 1, "★ 只留图标后仍被截断")
        self.assertEqual(mid["named"], 1, "只剩「全部」带名字")
        pg.set_viewport_size({"width": 1600, "height": 900})
        pg.wait_for_timeout(400)
        self.assertEqual(pg.evaluate(CHIPS)["tight"], "0", "★ 窗口放宽后名字没回来")



@unittest.skipUnless(_harness_up() and Path(CHROME).exists(), "harness 没在跑 —— skip 不是绿")
class WeakNotesFoldIntoOneStack(unittest.TestCase):
    """★ 用户 2026-10-22「这些弱警告都改成悬浮折叠警告条」：缓存口径牌与「标 * 是估算价」脚注并进同一个悬浮堆叠。"""
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def _probe(self, q):
        pg = self.br.new_page(viewport={"width": 1200, "height": 800})
        self.addCleanup(pg.close)
        pg.goto(f"{HARNESS}/harness.html?{q}")
        pg.wait_for_timeout(1800)
        return pg.evaluate("""() => { const e = document.querySelector('.ov-xs[data-warn-n]');
          return { n: e ? +e.dataset.warnN : 0, keys: e ? [...e.querySelectorAll('.ov-xs-it')].map(x => x.dataset.priceWarnItem) : [],
                   chip: e ? e.querySelector('.ov-xs-chip').textContent : '',
                   footnote: document.body.innerText.includes('标 * 的是估算价'),
                   loose: [...document.querySelectorAll('span')].filter(s => s.children.length === 0 && s.textContent === '不含缓存读' && !s.closest('.ov-xs')).length }; }""")

    def test_token_page_cache_note_is_in_the_stack(self):
        r = self._probe("nav=traffic&mode=noRead")
        self.assertIn("cache", r["keys"], "★ 缓存口径没进堆叠")
        self.assertEqual(r["loose"], 0, "★ 堆叠外还挂着一块口径牌")
        self.assertTrue(r["chip"].endswith("项提示"))

    def test_platform_page_has_no_loose_footnote(self):
        r = self._probe("nav=platform:claude&mode=noRead")
        self.assertIn("cache", r["keys"])
        self.assertIn("unpriced", r["keys"], "夹具里 Claude 有无牌价模型（claude-haiku-5-5）—— 它要在堆叠里")
        self.assertFalse(r["footnote"], "★ 「标 * 的是估算价」还常驻在表下")

    def test_full_mode_has_no_cache_note(self):
        self.assertNotIn("cache", self._probe("nav=traffic")["keys"], "默认口径不该多一条")


if __name__ == "__main__":
    unittest.main()
