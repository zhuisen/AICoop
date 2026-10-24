"""带 token 数的列表一律按**本期 Token 总量**降序（用户 2026-10-25：「底部的卡片没有按照 token 总计消耗的大小进行排序」
「悬浮弹窗从上到下的顺序没有按照 token 总计消耗的大小进行排序」「审查所有地方，都要这样进行排序」）。

✗ 已被取代：2026-10-15 的「卡片按今日 token 降序」· 浮层「按平台注册顺序」· 2026-08-12 的「两列行按用户自己排的顺序」
（设置里的平台排序现在只管不带数字的平台胶囊）。

## 守的（真 bundle，年度 / 30d / 今日三档）
1. 平台卡片、两列行、浮层逐行三处顺序相同，且按卡上那个本期大数降序；
2. 平台详情「总量」档的三类按本期 token 降序（图例 = 堆叠层 = 浮层）；
3. 源码里的其它几处（菜单栏小时明细、请求页今天总计、中转站今日按模型、缓存构成文字、设置平台列表兜底）按 token 排。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import re
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

PROBE = """async (clicks) => {
  const q = (s) => [...document.querySelectorAll(s)];
  const hits = [];
  for (const txt of clicks) {
    const el = q('#root span, #root div, #root button').find(e => (e.textContent || '').trim() === txt && !e.children.length);
    hits.push(!!el);
    if (el) { el.dispatchEvent(new MouseEvent('click', { bubbles: true })); await new Promise(r => setTimeout(r, 900)); }
  }
  const cards = q('[data-plat-card]').map(e => [e.dataset.platCard, Number(e.dataset.total)]);
  const rows = q('[data-plat-row]').map(e => e.dataset.platRow);
  const tip = document.querySelector('[data-tk-tip]');
  const hit = tip && tip.previousElementSibling;
  if (hit) { const r = hit.getBoundingClientRect();
    hit.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: r.left + r.width * 0.9, clientY: r.top + r.height / 2 })); }
  await new Promise(r => setTimeout(r, 300));
  const tipRows = q('[data-tk-tip] [data-tip-row]').map(e => e.dataset.tipRow);
  const legend = q('[data-cls-legend]').map(e => [e.dataset.clsLegend, Number(e.dataset.sum)]);
  const layers = q('[data-tk-chart] [data-layer]').map(e => e.dataset.layer);
  return { hits, cards, rows, tipRows, legend, layers };
}"""


def _probe(q, clicks=()):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        pg = br.new_page(viewport={"width": 1200, "height": 900})
        pg.goto("http://127.0.0.1:3304/harness.html?" + q, timeout=30000)
        pg.wait_for_timeout(2200)
        r = pg.evaluate(PROBE, list(clicks))
        br.close()
    return r


def code(rel):
    s = (SRC / rel).read_text(encoding="utf-8")
    s = re.sub(r"\{/\*[\s\S]*?\*/\}", "", s)
    return re.sub(r"(?<![:/\"'])//[^\n]*", "", s)


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TokenPageOnTheRealBundle(unittest.TestCase):
    def test_cards_rows_and_tooltip_follow_the_window_total(self):
        for q, clicks in (("nav=traffic", ("年度",)), ("nav=traffic", ()), ("nav=traffic", ("今日",))):
            r = _probe(q, clicks)
            if r is None:
                self.skipTest("harness 3304 没起 —— skip 不是绿")
            with self.subTest(clicks=clicks):
                self.assertTrue(all(r["hits"]), "★ 前提：档位点中了 %s" % r["hits"])
                self.assertGreaterEqual(len(r["cards"]), 3, "卡片没渲染出来：%s" % r)
                totals = [v for _, v in r["cards"]]
                self.assertEqual(totals, sorted(totals, reverse=True), "★★ 卡片没按本期 token 总量降序：%s" % r["cards"])
                self.assertGreater(len(set(totals)), 1, "夹具里各家总量相同 —— 断言打空了")
                self.assertEqual(len(r["tipRows"]), len(r["rows"]), "★ 前提：浮层弹出来了 %s" % r)
                self.assertEqual(r["tipRows"], r["rows"], "★★ 浮层从上到下与两列行不是同一个顺序")
                self.assertEqual(r["tipRows"], r["layers"], "浮层与堆叠层（本期总量降序）不同序")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class PlatformTotalModeOnTheRealBundle(unittest.TestCase):
    def test_classes_follow_their_window_total(self):
        r = _probe("nav=platform:claude", ("总量",))
        if r is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        self.assertTrue(all(r["hits"]), "★ 前提：点中了「总量」")
        self.assertGreaterEqual(len(r["legend"]), 2, "★ 前提：总量档图例渲染出来了 %s" % r)
        sums = [v for _, v in r["legend"]]
        self.assertEqual(sums, sorted(sums, reverse=True), "★★ 总量三类没按本期 token 降序：%s" % r["legend"])
        self.assertEqual([k for k, _ in r["legend"]], r["layers"], "图例与堆叠层不同序")
        self.assertEqual(r["tipRows"], r["layers"], "★ 浮层与堆叠层不同序")


class TheOtherPlacesSortByTokens(unittest.TestCase):
    def test_sources(self):
        mb = code("components/MenuBarToday.tsx")
        i = mb.index("function breakdown(")
        self.assertNotIn(".sort(", mb[i:mb.index("if (!rows.length)", i)], "菜单栏小时明细又按这一小时的值重排")
        self.assertIn(".sort((a, b) => (b.s.input + b.s.output) - (a.s.input + a.s.output))", code("pages/RequestsPage.tsx"))
        self.assertIn("sort((a, b) => b.total_tokens - a.total_tokens)", code("relayView.ts"))
        self.assertIn("parts.sort((a, b) => b[1] - a[1])", code("traffic.ts"))
        self.assertIn("orderedKeys([...all], prefs, (k) => vol30(k) ?? 0)", code("pages/SettingsPage.tsx"))


if __name__ == "__main__":
    unittest.main()
