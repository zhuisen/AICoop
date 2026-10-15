"""总览卡片「删除」确认态不许乱（用户 2026-10-16 截图：点删除后「取消」折两行、「探针」被挤截断）。

根因：确认态用「确认删除」+「取消」（~120px）顶替 34px 的垃圾桶，320px 宽的卡一行放不下，
动作条从 46px 涨到 60px。改法：确认态整条只剩「删除 X？/ 确认删除 / 取消」。codex 与 Gemini 两种卡同一套。

## 守的（真 bundle，860 / 1200 两档，codex + Gemini 池）
1. 确认态只有提示 + 确认删除 + 取消 —— 切换 / 探针 / 图标都不在这一行。
2. 每块一行、不截断；整条高度与平常态相同（卡片不跳）。
3. 点「取消」回到完整动作条。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import unittest
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
URL = "http://127.0.0.1:3304/harness.html?nav=home&agypool=3"
BAR = """(sel) => {
  const anchor = [...document.querySelectorAll('[title]')].find(e => e.title.startsWith(sel) && e.getBoundingClientRect().width > 0);
  if (!anchor) return null;
  const bar = anchor.parentElement, br = bar.getBoundingClientRect();
  const kids = [...bar.children].filter(e => e.getBoundingClientRect().height > 4).map(e => {
    const r = e.getBoundingClientRect(), rg = document.createRange(); rg.selectNodeContents(e);
    const tops = new Set([...rg.getClientRects()].filter(x => x.width > 0).map(x => Math.round(x.top)));
    return { t: e.textContent.trim(), h: r.height, lines: tops.size, clip: e.scrollWidth > e.clientWidth + 1 };
  });
  return { h: br.height, kids };
}"""


def _run(prov, w, h):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        ctx = br.new_context(viewport={"width": w, "height": h})
        ctx.add_init_script("localStorage.setItem('codexbar_provider', '%s')" % prov)
        pg = ctx.new_page()
        pg.goto(URL, timeout=30000)
        pg.wait_for_timeout(2000)
        cards = pg.locator("[data-cards-grid] > *")
        cards.nth(min(1, cards.count() - 1)).click(position={"x": 120, "y": 40})
        pg.wait_for_timeout(500)
        before = pg.evaluate(BAR, "重命名")
        pg.locator('[title^="删除 "], [title^="从池里移除"]').locator("visible=true").first.click()
        pg.wait_for_timeout(400)
        confirm = pg.evaluate(BAR, "删除 ") or pg.evaluate(BAR, "从池里移除")
        pg.locator("[data-confirm-delete] ~ span", has_text="取消").first.click()
        pg.wait_for_timeout(300)
        back = pg.evaluate(BAR, "重命名")
        br.close()
    return before, confirm, back


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheDeleteConfirmStaysOnOneRow(unittest.TestCase):
    def test_both_pools_both_sizes(self):
        for prov in ("codex", "gemini"):
            for w, h in ((1200, 800), (860, 560)):
                with self.subTest(prov=prov, w=w):
                    r = _run(prov, w, h)
                    if r is None:
                        self.skipTest("harness 3304 没起 —— skip 不是绿")
                    before, confirm, back = r
                    self.assertIsNotNone(before, "动作条没展开（卡片没选中）")
                    self.assertIsNotNone(confirm, "确认态没出现")
                    texts = [k["t"] for k in confirm["kids"] if k["t"]]
                    self.assertEqual(len(texts), 3, "★★ 确认态这一行应只有 提示/确认删除/取消：%s" % texts)
                    self.assertRegex(texts[0], r"^(删除|移除) .+？$")
                    self.assertEqual(texts[1:], ["确认删除", "取消"])
                    for k in confirm["kids"]:
                        if k["t"]:
                            self.assertEqual(k["lines"], 1, "★★ %r 折行了" % k["t"])
                            self.assertFalse(k["clip"], "★ %r 被截断" % k["t"])
                    self.assertAlmostEqual(confirm["h"], before["h"], delta=0.5,
                                           msg="★ 确认态动作条高度变了 %.1f → %.1f" % (before["h"], confirm["h"]))
                    self.assertIsNotNone(back, "★ 点「取消」没回到完整动作条")


if __name__ == "__main__":
    unittest.main()
