"""总览卡片「删除」二段确认不许把布局弄乱（用户 2026-10-16 截图：点删除后「取消」折两行、「探针」被挤截断）。

## 2026-10-19 换了载体，守的东西没变

原来确认态挤在卡片的动作条里（320px 宽的卡差 ~80px），修法是确认态整条只剩「删除 X？/ 确认删除 / 取消」。
交接包 page5 起删除收进底栏 ⋯ 菜单：第一次点只把**那一项的文字**原位换成「再点一次确认删除」，
5 秒内再点才执行，点菜单外 / Esc 即取消。所以「不乱」的判据跟着换成：

1. 第一次点**不删**（不发命令）—— 不可逆动作必须两步。
2. 确认态那一项一行、不截断，高度与菜单里其它项相同（菜单不跳）；卡片仍是 148 高。
3. 确认态旁边**不挨着**「切换 / 探针」：它在菜单里，那两个在底栏，不是同一行。
4. 关掉菜单再打开，回到「删除这个号」（确认态不残留）。

真 bundle，codex + Gemini 两个池 × 860 / 1200 两档。harness 没起 ⇒ skip（不是绿）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import unittest
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
URL = "http://127.0.0.1:3304/harness.html?nav=home&agypool=3&notrans=1&ovhover=1"
ITEM = """() => {
  const card = document.querySelectorAll('[data-cards-grid] > [data-aid]')[1];
  const menu = card && card.querySelector('[data-ov-menu]');
  if (!menu) return null;
  const it = menu.querySelector('[data-ov-mi="remove"]');
  const lines = e => { const tops = new Set();
    for (const n of e.childNodes) { if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      for (const x of rg.getClientRects()) if (x.width > 0) tops.add(Math.round(x.top)); }
    return tops.size; };
  const others = [...menu.querySelectorAll('[data-ov-mi]')].filter(e => e !== it).map(e => Math.round(e.getBoundingClientRect().height));
  return { open: menu.hasAttribute('data-open'), text: it ? it.textContent.trim() : null,
           armed: it ? it.hasAttribute('data-confirm-delete') : false,
           h: it ? Math.round(it.getBoundingClientRect().height) : null, others,
           lines: it ? lines(it) : 0, clip: it ? it.scrollWidth > it.clientWidth + 1 : true,
           cardH: Math.round(card.getBoundingClientRect().height),
           inFooter: !!(it && it.closest('[data-ov-actions]') && !it.closest('[data-ov-menu]')) };
}"""
SENT = "(window.__RUN_ROTATE__ || []).filter(a => a[0] === 'remove').length"


def _run(prov, w, h):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        ctx = br.new_context(viewport={"width": w, "height": h})
        ctx.add_init_script("localStorage.setItem('codexbar_provider', '%s')" % prov)
        pg = ctx.new_page()
        pg.goto(URL, timeout=30000)
        pg.wait_for_timeout(2200)
        more = "document.querySelectorAll('[data-cards-grid] > [data-aid]')[1].querySelector('[data-ov-ab=\"more\"]').click()"
        remove = "document.querySelectorAll('[data-cards-grid] > [data-aid]')[1].querySelector('[data-ov-mi=\"remove\"]').click()"
        pg.evaluate(more); pg.wait_for_timeout(250)
        before = pg.evaluate(ITEM)
        pg.evaluate(remove); pg.wait_for_timeout(250)
        armed = pg.evaluate(ITEM)
        sent_after_first = pg.evaluate(SENT)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
        pg.evaluate(more); pg.wait_for_timeout(250)
        reopened = pg.evaluate(ITEM)
        br.close()
    return before, armed, sent_after_first, reopened


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheDeleteConfirmStaysOnOneRow(unittest.TestCase):
    def test_both_pools_both_sizes(self):
        for prov in ("codex", "gemini"):
            for w, h in ((1200, 800), (860, 560)):
                with self.subTest(prov=prov, w=w):
                    r = _run(prov, w, h)
                    if r is None:
                        self.skipTest("harness 3304 没起 —— skip 不是绿")
                    before, armed, sent, reopened = r
                    self.assertIsNotNone(before, "★ 第 2 张卡没有 ⋯ 菜单")
                    self.assertTrue(before["open"], "★ ⋯ 没打开")
                    self.assertIn(before["text"], ("删除这个号", "从池里移除"), "★ 菜单里没有删除项")
                    self.assertFalse(before["armed"])
                    self.assertTrue(armed["armed"], "★★ 第一次点没有进入确认态")
                    self.assertRegex(armed["text"], r"^再点一次确认(删除|移除)$")
                    self.assertEqual(sent, 0, "★★★ 第一次点就删了 —— 不可逆动作必须两步")
                    self.assertEqual(armed["lines"], 1, "★★ 确认态折行了")
                    self.assertFalse(armed["clip"], "★ 确认态被截断")
                    self.assertTrue(armed["others"], "★ 菜单里没有别的项可比")
                    self.assertEqual({armed["h"]}, set(armed["others"]), "★★ 确认态那一项与别的项不等高 —— 菜单在跳")
                    self.assertEqual(armed["cardH"], 148, "★★ 卡片高度变了")
                    self.assertFalse(armed["inFooter"], "★ 确认态跑进了底栏，挨着切换 / 探针")
                    self.assertFalse(reopened["armed"], "★★ 关掉再开，确认态还残留着")
                    self.assertIn(reopened["text"], ("删除这个号", "从池里移除"))


if __name__ == "__main__":
    unittest.main()
