"""「请求」页右侧「今天总计」与右上角 KPI 跟着筛选走（用户 2026-10-22）。

用户原话：「我选择 claude 右侧不只是只有单条请求的内容的，还有今天总请求的总结」。
同日又说右上角「同步左侧的按钮，如果选全部就全部信息展示，如果是 codex 就只有 codex」。所以：
- 右上角 = 所选那一家（「全部」= 今天全部请求）的 次数 · 均速 · 首字中位（`dayMetrics(list)`）；
- 右侧选了一家 ⇒ 那一家的总计；「全部」⇒ 各家一行（`daySummary`）。
"""
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_requests_p3 import CHROME, HARNESS, _harness_up, _node

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class Logic(unittest.TestCase):
    def test_summary_sums_tokens_and_keeps_unknown_apart_from_zero(self):
        got = _node("m.daySummary([R({input:1000,cached:800,output:50,tps:40}), R({input:500,cached:0,output:null,tps:60,est:true})])")
        self.assertEqual((got["n"], got["input"], got["cached"], got["output"]), (2, 1500, 800, 50))
        self.assertEqual(got["measured"], 1)
        self.assertEqual(got["avgTps"], 40, "★ 估值行不进均速")
        empty = _node("m.daySummary([])")
        self.assertEqual(empty["n"], 0)
        self.assertIsNone(empty["avgTps"], "没有行 ⇒ 读不到，不是 0")
        self.assertIsNone(empty["cacheRate"])


@unittest.skipUnless(_harness_up() and Path(CHROME).exists(), "harness 没在跑 —— skip 不是绿")
class Rendered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def _page(self):
        pg = self.br.new_page(viewport={"width": 1200, "height": 760})
        pg.goto(f"{HARNESS}/harness.html?nav=requests")
        pg.wait_for_selector("[data-req-row]", timeout=15000)
        pg.wait_for_timeout(400)
        self.addCleanup(pg.close)
        return pg

    def test_all_shows_one_row_per_ai_not_a_total(self):
        pg = self._page()
        rows = pg.evaluate("() => [...document.querySelectorAll('[data-req-summary=all] [data-req-summary-row]')].map(e => e.dataset.reqSummaryRow)")
        self.assertGreaterEqual(len(rows), 2, f"夹具不到两家 —— 判不了：{rows}")
        self.assertEqual(len(rows), len(set(rows)))

    KPIS = "() => [...document.querySelectorAll('[data-req-kpis] > *')].map(e => e.textContent.replace(/\\s+/g, ''))"

    def test_header_follows_the_filter(self):
        pg = self._page()
        all_ = pg.evaluate(self.KPIS)
        n_all = pg.evaluate("() => document.querySelectorAll('[data-req-row]').length")
        self.assertTrue(all_[0].endswith(f"{n_all}次"), f"「全部」次数 ≠ 列表行数：{all_[0]} vs {n_all}")
        self.assertNotIn("—", all_[1], "★ 选「全部」均速也要有数（用户：全部就全部信息展示）")
        pg.click("[data-req-filter=claude]")
        pg.wait_for_timeout(250)
        cl = pg.evaluate(self.KPIS)
        n_cl = pg.evaluate("() => document.querySelectorAll('[data-req-row]').length")
        self.assertLess(n_cl, n_all, "夹具里 Claude 不少于全部 —— 判不了")
        self.assertTrue(cl[0].endswith(f"{n_cl}次"), f"★ 选了 Claude 右上角次数仍是全部：{cl[0]} vs {n_cl}")

    def test_picking_claude_shows_claudes_day_summary(self):
        pg = self._page()
        pg.click("[data-req-filter=claude]")
        pg.wait_for_timeout(250)
        txt = pg.evaluate("() => document.querySelector('[data-req-summary=claude]')?.textContent || ''")
        self.assertIn("Claude", txt)
        n = pg.evaluate("() => document.querySelectorAll('[data-req-row]').length")
        self.assertIn(f"{n} 次", txt, "★ 总计的次数要等于列表里这一家的行数")
        self.assertIn("首字中位", txt)
        self.assertFalse(pg.evaluate("() => !!document.querySelector('[data-req-summary-row]')"), "选了一家就不该再出各家行")


if __name__ == "__main__":
    unittest.main()
