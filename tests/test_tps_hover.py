"""托盘胶囊悬停面板（交接包 2026-10-19 page2）的闸。

三层：
  ① `tpsHoverLogic.ts` 的**行为**（node 直接跑零 import 模块 —— CI 没有 node_modules）：
     弹簧曲线、行版面 / logo 落点、飞行起止与错开、飞回不晚于 Rust 藏窗、250 ms 展开 / 折叠规则、
     停下 40% → 3 s → 收起、高度上报时机；
  ② 源码 / 样式**形态**（剥掉注释再断言）：所有文字不换行；
  ③ 真 bundle 的 `--dump-dom`（harness 127.0.0.1:3304，跑不到就 skip 不是绿）：表头、无跨 AI 合计、
     行顺序、— 规则、无 ≈、链接 emit 的 payload、宽 300、logo 落点 = 版面逻辑（实量）、悬停展开 / 离开折叠、
     停下态只降数据不降 logo、托盘 logo 藏 / 放回、减弱动态效果与无版面兜底不飞。
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "codexbar" / "src"
LOGIC = SRC / "tpsHoverLogic.ts"
CSS = SRC / "tpsHover.css"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness-tpshover.html?notrans=1"


def strip_css_comments(s):
    return re.sub(r"/\*[\s\S]*?\*/", "", s)


def node(expr):
    js = "import('%s').then(m => console.log(JSON.stringify(%s)))" % (LOGIC.as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", js],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


# ── ① 行为 ────────────────────────────────────────────────────────────────

class TheSpringIsTheHandoffOne(unittest.TestCase):
    def test_sp_is_crit_034(self):
        got = node("[m.SPRING, m.critSpring(0.34, 0.5)]")
        self.assertEqual(got[0], got[1], "SPRING 应逐字等于 HoverMotion.html 的 SP = crit(0.34, 0.5)")


class RowLayout(unittest.TestCase):
    C = "{multi:false,open:false,nSess:1,collapsed:false}"

    def test_four_collapsed(self):
        got = node("m.layoutPanel([%s])" % ",".join([self.C] * 4))
        # 描边 1 + 上内边距 4 + 表头 26 = 31；行 38、分隔线 1；logo 居中 (38-18)/2 = 10
        self.assertEqual(got["logoY"], [41, 80, 119, 158])
        self.assertEqual(got["height"], 224, "4 家全折叠 = 1+4+26+4×38+3+37+1（交接包写 ≈222）")

    def test_expanded_row_is_32_and_sessions_push_down(self):
        got = node("m.layoutPanel([%s,{multi:true,open:true,nSess:3,collapsed:false},%s,%s])" % (self.C, self.C, self.C))
        # Claude 行 32 高 ⇒ logo y = 70 + 7；会话 3×22 + 底部 4 推下后两行
        self.assertEqual(got["logoY"], [41, 77, 183, 222])
        self.assertEqual(got["height"], 288)

    def test_collapsed_block_takes_no_height(self):
        got = node("m.layoutPanel([{multi:false,open:false,nSess:1,collapsed:true},%s])" % self.C)
        # 收起的那块不占高；下一块仍带自己的分隔线（DOM 里同样如此 —— 实量闸在 ③）
        self.assertEqual(got["height"], 1 + 4 + 26 + (1 + 38) + 37 + 1)

    def test_logo_x(self):
        self.assertEqual(node("m.LOGO_X"), 37, "描边 1 + 内边距 14 + 箭头列 14 + 间距 8")

    def test_no_chevron_column_when_nothing_expands(self):
        """用户 2026-10-19「左边这里有点空旷」：没有一行是多会话 ⇒ 不留箭头列，logo 与底栏左对齐。"""
        self.assertEqual(node("m.LOGO_X_NOCHEV"), 15)
        lay = "{panel:{x:40,y:30,w:300,h:120},segments:[]}"
        self.assertEqual(node("[m.rowLogoPoint(%s, 41, false).x, m.rowLogoPoint(%s, 41).x]" % (lay, lay)), [55, 77])


class Flights(unittest.TestCase):
    LAY = ("{panel:{x:40,y:30,w:300,h:224},window:{w:380,h:380},menubar_h:24,pill:{x:228,y:3,w:104,h:18},"
           "segments:[{platform:'codex',x:6,w:12,logo:{x:234,y:6,size:12}},{platform:'claude',x:29,w:12,logo:{x:257,y:6,size:12}},"
           "{platform:'grok',x:75,w:12,logo:{x:303,y:6,size:12}}]}")

    def test_from_pill_to_row_and_stagger_by_flier(self):
        got = node("m.planFlights(%s, ['codex','claude','agy','grok'], [41,80,119,158])" % self.LAY)
        self.assertEqual([f["key"] for f in got], ["codex", "claude", "grok"], "胶囊里没有的那家不飞")
        self.assertEqual(got[0]["pill"], {"x": 234, "y": 6, "s": 1})
        self.assertEqual(got[2]["row"], {"x": 77, "y": 188, "s": 1}, "落点 = 面板 + (37, 那一行的 logoY)；胶囊 logo 与行内同为 18 ⇒ 不缩放")
        self.assertEqual([f["delayIn"] for f in got], [0, 35, 70], "相邻错开 35 ms（按飞行者计，不留空档）")
        self.assertEqual([f["delayBack"] for f in got], [110, 85, 60], "飞回：右边先走，60 + 25·k")

    def test_null_layout_never_flies(self):
        self.assertEqual(node("m.planFlights(null, ['codex'], [41])"), [])

    def test_parse_layout_rejects_shapes(self):
        self.assertEqual(node("[m.parseLayout(null), m.parseLayout({}), m.parseLayout({panel:{x:'a',y:1}})]"), [None, None, None])
        self.assertEqual(node("m.parseLayout(%s).segments.length" % self.LAY), 3)

    def test_return_flight_ends_before_rust_hides(self):
        got = node("[1,2,3,4].map(m.restoreLogosAt)")
        self.assertTrue(all(0 < v <= 500 for v in got), "托盘必须在 Rust 520 ms 藏窗前画回 logo：%r" % got)
        self.assertEqual(node("m.restoreLogosAt(0)"), 0)

    def test_settle_after_last_lands(self):
        self.assertEqual(node("[m.settleMs(0), m.settleMs(4)]"), [0, 465], "320 + 3×35 + 40（2026-10-21 飞入缩短）")
        self.assertGreaterEqual(node("m.settleMs(8)"), 320 + 7 * 35)


class ExpandRule(unittest.TestCase):
    def run_evs(self, evs):
        return node("(() => { let s = m.EXPAND0; const out = []; for (const e of %s) { s = m.expandReduce(s, e); "
                    "out.push({...s.open}); } return out; })()" % evs)

    def test_dwell_250_opens(self):
        got = self.run_evs("[{t:'enter',key:'claude',multi:true,now:0},{t:'tick',now:249},{t:'tick',now:250}]")
        self.assertEqual([g.get("claude", False) for g in got], [False, False, True])

    def test_leaving_before_250_never_opens(self):
        got = self.run_evs("[{t:'enter',key:'claude',multi:true,now:0},{t:'leave',key:'claude',now:200},{t:'tick',now:400}]")
        self.assertFalse(got[-1].get("claude", False))

    def test_leaving_the_row_closes_after_250(self):
        got = self.run_evs("[{t:'enter',key:'claude',multi:true,now:0},{t:'tick',now:250},"
                           "{t:'leave',key:'claude',now:300},{t:'tick',now:549},{t:'tick',now:550}]")
        self.assertEqual([g.get("claude", False) for g in got[2:]], [True, True, False])

    def test_coming_back_cancels_the_close(self):
        got = self.run_evs("[{t:'enter',key:'claude',multi:true,now:0},{t:'tick',now:250},{t:'leave',key:'claude',now:300},"
                           "{t:'enter',key:'claude',multi:true,now:400},{t:'tick',now:900}]")
        self.assertTrue(got[-1]["claude"])

    def test_moving_to_the_next_row(self):
        got = self.run_evs("[{t:'enter',key:'codex',multi:true,now:0},{t:'tick',now:250},{t:'leave',key:'codex',now:300},"
                           "{t:'enter',key:'claude',multi:true,now:300},{t:'tick',now:550}]")
        self.assertEqual(got[-1], {"codex": False, "claude": True})

    def test_single_session_row_never_opens(self):
        got = self.run_evs("[{t:'enter',key:'agy',multi:false,now:0},{t:'tick',now:1000}]")
        self.assertFalse(got[-1].get("agy", False))

    def test_prune_and_reset(self):
        got = self.run_evs("[{t:'enter',key:'claude',multi:true,now:0},{t:'tick',now:250},{t:'prune',multi:['codex']},"
                           "{t:'enter',key:'codex',multi:true,now:300},{t:'tick',now:550},{t:'reset'}]")
        self.assertFalse(got[2]["claude"], "不再是多会话的行要折叠")
        self.assertTrue(got[4]["codex"])
        self.assertEqual(got[5], {})

    def test_repeated_hits_on_one_row_do_not_restart_the_dwell(self):
        """Rust 每 16 ms 报一次光标：同一行重复命中若每次都派发 enter，250 ms 计时永远走不完。"""
        got = node("(() => { let s = m.EXPAND0, prev = null; const multi = () => true;"
                   " for (let t = 0; t <= 400; t += 16) { for (const e of m.hitEvents(prev, 'claude', multi, t)) s = m.expandReduce(s, e);"
                   " prev = 'claude'; s = m.expandReduce(s, {t:'tick', now:t}); } return s.open; })()")
        self.assertTrue(got.get("claude"), got)
        self.assertEqual(node("m.hitEvents('a', 'a', () => true, 0)"), [])
        self.assertEqual(node("m.hitEvents('a', 'b', () => false, 5)"),
                         [{"t": "leave", "key": "a", "now": 5}, {"t": "enter", "key": "b", "multi": False, "now": 5}])
        self.assertEqual(node("m.hitEvents('a', null, () => true, 5)"), [{"t": "leave", "key": "a", "now": 5}])

    def test_next_due(self):
        self.assertEqual(node("[m.nextDue(m.EXPAND0), m.nextDue(m.expandReduce(m.EXPAND0, {t:'enter',key:'a',multi:true,now:10}))]"),
                         [None, 260])


class StoppedRowHoldsThenCollapses(unittest.TestCase):
    def phases(self, script):
        return node("(() => { const O = ['codex','claude','agy','grok']; let s = []; const out = [];"
                    " for (const [rows, now] of %s) { s = m.reconcile(s, rows.map(k => ({key:k,row:k})), now, O);"
                    " out.push(s.map(x => x.key + ':' + x.phase)); } return out; })()" % script)

    def test_hold_3s_then_collapse_then_gone(self):
        got = self.phases("[[['codex','claude'],0],[['claude'],1000],[['claude'],3999],[['claude'],4000],"
                          "[['claude'],4399],[['claude'],4400]]")
        self.assertEqual(got, [["codex:live", "claude:live"], ["codex:held", "claude:live"], ["codex:held", "claude:live"],
                               ["codex:collapsing", "claude:live"], ["codex:collapsing", "claude:live"], ["claude:live"]])

    def test_restart_goes_back_to_live(self):
        got = self.phases("[[['codex'],0],[[],1000],[['codex'],2000]]")
        self.assertEqual(got[-1], ["codex:live"])

    def test_fixed_order(self):
        got = self.phases("[[['grok','agy','codex','claude'],0]]")
        self.assertEqual(got[0], ["codex:live", "claude:live", "agy:live", "grok:live"])

    def test_next_phase_at(self):
        got = node("(() => { const O=['codex']; let s = m.reconcile([], [{key:'codex',row:1}], 0, O);"
                   " s = m.reconcile(s, [], 1000, O); const a = m.nextPhaseAt(s); s = m.reconcile(s, [], 4000, O);"
                   " return [a, m.nextPhaseAt(s), m.nextPhaseAt([])]; })()")
        self.assertEqual(got, [4000, 4400, None])


class ResizeTiming(unittest.TestCase):
    def test_grow_now_shrink_after_collapse(self):
        self.assertEqual(node("[m.resizeDelay(null,224,false), m.resizeDelay(224,288,false), m.resizeDelay(288,224,false),"
                              " m.resizeDelay(288,224,true)]"), [0, 0, 400, 0])

    def test_avg(self):
        self.assertEqual(node("[m.fmtAvg(58.44), m.fmtAvg(null), m.fmtAvg(NaN)]"), ["58.4", "—", "—"])


# ── ② 形态 ────────────────────────────────────────────────────────────────

class NothingWraps(unittest.TestCase):
    def test_every_descendant_is_nowrap(self):
        css = re.sub(r"\s+", " ", strip_css_comments(CSS.read_text()))
        self.assertRegex(css, r"\.hv-win \* \{ white-space: nowrap; \}")


# ── ③ 真 bundle ───────────────────────────────────────────────────────────

def _reachable():
    try:
        urllib.request.urlopen(BASE, timeout=3).read(64)
        return Path(CHROME).exists()
    except Exception:                               # noqa: BLE001
        return False


_CACHE = {}


def dom(query, budget=3000):
    key = (query, budget)
    if key in _CACHE:
        return _CACHE[key]
    prof = tempfile.mkdtemp(prefix="tpshover-")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--use-mock-keychain", "--disable-gpu",
                            "--user-data-dir=" + prof, "--window-size=380,400",
                            "--virtual-time-budget=%d" % budget, "--dump-dom", BASE + query],
                           capture_output=True, text=True, timeout=90)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    # 打桩脚本本身含 `data-hover-row="' + k + '"` 之类的字面量 —— 先剥掉，断言只看渲染出来的 DOM
    h = re.sub(r"<script[\s\S]*?</script>", "", r.stdout)
    if "data-hover-panel" not in h or "data-hv-calls" not in h:
        raise AssertionError("悬停面板没渲染出来（没有 data-hover-panel / data-hv-calls）—— 零渲染不是通过")
    _CACHE[key] = h
    return h


def body_json(h, name):
    m = re.search(r'%s="([^"]*)"' % name, h)
    assert m, "body 上没有 %s" % name
    return json.loads(unescape(m.group(1)))


def text(h):
    h = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<title[\s\S]*?</title>", "", h)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def attr(h, name):
    return re.findall(r'%s="([^"]*)"' % name, h)


def element(h, marker):
    """从 marker 所在的开标签起，取到与它配对的闭标签（按 div/span 嵌套计数）。"""
    i = h.find(marker)
    assert i >= 0, marker
    start = h.rfind("<", 0, i)
    tag = re.match(r"<(\w+)", h[start:]).group(1)
    depth, j = 0, start
    for m in re.finditer(r"<(/?)%s\b[^>]*>" % tag, h[start:]):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return h[start:start + m.end()]
    return h[start:]


@unittest.skipUnless(_reachable(), "harness 127.0.0.1:3304 不可达（先跑 make_harness.py 并起静态服务）")
class TheBundleRenders(unittest.TestCase):
    def test_header_and_no_cross_ai_total(self):
        h = dom("&hv=4")
        self.assertEqual(body_json(h, "data-hv-errors"), [])
        self.assertEqual(text(element(h, "data-hover-head")), "AI 速度 Token", "表头只有三个字段，不要顶部跨 AI 总数")
        t = text(element(h, "data-hover-panel"))
        nums = re.findall(r"([\d.—]+) t/s", t)
        # AI 行合计 · 其折叠着的会话（仍在 DOM 里）· 底栏均速 —— 除此之外不许有别的 t/s
        self.assertEqual(nums, ["244", "178", "66", "190", "82", "64", "44", "141", "82", "58.4"], nums)
        self.assertEqual(attr(h, "data-hover-tps"), ["244", "190", "141", "82"])
        self.assertNotIn("657", t, "出现了跨 AI 合计")

    def test_row_order_names_and_footer(self):
        h = dom("&hv=4")
        self.assertEqual(attr(h, "data-hover-row"), ["codex", "claude", "agy", "grok"])
        t = text(element(h, "data-hover-panel"))
        for name in ("Codex", "Claude", "Gemini", "Grok"):
            self.assertIn(name, t)
        self.assertNotRegex(t, r"\bagy\b", "显示名叫 Gemini，agy 不作名字")
        self.assertEqual(text(element(h, "data-hover-foot")), "今日 48.7M · 均 58.4 t/s 请求页 →")
        self.assertEqual(re.findall(r"data-hover-n[^>]*>×(\d+)<", h), ["2", "3"], "×N 只给多会话的行")

    def test_no_response_dash_and_no_approx(self):
        h = dom("&hv=2")
        self.assertEqual(attr(h, "data-hover-tps"), ["178", "—"], "在跑但还没完成响应写 —，不写 0")
        t = text(element(h, "data-hover-panel"))
        self.assertNotIn("≈", t)
        self.assertNotIn("估", t)

    def test_single_session_panel_drops_the_chevron_column(self):
        self.assertIn("hv-nochev", dom("&hv=1"), "1 家 1 会话：箭头列应让出来")
        self.assertNotIn("hv-nochev", dom("&hv=4"), "有 ×N 的行：箭头列要留着")

    def test_link_emits_open_main_page(self):
        h = dom("&hv=4&hvclick=link")
        self.assertIn({"event": "open-main-page", "payload": {"page": "requests", "platform": None}},
                      body_json(h, "data-hv-emit"))

    def test_width_and_logo_targets_match_the_dom(self):
        for q in ("&hv=4", "&hv=4&hvexpand=claude", "&hv=1"):
            h = dom(q)
            panel = body_json(h, "data-hv-panel")
            self.assertEqual(panel["w"], 300, q)
            self.assertEqual(panel["h"], panel["logic"], "版面逻辑的总高 = 实量（%s）" % q)
            geom = body_json(h, "data-hv-geom")
            self.assertTrue(geom, q)
            for g in geom:
                self.assertAlmostEqual(g["ax"], g["tx"], delta=0.5, msg="%s %s x" % (q, g["k"]))
                self.assertAlmostEqual(g["ay"], g["ty"], delta=0.5, msg="%s %s y" % (q, g["k"]))
                self.assertEqual(g["w"], 18)

    def test_height_is_reported_to_rust(self):
        calls = body_json(dom("&hv=4&hvexpand=claude"), "data-hv-calls")
        sizes = [json.loads(c.split("=", 1)[1])["h"] for c in calls if c.startswith("tpshover_resize=")]
        self.assertEqual(sizes[-1], 288, calls)
        self.assertIn(224, sizes)

    def test_hover_expands_and_leaving_collapses(self):
        opened = dom("&hv=4&hvexpand=claude")
        self.assertEqual(attr(opened, "data-hover-open"), ["0", "1", "0", "0"])
        self.assertIn("ERP · 退货对账", text(element(opened, 'data-hover-sessions="claude"')))
        left = dom("&hv=4&hvexpand=claude&hvleave=1&hvat=2600")
        self.assertEqual(attr(left, "data-hover-open"), ["0", "0", "0", "0"], "离开这一行 250 ms 后折叠")
        single = dom("&hv=4&hvexpand=agy")
        self.assertEqual(attr(single, "data-hover-open"), ["0", "0", "0", "0"], "单会话的行不展开")

    def test_rust_cursor_alone_expands_and_collapses(self):
        """用户 2026-10-22：「悬浮弹窗后进一步悬浮没有展开会话」。AICoop 不在前台时 WKWebView 收不到鼠标移动，
        展开只能靠 Rust 报的光标（`tpshover-cursor`）。这里**不发任何网页鼠标事件**，只按 16 ms 报坐标。"""
        opened = dom("&hv=4&hvcursor=claude")
        self.assertIn("hvcursor →命中 1", body_json(opened, "data-hv-clicks"))
        self.assertEqual(attr(opened, "data-hover-open"), ["0", "1", "0", "0"])
        left = dom("&hv=4&hvcursor=claude&hvcursorleave=1&hvat=2600")
        self.assertEqual(attr(left, "data-hover-open"), ["0", "0", "0", "0"], "光标离开面板（null）250 ms 后折叠")
        single = dom("&hv=4&hvcursor=agy")
        self.assertEqual(attr(single, "data-hover-open"), ["0", "0", "0", "0"], "单会话的行不展开")

    def test_sessions_stay_in_the_dom_when_folded(self):
        h = dom("&hv=4")
        self.assertEqual(len(re.findall(r"data-hover-sess\b", h)), 5, "折叠用 CSS，不用条件渲染")

    def test_stopped_row_dims_data_not_logo(self):
        h = dom("&hv=4&hvstop=codex&hvat=2400", budget=2500)
        self.assertEqual(attr(h, "data-hover-phase")[0], "held")
        block = element(h, 'data-hover-block="codex"')
        tps = re.search(r'<span[^>]*data-hover-tps="244"[^>]*>', block).group(0)
        self.assertIn("opacity: 0.4", tps, "停下那一行的数据降到 40%")
        # 从这一块的开标签一直取到 logo 自己的 <img>（含 logo 格的开标签与 img 本身）
        chain = re.match(r'[\s\S]*?data-hover-logo-cell="codex"[^>]*>\s*<img[^>]*>', block).group(0)
        chain = re.sub(r'<span class="hv-chev"[^>]*>(?:<svg[\s\S]*?</svg>)?</span>', "", chain)
        self.assertNotIn("opacity", chain, "logo 任何状态都不变暗：它的祖先与它自己都不许带 opacity")
        collapsing = dom("&hv=4&hvstop=codex&hvat=4100", budget=4200)
        self.assertEqual(attr(collapsing, "data-hover-phase")[0], "collapsing")
        self.assertIn("grid-template-rows: 0fr", element(collapsing, 'data-hover-block="codex"')[:300])
        gone = dom("&hv=4&hvstop=codex&hvat=4900", budget=5000)
        self.assertEqual(attr(gone, "data-hover-row"), ["claude", "agy", "grok"])

    def test_tray_logos_hidden_while_flying_and_restored(self):
        calls = body_json(dom("&hv=4&hvclose=leave&hvat=2600"), "data-hv-calls")
        hides = [c for c in calls if c.startswith("tray_pill_hide_logos")]
        self.assertEqual(hides, ['tray_pill_hide_logos={"hidden":true}', 'tray_pill_hide_logos={"hidden":true}',
                                 'tray_pill_hide_logos={"hidden":false}'], "打开飞入藏 · 关闭飞回再藏 · 落地放回")

    def test_no_flight_without_layout_or_with_reduced_motion(self):
        for q in ("&hv=4&hvnull=1", "&hv=4&hvreduce=1"):
            h = dom(q + "&hvat=300", budget=400)
            self.assertEqual(attr(h, "data-hover-mode"), ["open"], q)
            self.assertNotIn("data-hover-fly", h, "不飞：%s" % q)
            calls = body_json(h, "data-hv-calls")
            self.assertFalse([c for c in calls if c.startswith("tray_pill_hide_logos")], q)
        flying = dom("&hv=4&hvat=300", budget=400)
        self.assertEqual(len(re.findall(r"data-hover-fly=", flying)), 4, "有版面时 300 ms 那一刻 4 个 logo 在飞")

    def test_click_close_fades(self):
        h = dom("&hv=4&hvclose=click&hvat=1700", budget=1800)
        self.assertEqual(attr(h, "data-hover-mode"), ["clicked"])


if __name__ == "__main__":
    unittest.main()
