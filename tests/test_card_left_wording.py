"""「还剩几天」只有一种说法（用户 2026-10-03）：角标写「剩 2 天」，点进弹窗却是「还剩 1 天」。

根因是**同一个量在三处各算各的**：
  · `CardBadge`   `Math.ceil(days)`（向上取整，注释写的理由是「10 小时不能标成 0 天」）
  · `MenuBar`     `Math.ceil`（菜单栏横幅同款）
  · `UseCreditDialog` `Math.floor`（向下取整）
于是剩 1.3 天的卡，角标说 2 天、弹窗说 1 天。用户的口径：**剩一天才是对的**（向下取整，不够一天说小时）。
现在只有一个实现 `helpers.ts::cardLeftText`，三处都调它；闸分两层：纯函数在边界输入上的行为（node 直接跑真文件），
以及三处是否真的都走它（防止下一个人又在某处手写一遍取整）。
"""
try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"


def run_node(days):
    script = ("import('%s').then(m => console.log(JSON.stringify(%s.map(d => m.cardLeftText(d)))))"
              % ((SRC / "helpers.ts").as_posix(), json.dumps(days)))
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def code(p):
    s = (SRC / p).read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//[^\n]*", "", s)


class TheWordingIsFloorNotCeil(unittest.TestCase):
    def test_boundaries(self):
        d = [0.2, 0.99, 1.0, 1.3, 1.99, 2.0, 2.9, 26.4]
        self.assertEqual(run_node(d), ["4小时", "23小时", "1天", "1天", "1天", "2天", "2天", "26天"],
                         "★★ 剩 1.3 / 1.99 天必须说「1天」（向下取整），不能说 2 天；不够一天说小时")

    def test_it_never_says_zero(self):
        self.assertEqual(run_node([0.001, 0.03]), ["1小时", "1小时"], "★ 最后几十分钟也不能写成 0 小时 / 0 天")


class EverySiteUsesTheOneImplementation(unittest.TestCase):
    # 2026-10-19：卡上的「重置卡 ×N · 剩 X」从 CardBadge 组件搬进 AccountCard 的页脚（交接包 page5）。
    # P5（2026-10-21）：卡上的 chip 与「用一张重置卡？」弹层合进同一个组件 `ov/CreditChip.tsx`（旧弹窗删除）。
    SITES = ["components/ov/CreditChip.tsx", "MenuBar.tsx"]

    def test_each_site_calls_it(self):
        for p in self.SITES:
            self.assertIn("cardLeftText(", code(p), f"★★ {p} 没走 cardLeftText —— 又会各算各的")

    def test_nobody_rounds_card_days_by_hand(self):
        for p in self.SITES:
            c = code(p)
            self.assertNotRegex(c, r"Math\.(ceil|floor|round)\([^)]*(cardDays|\.days|\bd\b)", f"★★ {p} 里手写了「还剩几天」的取整")

    def test_the_helper_is_defined_once(self):
        h = code("helpers.ts")
        self.assertEqual(len(re.findall(r"export function cardLeftText", h)), 1)


# `ovoff=1`：harness 把那张快到期的卡补在**末尾**的活号上，而末尾三个号被夹具设成了停用 ——
#   2026-10-19 起停用号收进折叠条，不展开就点不到。
BASE = "http://127.0.0.1:3304/harness.html?nav=home&ovoff=1"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _render_pairs():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    import urllib.request
    try:
        urllib.request.urlopen(BASE, timeout=2).read(1)
    except Exception:
        return None
    pairs = []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = br.new_page(viewport={"width": 1300, "height": 900})
        pg.goto(BASE, timeout=30000); pg.wait_for_timeout(3000)
        # P5（2026-10-21）：chip 本身就是入口（悬停也不让位），点开卡内弹层；弹层每行把 `cardLeftText` 写在 `data-left`。
        n = pg.locator("[data-card-badge]").count()
        for i in range(n):
            b = pg.locator("[data-card-badge]").nth(i)
            # P5 稿：`重置卡 ×1 · 剩 1天`
            m = re.search(r"·\s*剩\s*(\d+)\s*(天|小时)", b.inner_text())
            if not m:
                continue                       # 没到「快到期」档的 chip 不带「· 剩 N 天」
            b.click(); pg.wait_for_timeout(250)
            row = pg.locator("[data-use-credit-dialog][data-open] [data-use-credit-row]").first
            pairs.append((m.group(1) + m.group(2), row.get_attribute("data-left") if row.count() else None))
            pg.keyboard.press("Escape"); pg.wait_for_timeout(150)
        br.close()
    return pairs


class BadgeAndDialogAgree(unittest.TestCase):
    def test_same_card_same_wording(self):
        pairs = _render_pairs()
        if pairs is None:
            self.skipTest("没有 playwright 或 harness 静态服务（3304）没在跑")
        self.assertTrue(pairs, "★★ 没有一张带「剩 N 天」的角标 —— 夹具里应有快到期的卡，闸此刻没有判别力")
        for badge, dialog in pairs:
            self.assertEqual(badge, dialog, f"★★★ chip 写「剩{badge}」，弹层最先过期那张却是「还剩 {dialog}」—— 口径又分叉了")


if __name__ == "__main__":
    unittest.main(verbosity=2)
