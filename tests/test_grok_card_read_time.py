"""总览 Grok 档：卡片常显读数时刻，页脚一行（用户 2026-10-15 选「卡片显示读数时间」）。

原来只有降级时才说「HH:MM · N 分钟前的读数」，健康时写死「xAI 账单 · 不在轮换池」——
看不出这个数是几分钟前的；页脚又是竖排两行（文字 + 下面一行隐形占位），卡底多出 ~26px 空白。

## 守的（全部在真 bundle 上量）
1. 健康态页脚写出读数时刻（`HH:MM · N 分钟前`），降级态仍是「…的读数」。
2. 页脚只有一行：隐形占位与文字同一行。
3. 读数时刻不被省略号截断（Range 量文字实宽 ≤ 盒宽）。
4. 页脚下方留白与 codex 账号卡一致（页面统一性）。⚠️ 不比卡高：账号卡高随窗口行数变
   （5h+周 156px / 只有周 ~135px），grok 只有周一行。原来 grok 卡 157 ≈ 两行账号卡，
   是多出来那行隐形占位**碰巧**凑出来的，不是对齐。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import re
import unittest
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
URL = "http://127.0.0.1:3304/harness.html?nav=home"

PROBE = """() => {
  const e = document.querySelector('[data-grok-read-at]');
  if (!e) return null;
  const r = document.createRange(); r.selectNodeContents(e);
  const foot = e.parentElement, ghost = foot.lastElementChild;
  const card = e.closest('[data-cards-grid]').firstElementChild;
  return { text: e.textContent, need: r.getBoundingClientRect().width, have: e.getBoundingClientRect().width,
           textTop: e.getBoundingClientRect().top, textBottom: e.getBoundingClientRect().bottom,
           ghostTop: ghost.getBoundingClientRect().top,
           // 2026-10-19：页脚是共用外壳 `ov/OvCard` 的 `[data-ov-foot]`（定高 28），量到它为止 ——
           //   文字外面那层内联 span 比页脚矮，量它会把两张同构的卡量出不同的「留白」。
           below: card.getBoundingClientRect().bottom - (e.closest('[data-ov-foot]') || foot).getBoundingClientRect().bottom };
}"""
CODEX = """() => {
  const exp = [...document.querySelectorAll('[data-cards-grid] span')].find(s => /^到期 /.test(s.textContent));
  const foot = exp.closest('[data-ov-foot]') || exp.parentElement;
  let card = foot; while (card && parseFloat(getComputedStyle(card).borderBottomWidth) === 0) card = card.parentElement;
  return card.getBoundingClientRect().bottom - foot.getBoundingClientRect().bottom;
}"""


def _measure(w, h, prov, grok="ok", probe=PROBE):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        return "skip"
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        ctx = br.new_context(viewport={"width": w, "height": h})
        ctx.add_init_script("localStorage.setItem('codexbar_provider', '%s')" % prov)
        pg = ctx.new_page()
        pg.goto("%s&grok=%s" % (URL, grok), timeout=30000)
        pg.wait_for_timeout(2200)
        r = pg.evaluate(probe)
        br.close()
    return r


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheGrokCardSaysWhenItWasRead(unittest.TestCase):
    def _get(self, *a, **k):
        r = _measure(*a, **k)
        if r == "skip":
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        self.assertIsNotNone(r, "grok 卡没渲染（或 data-grok-read-at 丢了）")
        return r

    def test_healthy_footer_shows_the_reading_time(self):
        for w, h in ((1200, 800), (860, 560)):
            with self.subTest(w=w):
                r = self._get(w, h, "grok")
                self.assertRegex(r["text"], r"^xAI 账单 · \d\d:\d\d · (刚刚|\d+ (分钟|小时|天)前)$",
                                 "★★ 健康态没写读数时刻")

    def test_stale_footer_still_says_it_is_old(self):
        r = self._get(1200, 800, "grok", grok="stale")
        self.assertRegex(r["text"], r"^\d\d:\d\d · .+前的读数$", "★ 降级态的「旧读数」披露丢了")

    def test_footer_is_one_row(self):
        for w, h in ((1200, 800), (860, 560)):
            with self.subTest(w=w):
                r = self._get(w, h, "grok")
                self.assertLess(r["ghostTop"], r["textBottom"], "★★ 页脚又竖排成两行（卡底空白）：%s" % r)

    def test_reading_time_is_not_truncated(self):
        for w, h in ((1200, 800), (1440, 900), (860, 560)):
            with self.subTest(w=w):
                r = self._get(w, h, "grok")
                self.assertLessEqual(r["need"], r["have"] + 0.5, "★ 读数时刻被省略号截断：%s" % r)

    def test_space_under_the_footer_matches_the_account_cards(self):
        PROBE_G = PROBE.replace("const card = e.closest('[data-cards-grid]').firstElementChild;",
                                "let card = e; while (parseFloat(getComputedStyle(card).borderBottomWidth) === 0) card = card.parentElement;")
        for w, h in ((1200, 800), (860, 560)):
            with self.subTest(w=w):
                g = self._get(w, h, "grok", probe=PROBE_G)["below"]
                c = self._get(w, h, "codex", probe=CODEX)
                self.assertGreater(c, 0)
                self.assertAlmostEqual(g, c, delta=1.5, msg="★★ grok 卡底多出空白 %.1f vs 账号卡 %.1f" % (g, c))


if __name__ == "__main__":
    unittest.main()
