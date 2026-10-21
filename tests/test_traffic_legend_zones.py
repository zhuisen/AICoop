"""Token 消耗页「平台行」的不变量闸 —— 坏了也不报错的三件事。

## 由来

2026-08-26 用户选的「主次双区图例」（前 3 名完整行 + 其余紧凑格）。2026-10-22 AICoop R2（阶段 4）
换成稿里的**两列平台行**（左列 `slice(0, perCol)`、右列 `slice(perCol)`，`tokenView.ts::twoCol`）。
形状换了，守的三件事没变：

  ① **没有平台会从两列之间掉出去**：两次 `slice` 用同一个下标。写成 `slice(0,3)` + `slice(4)`
     会静默吞掉一家 —— 页面照常、总量照常，只是那家**不见了**。
  ② **两列共用同一个分母**（本期全部平台合计）。各算各的，右列的 % 看着正常却和左列不可比。
  ③ **两列每一行的交互一样**：都走同一个 `row()`（点进详情 + 悬停点亮图层）。
"""
import re
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src" / "pages" / "TrafficPage.tsx"
HARNESS = "http://127.0.0.1:3304/harness.html"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def strip_comments(src: str) -> str:
    src = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


class TwoColumnsNeverLoseAPlatform(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = strip_comments(SRC.read_text(encoding="utf-8"))

    def test_both_columns_split_at_the_same_index(self):
        m = re.search(r"const left = list\.slice\(0, (\w+(?:\.\w+)?)\), right = list\.slice\((\w+(?:\.\w+)?)\);", self.code)
        self.assertTrue(m, "探针失准：没找到两列的切分")
        self.assertEqual(m.group(1), m.group(2), "★★ 两列切在不同下标 —— 中间那家会消失")

    def test_both_columns_share_one_denominator(self):
        self.assertRegex(self.code, r"const grand = Math\.max\(1, rows\.reduce\(\(s, r\) => s \+ r\.total, 0\)\);")
        self.assertEqual(len(re.findall(r"\(r\.total / grand\)", self.code)), 1, "★ 占比不是同一个分母算的")

    def test_both_columns_use_the_same_row(self):
        self.assertIn("{left.map((r, i) => row(r, i === 0))}", self.code)
        self.assertIn("{right.map((r, i) => row(r, i === 0))}", self.code)
        row = self.code[self.code.index("const row = (r: PlatRow"):self.code.index("return (\n    <div data-token-page")]
        for need in ("onClick={() => onDrill(r.key)}", "onMouseEnter={() => setHoverKey(r.key)}",
                     "onMouseLeave={() => setHoverKey(null)}"):
            self.assertIn(need, row)


def _harness_up():
    try:
        urllib.request.urlopen(HARNESS, timeout=2)
        return True
    except Exception:
        return False


@unittest.skipUnless(_harness_up(), "harness 没在跑 —— skip 不是绿")
class EveryPlatformHasARow(unittest.TestCase):
    def test_rows_equal_platforms_and_shares_sum_to_100(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
            pg = br.new_page(viewport={"width": 1000, "height": 800})
            pg.goto(f"{HARNESS}?nav=traffic")
            pg.wait_for_selector("[data-plat-row]", timeout=15000)
            r = pg.evaluate("""() => ({
              chips: [...document.querySelectorAll('[data-chip]')].map(e => e.getAttribute('data-chip')).filter(k => k !== 'all'),
              rows: [...document.querySelectorAll('[data-plat-row]')].map(e => e.getAttribute('data-plat-row')),
              pct: [...document.querySelectorAll('[data-plat-row]')].map(e => parseFloat(e.children[e.children.length - 3].textContent)),
            })""")
            pg.close()
            br.close()
        self.assertGreaterEqual(len(r["rows"]), 3, "夹具平台太少 —— 证不到两列")
        self.assertEqual(sorted(r["rows"]), sorted(r["chips"]), "★★ 有平台没有行")
        self.assertAlmostEqual(sum(r["pct"]), 100.0, delta=0.6, msg="★ 占比加起来不是 100 —— 分母不一致")


if __name__ == "__main__":
    unittest.main()
