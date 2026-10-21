"""刘海卡片（交接包 2026-10-19 page4 · 4e「④ 悬浮卡片 + 光桥」）的闸。

三层：
  ① `notchCard.ts` 的**行为**（node 直接跑零 import 模块 —— CI 没有 node_modules）：Tab 默认规则、<10% 告警判定与置顶、
     告警行文字、卡片版面与最高 560、logo 来向、果冻下垂几何、高度上报时机、面积图不过冲；
  ② 源码 / 样式**形态**（剥掉注释再断言）：所有文字不换行、卡片本身不响应点击、飞入 logo 只在「在跑」Tab；
  ③ 真 bundle 的 `--dump-dom`（harness 127.0.0.1:3304，跑不到就 skip 不是绿）：三个场景 A / B / C、今日 Tab、
     会话展开、果冻下垂、减弱动态效果、链接 emit 的 payload、每次展开回到默认 Tab、实量高度 = 版面逻辑、logo 落点 = 版面逻辑。

不碰凭证、不起脚本；harness 用的是脱敏夹具。
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
CARD = SRC / "notchCard.ts"
MB = SRC / "mbLogic.ts"
TSX = SRC / "NotchHud.tsx"
CSS = SRC / "notch.css"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness-notch.html?notrans=1"


def code_only(s):
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/\"])//[^\n]*", "", s)


def node(expr, mod=CARD):
    js = "import('%s').then(m => console.log(JSON.stringify(%s)))" % (mod.as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", js],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def W(pct, refill="1h00m", **kw):
    return dict(pct=pct, refill=refill, **kw)


ABSENT = dict(pct=None, refill="", absent=True)


def L(key, name, w5, ww):
    return dict(key=key, name=name, w5=w5, ww=ww)


# ── ① 行为 ────────────────────────────────────────────────────────────────

class TheSpringIsTheHandoffOne(unittest.TestCase):
    def test_sp_is_crit_036_055(self):
        """原型 `SP` = README「动效曲线」的 crit(0.36, 0.55)；现算比对，抄错一位就红。"""
        self.assertEqual(node("m.SPRING"), node("m.critSpring(0.36, 0.55)", MB))


class DefaultTab(unittest.TestCase):
    def test_running_defaults_to_run_and_idle_to_today(self):
        self.assertEqual(node("[m.defaultView(0), m.defaultView(1), m.defaultView(3)]"), ["today", "run", "run"])

    def test_run_tab_is_unreachable_while_idle(self):
        """空闲时「在跑」置灰不可点：选了也落到今日；展开着时最后一家停下同样落到今日。"""
        self.assertEqual(node("[m.effectiveView('run', 0), m.effectiveView('today', 2), m.effectiveView('run', 2)]"),
                         ["today", "today", "run"])


class LowQuota(unittest.TestCase):
    def test_low_is_judged_on_the_displayed_integer_and_agrees_with_the_menubar(self):
        """★ 两份实现（菜单栏 `mbLogic.isLow`、这里）在边界上必须一致：9.6 显示 10 不红，9.4 显示 9 红。"""
        xs = "[9.4, 9.5, 9.6, 10, 0, -1, null, NaN, 100]"
        mine = node(f"{xs}.map(m.isLowPct)")
        self.assertEqual(mine, node(f"{xs}.map(m.isLow)", MB))
        self.assertEqual(mine, [True, False, False, False, True, True, False, False, False])

    def test_low_row_is_pinned_tightest_first_rest_in_fixed_order(self):
        lines = [L("grok", "grok", ABSENT, W(65)), L("agy", "号C", W(8), W(41)), L("codex", "号F", W(100), W(5)),
                 L("claude", "号A", W(72), W(58))]
        got = node("m.orderQuota(%s).map(l => l.key)" % json.dumps(lines))
        self.assertEqual(got, ["codex", "agy", "claude", "grok"], "低的置顶、最紧的排最前；其余按 Codex→Claude→Gemini→Grok")
        calm = [L("grok", "grok", ABSENT, W(65)), L("claude", "号A", W(72), W(58)), L("codex", "号F", W(100), W(100))]
        self.assertEqual(node("m.orderQuota(%s).map(l => l.key)" % json.dumps(calm)), ["codex", "claude", "grok"])

    def test_unknown_and_absent_windows_never_alert(self):
        """读不到（—）不是 0%；Grok 的 5h 是「没有这个窗口」。两者都不许触发告警。"""
        lines = [L("codex", "号F", W(None, "失效"), W(None, "失效")), L("grok", "grok", ABSENT, W(None, "—"))]
        self.assertIsNone(node("m.alertOf(%s)" % json.dumps(lines)))
        self.assertEqual(node("m.alertKeys(%s)" % json.dumps(lines)), [])

    def test_alert_line_names_the_tightest_window(self):
        lines = [L("codex", "号F", W(100), W(100)), L("agy", "号C", W(8, "0h54m"), W(41))]
        a = node("m.alertOf(%s)" % json.dumps(lines))
        self.assertEqual(a["head"] + a["pct"] + a["tail"], "Gemini 号C 5h 剩 8% · 0h54m 后回满", "交接包示意原文")
        self.assertEqual(a["key"], "agy")
        two = [L("codex", "号F", W(9, "2h00m"), W(100)), L("agy", "号C", W(80), W(3, "4d2h"))]
        b = node("m.alertOf(%s)" % json.dumps(two))
        self.assertEqual(b["head"] + b["pct"] + b["tail"], "Gemini 号C 周 剩 3% · 4d2h 后回满", "几家同时低只写最紧的那一家")
        self.assertEqual(node("m.alertKeys(%s)" % json.dumps(two)), ["codex", "agy"], "光晕里每个低的都换橙红")

    def test_alert_line_does_not_say_refill_without_a_duration(self):
        a = node("m.alertOf(%s)" % json.dumps([L("agy", "号C", W(8, "未启动"), W(41))]))
        self.assertEqual(a["tail"], "", "「未启动 后回满」是病句")

    def test_pct_text(self):
        self.assertEqual(node("[m.pctText(m.ABSENT), m.pctText({pct:null, refill:''}), m.pctText({pct:8.4, refill:''}),"
                              " m.pctText({pct:100.4, refill:''}), m.pctText({pct:-2, refill:''})]"),
                         ["", "—", "8%", "100%", "0%"])

    def test_name_column_grows_for_real_names(self):
        self.assertEqual(node("[m.nameColWidth(['号A','号F']), m.nameColWidth(['tomyhuohuo-long-name'])]"), [34, 64])


def layout(alert=False, view="run", run=(), today=0, quota=4):
    return node("m.layoutCard(%s)" % json.dumps({"alert": alert, "view": view, "todayRows": today, "quotaRows": quota,
                                                   "run": [dict(multi=m_, open=o, nSess=n) for m_, o, n in run]}))


A_ROWS = [(True, False, 2), (True, False, 3), (False, False, 1)]


class CardLayout(unittest.TestCase):
    def test_scene_a_matches_the_prototype_geometry(self):
        """原型 `renderVals()`：y = 8 + 告警 34 + Tab 30；在跑每行 32 + 会话；底栏 37；额度块 = 8 + 26 + 28n + 33 + 8。"""
        g = layout(run=A_ROWS)
        self.assertEqual(g["rowTop"], [38, 70, 102])
        self.assertEqual(g["height"], 8 + 30 + 3 * 32 + 37 + 8 + 26 + 4 * 28 + 33 + 8)

    def test_alert_row_pushes_everything_down_34(self):
        a, c = layout(run=A_ROWS), layout(alert=True, run=A_ROWS)
        self.assertEqual([y - 34 for y in c["rowTop"]], a["rowTop"])
        self.assertEqual(c["height"] - a["height"], 34)

    def test_open_session_row_adds_22_each_plus_4(self):
        a = layout(run=A_ROWS)
        b = layout(run=[(True, False, 2), (True, True, 3), (False, False, 1)])
        self.assertEqual(b["height"] - a["height"], 3 * 22 + 4)
        self.assertEqual(b["rowTop"][2] - a["rowTop"][2], 3 * 22 + 4, "下面的行被推下去")
        self.assertEqual(layout(run=[(False, True, 3)])["height"], layout(run=[(False, False, 3)])["height"],
                         "单会话的行不展开")

    def test_tallest_card_fits_an_air_screen(self):
        """交接包：最高约 560（C 场景 + 今日 Tab），要放进 900 高的 Air。"""
        cap = node("m.todayRowCap(true, 4)")
        self.assertEqual(cap, 4)
        self.assertLessEqual(layout(alert=True, view="today", run=A_ROWS, today=cap)["height"], node("m.CARD_H_MAX"))
        self.assertEqual(layout(alert=True, view="today", run=A_ROWS, today=4)["height"], 536)
        self.assertGreater(layout(alert=True, view="today", run=A_ROWS, today=cap + 1)["height"], node("m.CARD_H_MAX"),
                           "cap 再多一行就超 —— cap 不是随便挑的小数")
        self.assertEqual(node("m.todayRowCap(false, 4)"), 6)
        self.assertLessEqual(layout(view="today", run=A_ROWS, today=6)["height"], node("m.CARD_H_MAX"))

    def test_session_list_is_capped_to_fit(self):
        many = layout(alert=True, run=[(True, True, 40), (False, False, 1), (False, False, 1), (False, False, 1)])
        self.assertLessEqual(many["height"], node("m.CARD_H_MAX"), "一个会话很多的行展开也要放得进")


class LogoFlight(unittest.TestCase):
    def test_each_ai_comes_out_of_its_own_side_of_the_glow(self):
        """交接包「logo 来向」：Codex 左翼 · Claude 下沿左半 · Gemini 下沿右半 · Grok 右翼。"""
        nw, nh = 179, 32
        f = node("Object.fromEntries(['codex','claude','agy','grok'].map(k => [k, m.flyFrom(k, %d)]))" % nw)
        self.assertLess(f["codex"]["x"] + 12, 0, "Codex 从刘海左翼出来")
        self.assertLess(f["codex"]["y"], nh)
        self.assertGreater(f["grok"]["x"], nw, "Grok 从右翼出来")
        self.assertLess(f["grok"]["y"], nh)
        self.assertTrue(0 <= f["claude"]["x"] < nw / 2, "Claude 从下沿左半出来")
        self.assertTrue(nw / 2 <= f["agy"]["x"] < nw, "Gemini 从下沿右半出来")
        for k in ("claude", "agy"):
            self.assertGreaterEqual(f[k]["y"], nh, "下沿那两家在刘海下面")
        self.assertEqual((f["claude"]["x"], f["agy"]["x"]), (round(nw * 0.33 - 6, 6), round(nw * 0.67 - 6, 6)), "原型 ox")
        self.assertEqual(node("[m.side('codex'), m.side('claude'), m.side('agy'), m.side('grok')]"), [-1, -1, 1, 1],
                         "这一行的数据也从同一侧滑入")

    def test_lands_on_the_row_logo_cell(self):
        to = node("m.flyTo(38, 179, 32)")
        self.assertEqual(to, {"x": 179 / 2 - 150 + 8 + 6 + 14 + 7, "y": 32 + 10 + 38 + 7})
        self.assertEqual(node("[m.FLY_FROM_S, m.FLY_TO_S, m.FLY_LOGO * m.FLY_TO_S]"), [0.4, 1.5, 18], "0.4→1.5 倍，落地 18")


class JellyDrip(unittest.TestCase):
    def test_grows_up_to_8_within_24_and_follows_the_cursor(self):
        """定稿 D：距刘海 24 pt 内鼓出一滴黑，最多 8 pt（顶在刘海里 6，伸出下沿 = 8p）。"""
        r = node("[0, 6, 12, 24, 30].map(d => m.dripGeom({dx: 0, distance: d}, 179, false))")
        self.assertEqual([x["h"] for x in r], [14, 12, 10, 6, 6])
        self.assertEqual([x["on"] for x in r], [True, True, True, False, False])
        self.assertEqual(r[0]["left"], 179 / 2 - 22, "在光标正上方（44 宽居中）")
        moved = node("m.dripGeom({dx: 30, distance: 5}, 179, false)")
        self.assertEqual(moved["left"], 179 / 2 + 30 - 22, "跟光标横移")

    def test_stays_under_the_notch_and_disappears_when_open(self):
        r = node("[m.dripGeom({dx: -500, distance: 3}, 179, false), m.dripGeom({dx: 500, distance: 3}, 179, false),"
                 " m.dripGeom({dx: 0, distance: 0}, 179, true), m.dripGeom(null, 179, false)]")
        self.assertEqual(r[0]["left"], 4, "吸附只在刘海下沿变形，不跑出刘海")
        self.assertEqual(r[1]["left"], 179 - 48)
        self.assertEqual((r[2]["on"], r[2]["p"], r[2]["h"]), (False, 0, 6), "展开后不再下垂（那滴黑收回刘海里）")
        self.assertFalse(r[3]["on"])


class HeightReport(unittest.TestCase):
    def test_grow_now_shrink_after_the_height_animation(self):
        self.assertEqual(node("[m.resizeDelay(null, 300, false), m.resizeDelay(300, 400, false),"
                              " m.resizeDelay(400, 300, false), m.resizeDelay(400, 300, true)]"), [0, 0, 420, 0])


class AreaChart(unittest.TestCase):
    def test_bands_never_overshoot_their_endpoints(self):
        """水平切线三次贝塞尔：每个 y 都等于某个数据点的 y —— 画不出数据里没有的峰（全局 ui-design「单调曲线」）。"""
        top, base = [0, 50, 10, 80, 0], [0, 10, 0, 20, 0]
        d = node("m.stackPath(%s, %s, 100, 256, 70)" % (json.dumps(top), json.dumps(base)))
        ys = {float(y) for y in re.findall(r"[\d.]+,([\d.]+)", d)}
        allowed = {round(70 - v / 100 * 70, 1) for v in top + base}
        self.assertTrue(ys <= allowed, ys - allowed)
        self.assertTrue(d.startswith("M0.0,70.0 C32.0,70.0 32.0,35.0 64.0,35.0"), d[:60])
        self.assertTrue(d.endswith("Z"))

    def test_single_bucket_is_a_column_not_a_full_width_area(self):
        d = node("m.stackPath([5], [0], 10, 256, 70)")
        xs = [float(x) for x in re.findall(r"([\d.]+),[\d.]+", d)]
        self.assertLess(max(xs) - min(xs), 256 * 0.2, "一个小时桶画成横跨全宽的面积 = 画一个没发生的事实")


# ── ② 形态 ────────────────────────────────────────────────────────────────

class Shape(unittest.TestCase):
    def setUp(self):
        self.tsx = code_only(TSX.read_text(encoding="utf-8"))
        self.css = re.sub(r"\s+", " ", re.sub(r"/\*[\s\S]*?\*/", "", CSS.read_text(encoding="utf-8")))

    def test_every_descendant_is_nowrap(self):
        self.assertIn(".nh-root * { white-space: nowrap; }", self.css)

    def test_the_card_itself_takes_no_clicks(self):
        """功能 3「点击长成弹窗」已取消：卡片本身不响应点击，只有三个链接打开工作台对应页。"""
        tag = re.search(r'<div ref=\{cardRef\} className="nh-card"[^>]*>', self.tsx, re.S).group(0)
        self.assertNotIn("onClick", tag)
        self.assertNotIn("set_main_visible", self.tsx, "旧面板「点这里打开 CodexBar」那条路要随功能 3 一起退役")
        links = re.findall(r'data-notch-link="(\w+)" onClick=\{go\("(\w+)"\)\}>([^<]+)<', self.tsx)
        self.assertEqual(links, [("requests", "requests", "请求页 →"), ("traffic", "traffic", "用量页 →"),
                                 ("overview", "overview", "总览 →")], "在跑 = 请求页、今日 = 用量页，别弄反")
        self.assertRegex(self.tsx, r'emit\("open-main-page", \{ page, platform: null \}\)')

    def test_flying_logos_only_show_on_the_run_tab(self):
        self.assertRegex(self.tsx, r'className="nh-flylayer" style=\{\{ opacity: isRunV \? 1 : 0 \}\}')
        self.assertIn(".nh-flylayer {", self.css)
        self.assertRegex(self.css, r"\.nh-flylayer \{[^}]*transition: opacity 150ms;", "切到今日时淡出")

    def test_every_open_returns_to_the_default_tab(self):
        # AICoop 阶段 2：4e 卡片只在「在跑」那种展开里出现（空闲那种画额度格子），展开流程挂在 `cardOpen` 上
        i = self.tsx.index("if (cardOpen) {")
        self.assertIn("setChosen(v);", self.tsx[i:i + 900])
        self.assertIn("const v = C.defaultView(cur.rows.length);", self.tsx[i:i + 900])


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
    prof = tempfile.mkdtemp(prefix="notchcard-")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--use-mock-keychain", "--disable-gpu",
                            "--user-data-dir=" + prof, "--window-size=500,700",
                            "--virtual-time-budget=%d" % budget, "--dump-dom", BASE + query],
                           capture_output=True, text=True, timeout=90)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    # 打桩脚本里有 `data-notch-row="' + ...` 之类的字面量 —— 先剥掉，断言只看渲染出来的 DOM
    h = re.sub(r"<script[\s\S]*?</script>", "", r.stdout)
    if "data-notch-card" not in h or "data-nt-calls" not in h:
        raise AssertionError("刘海卡片没渲染出来（没有 data-notch-card / data-nt-calls）—— 零渲染不是通过")
    _CACHE[key] = h
    return h


def body_json(h, name):
    m = re.search(r'%s="([^"]*)"' % name, h)
    assert m, "body 上没有 %s" % name
    return json.loads(unescape(m.group(1)))


def text(h):
    h = re.sub(r"<style[\s\S]*?</style>|<title[\s\S]*?</title>", "", h)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def attr(h, name):
    return re.findall(r'%s="([^"]*)"' % name, h)


def element(h, marker):
    """从 marker 所在的开标签起，取到与它配对的闭标签（按同名标签嵌套计数）。"""
    i = h.find(marker)
    assert i >= 0, marker
    start = h.rfind("<", 0, i)
    tag = re.match(r"<(\w+)", h[start:]).group(1)
    depth = 0
    for m in re.finditer(r"<(/?)%s\b[^>]*>" % tag, h[start:]):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return h[start:start + m.end()]
    return h[start:]


def root_attr(h, name):
    m = re.search(r'<div class="nh-root[^"]*"[^>]*\b%s="([^"]*)"' % name, h)
    assert m, name
    return m.group(1)


@unittest.skipUnless(_reachable(), "harness 127.0.0.1:3304 不可达（先跑 make_harness.py 并起静态服务）")
class TheBundleRenders(unittest.TestCase):
    def test_scene_a_running(self):
        h = dom("")
        self.assertEqual(body_json(h, "data-nt-errors"), [])
        self.assertEqual(root_attr(h, "data-notch-view"), "run", "有 AI 在跑默认「在跑」")
        self.assertEqual(attr(h, "data-notch-row"), ["codex", "claude", "agy"], "固定顺序")
        self.assertEqual(attr(h, "data-notch-tps"), ["244", "190", "141"])
        t = text(element(h, "data-notch-card"))
        self.assertNotIn("575", t, "出现了跨 AI 合计 t/s")
        self.assertNotIn("≈", t)
        self.assertNotIn("估", t)
        self.assertNotRegex(t, r"\bagy\b", "显示名叫 Gemini")
        self.assertIn("在跑 3", t)
        self.assertIn("请求页 →", t)
        self.assertEqual(attr(h, "data-notch-qrow"), ["codex", "claude", "agy", "grok"], "额度行固定顺序")
        self.assertNotIn("data-notch-alert=", h, "没有低额度就没有告警行")
        self.assertEqual(attr(h, "data-notch-bridge"), ["lit"])
        self.assertIn('class="nh-root nh-active nh-open', h)

    def test_grok_has_no_5h_window_and_unread_is_a_dash(self):
        h = dom("")
        g5 = element(h, 'data-notch-win="grok:5h"')
        self.assertRegex(g5, r'style="opacity: 0;', "Grok 只有周额度，5h 留空")
        self.assertIn('data-notch-win="grok:周"', h)
        hn = dom("&claudeq=none")
        c5 = text(element(hn, 'data-notch-win="claude:5h"'))
        self.assertEqual(c5, "5h —", "读不到写 —，不写 0")

    def test_measured_height_and_logo_cells_match_the_layout_logic(self):
        for q, run in (("", A_ROWS), ("&ntexpand=claude", [(True, False, 2), (True, True, 3), (False, False, 1)])):
            h = dom(q)
            card = body_json(h, "data-nt-card")
            want = layout(run=run)
            self.assertEqual(card["logic"], want["height"], q)
            self.assertEqual(card["h"], card["logic"], "卡片实高 = 版面逻辑（%s）" % q)
            self.assertEqual(card["content"] + 16, card["logic"], "内容实高 + 上下内边距 = 版面逻辑（%s）" % q)
            self.assertEqual((card["w"], card["x"], card["y"]), (300, 179 / 2 - 150, 42), "宽 300、居中、刘海下沿下方 10")
            # AICoop 阶段 2：两种展开各报一份（`mode`），这里只看 4e 卡片那份的最后一次
            run_calls = [c for c in body_json(h, "data-nt-calls") if c.startswith("notch_card_resize=") and '"mode":"run"' in c]
            self.assertEqual(run_calls[-1:], ['notch_card_resize={"h":%d,"mode":"run"}' % want["height"]],
                             "最后报给 Rust 的高度 = 卡片实高")
            geom = {g["k"]: g for g in body_json(h, "data-nt-geom")}
            for i, k in enumerate(("codex", "claude", "agy")):
                to = node("m.flyTo(%d, 179, 32)" % want["rowTop"][i])
                self.assertEqual((geom[k]["x"], geom[k]["y"], geom[k]["w"]), (to["x"], to["y"], 18), "%s %s" % (q, k))

    def test_no_chevron_column_when_nothing_expands(self):
        """用户 2026-10-19（同悬停面板）：没有一行是多会话 ⇒ 不留箭头列，logo 与下块额度行对齐。"""
        self.assertEqual(node("[m.ROW_LOGO_X_NOCHEV, m.flyTo(38, 179, 32, false).x]"), [22, 179 / 2 - 150 + 22])
        one = dom("&hv=1")
        self.assertIn("nh-fold nh-nochev", one, "1 家 1 会话：箭头列应让出来")
        geom = {g["k"]: g for g in body_json(one, "data-nt-geom")}
        self.assertEqual(geom["codex"]["x"], 179 / 2 - 150 + 22, "DOM 里 logo 真的落在 22")
        self.assertNotIn("nh-nochev", dom(""), "有 ×N 的行：箭头列要留着")

    def test_hovering_a_multi_session_row_expands_it(self):
        h = dom("&ntexpand=claude")
        self.assertIn("ntexpand →命中 1", body_json(h, "data-nt-clicks"))
        self.assertEqual(re.findall(r'data-notch-row="(\w+)" data-notch-open-row="(\d)"', h),
                         [("codex", "0"), ("claude", "1"), ("agy", "0")])
        self.assertEqual(len(re.findall(r'data-notch-sess="', element(h, 'data-notch-sessions="claude"'))), 3)

    def test_scene_b_idle_defaults_to_today_and_greys_out_run(self):
        h = dom("&nt=B")
        self.assertEqual(body_json(h, "data-nt-errors"), [])
        self.assertEqual(root_attr(h, "data-notch-view"), "today", "空闲默认「今日」")
        run_btn = re.search(r'<button[^>]*data-notch-tab="run"[^>]*>', h).group(0)
        self.assertIn("disabled", run_btn, "在跑置灰不可点")
        self.assertIn("opacity: 0.4", run_btn)
        self.assertIn('class="nh-root nh-quiet', h, "空闲不亮")
        self.assertEqual(attr(h, "data-notch-bridge"), ["idle"], "空闲光桥中性灰")
        rows = attr(h, "data-notch-trow")
        self.assertTrue(rows, "今日 Tab 没有各家行")
        for k in rows:
            tok = text(element(h, 'data-notch-trow="%s"' % k)).split()[1:]
            self.assertNotIn("0", tok, "0 用量的平台不显示")
        t = text(element(h, "data-notch-today"))
        self.assertIn("用量页 →", t)
        self.assertRegex(t, r"今日 [\d,]+ 次请求 · 均 [\d.]+ t/s")
        self.assertIn("<path", element(h, "data-notch-chart"))

    def test_today_tab_from_running(self):
        h = dom("&nttab=today")
        self.assertIn("nttab →命中 1", body_json(h, "data-nt-clicks"))
        self.assertEqual(root_attr(h, "data-notch-view"), "today")
        card = body_json(h, "data-nt-card")
        self.assertEqual(card["h"], card["logic"])
        self.assertEqual(body_json(h, "data-nt-fly"), 0, "今日 Tab 上没有飞着的 logo")

    def test_scene_c_alert(self):
        h = dom("&nt=C")
        self.assertEqual(body_json(h, "data-nt-errors"), [])
        al = text(element(h, 'data-notch-alert="agy"'))
        self.assertRegex(al, r"^Gemini \S+ 5h 剩 8% · \d+h\d{2}m 后回满$")
        self.assertEqual(attr(h, "data-notch-qrow")[0], "agy", "< 10% 的那家置顶")
        hot = re.search(r'data-notch-qrow="agy" data-notch-hot="1" style="[^"]*background: rgba\(255, 77, 46, 0\.12\)', h)
        self.assertIsNotNone(hot, "整行橙红底")
        self.assertEqual(attr(h, "data-notch-alert-glow"), ["agy"], "光晕那一段叠一团快闪")
        tps = re.search(r'data-notch-tps="141" style="color: rgb\((\d+), (\d+), (\d+)\)', h)
        self.assertEqual(tps.groups(), ("255", "138", "115"), "在跑那一行的数字也换橙红")
        bridge = re.search(r'data-notch-bridge="lit" style="background: ([^;]+);', h).group(1)
        self.assertIn("rgb(255, 77, 46)", bridge, "光桥那一段换橙红")
        card = body_json(h, "data-nt-card")
        self.assertEqual(card["logic"], layout(alert=True, run=A_ROWS)["height"])

    def test_links_emit_open_main_page(self):
        for link, page in (("requests", "requests"), ("overview", "overview")):
            h = dom("&ntclick=" + link)
            self.assertIn("ntclick →命中 1", body_json(h, "data-nt-clicks"))
            self.assertIn({"event": "open-main-page", "payload": {"page": page, "platform": None}}, body_json(h, "data-nt-emit"))
        h = dom("&nt=B&ntclick=traffic")
        self.assertIn({"event": "open-main-page", "payload": {"page": "traffic", "platform": None}}, body_json(h, "data-nt-emit"))

    def test_every_open_goes_back_to_the_default_tab(self):
        h = dom("&nttab=today&ntclose=1&ntreopen=1&ntat=2600", budget=3500)
        self.assertEqual(root_attr(h, "data-notch-open"), "1")
        self.assertEqual(root_attr(h, "data-notch-view"), "run", "收起再展开要回到默认 Tab，不记住上次切的今日")

    def test_logos_fly_in_from_the_glow(self):
        h = dom("&ntat=400", budget=800)
        self.assertEqual(body_json(h, "data-nt-fly"), 3, "展开时在跑那三家的 logo 正在飞")
        for k in ("codex", "claude", "agy"):
            cell = re.search(r'<span class="nh-logo" data-notch-logo="%s" style="([^"]*)"' % k, h).group(1)
            self.assertIn("visibility: hidden", cell, "飞着的时候行里那个先藏起来，否则两个 logo")
        h2 = dom("")
        self.assertEqual(body_json(h2, "data-nt-fly"), 0, "落地后交给行自己画")

    def test_reduce_motion_never_flies_and_only_fades(self):
        h = dom("&ntreduce=1&ntat=400", budget=800)
        self.assertEqual(body_json(h, "data-nt-fly"), 0)
        self.assertIn("nh-reduce", re.search(r'<div class="(nh-root[^"]*)"', h).group(1), "减弱动态效果：光晕不呼吸、告警常亮")
        card = re.search(r'<div class="nh-card" data-notch-card="[^"]*" style="([^"]*)"', h).group(1)
        self.assertIn("transition: opacity 150ms", card, "只做 150 ms 淡入淡出")
        self.assertIn("transform: none", card, "没有位移 / 缩放")

    def test_jelly_drip_when_closed(self):
        h = dom("&ntopen=0&ntcur=10,6")
        self.assertEqual(root_attr(h, "data-notch-open"), "0")
        self.assertEqual(attr(h, "data-notch-drip"), ["12.0"], "距 6 pt ⇒ p = .75 ⇒ 6 + 8p = 12")
        h2 = dom("&ntopen=0&ntcur=10,30")
        self.assertEqual(attr(h2, "data-notch-drip"), ["0"], "24 pt 外不下垂")
        h3 = dom("&ntcur=10,6")
        self.assertEqual(attr(h3, "data-notch-drip"), ["0"], "展开后不再下垂")


if __name__ == "__main__":
    unittest.main()
