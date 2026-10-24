"""设置页「刘海屏版本」那一行（2026-10-19 前叫「刘海额度条」） —— 真 bundle 端到端（B87 · 四方评审 2026-10-17）。

## 守的
1. 没有刘海屏的 Mac（`notch_status` 回 `no_notch`）：行照样在、开关默认关，说明里写「这台 Mac 现在没有刘海屏」。
   ★ 用户的原话是「有些用户没有这个刘海屏需求」—— 默认关、不开就什么都不建；行不藏，是因为合盖的刘海机也读成没刘海。
2. 打开但没有刘海屏：开关变开，说明改成「现在没有检测到刘海屏…自动出现」—— 不许开关变绿、屏幕上什么都没有、也不说为什么。
3. Rust 报错：开关**拨回去**，说明里带上错误原文。原来是 `.catch(() => {})`，开关停在「开」。

IPC 经 init script 拦 `notch_status` / `set_notch_hud`，不改 harness 的内联快照、不碰 localStorage 以外的任何东西。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import unittest
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HARNESS = "http://127.0.0.1:3304/harness.html?nav=settings"

#: `__TAURI_INTERNALS__` 由 harness.html 在 bundle 之前赋值；用 setter 截住它，包一层 invoke。
TRAP = """(cfg) => {
  window.__notchCalls = [];
  let inner;
  Object.defineProperty(window, '__TAURI_INTERNALS__', { configurable: true,
    get() { return inner; },
    set(v) { const orig = v.invoke.bind(v);
      v.invoke = async (c, a, o) => {
        if (c === 'notch_status') return cfg.status;
        if (c === 'set_notch_hud') { window.__notchCalls.push(a);
          if (cfg.fail) throw new Error(cfg.fail);
          return a.on ? cfg.onReply : { active: false, reason: null }; }
        return orig(c, a, o); };
      inner = v; } });
}"""
PROBE = """() => { const t = document.querySelector('[data-notch-toggle]');
  if (!t) return null;
  const row = t.parentElement;
  const on = t.querySelector('[aria-pressed="true"]');
  return { desc: row.firstElementChild.textContent, knob: on ? on.dataset.segOpt : null,
           calls: window.__notchCalls }; }"""


def _run(cfg, click=False):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return "skip"
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        ctx = br.new_context(viewport={"width": 1200, "height": 900})
        ctx.add_init_script(script=f"({TRAP})({json.dumps(cfg, ensure_ascii=False)})")
        pg = ctx.new_page()
        pg.goto(HARNESS, timeout=30000)
        pg.wait_for_timeout(1800)
        before = pg.evaluate(PROBE)
        after = None
        if click and before:
            pg.click('[data-notch-toggle] [data-seg-opt="notch"]')
            pg.wait_for_timeout(500)
            after = pg.evaluate(PROBE)
        br.close()
    return before, after


NO_NOTCH = {"active": False, "reason": "no_notch"}
OFF_KNOB = "menubar"   # 2026-10-24 起是「显示位置」菜单栏 / 刘海屏二选一；刘海关 = 选菜单栏


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheNotchRowSaysWhatIsOnScreen(unittest.TestCase):
    def _get(self, cfg, click=False):
        r = _run(cfg, click)
        if r == "skip":
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        before, after = r
        self.assertIsNotNone(before, "★ 前提：设置页里真的有「显示位置」那一行")
        return before, after

    def test_a_mac_without_a_notch_sees_the_row_off_and_told_why(self):
        before, _ = self._get({"status": NO_NOTCH, "onReply": NO_NOTCH})
        self.assertEqual(before["knob"], OFF_KNOB, "★ 默认关（用户 2026-10-17 定）")
        self.assertIn("这台 Mac 现在没有刘海屏", before["desc"])
        self.assertEqual(before["calls"], [], "★ 只是打开设置页，不许替用户开")

    def test_turning_it_on_without_a_notch_says_nothing_will_show_yet(self):
        _, after = self._get({"status": NO_NOTCH, "onReply": NO_NOTCH}, click=True)
        self.assertEqual(after["calls"], [{"on": True}])
        self.assertNotEqual(after["knob"], OFF_KNOB, "开关记住了「开」")
        self.assertIn("没有检测到刘海屏", after["desc"], "★★ 开着却没显示，必须说出为什么")
        self.assertIn("自动出现", after["desc"])

    def test_an_error_rolls_the_toggle_back_and_shows_the_reason(self):
        _, after = self._get({"status": {"active": False, "reason": None}, "fail": "window build failed"}, click=True)
        self.assertEqual(after["calls"], [{"on": True}])
        self.assertEqual(after["knob"], OFF_KNOB, "★★ 失败要把开关拨回去 —— 原来 `.catch(() => {})` 让它停在「开」")
        self.assertIn("没能打开", after["desc"])
        self.assertIn("window build failed", after["desc"])


if __name__ == "__main__":
    unittest.main()
