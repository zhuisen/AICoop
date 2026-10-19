"""卡片操作栏看得清（真实渲染，两套主题）。

## 历史（为什么这个文件名还叫 action_bar）

2026-09-23 用户要「macOS 风格的半透明弹出动作条」，这里原来量的是**半透明 + 背景模糊**的浮层
压在卡片上之后的像素对比度（模糊让色值算法失效，所以必须量像素；量出来深色 4.08 / 浅色 4.93）。

2026-10-19 总览照交接包 page5 重做：**动作条浮层整个删除**，换成「悬停时底栏原位换成操作」
（`ov/OvCard` 的 `.ov-fact`）。新底栏是**不透明**的（卡片悬停底色 `--ovCardH`），所以那套像素量法
失去了存在理由 —— 不透明底上 computed 颜色直接算对比度就是对的。`-webkit-backdrop-filter` 那条
也随之作废（没有模糊了）。守的仍是同一件事：**操作里的每一个字在两套主题下都看得清**。

## 判据

- 普通按钮文字、琥珀「探针」、红色删除类：对悬停底色 ≥ 4.5（文字）。
- 主按钮（「切换」，实心 accent）：反白文字对 accent ≥ 4.5。
- 先正面证明主题真的切了、按钮真的看得见（零渲染会让所有对比度断言空转）。
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
BASE = "http://127.0.0.1:3304/harness.html?nav=home&notrans=1&ovhover=1"


def _rgb(s):
    m = re.match(r"rgba?\(([^)]*)\)", s or "")
    if not m:
        return None
    v = [float(x) for x in m.group(1).split(",")]
    return v[:3], (v[3] if len(v) == 4 else 1.0)


def _lum(c):
    f = lambda v: (v / 255) / 12.92 if v / 255 <= .03928 else (((v / 255) + .055) / 1.055) ** 2.4
    return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2])


def _cr(a, b):
    x, y = sorted([_lum(a), _lum(b)], reverse=True)
    return (x + .05) / (y + .05)


def _measure():
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        return None
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        for theme in ("dark", "light"):
            pg = br.new_page(viewport={"width": 1300, "height": 900})
            pg.goto(BASE + ("&theme=light" if theme == "light" else ""), timeout=30000)
            pg.wait_for_timeout(2600)
            out[theme] = pg.evaluate("""() => {
              const card = document.querySelector('.ov-card.ov-hov');
              if (!card) return null;
              const fact = card.querySelector('[data-ov-actions]');
              const bg = getComputedStyle(card).backgroundColor;
              const btns = [...fact.querySelectorAll('.ov-ab')].map(b => {
                const cs = getComputedStyle(b);
                return { t: b.textContent.trim(), cls: b.className, color: cs.color, bg: cs.backgroundColor,
                         op: +getComputedStyle(fact).opacity, w: b.getBoundingClientRect().width };
              });
              return { bg, btns, pageBg: getComputedStyle(document.querySelector('.ov-root')).color };
            }""")
            pg.close()
        br.close()
    return out


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheHoverFooterStaysReadable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _measure()
        if cls.r is None:
            raise unittest.SkipTest("没有 playwright 或 harness 3304 没起 —— skip 不是绿")

    def test_it_measured_something(self):
        for theme in ("dark", "light"):
            with self.subTest(theme=theme):
                d = self.r[theme]
                self.assertIsNotNone(d, "★★ 没有悬停态的卡（ovhover 没生效）")
                self.assertGreaterEqual(len(d["btns"]), 3, "★★ 底栏操作没渲染出来：%s" % d)
                self.assertTrue(all(b["op"] > .9 and b["w"] > 0 for b in d["btns"]), "★★ 操作看不见")

    def test_the_theme_really_switched(self):
        dark, light = _rgb(self.r["dark"]["bg"])[0], _rgb(self.r["light"]["bg"])[0]
        self.assertLess(_lum(dark), .1, "深色主题的卡片底不是深色")
        self.assertGreater(_lum(light), .7, "★★ 浅色主题没切过去 —— 下面量的浅色是假的")

    def test_the_footer_is_opaque(self):
        """★ 新底栏不透明 —— 这是下面「直接拿 computed 颜色算」成立的前提，所以单独守。"""
        for theme in ("dark", "light"):
            self.assertEqual(_rgb(self.r[theme]["bg"])[1], 1.0, "★★ %s 卡片底是半透明的，色值算法不再成立" % theme)

    def test_every_label_clears_4_5(self):
        for theme in ("dark", "light"):
            bg = _rgb(self.r[theme]["bg"])[0]
            for b in self.r[theme]["btns"]:
                if not b["t"]:
                    continue                      # 纯图标（⋯）
                with self.subTest(theme=theme, btn=b["t"]):
                    fg, a = _rgb(b["color"])
                    own, oa = _rgb(b["bg"])
                    under = own if oa >= .99 else bg
                    self.assertGreaterEqual(_cr(fg, under), 4.5, "★★ %s 下「%s」对比度不足" % (theme, b["t"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
