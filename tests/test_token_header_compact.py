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


if __name__ == "__main__":
    unittest.main()
