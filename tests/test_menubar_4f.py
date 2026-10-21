"""菜单栏弹窗 4f（交接包 2026-10-19 page4 §B）的闸。

三层：
  ① `mbLogic.ts` 的**行为**（node 直接跑，零 import 模块 —— CI 没有 node_modules）：
     低额度判显示整数、排序、通知合并、按住探针状态机、Claude 额度解析、名字列宽、弹簧曲线；
  ② 源码**形态**（剥掉注释再断言）：切换按钮不冒泡、hover 才长出切换列、弹窗里没有日夜切换、
     探针只走状态机、Claude 行不给切换；
  ③ 真 bundle 的 `--dump-dom`（harness 127.0.0.1:3304，跑不到就 skip 不是绿）：
     在跑条三态、Claude 行读数 / 读不到、通知合并、Gemini 低额度排最前、今日页不列 0 用量。
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "codexbar" / "src"
LOGIC = SRC / "mbLogic.ts"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness-menubar.html?w=352&grok=ok&notrans=1"


def strip_comments(s):
    s = re.sub(r"\{/\*[\s\S]*?\*/\}", "", s)
    s = re.sub(r"/\*[\s\S]*?\*/", "", s)
    return re.sub(r"(?m)(^|[^:\"'])//.*$", r"\1", s)


def node(expr):
    js = "import('%s').then(m => console.log(JSON.stringify(%s)))" % (LOGIC.as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", js],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


# ── ① 行为 ────────────────────────────────────────────────────────────────

class TheLowRuleJudgesTheShownInteger(unittest.TestCase):
    def test_boundaries(self):
        got = node("[9.4, 9.5, 9.6, 10, 0, null, undefined, NaN, -1].map(m.isLow)")
        # 9.5 → Math.round = 10 ⇒ 行上写「10%」⇒ 不红
        self.assertEqual(got, [True, False, False, False, True, False, False, False, True])

    def test_tightest_skips_unreadable(self):
        self.assertEqual(node("[m.tightestOf([40, null, 12]), m.tightestOf([null, undefined])]"), [12, None])


class TheSortPutsTheTightestFirst(unittest.TestCase):
    ROWS = ("[{n:'a',tight:50,inUse:false,next:false},{n:'b',tight:null,inUse:false,next:false},"
            "{n:'c',tight:8,inUse:false,next:false},{n:'d',tight:30,inUse:true,next:false},"
            "{n:'e',tight:90,inUse:false,next:true},{n:'f',tight:3,inUse:false,next:false},"
            "{n:'g',tight:70,inUse:false,next:false}]")

    def test_order(self):
        got = node("m.sortByAvailability(%s).map(r => r.n)" % self.ROWS)
        # 低（升序）→ 在用 → 下一个 → 其余降序 → 读不到
        self.assertEqual(got, ["f", "c", "d", "e", "g", "a", "b"])

    def test_stable_within_a_rank(self):
        got = node("m.sortByAvailability([{n:'x',tight:50,inUse:false,next:false},"
                   "{n:'y',tight:50,inUse:false,next:false},{n:'z',tight:null,inUse:false,next:false},"
                   "{n:'w',tight:null,inUse:false,next:false}]).map(r => r.n)")
        self.assertEqual(got, ["x", "y", "z", "w"])

    def test_title_follows_the_rule(self):
        self.assertEqual(node("[m.blockTitle(%s), m.blockTitle([{tight:50,inUse:false,next:false}])]" % self.ROWS),
                         ["账号 · 最紧的排最前", "账号 · 按可用排序"])

    def test_pool_dry_needs_a_reading(self):
        got = node("[m.poolDry([{tight:3},{tight:9}]), m.poolDry([{tight:3},{tight:40}]),"
                   " m.poolDry([{tight:null}]), m.poolDry([])]")
        self.assertEqual(got, [True, False, False, False], "★ 一个都读不到 ≠ 池见底")


class NoticesMergeIntoOne(unittest.TestCase):
    def test_bad_beats_warn_then_urgency(self):
        got = node("(() => { const r = m.mergeNotices(["
                   "{id:'card',tone:'warn',urgency:1,text:'c'},"
                   "m.lowNotice('a','号A','周',9,'3d'), m.lowNotice('b','号B','5h',4,'1h'),"
                   "m.subNotice('s','号D',5,'2026-10-24')]);"
                   " return [r.head && r.head.id, r.rest.map(x => x.id)]; })()")
        self.assertEqual(got, ["low:b:5h", ["low:a:周", "card", "sub:s"]])

    def test_empty(self):
        self.assertEqual(node("m.mergeNotices([])"), {"head": None, "rest": []})

    def test_low_notice_tail_only_for_a_real_duration(self):
        got = node("['1h11m', '未启动', '—', null].map(t => m.lowNotice('a','Yu','5h',6.4,t).text)")
        self.assertEqual(got, ["Yu 5h 只剩 6% · 1h11m 后回满", "Yu 5h 只剩 6%", "Yu 5h 只剩 6%", "Yu 5h 只剩 6%"])

    def test_sub_days(self):
        now = "new Date(2026, 9, 19, 8, 0).getTime()"
        self.assertEqual(node("[m.daysUntil('2026-10-24', %s), m.daysUntil('2026-10-19', %s),"
                              " m.daysUntil('bad', %s)]" % (now, now, now)), [4, -1, None])
        self.assertEqual(node("[m.subNotice('s','号D',0,'x').text, m.subNotice('s','号D',3,'x').text]"),
                         ["号D 订阅 今天到期（x）", "号D 订阅 3 天后到期（x）"])


class TheHoldProbeNeverFiresEarly(unittest.TestCase):
    """★★ 探针花钱：按住不满 600 ms 永远不执行；一次按住最多执行一次；正在探测时按下无效。"""

    RUN = ("(evs => { let s = m.HOLD_IDLE; const out = []; for (const e of evs) { s = m.holdReduce(s, e); "
           "out.push(s.phase); } return out; })")

    def phases(self, evs):
        return node("%s(%s)" % (self.RUN, evs))

    def test_release_before_600_retreats(self):
        got = self.phases("[{type:'down',now:0},{type:'tick',now:300},{type:'tick',now:599},"
                          "{type:'up',now:599},{type:'tick',now:700},{type:'tick',now:748},{type:'tick',now:749}]")
        self.assertEqual(got, ["holding", "holding", "holding", "retreat", "retreat", "retreat", "idle"])
        self.assertNotIn("fired", got)

    def test_leave_also_cancels(self):
        got = self.phases("[{type:'down',now:0},{type:'leave',now:200},{type:'tick',now:900}]")
        self.assertEqual(got, ["holding", "retreat", "idle"])

    def test_fires_once(self):
        got = self.phases("[{type:'down',now:0},{type:'tick',now:600},{type:'tick',now:700},"
                          "{type:'up',now:800},{type:'down',now:900},{type:'reset'}]")
        # fired 是终态：再 tick / 松手 / 按下都不会回到 holding 再 fired 一次，只有 reset 能出去
        self.assertEqual(got, ["holding", "fired", "fired", "fired", "fired", "idle"])

    def test_disabled_down_is_ignored(self):
        got = self.phases("[{type:'down',now:0,disabled:true},{type:'tick',now:5000}]")
        self.assertEqual(got, ["idle", "idle"])

    def test_fill_follows_the_handoff(self):
        got = node("[m.holdFill({phase:'holding',since:0}), m.holdFill(m.HOLD_IDLE)]")
        self.assertEqual(got, [{"width": 100, "transition": "width 600ms linear"},
                               {"width": 0, "transition": "width 150ms ease-out"}])


class ClaudeQuotaParse(unittest.TestCase):
    def test_remaining_is_100_minus_used(self):
        got = node("m.parseClaudeQuota(JSON.stringify({claude:{source:'statusline',captured_at:1760000000000,"
                   "five_hour:{used_pct:37,resets_at:1760007500},seven_day:{used_pct:22,resets_at:null}}}))")
        self.assertEqual(got, {"source": "statusline", "capturedAt": 1760000000,
                               "fiveH": {"rem": 63, "resetsAt": 1760007500},
                               "week": {"rem": 78, "resetsAt": None}})

    def test_unreadable_is_null_not_zero(self):
        got = node("['not json', '{}', JSON.stringify({claude:null})].map(m.parseClaudeQuota)")
        self.assertEqual(got, [None, None, None])
        got = node("m.parseClaudeQuota({claude:{source:'weird',five_hour:{used_pct:50,expired:true},"
                   "seven_day:{used_pct:'x'}}})")
        self.assertEqual(got, {"source": "none", "capturedAt": None, "fiveH": None, "week": None},
                         "★ 过期窗口 / 坏值必须是「读不到」")

    def test_reset_window_with_a_later_reading_is_full_and_idle(self):
        """重置点之后有新读数、却没再报这个窗口 ⇒ 100% 未启动（用户 2026-10-19：「—」改成像其他 AI 那样写）。"""
        got = node("m.parseClaudeQuota({claude:{source:'statusline',captured_at:2000,"
                   "five_hour:{used_pct:56,resets_at:1500,expired:true},seven_day:{used_pct:96,resets_at:9000,expired:false}}})")
        self.assertEqual(got["fiveH"], {"rem": 100, "resetsAt": None, "idle": True})
        self.assertEqual(got["week"], {"rem": 4, "resetsAt": 9000})

    def test_reset_window_without_a_later_reading_stays_unknown(self):
        """★ 重置后没有任何新读数 ⇒ 证不了它没被别处用掉，仍是「读不到」，不编一个满额。"""
        got = node("[1500, 1000].map(c => m.parseClaudeQuota({claude:{source:'statusline',captured_at:c,"
                   "five_hour:{used_pct:56,resets_at:1500,expired:true}}}).fiveH)")
        self.assertEqual(got, [None, None])

    def test_idle_window_says_not_started_on_every_surface(self):
        for f in ("codexbar/src/components/mb/ClaudeRow.tsx", "codexbar/src/NotchHud.tsx",
                  "codexbar/src/components/ov/ClaudeCard.tsx"):
            src = re.sub(r"//.*|/\*[\s\S]*?\*/", "", (ROOT / f).read_text(encoding="utf-8"))
            self.assertRegex(src, r"\.idle\s*\?\s*\"未启动\"", f)

    def test_stale(self):
        self.assertEqual(node("[m.isStale(0, 1801), m.isStale(0, 1800), m.isStale(null, 1e9)]"), [True, False, False])


class Layout(unittest.TestCase):
    def test_name_column(self):
        self.assertEqual(node("[m.nameColWidth(['号A']), m.nameColWidth(['tomyhuohuo']), "
                              "m.nameColWidth(['abcdefghijklmnop']), m.nameColWidth([])]"), [46, 80, 84, 46])

    def test_spring_is_the_one_the_css_uses(self):
        vars_ts = (SRC / "components" / "mb" / "vars.ts").read_text(encoding="utf-8")
        lit = re.search(r'const SPRING = "([^"]+)"', vars_ts).group(1)
        self.assertEqual(node("m.critSpring()"), lit, "vars.ts 里的弹簧曲线不是 critSpring() 算出来的那条")
        self.assertTrue(lit.startswith("linear(0.000, 0.041, 0.135,") and lit.endswith("1.000)"))


# ── ② 形态 ────────────────────────────────────────────────────────────────

class SourceShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rd = lambda p: strip_comments((SRC / p).read_text(encoding="utf-8"))
        cls.qrow = rd("components/mb/QuotaRow.tsx")
        cls.mb = rd("MenuBar.tsx")
        cls.hold = rd("components/mb/HoldProbe.tsx")
        cls.claude = rd("components/mb/ClaudeRow.tsx")
        cls.css = re.sub(r"/\*[\s\S]*?\*/", "", (SRC / "menubar.css").read_text(encoding="utf-8"))

    def test_switch_does_not_bubble_to_the_row(self):
        m = re.search(r'className="sw2"[\s\S]{0,400}?onClick=\{\(e\) => \{([^}]*)\}', self.qrow)
        self.assertTrue(m, "切换按钮的 onClick 没找到")
        self.assertIn("e.stopPropagation()", m.group(1), "★★ 点切换会顺带把主窗口弹出来")
        self.assertIn("onClick={switching ? undefined : onOpen}", self.qrow, "行点击没接到 onOpen")

    def test_switch_column_only_grows_on_hover(self):
        base = re.search(r"\.qrow\s*\{([^}]*)\}", self.css)
        hov = re.search(r"\.qrow:not\(\.qro\):hover\s*\{([^}]*)\}", self.css)
        self.assertTrue(base and hov)
        self.assertRegex(base.group(1), r"grid-template-columns:[^;]*\s0px\s*;", "平时切换列不是 0")
        self.assertRegex(hov.group(1), r"grid-template-columns:[^;]*\s46px\s*;", "hover 没长出 46px 的切换列")
        self.assertNotRegex(self.css, r"\.qrow\.qro:hover\s*\{[^}]*46px", "只读 / 在用行 hover 也长出了切换列")

    def test_no_day_night_toggle_in_the_popover(self):
        for bad in ("IconSun", "IconMoon", "toggleTheme", "setIsDark(!"):
            self.assertNotIn(bad, self.mb, "弹窗里又出现了日夜切换（交接包 4f 已移出）：%s" % bad)
        self.assertIn('"theme-changed"', self.mb, "主题仍要跟着设置页走")

    def test_probe_only_fires_through_the_state_machine(self):
        self.assertIn("useReducer(holdReduce", self.hold)
        self.assertIn("holdFill(", self.hold)
        self.assertIn("HOLD_MS", self.hold)
        self.assertNotRegex(self.hold, r"setTimeout\([^)]*\b600\b", "手写了 600 ms，绕开了 HOLD_MS")
        self.assertRegex(self.mb, r"<HoldProbe[\s\S]{0,300}?onFire=\{\(\) => run\(\"probe-all\"",
                         "探针按钮没接到全池探针")

    def test_no_cross_ai_speed_anywhere(self):
        """★★ DECISIONS.md：速度只在同一 AI 内合计，任何界面都不出现跨 AI 的 t/s（画板在在跑条表头画了一个，不照抄）。"""
        strip = strip_comments((SRC / "components" / "mb" / "RunStrip.tsx").read_text(encoding="utf-8"))
        for code, rel in ((strip, "RunStrip.tsx"), (self.mb, "MenuBar.tsx")):
            with self.subTest(f=rel):
                self.assertNotRegex(code, r"avg_tps|avgTps|today\.tps", "%s 用了跨 AI 的速度汇总" % rel)
        self.assertNotIn("均 {", strip)

    def test_claude_row_is_read_only(self):
        self.assertNotIn("onSwitch", self.claude, "Claude 不在轮换池，不许给切换（PLAN §4）")
        self.assertRegex(self.claude, r"<QuotaRow[\s\S]*?\breadOnly\b")
        self.assertIn("100 -", (SRC / "mbLogic.ts").read_text(encoding="utf-8"))


# ── ③ 真 bundle ───────────────────────────────────────────────────────────

def _reachable():
    try:
        urllib.request.urlopen(BASE, timeout=3).read(64)
        return Path(CHROME).exists()
    except Exception:                               # noqa: BLE001
        return False


def dom(query):
    prof = tempfile.mkdtemp(prefix="mb4f-")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--use-mock-keychain", "--disable-gpu",
                            "--user-data-dir=" + prof, "--window-size=520,800",
                            "--virtual-time-budget=5000", "--dump-dom", BASE + query],
                           capture_output=True, text=True, timeout=90)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    h = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<img[^>]*>", "", r.stdout)
    if "data-mb-tab" not in h:
        raise AssertionError("弹窗没渲染出来（没有 data-mb-tab）—— 零渲染不是通过")
    return h


def text(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()


def attr(h, name):
    return re.findall(r'%s="([^"]*)"' % name, h)


def after(h, marker, n=3000):
    i = h.find(marker)
    return h[i:i + n] if i >= 0 else ""


@unittest.skipUnless(_reachable(), "harness 127.0.0.1:3304 不可达（先跑 make_harness.py 并起静态服务）")
class TheBundleRenders(unittest.TestCase):
    def test_strip_three_states(self):
        idle, run, opened = dom("&run=0"), dom("&run=3"), dom("&run=3&mbstrip=1")
        self.assertEqual(attr(idle, "data-mb-status"), ["idle"])
        self.assertEqual(attr(idle, "data-mb-strip"), ["idle"])
        self.assertEqual(attr(run, "data-mb-status"), ["running"])
        self.assertEqual(attr(run, "data-mb-strip"), ["running"])
        self.assertEqual(attr(run, "data-mb-strip-open"), ["0"], "默认应折叠")
        self.assertEqual(attr(opened, "data-mb-strip-open"), ["1"])
        self.assertEqual(attr(opened, "data-mb-strip-row"), ["codex", "claude", "agy"])
        self.assertIn("在跑", text(after(run, "data-mb-status", 600)))
        head = text(after(opened, 'data-mb-strip="running"', 6000).split("data-mb-strip-row")[0])
        self.assertIn("今日", head)
        self.assertNotRegex(head, r"均\s*[\d.—]+\s*t/s", "在跑条表头出现了跨 AI 均速")

    def test_claude_row_reads_remaining(self):
        ok = dom("&mbplat=claude")
        self.assertEqual(attr(ok, "data-mb-claude"), ["ok"])
        t = text(after(ok, "data-mb-claude", 4000))
        self.assertIn("本机", t)
        self.assertIn("63%", t, "5h 剩余应为 100 − 37")
        self.assertIn("78%", t, "周剩余应为 100 − 22")
        self.assertNotIn("37%", t, "★★ 画成了已用")
        self.assertNotIn("切换", t)

    def test_claude_unreadable_says_so(self):
        none = dom("&mbplat=claude&claudeq=none")
        self.assertEqual(attr(none, "data-mb-claude"), ["none"])
        t = text(after(none, "data-mb-claude", 3000))
        self.assertIn("额度读不到", t)
        self.assertNotRegex(t, r"\b0%", "读不到写成了 0%")

    def test_notices_merge(self):
        h = dom("&mblow=1&mbsub=1")
        self.assertEqual(attr(h, "data-mb-notice"), ["bad"], "合并后只该有一条通知条，且红的在前")
        head = text(after(h, "data-mb-notice-head", 1200).split("data-mb-notice-rest")[0])
        self.assertRegex(head, r"只剩 \d+%")
        # 至少 = 夹具造的另外两条（重置卡、订阅）；真 state.json 里碰巧见底的号会再多几条，数目随当天用量变
        self.assertRegex(head, r"还有 [2-9] 条")
        rest = text(after(h, "data-mb-notice-rest", 3000).split("data-mb-block")[0])
        self.assertIn("重置卡", rest)
        self.assertIn("订阅", rest)

    def test_gemini_low_row_first(self):
        h = dom("&mbplat=gemini&agypool=4")
        rows = re.findall(r'<div class="(qrow[^"]*)" data-mb-agy="([^"]*)"', h)
        self.assertGreaterEqual(len(rows), 2, "Gemini 行没渲染出来: %s" % rows)
        self.assertIn("qlow", rows[0][0], "低额度的号没排在第一 / 没染警示: %s" % rows)
        self.assertTrue(all("qlow" not in c for c, _ in rows[1:]), rows)
        # ★ 池按名字排时 Asen（低额度）本来就在第一 —— 只看第一行判不出排序在不在。
        #   在用的 qq55 名字排第三，排序生效时它必须紧跟在低额度号之后。
        second = text(after(h, 'data-mb-agy="%s"' % rows[1][1], 2500).split(">", 1)[-1])[:40]
        self.assertIn("在用", second, "在用的号没排在第二（低额度 → 在用 → 下一个）: %s" % [r[1] for r in rows])
        self.assertIn("账号 · 最紧的排最前", text(after(h, "data-mb-block", 800)))

    def test_today_never_lists_zero_usage(self):
        h = dom("&tab=today")
        names = attr(h, "data-mb-today-row")
        self.assertTrue(names, "今日页一行都没有")
        for m in re.finditer(r'data-mb-today-row="([^"]*)"', h):
            cells = [c for c in re.findall(r">([^<>]+)<", h[m.start():m.start() + 2500]) if c.strip()]
            with self.subTest(p=m.group(1)):
                self.assertGreaterEqual(len(cells), 3, cells)
                self.assertNotIn(cells[2].strip(), ("0", "0k", "0.0M", "—"), "零用量的平台不该列出来: %s" % cells)


if __name__ == "__main__":
    unittest.main()
