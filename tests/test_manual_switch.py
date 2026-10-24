"""手动换号不被「在用」锁住（用户 2026-10-24「无法手动换号」）。

现场：只剩两个活号，一个标「直连」，一个标「在用」，两张卡都不给「切换」⇒ 没有号能切。
「在用」= 代理最后挑过它（`last_aid`，几小时前的也算）；「切换」改的是 auth.json（直连号）—— 两件事无关。
修法：只有直连号（切到自己 = 空操作）不给按钮；代理在用的号照样能切。总览卡与菜单栏行同一条。
真 bundle（harness 夹具：号C 在用、号A 直连）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness.html?nav=home&anon=1&notrans=1&ovplat=codex"
PROBE = """() => [...document.querySelectorAll('[data-ov-card]')].map(c => ({
  name: (c.querySelector('[data-card-name]') || {}).textContent || '',
  inuse: !!c.querySelector('[data-ov-tag="inuse"]') || /在用/.test((c.querySelector('[data-card-name]')?.parentElement || {}).textContent || ''),
  direct: !!c.querySelector('[data-ov-ab="inuse"]'),
  sw: !!c.querySelector('[data-ov-ab="switch"]') }))"""


def _strip(src):
    return "\n".join(l for l in src.split("\n") if not l.lstrip().startswith(("//", "*", "/*", "{/*")))


class TheWiring(unittest.TestCase):
    def test_only_the_direct_account_has_no_switch(self):
        card = _strip((ROOT / "codexbar" / "src" / "components" / "AccountCard.tsx").read_text(encoding="utf-8"))
        self.assertIn('{state === "dead" ? null : isDirect ? (', card, "★ 只有直连号不给切换")
        self.assertNotIn('state === "inuse" ? (\n        <Ab current', card, "★ 「在用」又占掉了切换按钮")
        mb = _strip((ROOT / "codexbar" / "src" / "MenuBar.tsx").read_text(encoding="utf-8"))
        self.assertIn("onSwitch={a.aid === currentNode ? undefined", mb)
        self.assertNotIn("a.aid === currentNode || a.aid === inUseNode ? undefined", mb, "★ 菜单栏行又把在用的号锁住了")


class OnTheRealBundle(unittest.TestCase):
    def test_the_in_use_card_can_be_switched_to(self):
        try:
            from playwright.sync_api import sync_playwright
            urllib.request.urlopen(BASE, timeout=2).read(1)
        except Exception:
            self.skipTest("harness / playwright 不在")
        with sync_playwright() as p:
            br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
            try:
                pg = br.new_page(viewport={"width": 1200, "height": 900})
                pg.goto(BASE)
                pg.wait_for_selector("[data-ov-card]", timeout=15000)
                pg.wait_for_timeout(500)
                cards = pg.evaluate(PROBE)
            finally:
                br.close()
        inuse = [c for c in cards if c["inuse"] and not c["direct"]]
        direct = [c for c in cards if c["direct"]]
        self.assertTrue(inuse, "已知阳性：夹具里要有一张「在用」但不是直连的卡 %s" % cards)
        self.assertTrue(direct, "已知阳性：夹具里要有一张直连卡")
        for c in inuse:
            self.assertTrue(c["sw"], "★★ 代理在用的号没有「切换」—— 只剩直连 + 在用时就没有号能切：%s" % c["name"])
        for c in direct:
            self.assertFalse(c["sw"], "直连号切到自己是空操作：%s" % c["name"])


if __name__ == "__main__":
    unittest.main()
