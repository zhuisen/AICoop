"""AICoop P99（动效总表，阶段 7）：减弱动态效果下只剩淡入淡出；Accordion 不做行高动画；流光文字接上了。

★ 判据从真 bundle 量出来，不抄一份清单：
  - 渲染闸：Chrome 模拟「减弱动态效果」，逐元素读计算样式里的过渡属性；再把文档里**每一个** `@keyframes`
    挂到一个探针元素上，读浏览器实际选中的那一份关键帧（同名取最后生效的那份 —— 这正是跨文件顺序会坑人的地方）。
  - 已知阳性：同一组探针在「不减弱」时必须找到移动类关键帧 / 过渡，否则探针是坏的。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import re
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
H = "http://127.0.0.1:3304"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PAGES = {"home": "harness.html?nav=home", "traffic": "harness.html?nav=traffic", "settings": "harness.html?nav=settings",
         "logs": "harness.html?nav=logs", "relay": "harness.html?nav=relay", "requests": "harness.html?nav=requests",
         "codex": "harness.html?nav=platform:codex", "menubar": "harness-menubar.html", "mbtoday": "harness-menubar.html?tab=today",
         "tpshover": "harness-tpshover.html", "notch": "harness-notch.html"}

# 「会移动 / 改尺寸 / 改布局」的过渡属性。opacity / 颜色 / 阴影 / filter / visibility 放行。
TRANSITIONS = r"""() => {
  const MOVE = /^(all|transform|translate|scale|rotate|width|height|min-.*|max-.*|left|top|right|bottom|inset|grid-template-.*|gap|row-gap|column-gap|margin.*|padding.*|clip-path|stroke-dash.*|background-position|mask-position|-webkit-mask-position|flex.*)$/;
  const ms = (s) => s.split(",").map((x) => parseFloat(x) * (x.trim().endsWith("ms") ? 1 : 1000));
  const bad = [];
  const all = document.querySelectorAll("*");
  for (const el of all) {
    const cs = getComputedStyle(el);
    const ps = cs.transitionProperty.split(",").map((s) => s.trim()), ds = ms(cs.transitionDuration);
    ps.forEach((p, i) => { if (ds[i % ds.length] > 0 && MOVE.test(p)) bad.push(el.tagName + "." + String(el.className).slice(0, 40) + " " + p); });
  }
  return { nodes: all.length, bad: [...new Set(bad)] };
}"""

# 文档里每个关键帧名，浏览器此刻实际用的那一份里有没有「会动」的属性。
KEYFRAMES = r"""() => {
  const names = new Set();
  const walk = (rules) => { for (const r of rules) { if (r.type === 7) names.add(r.name); if (r.cssRules) walk(r.cssRules); } };
  for (const sh of document.styleSheets) { try { walk(sh.cssRules); } catch (e) { names.add("__unreadable_sheet__"); } }
  const STILL = new Set(["offset", "easing", "composite", "computedOffset", "opacity", "color", "backgroundColor", "borderColor",
                         "boxShadow", "filter", "fill", "stroke", "visibility"]);
  const moving = [];
  for (const n of names) {
    if (n === "__unreadable_sheet__") { moving.push(n); continue; }
    const el = document.createElement("div");
    el.style.animation = `${n} 1s linear paused`;
    document.body.appendChild(el);
    const a = el.getAnimations()[0];
    const kf = a ? a.effect.getKeyframes() : [];
    // 每一帧都写着、且取值都一样的属性不算移动（只为居中写的 translate(-50%) / 停住的 mask-position）。
    // 只写在一帧里的不行：另一端取元素自己的值，探针元素上是 none，真元素上不一定。
    const keys = new Set(kf.flatMap((f) => Object.keys(f)).filter((k) => !STILL.has(k)
      && !(kf.length > 1 && kf.every((f) => f[k] != null && f[k] === kf[0][k]))));
    if (keys.size) moving.push(n + ":" + [...keys].join("/"));
    el.remove();
  }
  return { n: names.size, moving: moving.sort() };
}"""


def _up():
    try:
        urllib.request.urlopen(H + "/harness.html", timeout=2).read(1)
        return Path(CHROME).exists()
    except Exception:
        return False


def _strip_css_comments(s):
    return re.sub(r"/\*.*?\*/", "", s, flags=re.S)


def _keyframes(css):
    """[(name, body, in_reduce_block, offset)]，按出现顺序。手写括号配对，不靠正则吃嵌套。"""
    out, i, depth, reduce_until = [], 0, 0, -1
    css = _strip_css_comments(css)
    for m in re.finditer(r"@media[^{]*prefers-reduced-motion:\s*reduce[^{]*\{|@keyframes\s+([\w-]+)\s*\{", css):
        start = m.end()
        d, j = 1, start
        while d and j < len(css):
            d += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        if m.group(0).startswith("@media"):
            reduce_until = max(reduce_until, j)
        else:
            out.append((m.group(1), css[start:j - 1], m.start() < reduce_until, m.start()))
    return out


MOVING_KF = re.compile(r"transform|translate|scale\(|rotate|clip-path|position|inset")
STILL_PROPS = {"opacity", "color", "background-color", "border-color", "box-shadow", "filter", "fill", "stroke", "visibility"}


def _still(body):
    """减弱版关键帧是否「不动」：除颜色 / 透明度类外，每个属性都必须在每一帧里写着、且取值相同。"""
    frames = re.findall(r"([^{}]+)\{([^{}]*)\}", body)
    # `0%, 100% { … }` 是两帧
    decl = [dict((k.strip(), v.strip()) for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+)", d))
            for sel, d in frames for _ in sel.split(",")]
    keys = {k for d in decl for k in d} - STILL_PROPS
    return all(len(decl) > 1 and all(k in d for d in decl) and len({d[k] for d in decl}) == 1 for k in keys) \
        or (not keys)


class EveryMovingKeyframeHasAStillTwinInItsOwnFile(unittest.TestCase):
    """★ 源码闸：移动类关键帧必须在**同一个文件**、**更靠后**的减弱块里有同名版本。
    跨文件放不行 —— bundle 里共享块排在入口块之前（实测 reducedMotion.css 排第一），后来的原版会把它盖掉。"""

    def test_twins(self):
        files = sorted(SRC.rglob("*.css"))
        self.assertGreater(len(files), 5)
        missing, seen = [], 0
        for f in files:
            kfs = _keyframes(f.read_text(encoding="utf-8"))
            for name, body, red, at in kfs:
                if red or _still(body):   # 原版本来就不动（如 cbNvTipFade / 只呼吸透明度）；stroke-dashoffset 之类也要有静止版
                    continue
                seen += 1
                if not any(n == name and r and a > at and _still(b) for n, b, r, a in kfs):
                    missing.append(f"{f.relative_to(SRC)}::{name}")
        self.assertGreater(seen, 20, "只找到很少的移动类关键帧 —— 解析器坏了")
        self.assertEqual(missing, [], "★ 这些关键帧在减弱动态效果下仍会移动")

    def test_still_judge(self):
        self.assertTrue(_still(" from { opacity: 0; } "))
        self.assertTrue(_still(" from { opacity: 0; transform: translateX(-50%); } to { opacity: 1; transform: translateX(-50%); } "))
        self.assertFalse(_still(" from { opacity: 0; transform: translateX(-50%); } "), "只写一端的 transform 另一端取元素自身值 —— 不算静止")
        self.assertFalse(_still(" from { transform: translateY(4px); } to { transform: none; } "))
        self.assertTrue(_still(" 0%, 100% { mask-position: 0 0; } "))

    def test_the_parser_sees_a_reduce_block(self):
        got = _keyframes("@keyframes a { to { transform: none; } }\n@media (prefers-reduced-motion: reduce) { @keyframes a { from { opacity: 0; } } }")
        self.assertEqual([(n, r) for n, _, r, _ in got], [("a", False), ("a", True)])


class AccordionDoesNotAnimateRowHeight(unittest.TestCase):
    """P99 性能规矩「不做 grid-rows 类布局动画」：总览「已停用」折叠的行高一步到位，只有内容动。"""

    def test_fold_rules(self):
        css = _strip_css_comments((SRC / "components" / "ov" / "overview.css").read_text(encoding="utf-8"))
        rules = dict(re.findall(r"(\.ov-fold(?:\[data-open=\"1\"\])?)\s*\{([^}]*)\}", css))
        self.assertIn("grid-template-rows 0s", rules[".ov-fold"], "收起：行高在内容淡出之后一步收起")
        self.assertIn("transition: none", rules['.ov-fold[data-open="1"]'], "展开：行高一步到位")
        self.assertNotRegex(css, r"grid-template-rows\s+[1-9]\d*m?s", "★ 行高又在做动画")
        grid = dict(re.findall(r"(\.ov-fold(?:\[data-open=\"1\"\])? \.ov-fold-grid)\s*\{([^}]*)\}", css))
        self.assertIn("320ms", grid['.ov-fold[data-open="1"] .ov-fold-grid'])
        self.assertIn("240ms", grid[".ov-fold .ov-fold-grid"])
        tsx = (SRC / "components" / "ov" / "OvStrip.tsx").read_text(encoding="utf-8")
        self.assertNotIn('"gap 420ms', tsx)


class ShimmerIsWired(unittest.TestCase):
    def test_busy_labels_use_it(self):
        for f, n in (("pages/SettingsPage.tsx", 2), ("components/ConnectorPanel.tsx", 5)):   # 2026-10-24 +1：「重装服务…」
            with self.subTest(f=f):
                code = re.sub(r"\{/\*.*?\*/\}|/\*.*?\*/|//[^\n]*", "", (SRC / f).read_text(encoding="utf-8"), flags=re.S)
                self.assertEqual(len(re.findall(r"<ShimText text=", code)), n)


@unittest.skipUnless(_up(), "harness 3304 没起 —— skip 不是绿")
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

    def _eval(self, page, js, motion):
        ctx = self.br.new_context(viewport={"width": 1200, "height": 860}, reduced_motion=motion)
        self.addCleanup(ctx.close)
        pg = ctx.new_page()
        pg.goto(f"{H}/{PAGES[page]}", timeout=30000)
        pg.wait_for_timeout(1800)
        return pg.evaluate(js)

    def test_known_positive_without_reduce(self):
        """探针自检：不减弱时，同一组探针必须看得到移动类过渡和关键帧。"""
        t = self._eval("menubar", TRANSITIONS, "no-preference")
        k = self._eval("home", KEYFRAMES, "no-preference")
        self.assertGreater(len(t["bad"]), 3, t)
        self.assertGreater(len(k["moving"]), 10, k)

    def test_reduced_motion_leaves_only_fades(self):
        for page in PAGES:
            with self.subTest(page=page):
                t = self._eval(page, TRANSITIONS, "reduce")
                self.assertGreater(t["nodes"], 20, f"{page} 几乎没渲染")
                self.assertEqual(t["bad"], [], f"★ {page}：减弱动态效果下仍有位移 / 尺寸过渡")
                k = self._eval(page, KEYFRAMES, "reduce")
                if page != "tpshover":           # 悬停面板全靠内联过渡，没有关键帧
                    self.assertGreater(k["n"], 0)
                self.assertEqual(k["moving"], [], f"★ {page}：减弱动态效果下这些关键帧实际生效的版本仍会动")

    # ── 真选择器上的行为（评审 P7-codex-4：只挂关键帧名的探针看不到 `.ov-swl { animation: none !important }` 这类规则）──

    REAL = r"""(specs) => specs.map(([wrap, cls]) => {
      const host = document.querySelector(wrap) || document.body;
      const el = document.createElement("span");
      el.className = cls; el.textContent = "x"; el.dataset.t = "x"; el.dataset.open = "1";   // `.ov-cmenu:not([data-open])` 是 display:none
      host.appendChild(el);
      const cs = getComputedStyle(el), after = getComputedStyle(el, "::after");
      const anims = el.getAnimations();
      const kf = anims.flatMap((a) => a.effect.getKeyframes());
      const moving = [...new Set(kf.flatMap((f) => Object.keys(f)))].filter((k) => !["offset", "easing", "composite", "computedOffset", "opacity"].includes(k)
        && !kf.every((f) => f[k] != null && f[k] === kf[0][k]));
      const r = { cls, name: cs.animationName, n: anims.length, moving, mask: cs.webkitMaskImage || cs.maskImage || "none", op: cs.opacity, after: after.animationName };
      el.remove();
      return r;
    })"""

    SWAPS = [[".ov-root", "ov-swl ov-sw-out-a"], [".ov-root", "ov-swl ov-sw-in-b"], [".ov-root", "ov-tp"], [".ov-root", "ov-cmenu"]]

    def test_fades_survive_reduce(self):
        """★ 减弱动态效果要「只剩淡入淡出」，不是「全瞬切」：已知的淡入淡出在减弱下仍要有时长（评审 P7-gemini-1/3：
        改写属性列表后时长按下标配对，`transform 0ms, opacity 240ms` 的 opacity 会配到 0ms）。"""
        js = r"""(sel) => { const el = document.querySelector(sel); if (!el) return null; const cs = getComputedStyle(el);
            const ps = cs.transitionProperty.split(",").map((x) => x.trim()), ds = cs.transitionDuration.split(",").map((x) => parseFloat(x) * (x.trim().endsWith("ms") ? 1 : 1000));
            const i = ps.indexOf("opacity"); return i < 0 ? -1 : ds[i % ds.length]; }"""
        for page, q, sel in (("menubar", "harness-menubar.html", ".qrow .sw2"),
                             ("home", "harness.html?nav=home&ovplat=codex&ovdead=1", ".ov-fold .ov-fold-grid"),
                             ("tpshover", "harness-tpshover.html", "[data-idle-panel]")):
            with self.subTest(page=page):
                ctx = self.br.new_context(viewport={"width": 1200, "height": 860}, reduced_motion="reduce")
                self.addCleanup(ctx.close)
                pg = ctx.new_page(); pg.goto(f"{H}/{q}", timeout=30000); pg.wait_for_timeout(1500)
                d = pg.evaluate(js, sel)
                # 同一页再放一个「`transform 0ms, opacity 240ms`」的元素（悬停面板 `.hv-chev` 在减弱下就是这么拼的），走真实层叠
                d2 = pg.evaluate("""(js) => { const el = document.createElement("i"); el.className = "__probe";
                    el.style.transition = "transform 0ms, opacity 240ms"; document.body.appendChild(el);
                    const r = (0, eval)("(" + js + ")")(".__probe"); el.remove(); return r; }""", js)
                self.assertGreater(d2, 0, "★ 多段过渡里 opacity 配到了 transform 的 0ms")
                self.assertIsNotNone(d, f"{sel} 没渲染 —— 判不了")
                self.assertGreater(d, 0, f"★ {sel} 的淡入淡出在减弱模式下被清零了")

    def test_swap_text_still_fades_under_reduce(self):
        """★ 换字：新旧两层必须一出一进（只剩透明度），不许被 `animation: none` 定成两层都可见。"""
        ctx = self.br.new_context(viewport={"width": 1200, "height": 860}, reduced_motion="reduce")
        self.addCleanup(ctx.close)
        pg = ctx.new_page(); pg.goto(f"{H}/{PAGES['home']}", timeout=30000); pg.wait_for_selector(".ov-root", timeout=15000)
        for r in pg.evaluate(self.REAL, self.SWAPS):
            with self.subTest(cls=r["cls"]):
                self.assertNotEqual(r["name"], "none", "★ 减弱模式下这条动画被整条关掉了")
                self.assertGreater(r["n"], 0)
                self.assertEqual(r["moving"], [], "减弱模式下仍在移动")

    def test_shimmer_never_dims_the_text(self):
        ctx = self.br.new_context(viewport={"width": 1200, "height": 860})
        self.addCleanup(ctx.close)
        pg = ctx.new_page(); pg.goto(f"{H}/{PAGES['settings']}", timeout=30000); pg.wait_for_selector("[data-set-group]", timeout=15000)
        r = pg.evaluate(self.REAL, [["[data-set-group]", "cb-shim-text"]])[0]
        self.assertEqual((r["mask"], r["op"]), ("none", "1"), "★ 流光不许压暗底层文字（浅色琥珀字会掉到 1.8:1）")
        self.assertEqual(r["after"], "cbShimText", "流光层没挂上")

    def test_cmd_rules_tabs_stay_and_the_pill_slides(self):
        ctx = self.br.new_context(viewport={"width": 1200, "height": 1400})
        self.addCleanup(ctx.close)
        pg = ctx.new_page(); pg.goto(f"{H}/harness.html?nav=settings&notrans=1", timeout=30000); pg.wait_for_selector("[data-cmd-rules]", timeout=15000)
        pg.click("[data-cmd-rules]"); pg.wait_for_timeout(300)
        state = """() => { const sel = document.querySelector('[data-cmd-tab][aria-selected=true]'), p = document.querySelector('[data-cmd-pill]');
            const a = p.getBoundingClientRect(), b = sel.getBoundingClientRect();
            return { off: Math.abs(a.left - b.left) + Math.abs(a.width - b.width), body: document.querySelector('[data-cmd-body]').className,
                     tabsAnim: getComputedStyle(document.querySelector('[role=tablist]').parentElement).animationName }; }"""
        a = pg.evaluate(state)
        pg.click("[data-cmd-tab=agy]"); pg.wait_for_timeout(350)
        b = pg.evaluate(state)
        self.assertLess(a["off"], 1.5); self.assertLess(b["off"], 1.5, "★ 选中块没滑到新签下面")
        self.assertNotEqual(a["body"], b["body"], "★ 切签没换 A/B ⇒ 正文不重播")
        self.assertEqual(b["tabsAnim"], "none", "★ 签条跟着正文一起重播（刚点的签会闪一下）")
