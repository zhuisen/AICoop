"""总览卡片：第二行状态短、卡片不拥挤（用户 2026-10-23「太拥挤了」「话太多了」）。

用户点名的四句：「上次用 02:46 · 今日 11.4M」「此刻没有在跑的会话 · 今日 305」「24 小时内没启动过它」
「本周用量不到 1% · 推断」。用户选了「一律缩成短格式」：只写数字 + 最短的词（`02:46 · 11.4M` · `空闲 · 305` ·
`24h 未用` · `<1% · 推断`），整句进悬停提示 —— 信息不丢，只是不常驻。
另一半是列数：最小窗口 3 列（卡 ~245），第 4 列起每张要 ≥ 320（`overview.ts::ovCols`），列数在 `test_overview_5b` 守。

真 bundle，四家 × 多种状态；先正面证明每个场景都真的渲染出了状态行。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import unittest
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness.html?nav=home&anon=1&notrans=1&"
SCENES = ["ovplat=codex&run=1", "ovplat=codex&ovcool=1&ovunprobed=1&ovlow=1&ovoff=1", "ovplat=gemini&agypool=4&ovoff=1",
          "ovplat=claude", "ovplat=grok&grok=zero", "ovplat=grok&grok=expired"]
#: 最长的一句是在跑行 `244 t/s · ×2 · 3.8M`（19 字）。原来最长的「凭证失效 · 终端跑 codex-rotate login 重登」是 31 字。
MAX_CHARS = 20
LONG = ("上次用", "此刻没有在跑的会话", "24 小时内", "本周用量不到", "会话 · 今日", "点刷新再取一次", "终端跑", "后恢复")


def _measure():
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(BASE, timeout=2).read(1)
    except Exception:
        return None
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        try:
            for q in SCENES:
                pg = br.new_page(viewport={"width": 1200, "height": 900})
                pg.goto(BASE + q)
                pg.wait_for_selector("[data-ov-card] [data-ov-dyn]", timeout=15000)
                pg.wait_for_timeout(400)
                out[q] = pg.evaluate("""() => [...document.querySelectorAll('[data-ov-card] [data-ov-dyn]')].map(e => ({
                    t: e.textContent.trim(), title: e.title || (e.querySelector('[title]') || {}).title || ''}))""")
                pg.close()
        finally:
            br.close()
    return out


class TheStatusLineIsShort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _measure()

    def setUp(self):
        if self.m is None:
            self.skipTest("harness / playwright 不在")

    def test_every_scene_rendered_status_lines(self):
        for q, rows in self.m.items():
            with self.subTest(q=q):
                self.assertTrue(rows, "★ 这个场景一行状态都没渲染出来 —— 下面的断言会空转")

    def test_short_and_the_full_sentence_is_in_the_tooltip(self):
        for q, rows in self.m.items():
            for r in rows:
                with self.subTest(q=q, t=r["t"]):
                    self.assertLessEqual(len(r["t"]), MAX_CHARS, "★ 状态行太长了：%r" % r["t"])
                    for w in LONG:
                        self.assertNotIn(w, r["t"], "★ 长句又回到卡上了")
                    self.assertTrue(r["title"], "★ 缩短的那句要能悬停看全文")


if __name__ == "__main__":
    unittest.main()
