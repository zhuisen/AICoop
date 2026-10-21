"""总览卡片「删除」的确认不许把布局弄乱（用户 2026-10-16 截图：点删除后「取消」折两行、「探针」被挤截断）。

## 2026-10-21 第三次换载体（AICoop P5 §5），守的东西没变

✗ 2026-10-19 版（⋯ 菜单里那一项原位换成「再点一次确认删除」）已被 P5 取代：
⋯ → 删除 ⇒ **Alert Dialog**（宽 340，默认焦点在「取消」，Esc / 点背板 = 取消）⇒ 确认后先隐藏、toast 带「撤销」，
toast 到期才真删（延迟删除另有闸：`test_overview_p5::RenderedInteractions::test_delete_waits_for_the_undo_window`）。
所以「不乱」的判据跟着换成：

1. 点「删除」**不删**（不发命令），只弹确认框 —— 不可逆动作必须两步。
2. 确认框的标题与两个按钮各一行、不截断；卡片仍是 148 高（确认框是 fixed 浮层，不进卡片）。
3. 默认焦点在「取消」：连按回车不能删掉一个号。
4. Esc 关掉确认框，仍不发命令；再开 ⋯ 菜单，删除项还是「删除」。

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
    const tw = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) { if (!n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      const ts = new Set([...rg.getClientRects()].filter(x => x.width > 0).map(x => Math.round(x.top)));
      if (ts.size > 1) tops.add(n.textContent.trim()); }
    return [...tops]; };
  const dlg = document.querySelector('[data-ov-confirm] [role="alertdialog"]');
  const btns = dlg ? [...dlg.querySelectorAll('[data-confirm-cancel], [data-confirm-delete]')] : [];
  return { open: menu.hasAttribute('data-open'), text: it ? it.textContent.trim() : null,
           dialog: !!dlg, wrapped: dlg ? lines(dlg).filter(t => btns.some(b => b.textContent.includes(t)) || dlg.querySelector('b').textContent.includes(t)) : [],
           clip: btns.some(b => b.scrollWidth > b.clientWidth + 1),
           focus: document.activeElement && document.activeElement.hasAttribute('data-confirm-cancel'),
           cardH: Math.round(card.getBoundingClientRect().height),
           inCard: !!(dlg && dlg.closest('[data-aid]')) };
}"""
# ★ 两个池各走各的命令：codex `run_rotate`、Gemini `run_agy_rotate` —— 只数前者，Gemini 那一档就恒为 0（空闸）。
SENT = "[...(window.__RUN_ROTATE__ || []), ...(window.__RUN_AGY__ || [])].filter(a => a[0] === 'remove').length"


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
        pg.keyboard.press("Enter"); pg.wait_for_timeout(200)       # 焦点在「取消」⇒ 回车 = 取消
        after_enter = pg.evaluate(ITEM)
        pg.evaluate(more); pg.wait_for_timeout(250)
        pg.evaluate(remove); pg.wait_for_timeout(250)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
        after_esc = pg.evaluate(ITEM)
        pg.evaluate(more); pg.wait_for_timeout(250)
        reopened = pg.evaluate(ITEM)
        sent_end = pg.evaluate(SENT)
        # 已知阳性：真点「删除」、等 toast 到期（3.2 s）⇒ 计数器必须数到 1，否则上面的 0 证明不了任何事
        pg.evaluate(remove); pg.wait_for_timeout(250)
        pg.evaluate("document.querySelector('[data-confirm-delete]').click()")
        pg.mouse.move(5, 5); pg.wait_for_timeout(3800)
        sent_real = pg.evaluate(SENT)
        br.close()
    return before, armed, sent_after_first, after_enter, after_esc, reopened, sent_end, sent_real


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheDeleteConfirmStaysOnOneRow(unittest.TestCase):
    def test_both_pools_both_sizes(self):
        for prov in ("codex", "gemini"):
            for w, h in ((1200, 800), (860, 560)):
                with self.subTest(prov=prov, w=w):
                    r = _run(prov, w, h)
                    if r is None:
                        self.skipTest("harness 3304 没起 —— skip 不是绿")
                    before, armed, sent, after_enter, after_esc, reopened, sent_end, sent_real = r
                    self.assertIsNotNone(before, "★ 第 2 张卡没有 ⋯ 菜单")
                    self.assertTrue(before["open"], "★ ⋯ 没打开")
                    self.assertEqual(before["text"], "删除", "★ 菜单里没有删除项")
                    self.assertFalse(before["dialog"], "★ 还没点删除就有确认框")
                    self.assertTrue(armed["dialog"], "★★ 点删除没有弹确认框")
                    self.assertEqual(sent, 0, "★★★ 点删除就删了 —— 不可逆动作必须两步")
                    self.assertEqual(armed["wrapped"], [], "★★ 确认框的标题 / 按钮折行了")
                    self.assertFalse(armed["clip"], "★ 确认框按钮被截断")
                    self.assertTrue(armed["focus"], "★★ 默认焦点不在「取消」—— 连按回车会删号")
                    self.assertEqual(armed["cardH"], 148, "★★ 卡片高度变了")
                    self.assertFalse(armed["inCard"], "★ 确认框画进了卡片里")
                    self.assertFalse(after_enter["dialog"], "★ 回车（焦点在取消）没关掉确认框")
                    self.assertFalse(after_esc["dialog"], "★ Esc 没关掉确认框")
                    self.assertEqual(sent_end, 0, "★★★ 取消之后还是发了删除命令")
                    self.assertEqual(reopened["text"], "删除")
                    self.assertEqual(sent_real, 1, "★ 已知阳性：真确认删除后计数器没数到 —— 上面的「0」没有判别力")

if __name__ == "__main__":
    unittest.main()
