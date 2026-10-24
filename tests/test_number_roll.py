"""设置「数字滚动」（用户 2026-10-24「数字动效也没了，需要新增，并在设置处理」→ 单独新开关，放在入场动效下面）。

四方评审 2026-10-24（4/4）：v2.0.0 消耗页重写（`1f12bb3`）把 `useIntro` → `KpiStrip intro` 的 0→实际值滚动删了，
新的 `KpiGrid` 只画终值字符串；「入场动效」的说明仍写着「数字滚动」，而没有一条测试断言过数字会滚 —— 所以丢了没人发现。

守的：
1. 开着时，消耗页 KPI 的第一份有数的画面**不是终值**，且最后落在终值（滚动不改最终数字）；
2. 关掉时，第一份有数的画面就是终值；
3. 设置行在「入场动效」下面、调 Rust `set_number_roll`；App 启动重发；Rust 关掉时在跑胶囊的数字直接换。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import re
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "codexbar" / "src"
RS = ROOT / "codexbar" / "src-tauri" / "src"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HARNESS = "http://127.0.0.1:3304/harness.html?nav=traffic"

# harness 每次加载都会重写 `codexbar_settings`，用 setter 把要测的那一项并进去（同 test_settings_toggles.py）
TRAP = """(seed) => {
  const origSet = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) {
    if (k === 'codexbar_settings' && seed) { try { v = JSON.stringify(Object.assign(JSON.parse(v), seed)); } catch (e) {} }
    return origSet.call(this, k, v);
  };
}"""


def code(p):
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"\{/\*[\s\S]*?\*/\}", "", s)
    return re.sub(r"(?<![:/\"'])//[^\n]*", "", s)


def _frames(seed):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    seen = []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        ctx = br.new_context(viewport={"width": 1200, "height": 800})
        ctx.add_init_script(script=f"({TRAP})({json.dumps(seed)})")
        pg = ctx.new_page()
        pg.goto(HARNESS, timeout=30000)
        for _ in range(60):
            v = pg.evaluate("() => [...document.querySelectorAll('[data-kpi-value]')].map(e => e.textContent)")
            if v and (not seen or seen[-1] != v):
                seen.append(v)
            pg.wait_for_timeout(40)
        br.close()
    # 骨架（全是「—」）不算「有数的画面」
    return [f for f in seen if any(x not in ("—", "") for x in f)]


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class OnTheRealBundle(unittest.TestCase):
    def _get(self, seed):
        r = _frames(seed)
        if r is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        self.assertTrue(r, "★ 前提：消耗页的 KPI 真的渲染出来了")
        return r

    def test_on_the_numbers_roll_up_and_land_on_the_real_value(self):
        f = self._get(None)
        self.assertGreaterEqual(len(f), 3, f"★★ 开着「数字滚动」却没有中间帧：{f[:3]}")
        self.assertNotEqual(f[0][0], f[-1][0], "第一份有数的画面已经是终值 = 没滚")
        off = self._get({"numberRoll": False})
        self.assertEqual(f[-1], off[-1], "★ 滚完的数字必须与不滚时完全相同")

    def test_off_shows_the_final_value_at_once(self):
        f = self._get({"numberRoll": False})
        self.assertEqual(len(f), 1, f"关掉「数字滚动」仍有中间帧：{f[:3]}")


class TheSettingAndBothHalves(unittest.TestCase):
    def test_the_row_sits_under_intro_and_drives_rust(self):
        s = code(SRC / "pages" / "SettingsPage.tsx")
        i, j = s.index('label="入场动效"'), s.index('label="数字滚动"')
        self.assertLess(i, j, "放在入场动效下面")
        between = s[s.index("</OneLineRow>", i) + len("</OneLineRow>"):s.rindex("<OneLineRow", 0, j)]
        self.assertNotIn("<OneLineRow", between, "紧挨着入场动效那一行，中间没有别的行")
        row = s[j:s.index("</OneLineRow>", j)]
        self.assertIn("update({ numberRoll: next })", row)
        self.assertIn('invoke("set_number_roll", { on: next })', row)
        self.assertRegex(s[s.index("const DEFAULTS: Settings = {"):], r"\bnumberRoll:\s*true\b", "默认开")

    def test_app_resends_on_startup(self):
        app = code(SRC / "App.tsx")
        self.assertIn('invoke("set_number_roll", { on: st.numberRoll !== false })', app)

    def test_kpis_carry_numbers_and_the_grid_uses_the_progress(self):
        parts = code(SRC / "components" / "tk" / "TkParts.tsx")
        self.assertIn("k.n != null && k.fmt && roll >= 0 && roll < 1 ? k.fmt(k.n * roll) : k.value", parts)
        for page in ("TrafficPage.tsx", "PlatformPage.tsx"):
            pg = code(SRC / "pages" / page)
            self.assertIn("useNumberRoll(", pg, page)
            self.assertRegex(pg, r"<KpiGrid [^>]*roll=\{roll\}", page)

    def test_rust_switches_the_tray_roll(self):
        tp = code(RS / "tray_pill.rs")
        self.assertIn("let instant = r || !number_roll();", tp)
        self.assertIn("s.num.set(t, instant);", tp)
        self.assertIn("fn set_number_roll(on: bool)", code(RS / "lib.rs"))


if __name__ == "__main__":
    unittest.main()
