"""总览打开落在哪一档（用户 2026-10-24「为什么默认还是跳到 gemini 的页面？超过 1 分钟后也是」）。

规则（同菜单栏弹窗 10-22 那条「关掉 1 分钟内重开保持，超过 1 分钟回默认」）：
1. 入口点名了平台（托盘右键 / 账号行 / 额度格子）⇒ 用它；
2. 没点名：新的一次打开（冷启动、隐藏 ≥ 1 分钟）⇒ Codex；1 分钟内重开 ⇒ 保持；
3. 档只在这一次运行里记（sessionStorage）—— 老版本 localStorage 里存的 `gemini` 不再生效。

四方评审 2026-10-24（4/4）：原来档存 localStorage 跨启动永远记住，没点名平台的入口（Dock、刘海「总览 →」）
一律停在上次那档；1 分钟那条只在菜单栏弹窗里实现过。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import re
import subprocess
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "codexbar" / "src"
LIB = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HARNESS = "http://127.0.0.1:3304/harness.html"


def node(expr):
    js = "import('%s').then(m => console.log(JSON.stringify(%s)))" % ((SRC / "platforms.ts").as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def rs_code():
    return re.sub(r"(?m)^\s*//[^\n]*\n", "", LIB.read_text(encoding="utf-8"))


class TheRule(unittest.TestCase):
    def test_truth_table(self):
        got = node("[m.landingProvider('gemini', null, true), m.landingProvider('gemini', null, false),"
                   " m.landingProvider('codex', 'gemini', true), m.landingProvider('grok', 'claude', false)]")
        self.assertEqual(got, ["codex", "gemini", "gemini", "claude"],
                         "没点名：新的一次打开回 Codex、1 分钟内保持；点名的永远优先")

    def test_the_tab_is_remembered_only_for_this_run(self):
        src = re.sub(r"//[^\n]*", "", (SRC / "platforms.ts").read_text(encoding="utf-8"))
        body = src[src.index("export function loadPoolKey"):src.index("export const DEFAULT_POOL_KEY")]
        self.assertIn("sessionStorage.getItem(STORE_KEY)", body)
        self.assertIn("sessionStorage.setItem(STORE_KEY, k)", body)
        self.assertNotIn("localStorage", body, "★ 跨启动记住 = 重启后永远回到上次那档")


class TheRustSideSaysWhenAnOpenIsNew(unittest.TestCase):
    def setUp(self):
        self.rs = rs_code()

    def test_the_forwarder_judges_before_it_shows(self):
        i = self.rs.index('handle.listen_any("open-main-page"')
        body = self.rs[i:i + 1200]
        self.assertLess(body.index('o.insert("fresh".into(), Value::Bool(main_fresh(&h3)))'), body.index("w.show()"),
                        "★ 必须先判再显示 —— 显示之后窗口就可见了，永远判成「不是新的一次打开」")

    def test_every_hide_is_recorded_and_every_bare_show_reports(self):
        self.assertGreaterEqual(self.rs.count("mark_main_hidden();"), 3, "隐藏的三条路：关窗按钮 / set_main_visible(false) / ⌘Q")
        cr = self.rs[self.rs.index("WindowEvent::CloseRequested { api, .. } = event"):][:400]
        self.assertIn("mark_main_hidden();", cr)
        smv = self.rs[self.rs.index("fn set_main_visible("):][:400]
        self.assertIn("show_main(&app);", smv)
        self.assertIn("mark_main_hidden();", smv)
        ro = self.rs[self.rs.index("RunEvent::Reopen { .. } = event"):][:200]
        self.assertIn("show_main(app);", ro, "Dock 点图标也是一次打开")
        sm = self.rs[self.rs.index("fn show_main("):][:500]
        self.assertLess(sm.index("let fresh = main_fresh(app);"), sm.index("w.show()"))
        self.assertIn('"page": null, "fresh": true', sm)


PROBE = """() => ({ active: [...document.querySelectorAll('[data-provtab]')].filter(e => e.dataset.active === '1').map(e => e.dataset.provtab),
                 saved: sessionStorage.getItem('codexbar_provider') })"""


def _drive(init, events):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    out = []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        ctx = br.new_context(viewport={"width": 1200, "height": 800})
        if init:
            ctx.add_init_script(init)
        pg = ctx.new_page()
        pg.goto(HARNESS + "?nav=home", timeout=30000)
        pg.wait_for_timeout(2000)
        out.append(pg.evaluate(PROBE))
        for ev in events:
            pg.evaluate("(p) => window.__harnessFire('main-open-page', p)", ev)
            pg.wait_for_timeout(300)
            out.append(pg.evaluate(PROBE))
        br.close()
    return out


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class OnTheRealBundle(unittest.TestCase):
    def _get(self, init, events):
        r = _drive(init, events)
        if r is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        return r

    def test_an_old_saved_gemini_no_longer_wins_a_cold_start(self):
        s = self._get("localStorage.setItem('codexbar_provider', 'gemini')", [])
        self.assertEqual(s[0]["active"], ["codex"], "★★ 老版本存的 gemini 让每次启动都回 Gemini")

    def test_unnamed_opens_follow_freshness_and_named_ones_win(self):
        s = self._get("sessionStorage.setItem('codexbar_provider', 'gemini')", [
            {"page": "overview", "platform": None, "fresh": False},
            {"page": "overview", "platform": None, "fresh": True},
            {"page": "overview", "platform": "agy", "fresh": True},
            {"page": None, "fresh": True},
            {"page": "overview", "platform": "grok", "fresh": False},
            {"page": None, "fresh": False},
        ])
        self.assertEqual(s[0]["active"], ["gemini"], "前提：这次运行里停在 Gemini")
        self.assertEqual([x["active"] for x in s[1:]], [["gemini"], ["codex"], ["gemini"], ["codex"], ["grok"], ["grok"]],
                         "1 分钟内没点名 ⇒ 保持 · 新的一次没点名 ⇒ Codex · 点名 agy ⇒ Gemini · 只显示窗口且是新的 ⇒ Codex · "
                         "点名 grok ⇒ Grok · 只显示窗口且不是新的 ⇒ 不动")
        self.assertEqual(s[-1]["saved"], "grok", "这次运行里仍记住当前档")


if __name__ == "__main__":
    unittest.main()
