"""「请求」页（交接包 2026-10-19 page3）的闸。

## 守什么

1. **纯逻辑行为**（`codexbar/src/requests.ts`，零 import，`node --experimental-strip-types` 跑真文件）：
   按天 / 平台筛选、右上三项指标、数字写法、**读不到写 `—` 不写 0**、首字 > 30 s 琥珀、打码。
2. **表头在滚动容器里面且 sticky**（交接包「容易遗漏」第 1 条，踩过的坑：表头在外面时一出滚动条，
   内容区变窄、列与表头错位）。判据是真 bundle 上量出来的几何：滚下去之后表头仍贴在滚动框顶，
   且 9 个表头格的中心与第一行 9 个格的中心逐个对齐。
3. **页面根不滚**（860×560 也一样）、行高 34、详情栏宽 300、表头 9 格全居中。
4. **读失败不清空**：第 1 次读到、之后 IPC 失败 ⇒ 红条出现、行数不变、文字降到 55%、logo 不变暗。

几何闸跑在 harness 上（`127.0.0.1:3304`，没在跑就 skip —— **skip 不是绿**）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import calendar
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PURE = ROOT / "codexbar" / "src" / "requests.ts"
APP_DIR = ROOT / "codexbar" / "uishot" / "app"
HARNESS = "http://127.0.0.1:3304"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _node(expr, tz="Asia/Singapore"):
    """在真的 `requests.ts` 上跑一段表达式，返回 JSON 解析后的结果。时区钉死，日界才可复现。"""
    script = (
        "import('file://%s').then(m => {"
        "  const R = (o) => Object.assign({key:'k', platform:'codex', t_start:null, t_end:0, model:null,"
        "    source:null, session:null, session_title:null, account:null, input:null, cached:null,"
        "    output:null, reasoning:null, ttft_ms:null, gen_ms:null, total_ms:null, tool_ms:null,"
        "    tps:null, est:false, session_req_n:null}, o);"
        "  let v; try { v = (%s); } catch (e) { v = {__throw: String(e && e.message || e)}; }"
        "  console.log(JSON.stringify(v === undefined ? null : v));"
        "});" % (PURE.as_posix(), expr)
    )
    env = dict(os.environ, TZ=tz)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT, env=env)
    out = [l for l in r.stdout.splitlines() if l.strip()]
    if not out:
        raise AssertionError(f"node 没有产出结果：\nstdout={r.stdout}\nstderr={r.stderr[-800:]}")
    return json.loads(out[-1])


# 2026-10-19 10:00 SGT = 02:00 UTC（现算，不手写 epoch —— 手写过一次，差了一整年）
T_1019_10 = calendar.timegm((2026, 10, 19, 2, 0, 0))
T_1018_23 = T_1019_10 - 11 * 3600   # 10-18 23:00 SGT


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class TheBoundaryRejectsWhatItCannotRead(unittest.TestCase):
    """边界校验：顶层坏 ⇒ 抛（交给 hook 当读失败、保留上次列表）；单行坏 ⇒ 只丢这一行。"""

    def test_a_non_object_throws(self):
        self.assertIn("__throw", _node("m.parsePayload('[1,2]')"))
        self.assertIn("__throw", _node("m.parsePayload('not json')"))

    def test_missing_requests_throws_instead_of_reading_as_empty(self):
        """★ 「没有 requests 字段」≠「今天没有请求」—— 当成空列表就是把读不到画成没有。"""
        got = _node("m.parsePayload({ok:true})")
        self.assertIn("__throw", got)

    def test_bad_rows_are_dropped_good_rows_kept(self):
        got = _node("m.parsePayload({requests:[{key:'a',platform:'codex',t_end:1},"
                    "{key:'b',platform:'kimi',t_end:1},{platform:'codex',t_end:1},{key:'c',platform:'grok'}]}).requests.map(r=>r.key)")
        self.assertEqual(got, ["a"])

    def test_a_missing_number_is_null_not_zero(self):
        got = _node("m.parsePayload({requests:[{key:'a',platform:'claude',t_end:1,ttft_ms:'x',tps:NaN}]}).requests[0]")
        self.assertIsNone(got["ttft_ms"])
        self.assertIsNone(got["tps"])
        self.assertIsNone(got["input"])

    def test_ok_false_is_carried_through(self):
        got = _node("m.parsePayload({ok:false,error:'占用',stale_since:5,requests:[]})")
        self.assertEqual((got["ok"], got["error"], got["stale_since"]), (False, "占用", 5))


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class DaysAndFilters(unittest.TestCase):
    def test_timestamps_in_seconds_or_ms_land_on_the_same_day(self):
        self.assertEqual(_node(f"[m.localDateKey(m.toMs({T_1019_10})), m.localDateKey(m.toMs({T_1019_10 * 1000}))]"),
                         ["2026-10-19", "2026-10-19"])

    def test_rows_split_by_local_day_and_sort_newest_first(self):
        rows = (f"[R({{key:'y',t_end:{T_1018_23}}}), R({{key:'a',t_end:{T_1019_10 - 60}}}),"
                f" R({{key:'b',t_end:{T_1019_10}}})]")
        self.assertEqual(_node(f"m.rowsForDay({rows}, '2026-10-19').map(r=>r.key)"), ["b", "a"])
        self.assertEqual(_node(f"m.rowsForDay({rows}, '2026-10-18').map(r=>r.key)"), ["y"])

    def test_the_backend_day_boundary_wins(self):
        got = _node("m.dayKeys({days:{today:{date:'2026-01-02'},yesterday:{date:'2026-01-01'}}}, 0)")
        self.assertEqual(got, {"today": "2026-01-02", "yest": "2026-01-01"})

    def test_without_backend_days_yesterday_is_the_previous_local_day(self):
        got = _node(f"m.dayKeys(null, {T_1019_10 * 1000})")
        self.assertEqual(got, {"today": "2026-10-19", "yest": "2026-10-18"})
        got = _node("m.dayKeys({days:{today:{date:'2026-03-01'},yesterday:{date:null}}}, 0)")
        self.assertEqual(got["yest"], "2026-02-28", "跨月")

    def test_platform_filter(self):
        rows = "[R({key:'a',platform:'codex'}), R({key:'b',platform:'agy'}), R({key:'c',platform:'codex'})]"
        self.assertEqual(_node(f"m.filterPlatform({rows}, 'codex').map(r=>r.key)"), ["a", "c"])
        self.assertEqual(_node(f"m.filterPlatform({rows}, 'agy').map(r=>r.key)"), ["b"])
        self.assertEqual(_node(f"m.filterPlatform({rows}, 'all').length"), 3)

    def test_there_is_no_slow_filter(self):
        """定稿取消「慢请求」：筛选只有 全部 + 四家平台。"""
        self.assertEqual(_node("m.PLATFORM_ORDER"), ["codex", "claude", "agy", "grok"])
        self.assertEqual(_node("m.PLATFORM_NAME.agy"), "Gemini")


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class Metrics(unittest.TestCase):
    def test_count_avg_and_median(self):
        rows = ("[R({tps:10,ttft_ms:1000}), R({tps:20,ttft_ms:3000}), R({tps:null,ttft_ms:null}),"
                " R({tps:30,ttft_ms:2000})]")
        got = _node(f"m.dayMetrics({rows})")
        self.assertEqual(got["n"], 4)
        self.assertAlmostEqual(got["avgTps"], 20.0, msg="读不到的 t/s 不计入均速（不当 0）")
        self.assertAlmostEqual(got["ttftMedianS"], 2.0)

    def test_even_count_median_is_the_mean_of_the_middle_two(self):
        got = _node("m.dayMetrics([R({ttft_ms:1000}), R({ttft_ms:2000}), R({ttft_ms:4000}), R({ttft_ms:9000})])")
        self.assertAlmostEqual(got["ttftMedianS"], 3.0)

    def test_nothing_readable_is_null_not_zero(self):
        got = _node("m.dayMetrics([R({}), R({})])")
        self.assertEqual((got["n"], got["avgTps"], got["ttftMedianS"]), (2, None, None))
        got = _node("m.dayMetrics([])")
        self.assertEqual((got["n"], got["avgTps"], got["ttftMedianS"]), (0, None, None))


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class Formatting(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(_node("[999, 1000, 108500, 999999, 1234567, null].map(m.fmtTokens)"),
                         ["999", "1.0k", "108.5k", "1000.0k", "1.2M", "—"])

    def test_output_grouping_and_null(self):
        self.assertEqual(_node("[0, 747, 1685, 1234567, null].map(m.fmtInt)"), ["0", "747", "1,685", "1,234,567", "—"])

    def test_seconds_tps_and_dashes(self):
        self.assertEqual(_node("[m.fmtSecs(4200), m.fmtSecs(null), m.fmtTps(176.66), m.fmtTps(null), m.fmtTps(0)]"),
                         ["4.2 s", "—", "176.7", "—", "0.0"])

    def test_time_is_hh_mm_only(self):
        self.assertEqual(_node(f"m.fmtHHMM({T_1019_10 * 1000 + 26 * 60000 + 59000})"), "10:26")
        self.assertEqual(_node(f"m.fmtWhen({T_1019_10 * 1000}, 'SGT')"), "10/19 10:00 SGT")
        self.assertEqual(_node("m.tzLabel('Asia/Singapore', 'GMT+8')"), "SGT")
        self.assertEqual(_node("m.tzLabel('Europe/Paris', 'GMT+2')"), "GMT+2")

    def test_claude_prefix_is_stripped(self):
        self.assertEqual(_node("['claude-opus-5.5', 'gpt-6-sol', null].map(m.modelName)"), ["opus-5.5", "gpt-6-sol", "—"])

    def test_codex_source_labels(self):
        self.assertEqual(_node("[m.sourceLabel('codex','交互'), m.sourceLabel('codex','exec'),"
                               " m.sourceLabel('agy','agy -p'), m.sourceLabel('grok',null)]"),
                         ["codex · 交互", "codex exec", "agy -p", "—"])

    def test_ttft_tone(self):
        self.assertEqual(_node("[null, 30000, 30001, 1200].map(m.ttftTone)"), ["muted", "normal", "amber", "normal"])


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class PrivacyAndDetail(unittest.TestCase):
    def test_privacy_masks_real_labels_but_not_the_fixed_words(self):
        got = _node("['号A','直连','本机','单号',null].map(a => m.accountLabel(a, true, s => s.slice(0,1) + '•••'))")
        self.assertEqual(got, ["号•••", "直连", "本机", "单号", "—"])
        self.assertEqual(_node("m.accountLabel('号A', false, s => 'X')"), "号A")

    def test_cache_rate(self):
        self.assertEqual(_node("[m.cacheRate(160000,120000), m.cacheRate(0,0), m.cacheRate(null,5), m.cacheRate(100,null)]"),
                         [75, None, None, None])

    def test_split_needs_a_ttft(self):
        self.assertEqual(_node("m.timeSplit({ttft_ms:null, gen_ms:5000, total_ms:5000}).kind"), "none")
        self.assertEqual(_node("m.timeSplit({ttft_ms:4200, gen_ms:4200, total_ms:8400})"),
                         {"kind": "split", "ttftMs": 4200, "genMs": 4200})
        self.assertEqual(_node("m.timeSplit({ttft_ms:1000, gen_ms:null, total_ms:3000})")["genMs"], 2000)

    def test_slow_reason_only_for_long_ttft(self):
        self.assertIsNone(_node("m.slowWhy({ttft_ms:30000, input:100, cached:50})"))
        self.assertIsNone(_node("m.slowWhy({ttft_ms:null, input:100, cached:50})"))
        why = _node("m.slowWhy({ttft_ms:39500, input:100, cached:75})")
        self.assertIn("39.5 s", why)
        self.assertIn("75 %", why)

    def test_empty_copy(self):
        self.assertEqual(_node("m.emptyCopy(0,'today').title"), "今天还没有请求")
        self.assertIn("昨天", _node("m.emptyCopy(0,'today').sub"))
        self.assertEqual(_node("m.emptyCopy(5,'today').title"), "这个筛选下没有请求")

    def test_selection_follows_the_key(self):
        rows = "[R({key:'a'}), R({key:'b'}), R({key:'c'})]"
        self.assertEqual(_node(f"[m.selectedIndex({rows}, 'b'), m.selectedIndex({rows}, 'gone'),"
                               f" m.selectedIndex({rows}, null), m.selectedIndex([], 'a')]"), [1, 0, 0, -1])


# ───────────────────────── 真 bundle 几何 ─────────────────────────

_GEOM = r"""
(function () {
  var o = {};
  var sc = document.querySelector('[data-req-scroll]');
  var hd = document.querySelector('[data-req-head]');
  var body = document.querySelector('[data-page-body="requests"]');
  o.found = !!(sc && hd && body);
  if (!o.found) return o;
  o.rows = document.querySelectorAll('[data-req-row]').length;
  o.headInsideScroll = sc.contains(hd);
  o.headSticky = getComputedStyle(hd).position;
  o.scrollOverflowY = getComputedStyle(sc).overflowY;
  sc.scrollTop = 400;
  o.scrolled = sc.scrollTop;
  o.headTopDelta = Math.round(hd.getBoundingClientRect().top - sc.getBoundingClientRect().top);
  var heads = Array.prototype.slice.call(hd.children);
  var row = null, rows = document.querySelectorAll('[data-req-row]');
  for (var i = 0; i < rows.length; i++) { var r = rows[i].getBoundingClientRect();
    if (r.top > hd.getBoundingClientRect().bottom) { row = rows[i]; break; } }
  var cx = function (e) { var r = e.getBoundingClientRect(); return Math.round(r.left + r.width / 2); };
  o.headCenters = heads.map(cx);
  o.rowCenters = row ? Array.prototype.slice.call(row.children).map(cx) : [];
  o.headAlign = heads.map(function (e) { return getComputedStyle(e).textAlign; });
  o.rowH = rows.length ? Math.round(rows[0].getBoundingClientRect().height) : 0;
  var det = document.querySelector('[data-req-detail]');
  o.detailW = det ? Math.round(det.getBoundingClientRect().width) : 0;
  var se = document.scrollingElement;
  o.docOverflow = se.scrollHeight - se.clientHeight;
  o.bodyOverflow = body.scrollHeight - body.clientHeight;
  o.banner = !!document.querySelector('[data-req-banner]');
  // ★ **有效**不透明度 = 一路到 body 的乘积。只读元素自己的 `opacity` 会漏掉「包一层降透明度的父元素」。
  var eff = function (e) { var v = 1; while (e && e !== document.body) { v *= parseFloat(getComputedStyle(e).opacity); e = e.parentElement; } return Math.round(v * 100) / 100; };
  var cell = rows.length ? rows[0].children[4] : null;
  o.cellOpacity = cell ? eff(cell) : null;
  var logo = rows.length ? rows[0].querySelector('img') : null;
  o.logoOpacity = logo ? eff(logo) : null;
  var wrapNoWrap = [];
  hd.querySelectorAll('span').forEach(function (s) { if (getComputedStyle(s).whiteSpace !== 'nowrap') wrapNoWrap.push(s.textContent); });
  o.headWraps = wrapNoWrap;
  return o;
})()
"""


def _geom(query, w, h, budget=6000):
    import urllib.request
    src = APP_DIR / "harness.html"
    if not Path(CHROME).exists() or not src.exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    page = APP_DIR / "reqprobe.html"
    page.write_text(src.read_text(encoding="utf-8").replace(
        "</body>",
        "<script>setTimeout(() => { document.title = '__RQ__' + JSON.stringify(%s); }, %d);</script></body>"
        % (_GEOM, budget - 1500), 1), encoding="utf-8")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--use-mock-keychain", "--disable-gpu",
                            f"--window-size={w},{h}", f"--virtual-time-budget={budget}",
                            "--dump-dom", f"{HARNESS}/reqprobe.html?nav=requests&notrans=1&probe_ms=99999{query}"],
                           capture_output=True, text=True, timeout=180)
        m = re.search(r"__RQ__(\{.*?\})</title>", r.stdout, re.S)
        if not m:
            return None
        return json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&"))
    finally:
        page.unlink(missing_ok=True)


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheStickyHeaderLivesInsideTheScrollContainer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = {}
        for w, h in ((1200, 760), (860, 560)):
            r = _geom("", w, h)
            if r is None:
                raise unittest.SkipTest("harness 静态服务（3304）没在跑 / 没有 harness.html")
            cls.g[w] = r

    def test_the_page_actually_rendered(self):
        """★ 先正面证明页面在 —— 零渲染时下面每条都可能「恰好成立」。"""
        for w, g in self.g.items():
            self.assertTrue(g["found"], f"{w}: 请求页没渲染")
            self.assertGreater(g["rows"], 10, f"{w}: 夹具应有 64 行今天的请求")

    def test_header_is_a_sticky_child_of_the_scroller(self):
        for w, g in self.g.items():
            self.assertTrue(g["headInsideScroll"], f"{w}: ★★ 表头在滚动容器外 —— 出滚动条时列会错位")
            self.assertEqual(g["headSticky"], "sticky", w)
            self.assertIn(g["scrollOverflowY"], ("auto", "scroll"), w)

    def test_header_stays_on_top_after_scrolling(self):
        for w, g in self.g.items():
            self.assertGreater(g["scrolled"], 100, f"{w}: 没滚动起来，这条判不了")
            self.assertLessEqual(abs(g["headTopDelta"]), 1, f"{w}: 滚动后表头没有贴住滚动框顶")

    def test_header_columns_line_up_with_the_row_columns(self):
        for w, g in self.g.items():
            self.assertEqual(len(g["headCenters"]), 9, w)
            self.assertEqual(len(g["rowCenters"]), 9, w)
            for i, (a, b) in enumerate(zip(g["headCenters"], g["rowCenters"])):
                self.assertLessEqual(abs(a - b), 1, f"{w}: 第 {i + 1} 列表头与内容错位 {a} vs {b}")

    def test_all_nine_headers_are_centred_and_nowrap(self):
        for w, g in self.g.items():
            self.assertEqual(g["headAlign"], ["center"] * 9, w)
            self.assertEqual(g["headWraps"], [], w)

    def test_row_height_and_detail_width(self):
        for w, g in self.g.items():
            self.assertEqual(g["rowH"], 34, w)
            self.assertEqual(g["detailW"], 300, w)

    def test_the_page_root_never_scrolls(self):
        for w, g in self.g.items():
            self.assertLessEqual(g["docOverflow"], 0, f"{w}: 文档整体可滚")
            self.assertLessEqual(g["bodyOverflow"], 0, f"{w}: 页面根可滚 / 被撑高")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheListSurvivesAFailedRead(unittest.TestCase):
    """★★ 第 1 次读到、之后 IPC 一律失败（`?req=error`，需 >10 s 虚拟时间让轮询再读一次）。"""

    @classmethod
    def setUpClass(cls):
        cls.ok = _geom("", 1200, 760)
        cls.bad = _geom("&req=error", 1200, 760, budget=16000)
        if cls.ok is None or cls.bad is None:
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_banner_appears_and_rows_are_kept(self):
        self.assertFalse(self.ok["banner"], "成功时不该有红条")
        self.assertTrue(self.bad["banner"], "读失败后没有红条")
        self.assertEqual(self.bad["rows"], self.ok["rows"], "★★ 读失败把列表清掉了（读不到 ≠ 没有）")

    def test_text_dims_but_logos_do_not(self):
        self.assertEqual(self.ok["cellOpacity"], 1)
        self.assertEqual(self.bad["cellOpacity"], 0.55, "读失败时旧列表应降到 55%")
        self.assertEqual(self.bad["logoOpacity"], 1, "logo 任何状态都不变暗（交接包 README）")


if __name__ == "__main__":
    unittest.main()
