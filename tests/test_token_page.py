"""Token 消耗页（AICoop R2，阶段 4）的闸。

1. **纯逻辑**（`codexbar/src/tokenView.ts`，零 import，`node --experimental-strip-types` 跑真文件）：
   三档数字写法照稿示意数据、稿件缺陷的修正（F1 持平不写成下跌、F2 亚美元不抹位、S5 回本线现算）、
   分段宽、两列行高、横轴末尾锚定、临界阻尼端点。
2. **渲染**（harness `127.0.0.1:3304`，没在跑就 skip —— skip 不是绿）：7 格指标、胶囊选中只算该平台、
   两列平台行、卡片、消耗页的缓存四格与模型表列数随宽度变、860 不横向溢出。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import os
import shutil
import subprocess
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PURE = ROOT / "codexbar" / "src" / "tokenView.ts"
HARNESS = "http://127.0.0.1:3304"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _node(expr):
    script = ("import('file://%s').then(m => { let v; try { v = (%s); } catch (e) { v = {__throw: String(e)}; }"
              " console.log(JSON.stringify(v === undefined ? null : v)); });" % (PURE.as_posix(), expr))
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip()]
    if not out:
        raise AssertionError(f"node 没有产出：{r.stderr[-600:]}")
    return json.loads(out[-1])


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class Formatting(unittest.TestCase):
    def test_the_three_densities_match_the_board_samples(self):
        """稿 §3：1200 完整 16.34B · $7.30K · 56,073；1000 一位小数 16.3B · $7.3K · $243；860 再加 k（56.1k）。"""
        got = _node("[0,1,2].map(L => [m.fmtTokL(16.34e9,L), m.fmtUsdL(7300,L), m.fmtUsdL(243.32,L), m.fmtIntL(56073,L), m.fmtTokL(545e6,L), m.fmtTokL(9.6e6,L), m.fmtTokL(4200,L)])")
        self.assertEqual(got[0], ["16.34B", "$7.30K", "$243.32", "56,073", "545M", "9.6M", "4k"])
        self.assertEqual(got[1], ["16.3B", "$7.3K", "$243", "56,073", "545M", "9.6M", "4k"])
        self.assertEqual(got[2], ["16.3B", "$7.3K", "$243", "56.1k", "545M", "9.6M", "4k"])

    def test_sub_dollar_values_keep_two_decimals_at_860(self):
        """稿件缺陷 F2：稿里 860 把 $0.11 写成 $0.1、$0.046 写成 $0.0 —— 那是改数。"""
        self.assertEqual(_node("[m.fmtUsdL(0.11,2), m.fmtUsdL(0.046,2), m.fmtUsdL(42.0,2)]"), ["$0.11", "$0.05", "$42.0"])

    def test_flat_is_not_written_as_a_fall(self):
        """稿件缺陷 F1：`sgn(0)` 稿里输出 ↓0.0%。"""
        self.assertEqual(_node("[m.sgn(0), m.sgn(0.04), m.sgn(-20.5), m.sgn(31.2), m.sgn(null)]"),
                         ["0.0%", "0.0%", "↓20.5%", "↑31.2%", "—"])
        self.assertEqual(_node("[m.trendOf(0), m.trendOf(-1), m.trendOf(2), m.trendOf(null)]"), ["flat", "down", "up", "none"])
        self.assertIsNone(_node("m.changePct(10, 0)"), "上期为 0 ⇒ 没法比，不当 ↑∞")

    def test_segment_widths_match_the_board(self):
        got = _node("[0,2].map(L => ['今日','7d','30d','年度', L===2?'范围':'范围 ▾'].map(x => m.segWidth(x,L)))")
        self.assertEqual(got, [[52, 42, 49, 52, 68], [44, 34, 41, 44, 44]])

    def test_two_column_row_heights(self):
        """行高固定 36、区块高 = 36 × 每列家数（用户 2026-10-22「中间版块可以压缩」，取代稿 §5 撑满 168）。"""
        got = _node("[3,4,6,8,12].map(n => m.twoCol(n))")
        self.assertEqual([(g["rowH"], g["h"]) for g in got], [(36, 72), (36, 72), (36, 108), (36, 144), (36, 216)])

    def test_axis_labels_are_anchored_from_the_end(self):
        """全局 ui-design：抽稀从末尾锚定，最后一个点（今天）恒有标签；间距 ≥ 64 px。"""
        idx = _node("m.axisIdx(30, 1042)")
        self.assertEqual(idx[-1], 29)
        step = 1042 / 29
        self.assertTrue(all((b - a) * step >= 64 for a, b in zip(idx, idx[1:])), idx)
        self.assertEqual(_node("m.axisIdx(1, 500)"), [0])

    def test_critical_damping_ends_exactly_and_never_overshoots(self):
        vs = _node("Array.from({length: 21}, (_, i) => m.critEase(i/20))")
        self.assertEqual((vs[0], vs[-1]), (0, 1))
        self.assertTrue(all(b >= a for a, b in zip(vs, vs[1:])), "临界阻尼不回弹 ⇒ 单调")
        self.assertTrue(all(v <= 1 for v in vs))

    def test_resample_keeps_endpoints(self):
        self.assertEqual(_node("m.resample([0,10],5)"), [0, 2.5, 5, 7.5, 10])
        self.assertEqual(_node("m.resample([],3)"), [0, 0, 0])

    def test_hit_rate_counts_cache_write_as_input(self):
        """偏离 R2-8：缓存写是首次发送的输入，算进分母；没有输入 ⇒ null。"""
        self.assertAlmostEqual(_node("m.hitRate(90, 5, 5)"), 90.0)
        self.assertIsNone(_node("m.hitRate(0, 0, 0)"))

    def test_breakeven_is_computed_from_prices_not_hardcoded(self):
        """稿件缺陷 S5：稿写死「回本 1.4×」；Claude 5m 档按牌价只要 ≈ 0.28 次。自动缓存平台 ⇒ null。"""
        self.assertAlmostEqual(_node("m.breakevenReads(5, 0.5, 6.25)"), 0.2778, places=3)
        self.assertIsNone(_node("m.breakevenReads(4, 0.4, undefined)"))

    def test_stack_and_band_edges(self):
        self.assertEqual(_node("m.stackTops([[1,2],[3,4],[0,1]])"), [[1, 2], [4, 6], [4, 7]])
        self.assertEqual(_node("m.bandPath([], [], 10)"), "", "空数组不许出非法 path")
        one = _node("m.bandPath([[50,10]], [[50,40]], 10)")
        self.assertTrue(one.startswith("M45.0 40.0") and one.endswith("Z"), one)

    def test_layer_hit_uses_the_real_x_and_skips_empty_layers(self):
        """评审反例：两层 [100,0] / [0,100]，横向 25%、纵值 80 落在第二层；选中单平台时 0 厚度层不可点。"""
        tops = "m.stackTops([[100,0],[0,100]])"
        self.assertEqual(_node(f"m.layerAt({tops}, 0.25, 80)"), 1)
        self.assertEqual(_node(f"m.layerAt({tops}, 0.25, 50)"), 0)
        self.assertEqual(_node("m.layerAt(m.stackTops([[0,0],[5,5]]), 0.5, 0.1)"), 1, "零厚度的第一层被点中了")
        self.assertEqual(_node(f"[m.layerAt({tops}, 0.5, 0), m.layerAt({tops}, 0.5, 101)]"), [-1, -1])

    def test_mini_runs_break_at_missing_buckets(self):
        self.assertEqual(_node("m.nonNullRuns([90,null,70,71])"), [[[0, 90]], [[2, 70], [3, 71]]])
        self.assertEqual(_node("m.nonNullRuns([null,null])"), [])

    def test_point_delta_flat_has_no_direction(self):
        self.assertEqual(_node("[m.fmtPt(-0.02), m.fmtPt(0), m.fmtPt(1.24), m.fmtPt(-3), m.fmtPt(null)]"),
                         [{"text": "0.0 pt", "trend": "flat"}, {"text": "0.0 pt", "trend": "flat"},
                          {"text": "+1.2 pt", "trend": "up"}, {"text": "-3.0 pt", "trend": "down"},
                          {"text": "", "trend": "none"}])

    def test_breakeven_counts_the_1h_write_tier(self):
        """评审：opus-4-6 全是 1h 写时回本 1.11×，只按 5m 价算成 0.28×。"""
        self.assertAlmostEqual(_node("m.breakevenReads(5, 0.5, m.blendWritePrice(5, 6.25, 1))"), 1.1111, places=3)
        self.assertAlmostEqual(_node("m.breakevenReads(5, 0.5, m.blendWritePrice(5, 6.25, 0))"), 0.2778, places=3)
        self.assertAlmostEqual(_node("m.blendWritePrice(5, 6.25, 0.5)"), 8.125)

    def test_low_hit_threshold(self):
        self.assertEqual(_node("[m.lowHit(90, 92), m.lowHit(90.6, 92), m.lowHit(null, 92), m.lowHit(80, null)]"),
                         [True, False, False, False])

    def test_title_size_and_names(self):
        self.assertEqual(_node("[1200,1000,860].map(m.titleSize)"), [26, 24, 22])
        self.assertEqual(_node("m.displayName('agy','Antigravity')"), {"name": "Gemini", "src": "agy"})
        self.assertEqual(_node("m.displayName('agy','我的谷歌')")["name"], "我的谷歌", "用户改过名 ⇒ 用户的优先")
        self.assertEqual(_node("[m.shortDate('2026-10-01','2026'), m.shortDate('2025-11','2026')]"), ["10-01", "2025-11"])


def _num(s):
    """`2.1B` / `545M` / `4k` → 数。"""
    m = {"B": 1e9, "M": 1e6, "k": 1e3, "K": 1e3}
    s = (s or "").strip()
    return float(s[:-1]) * m[s[-1]] if s and s[-1] in m else float(s or "nan")


def _harness_up():
    try:
        urllib.request.urlopen(HARNESS + "/harness.html", timeout=2)
        return True
    except Exception:
        return False


PROBE = """() => {
  const q = (s) => [...document.querySelectorAll(s)];
  const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const root = document.querySelector('[data-token-page],[data-token-detail]');
  return {
    title: (document.querySelector('h1') || {}).textContent || null,
    kpis: q('[data-kpi]').map((e) => e.getAttribute('data-kpi')),
    chips: q('[data-chip]').map((e) => [e.getAttribute('data-chip'), e.getAttribute('aria-pressed')]),
    unit: (document.querySelector('[data-unit]') || {}).textContent || null,
    rows: q('[data-plat-row]').length, cards: q('[data-plat-card]').length,
    cache: q('[data-cache-cell]').length,
    head: (() => { const t = document.querySelector('[data-platform-table]'); return t ? t.firstElementChild.children.length : null; })(),
    overflow: root ? root.scrollWidth > root.clientWidth + 1 : null,
    kpiOverflow: q('[data-kpi-value],[data-kpi-sub]').filter((e) => e.scrollWidth > e.clientWidth + 1).length,
    kv: Object.fromEntries(q('[data-kpi]').map((e) => [e.getAttribute('data-kpi'), (e.querySelector('[data-kpi-value]') || {}).textContent])),
    layers: q('[data-tk-chart] path[data-layer]').map((e) => e.getAttribute('data-layer')),
    hitHead: !!q('[data-platform-table] > div:first-child > span').find((e) => e.textContent === '缓存命中'),
    headOverflow: (() => { const h = document.querySelector('[data-token-detail] > div, [data-token-page] > div');
                           return h ? h.scrollWidth > h.clientWidth + 1 : null; })(),
    chart: !!document.querySelector('[data-tk-chart]'),
    ytop: (document.querySelector('[data-ytick="3"]') || {}).textContent || null,
  };
}"""


@unittest.skipUnless(_harness_up(), "harness 没在跑（127.0.0.1:3304）—— skip 不是绿")
class Rendered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def open(self, nav, w=1200, h=800, extra=""):
        pg = self.br.new_page(viewport={"width": w, "height": h})
        pg.goto(f"{HARNESS}/harness.html?nav={nav}{extra}")
        pg.wait_for_selector("[data-tk-chart]", timeout=15000)
        pg.wait_for_timeout(700)
        return pg

    def test_overview_has_seven_kpis_rows_and_cards(self):
        pg = self.open("traffic")
        r = pg.evaluate(PROBE)
        pg.close()
        self.assertEqual(r["title"], "消耗", "用户 2026-10-22：标题改「消耗」，平台胶囊并进标题行")
        self.assertEqual(r["kpis"], ["总 Token", "请求数", "日均", "等效费用", "日均费用", "最大占比", "缓存命中"])
        self.assertEqual(r["chips"][0], ["all", "true"], "「全部」固定第一且默认选中")
        self.assertGreaterEqual(r["rows"], 2)
        self.assertEqual(r["rows"], len(r["chips"]) - 1, "两列行与胶囊一平台一个")
        self.assertEqual(r["cards"], r["rows"])
        self.assertEqual(r["unit"], "token")
        self.assertFalse(r["overflow"])

    def test_picking_a_chip_scopes_kpis_and_chart(self):
        """★ 评审：只看标签不够 —— 断言打在**数**上：选中后首格 = 该平台行的 Token，图上只剩它一层有量，再点「全部」恢复。"""
        pg = self.open("traffic")
        before = pg.evaluate(PROBE)
        keys = [c[0] for c in before["chips"] if c[0] != "all"]
        rows = pg.evaluate("() => Object.fromEntries([...document.querySelectorAll('[data-plat-row]')].map(e =>"
                           " [e.getAttribute('data-plat-row'), e.children[e.children.length - 4].textContent]))")
        key = next(k for k in keys if rows.get(k) and rows[k] != before["kv"]["总 Token"])
        pg.dispatch_event(f"[data-chip='{key}']", "mousedown", {"button": 0})
        pg.wait_for_timeout(900)
        r = pg.evaluate(PROBE)
        # 图层只剩它：悬停浮层逐行只列选中的那一家（零厚度带的 bbox 仍跨整条曲线，不能拿高度判）。
        box = pg.evaluate("() => { const r = document.querySelector('[data-tk-chart] > div:not([data-tk-tip])').getBoundingClientRect();"
                          " return [r.left + r.width * 0.9, r.top + r.height * 0.5]; }")
        pg.mouse.move(*box)
        pg.wait_for_timeout(300)
        tip = pg.evaluate("() => [...document.querySelector('[data-tk-tip]').children].length")
        pg.dispatch_event("[data-chip='all']", "mousedown", {"button": 0})
        pg.wait_for_timeout(900)
        back = pg.evaluate(PROBE)
        pg.close()
        self.assertIn([key, "true"], r["chips"])
        self.assertEqual(r["kpis"][0], "Token", "选中单平台 ⇒ 首格「Token」")
        self.assertEqual(r["kpis"][5], "占全部")
        self.assertTrue(r["unit"].startswith("token · "), r["unit"])
        self.assertEqual(r["kv"]["Token"], rows[key], "★★ 首格不是选中平台的数 —— KPI 没跟着筛")
        self.assertNotEqual(r["kv"]["Token"], before["kv"]["总 Token"])
        self.assertEqual(tip, 3, f"★ 浮层不是「标题 + 选中那一家 + 合计」三行（{tip}）—— 图没跟着筛")
        self.assertLess(_num(r["ytop"]), _num(before["ytop"]), "★ 纵轴没缩到选中那一家的量级 —— 其余图层还在画")
        self.assertEqual(back["kv"]["总 Token"], before["kv"]["总 Token"], "点回「全部」没恢复")

    def test_860_uses_short_labels_and_does_not_overflow(self):
        pg = self.open("traffic", 860, 600)
        r = pg.evaluate(PROBE)
        pg.close()
        self.assertEqual(r["kpis"], ["Token", "请求", "日均", "费用", "日均费", "最大", "缓存"])
        self.assertFalse(r["overflow"], "860 横向溢出")
        self.assertEqual(r["kpiOverflow"], 0, "860 指标数字被截断")

    def test_detail_drops_the_cache_column_when_cache_reads_are_excluded(self):
        """评审：口径不计缓存读时，KPI / 四格已删，模型表那一列也得一起删（「不同口径 = 不同页面」）。"""
        for mode, cache, hit in (("full", 4, True), ("noRead", 0, False), ("none", 0, False)):
            with self.subTest(mode=mode):
                pg = self.open("platform:claude", 860, 700, f"&mode={mode}")
                r = pg.evaluate(PROBE)
                pg.close()
                self.assertEqual(r["cache"], cache)
                self.assertEqual(r["hitHead"], hit)
                self.assertEqual(r["head"], 8 if hit else 7)
                self.assertFalse(r["headOverflow"], "860 + 口径牌时顶栏溢出")

    def test_model_row_isolates_only_in_models_mode(self):
        pg = self.open("platform:claude")
        n0 = len(pg.evaluate(PROBE)["layers"])
        first = pg.evaluate("() => document.querySelector('[data-model-row]').getAttribute('data-model-row')")
        pg.click(f"[data-model-row='{first}']")
        pg.wait_for_timeout(700)
        n1 = pg.evaluate(PROBE)["layers"]
        pg.click(f"[data-model-row='{first}']")
        pg.wait_for_timeout(300)
        pg.click("text=总量")
        pg.wait_for_timeout(700)
        t0 = pg.evaluate(PROBE)["layers"]
        pg.click(f"[data-model-row='{first}']")
        pg.wait_for_timeout(500)
        t1 = pg.evaluate(PROBE)["layers"]
        op = pg.evaluate(f"() => getComputedStyle(document.querySelector(\"[data-model-row='{first}']\")).opacity")
        pg.close()
        self.assertGreaterEqual(n0, 2, "夹具只有一个模型 —— 证不到隔离")
        self.assertEqual(len(n1), n0 - 1)
        self.assertNotIn(first, n1)
        self.assertEqual(t0, t1, "总量档点模型行改了图")
        self.assertEqual(op, "1", "★ 总量档点了模型行变暗，而图没变")

    def test_model_table_never_clips_its_last_column(self):
        """接 `test_narrow_window_nowrap` 删掉的那条：窄窗下最右一列（缓存命中 / 费用每百万）不许被悄悄裁掉。"""
        for w in (1200, 1000, 860):
            with self.subTest(w=w):
                pg = self.open("platform:claude", w, 800)
                r = pg.evaluate("""() => [...document.querySelectorAll('[data-platform-table] > div')].map(row => {
                    const box = row.getBoundingClientRect(), last = row.lastElementChild.getBoundingClientRect();
                    return [last.right <= box.right + 0.5, row.lastElementChild.scrollWidth <= row.lastElementChild.clientWidth + 1];
                  })""")
                pg.close()
                self.assertGreaterEqual(len(r), 2)
                self.assertTrue(all(a and b for a, b in r), f"★ {w} 宽最右一列被裁：{r}")

    def test_detail_has_cache_grid_and_width_dependent_columns(self):
        for w, cols in ((1200, 11), (1000, 9), (860, 8)):
            with self.subTest(w=w):
                pg = self.open("platform:codex", w, 800)
                r = pg.evaluate(PROBE)
                pg.close()
                self.assertTrue(r["title"].endswith("消耗"))
                self.assertEqual(r["cache"], 4)
                self.assertEqual(r["head"], cols)
                self.assertNotIn("all", [c[0] for c in r["chips"]], "消耗页的胶囊没有「全部」")
                self.assertIn(["codex", "true"], r["chips"])
                self.assertFalse(r["overflow"])

    def test_cache_grid_is_folded_by_default_and_toggles(self):
        """用户 2026-10-23：具体 AI 消耗页的「缓存命中」做成折叠 / 展开，默认折叠。"""
        pg = self.open("platform:claude", 1200, 800)
        vis = """() => { const b = document.querySelector('[data-cache-body]'); const t = document.querySelector('[data-act="cache-toggle"]');
          if (!b || !t) return null; const r = b.getBoundingClientRect();
          return {shown: getComputedStyle(b).display !== 'none' && r.height > 0, cells: b.querySelectorAll('[data-cache-cell]').length,
                  exp: t.getAttribute('aria-expanded'), label: t.textContent,
                  sum: (document.querySelector('[data-cache-summary]') || {}).textContent || null}; }"""
        a = pg.evaluate(vis)
        pg.evaluate("() => document.querySelector('[data-act=\"cache-toggle\"]').click()")
        pg.wait_for_timeout(150)
        b = pg.evaluate(vis)
        pg.evaluate("() => document.querySelector('[data-act=\"cache-toggle\"]').click()")
        pg.wait_for_timeout(150)
        c = pg.evaluate(vis)
        pg.close()
        self.assertIsNotNone(a, "★ 缓存命中块没渲染出来 —— 下面的断言会空转")
        self.assertEqual(a["cells"], 4, "已知阳性：折叠时四格仍在 DOM 里")
        self.assertEqual((a["shown"], a["exp"]), (False, "false"), "★ 默认要折叠")
        self.assertIn("展开", a["label"])
        self.assertRegex(a["sum"] or "", r"命中率 \d+\.\d%.*已省 \$\d+K?.*请求成本 \$\d+\.\d\d/次",
                         "★ 折叠时标题行要有汇总：命中率 · 已省（取整）· 请求成本 /次")
        self.assertNotRegex(a["sum"] or "", r"已省 \$\d+\.\d", "已省取整，不带小数")
        self.assertEqual((b["shown"], b["exp"]), (True, "true"), "★ 点标题行要展开")
        self.assertIn("收起", b["label"])
        self.assertIsNone(b["sum"], "展开后四格自己说，标题行不重复汇总")
        self.assertEqual((c["shown"], c["exp"]), (False, "false"), "再点一次收起")


if __name__ == "__main__":
    unittest.main()
