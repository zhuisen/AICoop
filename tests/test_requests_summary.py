"""「请求」页右侧「今天总计」与顶栏 KPI 不跨 AI（用户 2026-10-22）。

用户原话：「我选择 claude 右侧不只是只有单条请求的内容的，还有今天总请求的总结」。
本仓铁律：四家的 t/s 口径不同，**任何界面都不出跨 AI 的合计速度**。所以：
- 顶栏「均速 / 首字」只有一家有实测时才写数，两家以上写「—」（`topMetrics`）；
- 右侧选了一家 ⇒ 那一家的总计；「全部」⇒ 各家一行，不合成一个数（`daySummary`）。
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
    def test_top_speed_is_a_dash_when_two_ais_have_measurements(self):
        got = _node("m.topMetrics([R({platform:'codex',tps:100,ttft_ms:1000}), R({platform:'claude',tps:20,ttft_ms:3000})])")
        self.assertEqual(got["n"], 2)
        self.assertIsNone(got["avgTps"], "★ 两家各有实测 ⇒ 不许合成一个均速")
        self.assertIsNone(got["ttftMedianS"], "★ 首字中位同理")

    def test_top_speed_is_that_ais_number_when_only_one_measured(self):
        got = _node("m.topMetrics([R({platform:'codex',tps:100,ttft_ms:1000}), R({platform:'claude',tps:20,est:true})])")
        self.assertEqual(got["n"], 2, "次数仍是全部")
        self.assertEqual(got["avgTps"], 100, "只有 Codex 有实测 ⇒ 写 Codex 的数")
        self.assertEqual(got["ttftMedianS"], 1.0)

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
