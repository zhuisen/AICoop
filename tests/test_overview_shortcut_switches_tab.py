"""总览上 ⌘1~⌘4 切 Codex / Claude / Gemini / Grok 档（2026-10-19 交接包 page5 加了 Claude 档，顺序跟光晕），**不切号**（用户 2026-10-16：
「在总览界面 command+数字，是切换 codex、gemini、grok，而不是切换对应的账号」）。

取代 2026-09-14 / 09-19 的「⌘N 切第 N 张卡」。原来那条在**任何页面**都会切 codex 号 ——
看不见、却在换正在计费的账号。

## 守的
1. 纯函数 `platforms.ts::poolKeyAt`：序号 = Tab 显示顺序（从 `POOL_PLATFORMS` 推，不手抄），
   越界 / 负数 / 非整数都是 `undefined`。
2. 接线：`useKeyboard` 的回调只认总览、只调 `setProvider`，不碰任何切号路径。
3. 卡片上不再画 `⌘N` 角标（承诺随行为一起撤）。
4. 真 bundle 端到端：总览按 ⌘2 → Gemini 档、⌘3 → Grok、⌘1 → Codex；⌘4 不动；
   设置页按 ⌘2 不改档；全程**零**切号调用。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import re
import shutil
import subprocess
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
PLATFORMS = SRC / "platforms.ts"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HARNESS = "http://127.0.0.1:3304/harness.html"


def _strip(src):
    """剥 `//` 行尾/整行注释、`/* */` 与 JSX `{/* */}` —— 断言只打在代码上。"""
    src = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", l) for l in src.splitlines())


def _node(expr):
    script = "import('file://%s').then(m => console.log(JSON.stringify(%s)));" % (PLATFORMS.as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip().startswith(("[", "{"))]
    if not out:
        raise AssertionError(f"node 没有产出：{r.stderr[-500:]}")
    return json.loads(out[-1])


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class TheIndexMapsToTheTabOrder(unittest.TestCase):
    def test_each_index_is_the_tab_at_that_position(self):
        got = _node("{ keys: m.POOL_PLATFORMS.map(p => p.key),"
                    "  at: [0,1,2,3,4,8,-1,1.5].map(i => m.poolKeyAt(i) ?? null) }")
        self.assertEqual(got["keys"], ["codex", "claude", "gemini", "grok"], f"夹具前提：四档、顺序同光晕 {got['keys']}")
        self.assertEqual(got["at"][:4], got["keys"], "★★ ⌘N 与 Tab 显示顺序不一致")
        self.assertEqual(got["at"][4:], [None] * 4, "★ 越界 / 负数 / 非整数必须什么也不做")


class TheHandlerOnlySwitchesTabs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = _strip((SRC / "App.tsx").read_text(encoding="utf-8"))
        i = c.index("useKeyboard(win, refresh")
        cls.seg = c[i:c.index("\n  });", i)]

    def test_it_switches_the_tab(self):
        self.assertIn("poolKeyAt(idx)", self.seg, "★★ ⌘N 没有按 Tab 顺序取档")
        self.assertRegex(self.seg, r"setProvider\(\s*k\s*\)", "★★ 取到了档却没切过去")

    def test_only_on_the_overview(self):
        self.assertIn('page !== "overview"', self.seg, "★ 别的页面没有档位 Tab，⌘N 不该有作用")

    def test_it_never_switches_an_account(self):
        for bad in ("run(", "switchTo(", "orderedAlive", "orderedAgy", '"switch"'):
            with self.subTest(bad=bad):
                self.assertNotIn(bad, self.seg, f"★★★ ⌘N 又在切号（{bad}）")


class TheCardsDropTheBadge(unittest.TestCase):
    def test_no_shortcut_badge_on_any_card(self):
        for f in ("components/AccountCard.tsx", "components/AgyCard.tsx", "components/GrokCard.tsx"):
            with self.subTest(f=f):
                self.assertNotIn("⌘${", _strip((SRC / f).read_text(encoding="utf-8")),
                                 "★★ 卡上还画着 ⌘N —— 按它切的已经不是这张卡")
        self.assertNotIn("shortcut=", _strip((SRC / "App.tsx").read_text(encoding="utf-8")))

    def test_the_tabs_say_which_key(self):
        # 2026-10-19：平台档从 ProviderTabs 换成 `ov/OvHeader::OvTabs`；Overview 按 `POOL_PLATFORMS` 的顺序传档。
        c = _strip((SRC / "components" / "ov" / "OvHeader.tsx").read_text(encoding="utf-8"))
        self.assertIn(' · ⌘${i + 1}`}', c, "★ Tab 的悬浮提示没写快捷键")
        self.assertIn("{tabs.map((tb, i) => {", c, "★ 序号不是档在列表里的位置")
        ov = _strip((SRC / "components" / "ov" / "Overview.tsx").read_text(encoding="utf-8"))
        self.assertIn("const TAB_ORDER: PoolKey[] = POOL_PLATFORMS.map((p) => p.key);", ov, "★★ 档的顺序不从 POOL_PLATFORMS 推 —— ⌘N 会对不上")


PROBE_ACTIVE = """() => { const on = [...document.querySelectorAll('[data-provtab]')]
  .filter(e => e.dataset.active === '1');
  return { active: on.map(e => e.dataset.provtab), n: document.querySelectorAll('[data-provtab]').length,
           saved: localStorage.getItem('codexbar_provider') }; }"""
WRAP = """() => { const T = window.__TAURI_INTERNALS__; const orig = T.invoke.bind(T); window.__calls = [];
  T.invoke = (c, a, o) => { window.__calls.push([c, JSON.stringify(a ?? null)]); return orig(c, a, o); }; }"""


def _drive(nav, keys):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    states = []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        ctx = br.new_context(viewport={"width": 1200, "height": 800})
        ctx.add_init_script("localStorage.setItem('codexbar_provider', 'codex')")
        pg = ctx.new_page()
        pg.goto(f"{HARNESS}?nav={nav}", timeout=30000)
        pg.wait_for_timeout(2200)
        pg.evaluate(WRAP)
        states.append(pg.evaluate(PROBE_ACTIVE))
        for k in keys:
            pg.keyboard.press(f"Meta+{k}")
            pg.wait_for_timeout(300)
            states.append(pg.evaluate(PROBE_ACTIVE))
        calls = pg.evaluate("window.__calls")
        br.close()
    return states, calls


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class EndToEndInTheRealBundle(unittest.TestCase):
    def test_overview(self):
        r = _drive("home", ["2", "3", "4", "5", "1"])
        if r is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        states, calls = r
        self.assertEqual(states[0]["n"], 4, f"夹具前提：Tab 渲染出来了 {states[0]}")
        self.assertEqual(states[0]["active"], ["codex"], f"起点不是 Codex：{states[0]}")
        got = [s["active"] for s in states[1:]]
        self.assertEqual(got, [["claude"], ["gemini"], ["grok"], ["grok"], ["codex"]],
                         f"★★ ⌘2/⌘3/⌘4/⌘5/⌘1 之后的档：{got}")
        self.assertEqual(states[-1]["saved"], "codex", "切档没记住")
        sw = [c for c in calls if '"switch"' in c[1] or "switch" in c[0]]
        self.assertEqual(sw, [], f"★★★ 按 ⌘N 触发了切号：{sw}")

    def test_other_pages_ignore_it(self):
        r = _drive("settings", ["2"])
        if r is None:
            self.skipTest("harness 3304 没起")
        states, calls = r
        self.assertEqual(states[-1]["saved"], "codex", "★ 设置页按 ⌘2 改了档")
        self.assertEqual([c for c in calls if '"switch"' in c[1]], [], "★★★ 设置页按 ⌘N 切了号")


if __name__ == "__main__":
    unittest.main()
