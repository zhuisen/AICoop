"""Gemini 总览卡：名字行的徽章不折行、两条细条起点对齐（用户 2026-10-16 截图「gemini 总览卡片错位了」）。

现场：`tomyhuo… ULTRA 当前 下一个` 里「当前」被挤成两行（当 / 前）；「5h」与「周」两条细条起点差 ~2.4px。
根因：「当前 / 切换 / 只读」没有 `flexShrink: 0`（「下一个」有）；窗口标签按字形自然宽（两个等宽字 vs 一个汉字）。

## 守的（真 bundle，Gemini 池 3 个号，第一个号用长名字；860 / 1200 / 1440 三档）
1. 每个徽章一行（含「当前」，2026-10-19 起叫「在用」）。
2. 名字只截断不消失（≥ 40px）。
3. 同一张卡里两条细条左边缘对齐（≤ 0.5px）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import unittest
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# ★ 2026-10-19 总览重做（交接包 page5）：停用的号收进「已停用」条 ⇒ `ovoff=1` 把条展开，3 张卡都在可见网格里；
#   「当前」改叫交接包的「在用」（同一个徽章，标签带 ✓ 图标，所以按 `data-ov-tag` 取而不是按无子节点的 span）。
URL = "http://127.0.0.1:3304/harness.html?nav=home&agypool=3&agyname0=tomyhuohuo&ovoff=1"
BADGES = ("在用", "下一个", "只读", "已停用", "冷却中", "ULTRA")
PROBE = """(badges) => [...document.querySelectorAll('[data-ov-page] [data-ov-card]')].map(card => {
  // 只量文字节点：「在用」带一个 ✓ 图标（svg），它的矩形顶边和字不同，会被误数成第二行。
  const lines = e => { const tops = new Set();
    for (const n of e.childNodes) { if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n);
      for (const x of rg.getClientRects()) if (x.width > 0) tops.add(Math.round(x.top)); }
    return tops.size; };
  const badge = [...card.querySelectorAll('[data-ov-tag]')].filter(e => e.getBoundingClientRect().width > 0)
                     .map(e => ({ t: e.textContent.trim(), lines: lines(e) }));
  const name = card.querySelector('[data-card-name]');
  const bars = [...card.querySelectorAll('[data-ov-win]')]
                    .map(e => ({ t: e.dataset.ovWin, x: e.children[1] && e.children[1].getBoundingClientRect().left }));
  return { badge, nameW: name ? name.getBoundingClientRect().width : null, nameNat: name ? name.scrollWidth : null, bars };
})"""


def _run(w, h):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        ctx = br.new_context(viewport={"width": w, "height": h})
        ctx.add_init_script("localStorage.setItem('codexbar_provider', 'gemini')")
        pg = ctx.new_page()
        pg.goto(URL, timeout=30000)
        pg.wait_for_timeout(2200)
        out = pg.evaluate(PROBE, list(BADGES))
        br.close()
    return out


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheGeminiCardHeaderStaysOnOneRow(unittest.TestCase):
    def test_three_sizes(self):
        for w, h in ((1440, 900), (1200, 800), (860, 560)):
            with self.subTest(w=w):
                cards = _run(w, h)
                if cards is None:
                    self.skipTest("harness 3304 没起 —— skip 不是绿")
                self.assertEqual(len(cards), 3, "★ 夹具没渲染出 3 张 Gemini 卡")
                self.assertIn("在用", [b["t"] for c in cards for b in c["badge"]], "★ 夹具里没有「在用」徽章，这条闸没在验东西")
                for i, c in enumerate(cards):
                    for b in c["badge"]:
                        self.assertEqual(b["lines"], 1, "★★ 第 %d 张卡的「%s」折行了" % (i, b["t"]))
                    # 短名字（`Asen` 自然宽 ~35px）本来就不到 40：判据是「不被压到 40 以下，除非它本来就这么短」。
                    self.assertGreaterEqual(c["nameW"] or 0, min(39.5, (c["nameNat"] or 0) - 0.5), "★ 第 %d 张卡的名字被压没了" % i)
                    xs = [b["x"] for b in c["bars"] if b["x"] is not None]
                    self.assertEqual(len(xs), 2, "★ 第 %d 张卡没找到两条细条：%s" % (i, c["bars"]))
                    self.assertLessEqual(abs(xs[0] - xs[1]), 0.5, "★★ 第 %d 张卡两条细条起点不齐：%s" % (i, c["bars"]))


if __name__ == "__main__":
    unittest.main()
