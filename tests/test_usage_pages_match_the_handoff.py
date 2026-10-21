"""「Token 消耗」与「X 消耗」是**同一族的两页**，骨架必须都在。

## 由来（2026-09-13，用户实报「ai 总览的内容和位置不是 1:1」）

1. **数据源披露**（「读本地 transcript · 不消耗额度」）。`不消耗额度` 是本仓反复强调的披露，
   "这页会不会花我的钱"正是第一次看到它时会问的。
2. **「请求数」两页都有、紧跟 Token**。后端有值 ≠ 已披露。

## 2026-10-22 改写（AICoop R2，阶段 4）

两页的 7 格现在由**同一个函数** `tkModel.ts::buildKpis` 出（原来两页各写一份 `const kpis`，漂过两次）。
判据随之改成：两页都调它、加载骨架 `skeletonKpis` 与它同一组标签、渲染出来请求数紧跟 Token。
披露从副标行挪进标题旁的 `data-src`（偏离 R2-13），断言打在它的 `title` 上。
"""
import re
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
PAGES = {"总览": SRC / "pages" / "TrafficPage.tsx", "详情": SRC / "pages" / "PlatformPage.tsx"}
MODEL = SRC / "components" / "tk" / "tkModel.ts"
HARNESS = "http://127.0.0.1:3304/harness.html"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def code(p):
    """剥掉 JSX 注释与行注释（形态⑫：闸撞上自己的说明文字）。"""
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//.*", "", s)


def fn_body(src, name):
    i = src.index(f"export function {name}(")
    j = src.find("\nexport function ", i + 10)
    return src[i:j if j > 0 else len(src)]


def labels_in(body):
    """`label:` 后面那个表达式里的全部字符串字面量（含三元两支）。"""
    out = set()
    for m in re.finditer(r"label:\s*([^,}]*(?:\?[^,}]*)?)", body):
        out |= set(re.findall(r'"([^"]+)"', m.group(1)))
    return out


class BothPagesShareOneKpiSource(unittest.TestCase):
    def test_both_pages_build_kpis_with_the_shared_function(self):
        for name, p in PAGES.items():
            with self.subTest(page=name):
                self.assertRegex(code(p), r"buildKpis\(\{", f"★ {name} 不走 buildKpis —— 两页又各写一份了")
                self.assertNotIn("const kpis: Kpi[]", code(p), "旧的页内 KPI 定义回来了")

    def test_the_loading_skeleton_carries_the_same_columns(self):
        src = code(MODEL)
        build = labels_in(fn_body(src, "buildKpis"))
        skel = set(re.findall(r'"([^"]+)"', fn_body(src, "skeletonKpis").split("labels.map")[0]))
        skel -= {"—", "读取中"}
        self.assertGreaterEqual(len(skel), 10, f"探针失准：骨架只解析出 {skel}")
        self.assertEqual(skel - build, set(), "★ 骨架里有加载后不存在的格子 —— 数据到达时会跳列")
        for need in ("请求数", "等效费用", "最大占比", "缓存命中"):
            self.assertIn(need, skel)

    def test_the_skeleton_values_are_dashes(self):
        body = fn_body(code(MODEL), "skeletonKpis")
        self.assertIn('value: "—"', body)
        self.assertNotRegex(body, r'value:\s*"(?!—)', "★ 骨架里有不是「—」的值 —— 空窗期在说假话")

    def test_each_page_discloses_the_source(self):
        for name, p in PAGES.items():
            with self.subTest(page=name):
                src = code(p)
                i = src.find("<span data-src title=")
                self.assertGreaterEqual(i, 0, f"★ {name} 没有数据源披露")
                self.assertIn("不消耗额度", src[i:src.index("style=", i)], "★ 披露没说「不消耗额度」")

    def test_the_rounds_field_is_actually_consumed(self):
        body = fn_body(code(MODEL), "buildKpis")
        self.assertRegex(body, r"fmtIntL\(rounds, L\)", "★ 请求数没被显示 —— 后端有值 ≠ 已披露")


def _harness_up():
    try:
        urllib.request.urlopen(HARNESS, timeout=2)
        return True
    except Exception:
        return False


@unittest.skipUnless(_harness_up(), "harness 没在跑 —— skip 不是绿")
class TheRequestCountSitsRightAfterTheToken(unittest.TestCase):
    def test_on_both_pages(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
            got = {}
            for nav in ("traffic", "platform:claude"):
                pg = br.new_page(viewport={"width": 1200, "height": 800})
                pg.goto(f"{HARNESS}?nav={nav}")
                pg.wait_for_selector("[data-kpi]", timeout=15000)
                got[nav] = pg.evaluate("() => [...document.querySelectorAll('[data-kpi]')].map(e => e.getAttribute('data-kpi'))")
                pg.close()
            br.close()
        self.assertEqual(got["traffic"][:2], ["总 Token", "请求数"])
        self.assertEqual(got["platform:claude"][:2], ["Token", "请求数"])
        self.assertEqual(got["traffic"][3], "等效费用")
        self.assertEqual(got["platform:claude"][3], "等效费用", "两页的费用格不在同一位置")


if __name__ == "__main__":
    unittest.main()
