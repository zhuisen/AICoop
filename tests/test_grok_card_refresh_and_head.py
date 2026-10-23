"""Grok 总览卡：点刷新有反应 · 名字行不截断（用户 2026-10-23 截图两条）。

1. 「grok 点刷新没有对应的 UI 交互反应」：token 过期时 grok-quota 不发请求、几十毫秒就回来，转圈一闪而过、
   数字不变 ⇒ 看上去就是没点中。修法：结果出来就弹 toast，失败按原因说「为什么没变、要做什么」
   （`grok.ts::grokRefreshToast`，头部 / 卡片 / ⌘K / 菜单栏四个入口共用）。
2. 「面板出现边界截断内容」：带 SuperGrok 徽章时名字行要 180px，860 / 1200 / 1440 只有 155–175，
   最右的失效标记被裁掉一半。修法：失效标记排在套餐徽章前面；套餐徽章空间不够时缩成省略号（全名在悬停提示里）。

真 bundle（harness 127.0.0.1:3304，`?grok=expired&grokplan=SuperGrok`）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import pathlib
import subprocess
import unittest
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness.html?nav=home&anon=1&notrans=1&ovplat=grok&grok=expired&grokplan=SuperGrok"
GROK_TS = (pathlib.Path(__file__).resolve().parents[1] / "codexbar" / "src" / "grok.ts").as_posix()

HEAD = """() => { const c = document.querySelector('[data-ov-card]'); if (!c) return null;
  const n = c.querySelector('[data-card-name]').parentElement, r = n.getBoundingClientRect();
  const kids = [...n.children].map(e => { const b = e.getBoundingClientRect();
    return {t: (e.textContent || '').trim(), plan: e.hasAttribute('data-grok-plan'), l: b.left, r: b.right, w: b.width}; });
  return {left: r.left, right: r.right, kids}; }"""


def _run(fn):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        try:
            return fn(br)
        finally:
            br.close()


class TheNameRowNeverClipsTheWarning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def go(br):
            out = {}
            for w in (860, 1000, 1200, 1440):
                pg = br.new_page(viewport={"width": w, "height": 800})
                pg.goto(BASE)
                pg.wait_for_selector("[data-ov-card] [data-card-name]", timeout=15000)
                pg.wait_for_timeout(500)
                out[w] = pg.evaluate(HEAD)
                pg.close()
            return out
        cls.m = _run(go)

    def setUp(self):
        if self.m is None:
            self.skipTest("harness / playwright 不在")

    def test_every_item_but_the_plan_is_whole_and_inside(self):
        for w, h in self.m.items():
            with self.subTest(w=w):
                self.assertIsNotNone(h, "★ 总览 grok 卡没渲染出来")
                self.assertTrue(any(k["plan"] for k in h["kids"]), "已知阳性：夹具里得有套餐徽章")
                self.assertGreaterEqual(len(h["kids"]), 4, "名字 · 在用 · 失效标记 · 套餐")
                for k in h["kids"]:
                    if k["plan"]:
                        continue
                    self.assertLessEqual(k["r"], h["right"] + 0.5, "★ %r 被名字行右边界裁掉（%d 宽）" % (k["t"] or "标记", w))

    def test_the_warning_comes_before_the_plan(self):
        for w, h in self.m.items():
            with self.subTest(w=w):
                plan_i = next(i for i, k in enumerate(h["kids"]) if k["plan"])
                self.assertEqual(plan_i, len(h["kids"]) - 1, "套餐徽章排最后，空间不够只缩它")
                self.assertLessEqual(h["kids"][plan_i]["r"], h["right"] + 0.5, "套餐徽章缩成省略号，不溢出")


class RefreshGivesFeedback(unittest.TestCase):
    def test_expired_token_refresh_says_why(self):
        def go(br):
            pg = br.new_page(viewport={"width": 1200, "height": 800})
            pg.goto(BASE + "&grokdelay=800")
            pg.wait_for_selector("[data-ov-head='refresh']", timeout=15000)
            pg.wait_for_timeout(400)
            pg.evaluate("() => document.querySelector(\"[data-ov-head='refresh']\").click()")
            pg.wait_for_timeout(200)
            busy = pg.evaluate("() => document.querySelector(\"[data-ov-head='refresh']\").textContent")
            pg.wait_for_selector("[data-toast]", timeout=5000)
            toast = pg.evaluate("() => [...document.querySelectorAll('[data-toast]')].map(e => e.textContent).join('|')")
            pg.close()
            return busy, toast
        got = _run(go)
        if got is None:
            self.skipTest("harness / playwright 不在")
        busy, toast = got
        self.assertIn("刷新中", busy, "请求在途时按钮要转圈 / 写「刷新中…」")
        self.assertIn("token 已过期", toast, "★ 刷新完要说为什么数字没变")


class TheToastNamesTheReason(unittest.TestCase):
    def toast(self, ok, reason):
        expr = "m.grokRefreshToast(%s, %s)" % (json.dumps(ok), json.dumps({"reason": reason} if reason else None))
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                            "import('%s').then(m => console.log(JSON.stringify(%s)))" % (GROK_TS, expr)],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_reasons(self):
        self.assertEqual(self.toast(True, None), "已刷新 Grok · 免费")
        self.assertIn("起一次 grok 会话", self.toast(False, "token_expired"))
        self.assertIn("重新登录", self.toast(False, "unauthorized"))
        self.assertIn("限流", self.toast(False, "rate_limited"))
        self.assertIn("没读到", self.toast(False, None))


if __name__ == "__main__":
    unittest.main()
