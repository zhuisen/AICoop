"""工作台 · 总览（交接包 2026-10-19 page5 · 5b 卡片版）的行为闸。

## 两半

1. **纯逻辑**（`codexbar/src/overview.ts`，零 import）：`node --experimental-strip-types` 直接跑真文件。
   续航接力、分档、排序、「今天的切换」、在用 vs 停用 —— 期望值从真源推导，不抄副本。
   接力的口径还要与 `codex-rotate::_burst` **逐项对上**（「在其上扩展，不另造」）：两份实现同一条规则，
   边界输入上必须给同一个数。
2. **真 bundle**（harness 127.0.0.1:3304，Chrome 带 `--use-mock-keychain`，串行）：
   卡片各状态都是 148 高、文字不折行、列数跟宽度走、导航只收到一次、Grok 无续航/切换、
   Claude 无切换/探针、断档斜纹存在且数值 = 断档前时长、悬停才出动作、停用条折叠在 DOM 里。

harness 没起 / 没有 playwright ⇒ skip（**skip 不是绿**）。`OV_REBUILD=1` 时先重编 bundle
（`tools/mutate.py` 变异源码后必须重编，否则测的是旧 bundle —— CLAUDE.md §7.2 末段）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURE = ROOT / "codexbar" / "src" / "overview.ts"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness.html?nav=home&anon=1&notrans=1"


def _node(expr):
    """在真 `overview.ts` 上求值 `expr`（`m` = 模块）。`Infinity` 经 JSON 会变 null，所以先换成字符串。"""
    script = ("import('file://%s').then(m => {"
              "  const v = (%s);"
              "  console.log(JSON.stringify(v, (k, x) => x === Infinity ? 'Inf' : x));"
              "});" % (PURE.as_posix(), expr))
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip()[:1] in "[{\"tfn0123456789-"]
    if not out:
        raise AssertionError("node 没有产出结果：\nstdout=%s\nstderr=%s" % (r.stdout, r.stderr[-800:]))
    return json.loads(out[-1])


def R(id_, now, usable=True, back=None, refill=None, full=None, week=None):
    """一个 `RelayInput`（JS 字面量）。"""
    j = lambda v: "null" if v is None else repr(v)
    return ("{id:%r,label:%r,usable:%s,nowMin:%s,backAtMin:%s,refillAtMin:%s,fullMin:%s,weekMin:%s}"
            % (id_, id_, "true" if usable else "false", j(now), j(back), j(refill), j(full), j(week)))


def plan(*inputs, sim=None):
    return _node("m.relayPlan([%s]%s)" % (",".join(inputs), "" if sim is None else ", %d" % sim))


NODE = shutil.which("node") is not None


@unittest.skipUnless(NODE, "没有 node")
class RelayPlanBehaviour(unittest.TestCase):
    """接力条（交接包 README「续航接力条（核心）」）。"""

    def test_without_refills_the_value_is_the_sum_of_now(self):
        """★★ 没人回满得及接力 ⇒ 断档前 == Σ 可用号的 nowMin（= `_burst.now_min` 的口径）。"""
        p = plan(R("a", 3), R("b", 4), R("c", 2.5))
        self.assertAlmostEqual(p["continuousMin"], 9.5)
        self.assertEqual([s["kind"] for s in p["segs"]][:3], ["now", "now", "now"])
        self.assertEqual(p["firstGap"]["start"], 9.5)

    def test_an_account_that_refills_comes_back_as_back(self):
        """★★ 5h 回满的号算回接力，画成 `back`（淡色），只有真的没号可用才是断档。"""
        # a 用 0–10，b 用 10–55；a 的 5h 在 50 回满 ⇒ 55 起接上（淡色），之后才断。
        p = plan(R("a", 10, refill=50, full=60), R("b", 45))
        kinds = [(s["kind"], s.get("id")) for s in p["segs"]]
        self.assertEqual(kinds[:4], [("now", "a"), ("now", "b"), ("back", "a"), ("gap", None)],
                         "★★ a 50 分钟就回满了，b 用完（55）时应由 a 接上，不是断档")
        self.assertEqual(p["continuousMin"], 115)

    def test_a_gap_only_when_nobody_is_available(self):
        p = plan(R("a", 10, refill=40, full=20))
        g = p["firstGap"]
        self.assertEqual((g["start"], g["end"]), (10, 40))
        self.assertEqual(g["resumeLabel"], "a")
        self.assertEqual(g["resumeWhy"], "refill")
        self.assertEqual(p["continuousMin"], 10, "★★ 数值 = 断档前时长")

    def test_a_cooling_account_returns_when_the_cooldown_ends(self):
        p = plan(R("a", 5), R("c", 30, usable=False, back=20))
        g = p["firstGap"]
        self.assertEqual((g["start"], g["end"], g["resumeWhy"]), (5, 20, "cool"))
        self.assertIn(("back", "c"), [(s["kind"], s.get("id")) for s in p["segs"]])

    def test_unknown_pace_is_open_and_at_least_never_zero(self):
        """★★ 配速未知 ⇒ 排在已知之后、画成 `open`、数值带「≥」；绝不当 0。"""
        p = plan(R("pro", None), R("a", 7))
        self.assertEqual([s["kind"] for s in p["segs"]], ["now", "open"])
        self.assertTrue(p["atLeast"])
        self.assertEqual(p["continuousMin"], 7)
        only = plan(R("pro", None))
        self.assertIsNone(only["continuousMin"], "★★ 打头就是未知 ⇒ 「—」，不是「≥0」")

    def test_an_idle_window_refills_but_a_cooldown_still_holds(self):
        """★ 已在计时的窗口到点就回满（没轮到它也一样）；但冷却没结束之前它不回来。"""
        p = plan(R("a", 100), R("b", 30, refill=50, full=90))
        b = [s for s in p["segs"] if s.get("id") == "b"]
        self.assertAlmostEqual(b[0]["end"] - b[0]["start"], 90, msg="★ b 的 5h 在 50 已回满，100 轮到它时应是整窗 90")
        p2 = plan(R("a", 5), R("c", 0, usable=False, back=60, refill=50, full=40))
        g = p2["firstGap"]
        self.assertEqual((g["start"], g["end"]), (5, 60), "★★ 窗口 50 回满，但冷却到 60 —— 不能 50 就接上")

    def test_the_week_cap_stops_the_comeback(self):
        p = plan(R("a", 10, refill=20, full=60, week=25))
        backs = [s for s in p["segs"] if s["kind"] == "back"]
        self.assertEqual(len(backs), 1)
        self.assertAlmostEqual(backs[0]["end"] - backs[0]["start"], 15, msg="★ 周只剩 25 分钟，回满也只能再用 15")

    def test_no_gap_until_the_horizon_means_at_least(self):
        p = plan(R("a", 100, refill=100, full=100), R("b", 100, refill=200, full=100),
                 R("c", 100, refill=300, full=100), sim=600)
        self.assertIsNone(p["firstGap"])
        self.assertTrue(p["atLeast"], "★ 一路接到模拟尽头 ⇒ 真实值只会更长")


@unittest.skipUnless(NODE, "没有 node")
class RelayMatchesBurst(unittest.TestCase):
    """★★ 两份实现同一条规则（`_burst.now_min` vs 接力条），边界输入上必须给同一个数。"""

    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("cr_ov5b", str(ROOT / "codex-rotate"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.CR = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.CR)

    def _both(self, ratio):
        now = 1_900_000_000
        ents = [  # (aid, eta.left_min, per_window_min, 周剩余%, 5h 剩余%, 5h 重置串)
            ("A", 3.2, 4.0, 80, 70, "2h10m"),
            ("B", 4.0, 4.0, 2, 100, ""),       # 周只剩 2% ⇒ 周上限比 5h 先到
            ("C", 1.5, 4.0, 55, 30, "0h50m"),
        ]
        board = {"queue": [{"aid": a, "label": a, "off": False, "dead": False, "cool_min": 0,
                            "wins": [{"label": "5h", "rem": r5, "reset": rs}], "weekly": wk, "tightest": min(wk, r5),
                            "eta5h": {"left_min": left, "per_window_min": pw}} for a, left, pw, wk, r5, rs in ents],
                 "rest": [], "burn_pp_per_hour": None,
                 "burst": {"wk_per_5h": ratio, "per_window_min": 4.0}}
        js = _node("(() => { const p = m.relayPlan(m.codexRelayInputs(%s)); return p.firstGap ? p.firstGap.start : null; })()"
                   % json.dumps(board))
        py = self.CR._burst([{"eta": {"left_min": left, "per_window_min": pw, "n": 3}, "wk": wk, "rem5": r5,
                              "r5": None, "usable": True} for _, left, pw, wk, r5, _ in ents], ratio, now)["now_min"]
        return js, py

    def test_with_the_week_ratio(self):
        js, py = self._both(0.156)
        self.assertAlmostEqual(js, py, places=1, msg="★★ 接力条断档前 %s ≠ _burst.now_min %s" % (js, py))

    def test_without_the_week_ratio(self):
        js, py = self._both(None)
        self.assertAlmostEqual(js, py, places=1, msg="★★ 比值缺失时两边不一致：%s vs %s" % (js, py))

    def test_off_and_dead_do_not_join(self):
        """停用 / 失效的号不进接力（与 `_burst` 的 pool 同一个过滤）。"""
        b = {"queue": [], "burn_pp_per_hour": None, "burst": None,
             "rest": [{"aid": "X", "label": "X", "off": True, "dead": False, "cool_min": 5, "wins": [], "weekly": 50,
                       "tightest": 50, "eta5h": {"left_min": 3, "per_window_min": 4}},
                      {"aid": "Y", "label": "Y", "off": False, "dead": True, "cool_min": 5, "wins": [], "weekly": 50,
                       "tightest": 50, "eta5h": {"left_min": 3, "per_window_min": 4}},
                      {"aid": "Z", "label": "Z", "off": False, "dead": False, "cool_min": 5, "wins": [], "weekly": 50,
                       "tightest": 50, "eta5h": {"left_min": 3, "per_window_min": 4}}]}
        ids = _node("m.codexRelayInputs(%s).map(x => x.id)" % json.dumps(b))
        self.assertEqual(ids, ["Z"])


@unittest.skipUnless(NODE, "没有 node")
class LayoutSortAndState(unittest.TestCase):
    def test_breakpoints_are_on_content_width(self):
        # 列数 = max(2, ⌊(w + 12) / 257⌋)（AICoop P5_Spec §01）；边界 501 / 759 / 1016 / 1273。
        got = _node("[500, 501, 758, 759, 1015, 1016, 1272, 1273].map(w => m.ovLayout(w).cols)")
        self.assertEqual(got, [2, 2, 2, 3, 3, 4, 4, 5])
        # ★ 喂回 ovBand 的档位值必须算出**整个**同一份版面（Overview 存的是档位，不是原始宽度）——
        #   只比列数会漏掉 hero 三栏 / 标签 / Tab 名在 900 / 1100 那几条边界上的错档（四方评审 codex）。
        ws = [700, 758, 759, 899, 900, 1015, 1016, 1099, 1100, 1196, 1200, 1272, 1273, 1500]
        self.assertEqual(_node("%s.map(w => JSON.stringify(m.ovLayout(m.ovBand(w))) === JSON.stringify(m.ovLayout(w)))" % ws),
                         [True] * len(ws))
        self.assertEqual(_node("[m.ovLayout(1108).wide, m.ovLayout(908).wide, m.ovLayout(768).tabNames]"),
                         [True, False, False])

    def test_custom_order_wins_and_nothing_is_dropped(self):
        items = "[{id:'a',state:'ok',tightest:50,name:'a'},{id:'b',state:'inuse',tightest:10,name:'b'},{id:'n',state:'ok',tightest:90,name:'n'}]"
        self.assertEqual(_node("m.ovSort(%s, x => x).map(x => x.id)" % items), ["b", "n", "a"], "默认：在用 → 可用度降序")
        self.assertEqual(_node("m.ovSort(%s, x => x, ['a','b']).map(x => x.id)" % items), ["a", "b", "n"],
                         "★★ 拖过的顺序优先，没排过的追加在末尾、不丢")

    def test_in_use_beats_rotate_off(self):
        """★★ 停用号也能被借用 / 被别的 agy 写回成当值号 —— 那一刻它是「在用」，不能收进停用条藏起来。"""
        s = _node("m.ovState({inUse:true,next:false,dead:false,off:true,coolSec:0,tightest:50})")
        self.assertEqual(s, "inuse")
        self.assertEqual(_node("m.ovState({inUse:false,next:false,dead:false,off:true,coolSec:0,tightest:50})"), "off")
        self.assertEqual(_node("m.ovState({inUse:true,next:false,dead:true,off:false,coolSec:0,tightest:50})"), "dead")

    def test_low_is_judged_on_the_shown_integer(self):
        self.assertEqual(_node("[9.4, 9.5, 10].map(m.ovIsLow)"), [True, False, False])

    def test_today_switches(self):
        ev = ("[{t:100,type:'switch',from:'A',to:'B',reason:'cool_429'},{t:50,type:'switch',from:'B',to:'B',reason:'x'},"
              "{t:5,type:'switch',from:'C',to:'A',reason:'manual'},{t:200,type:'note',from:'A',to:'C',reason:''},"
              "{t:300,type:'failover',from:null,to:'C',reason:'stream_err'}]")
        rows = _node("m.todaySwitches(%s, 10000)" % ev)
        self.assertEqual([(r["t"], r["from"], r["to"], r["why"]) for r in rows],
                         [(300, "—", "C", "断流换号"), (100, "A", "B", "429 冷却")],
                         "只认今天的真换号，新的在前")

    def test_parse_reset_unknown_is_null_not_zero(self):
        self.assertEqual(_node("['2h05m','6d6h','',null,'soon'].map(m.parseReset)"), [125, 9000, None, None, None])

    def test_fmt_dur(self):
        self.assertEqual(_node("[0.4, 25, 125, 1500, -1].map(m.fmtDur)"), ["<1m", "25m", "2h05m", "1d1h", "—"])


# ── 真 bundle ────────────────────────────────────────────────────────────────

PROBE = r"""() => {
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && +cs.opacity > 0.05; };
  const root = document.querySelector('.ov-root'), page = document.querySelector('[data-ov-page]');
  if (!root || !page) return { mounted: false };
  const cards = [...document.querySelectorAll('[data-ov-card]')].map(c => {
    const a = c.querySelector('[data-ov-actions]'), d = c.querySelector('.ov-fdef');
    return { id: c.dataset.aid, st: c.dataset.ovCard, h: Math.round(c.getBoundingClientRect().height * 10) / 10,
             off: !!c.closest('[data-cards-off]'), vis: vis(c), act: vis(a), def: vis(d),
             abs: [...c.querySelectorAll('[data-ov-ab]')].map(e => e.dataset.ovAb) };
  });
  const wrapped = [];
  const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = tw.nextNode(); n; n = tw.nextNode()) {
    if (!n.textContent.trim()) continue;
    const rg = document.createRange(); rg.selectNodeContents(n);
    const tops = new Set([...rg.getClientRects()].filter(x => x.width > 0).map(x => Math.round(x.top)));
    if (tops.size > 1) wrapped.push(n.textContent.trim().slice(0, 30));
  }
  const grid = document.querySelector('[data-cards-grid]');
  const gaps = [...page.querySelectorAll('[data-relay-gap]')].map(e => parseFloat(e.style.left));
  const se = document.scrollingElement;
  return { mounted: true,
    cards, wrapped,
    cols: grid ? +grid.dataset.ovCols : null,
    gridCols: grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : null,
    rootOverflow: Math.max(se.scrollHeight - se.clientHeight, root.scrollHeight - root.clientHeight),
    bar: !!page.querySelector('[data-runway-bar]'),
    gaps, hours: (page.querySelector('[data-runway-hours]') || {}).textContent || null,
    heads: [...document.querySelectorAll('[data-ov-head]')].map(e => e.dataset.ovHead),
    nav: +(document.querySelector('[data-nav-count]') || { dataset: { navCount: -1 } }).dataset.navCount,
    tab: (document.querySelector('[data-provtab][data-active="1"]') || { dataset: {} }).dataset.provtab || null,
    strips: [...document.querySelectorAll('[data-ov-strip]')].map(s => ({ kind: s.dataset.ovStrip,
             open: (s.querySelector('.ov-strip') || { dataset: {} }).dataset.open === '1' })),
    grok5h: !!page.querySelector('[data-ov-grok-quota]') && page.querySelector('[data-ov-grok-quota]').textContent.includes('没有这个窗口'),
  };
}"""

_cache = {}
_rebuilt = []


def _rebuild_once():
    if os.environ.get("OV_REBUILD") != "1" or _rebuilt:
        return
    cb = ROOT / "codexbar"
    subprocess.run(["npx", "vite", "build", "--outDir", "uishot/app"], cwd=cb, check=True, capture_output=True, timeout=300)
    subprocess.run(["python3", "uishot/make_harness.py"], cwd=cb, check=True, capture_output=True, timeout=300)
    _rebuilt.append(1)


def _dom(query, w=1200, h=900, wait=2600):
    key = (query, w, h)
    if key in _cache:
        return _cache[key]
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        raise unittest.SkipTest("没有 playwright 或 harness 3304 没起 —— skip 不是绿")
    _rebuild_once()
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        pg = br.new_page(viewport={"width": w, "height": h})
        pg.goto(BASE + "&" + query, timeout=30000)
        pg.wait_for_timeout(wait)
        out = pg.evaluate(PROBE)
        br.close()
    if not out.get("mounted"):
        raise AssertionError("★★ 总览没渲染出来（%s %dx%d）—— 不是环境问题，不许 skip" % (query, w, h))
    _cache[key] = out
    return out


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class CardsAreFixedAndNothingWraps(unittest.TestCase):
    """卡片在各状态下都是 148 高；所有文字不换行；页面根不滚。"""

    SCENES = [
        ("ovplat=codex&ovcool=1&ovunprobed=1&ovlow=1&ovoff=1", {"inuse", "cool", "unprobed", "off"}),
        ("ovplat=codex&ovhover=1", {"inuse"}),
        ("ovplat=gemini&agypool=4&ovoff=1", {"inuse", "cool", "off"}),
        ("ovplat=claude", {"inuse"}),
        ("ovplat=grok", {"readonly"}),
    ]

    def test_148_in_every_state_and_width(self):
        for q, want in self.SCENES:
            for w in (1200, 1000, 860):
                with self.subTest(q=q, w=w):
                    d = _dom(q, w)
                    states = {c["st"] for c in d["cards"]}
                    self.assertTrue(want <= states, "★ 夹具没给出要验的状态 %s（实际 %s）—— 闸没有判别力" % (want, states))
                    hs = {c["h"] for c in d["cards"] if c["vis"]}
                    self.assertTrue(hs, "★★ 一张可见卡片都没有")
                    self.assertEqual(hs, {148.0}, "★★ 卡片不是固定 148 高：%s" % hs)

    def test_no_text_wraps(self):
        for q, _ in self.SCENES:
            for w in (1200, 860):
                with self.subTest(q=q, w=w):
                    self.assertEqual(_dom(q, w)["wrapped"], [], "★★ 有文字折行了")

    def test_the_page_root_does_not_scroll(self):
        for w, h in ((1200, 900), (860, 560)):
            with self.subTest(w=w):
                d = _dom("ovplat=codex&ovoff=1", w, h)
                self.assertLessEqual(d["rootOverflow"], 1, "★★ 页面根在滚 —— 卡片区应在自己的框里滚")


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class ColumnsFollowTheWidth(unittest.TestCase):
    def test_columns_follow_the_window_width(self):
        # AICoop P5_Spec §01（2026-10-21）：`max(2, ⌊(内容宽 + 12) / 257⌋)` ⇒ 1440 / 1200 / 1000 / 860 → 5 / 4 / 3 / 3。
        # 两列要内容宽 < 759（窗口约 < 855），低于最小窗口 860 —— 应用里到不了，只在纯函数闸里验。
        for w, cols in ((1440, 5), (1200, 4), (1000, 3), (860, 3)):
            with self.subTest(w=w):
                d = _dom("ovplat=codex", w)
                self.assertEqual((d["cols"], d["gridCols"]), (cols, cols), "★★ %d 宽应 %d 列" % (w, cols))

    def test_the_header_drops_labels_but_keeps_every_action(self):
        wide, narrow = _dom("ovplat=codex", 1200), _dom("ovplat=codex", 860)
        for d in (wide, narrow):
            for h in ("refresh", "probe", "toggles", "auto", "more"):
                self.assertIn(h, d["heads"], "★★ 头部少了 %s" % h)


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class ReadOnlyPlatformsHaveNoSwitch(unittest.TestCase):
    def test_grok_has_no_runway_and_no_switch(self):
        d = _dom("ovplat=grok&ovhover=0")
        self.assertTrue(d["cards"], "★ 没渲染出 grok 卡")
        self.assertFalse(d["bar"], "★★ Grok 画了续航条 —— 它只有周额度、单号")
        abs_ = {a for c in d["cards"] for a in c["abs"]}
        self.assertIn("refresh", abs_, "★ 已知阳性：grok 卡应有「刷新」")
        self.assertFalse(abs_ & {"switch", "probe", "more"}, "★★ Grok 有切换/探针：%s" % abs_)
        self.assertNotIn("probe", d["heads"])
        self.assertTrue(d["grok5h"], "★ 5h 那行没说「没有这个窗口」")

    def test_claude_has_no_switch_and_no_probe(self):
        d = _dom("ovplat=claude&ovhover=0")
        abs_ = {a for c in d["cards"] for a in c["abs"]}
        self.assertIn("refresh", abs_, "★ 已知阳性：Claude 卡应有「刷新」")
        self.assertFalse(abs_ & {"switch", "probe"}, "★★ Claude 有切换/探针：%s" % abs_)
        self.assertFalse({"probe", "toggles", "auto"} & set(d["heads"]), "★★ Claude 头部有探针/定时/自动切号")

    def test_known_positive_codex_does_have_them(self):
        """反向：同一个探针在 Codex 上必须看得到切换与探针（防「恒无」的空闸）。"""
        d = _dom("ovplat=codex&ovhover=1")
        abs_ = {a for c in d["cards"] for a in c["abs"]}
        self.assertTrue({"switch", "probe"} <= abs_, abs_)


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheGapIsDrawnAndTheNumberStopsThere(unittest.TestCase):
    def test_gap_and_value(self):
        d = _dom("ovplat=codex&relay=long&ovcool=1")
        self.assertTrue(d["gaps"], "★★ 没有断档斜纹")
        start = min(d["gaps"]) * 240 / 100
        want = _node("m.fmtDur(%r)" % start) if NODE else None
        self.assertIsNotNone(d["hours"])
        self.assertEqual(d["hours"].lstrip("≥ "), want, "★★ 「还能连续用」%s ≠ 断档前时长 %s" % (d["hours"], want))


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class NavigationArrivesOnce(unittest.TestCase):
    def test_requests_once(self):
        self.assertEqual(_nav("nav=requests&navtwice=1")["nav"], 1, "★★ 一次「请求页 →」跳了不止一回")

    def test_overview_jump_lands_on_the_platform_once(self):
        for to, tab in (("agy", "gemini"), ("claude", "claude"), ("grok", "grok")):
            with self.subTest(to=to):
                d = _nav("nav=ovjump&ovto=%s&navtwice=1" % to)
                self.assertEqual(d["nav"], 1, "★★ 一次点击跳了 %s 回" % d["nav"])
                self.assertEqual(d["tab"], tab, "★★ 没停在 %s 档" % tab)


def _nav(q):
    """导航场景：页面不一定停在总览，所以只取计数与档位。"""
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        raise unittest.SkipTest("没有 playwright 或 harness 3304 没起")
    _rebuild_once()
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        pg = br.new_page(viewport={"width": 1200, "height": 900})
        pg.goto("http://127.0.0.1:3304/harness.html?anon=1&notrans=1&" + q, timeout=30000)
        pg.wait_for_timeout(2600)
        out = pg.evaluate("""() => ({
          nav: +(document.querySelector('[data-nav-count]') || {dataset: {navCount: -1}}).dataset.navCount,
          tab: (document.querySelector('[data-provtab][data-active="1"]') || {dataset: {}}).dataset.provtab || null })""")
        br.close()
    return out


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class HoverAndTheDisabledStrip(unittest.TestCase):
    def test_only_the_hovered_card_shows_actions_and_the_footer_swaps(self):
        d = _dom("ovplat=codex&ovhover=1")
        main = [c for c in d["cards"] if not c["off"]]
        self.assertGreaterEqual(len(main), 2)
        self.assertEqual([c["act"] for c in main], [i == 1 for i in range(len(main))], "★★ 动作只该出现在悬停那张卡上")
        self.assertFalse(main[1]["def"], "★ 悬停时默认页脚没让位")
        self.assertTrue(main[0]["def"])
        self.assertNotIn("switch", main[0]["abs"], "★★ 在用的那张卡有「切换」")

    def test_the_strip_folds_but_stays_in_the_dom(self):
        closed, opened = _dom("ovplat=codex"), _dom("ovplat=codex&ovoff=1")
        self.assertEqual([s["open"] for s in closed["strips"] if s["kind"] == "off"], [False])
        self.assertEqual([s["open"] for s in opened["strips"] if s["kind"] == "off"], [True])
        off_c = [c for c in closed["cards"] if c["off"]]
        off_o = [c for c in opened["cards"] if c["off"]]
        self.assertTrue(off_c, "★★ 折叠时停用卡离开了 DOM（本仓：折叠用 CSS，不用条件渲染）")
        self.assertFalse(any(c["vis"] for c in off_c), "★ 折叠了还看得见")
        self.assertTrue(off_o and all(c["vis"] for c in off_o), "★ 展开了却看不见")


if __name__ == "__main__":
    unittest.main(verbosity=2)
