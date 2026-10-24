"""总览自动排序不冻结在上一会话的种子板子上（samchen #4 ③）。

冷启动第一帧的 `board` 是 localStorage 里上一会话的（`useRotationBoard` 的种子），「下一个」可能早就不是它了；
`freeze()` 原来照它冻住顺序，窗口一直有焦点就一直错着。

做法（Gemini 档 —— 那里卡片状态的冷却 / 失效来自板子；codex 档的状态全来自现读的 state，种子影响不到顺序）：
种一份「其余区第二张在冷却」的旧板子，把真读延迟 1.5 s；真读回来后，其余区的顺序必须跟真板子走。
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
URL = "http://127.0.0.1:3304/harness.html?nav=home&ovplat=gemini&agypool=5&agyrotoff=0"

# 先跑一次拿到真板子，再把它改成「下一个 = 别人」当种子；真读延迟 1.5 s。
TRAP = """(seed) => {
  if (seed) localStorage.setItem('aicoop_board_agy', JSON.stringify(seed));
  let inner;
  Object.defineProperty(window, '__TAURI_INTERNALS__', { configurable: true, get() { return inner; },
    set(v) { const orig = v.invoke.bind(v);
      v.invoke = async (c, a, o) => {
        if (c === 'read_agy_board' && seed) await new Promise((r) => setTimeout(r, 1500));
        return orig(c, a, o); };
      inner = v; } }); }"""

REST = """() => [...document.querySelectorAll('[data-ov-card]:not([data-ov-pinned])')].map(e => e.getAttribute('data-aid'))"""


def _run(seed_from=None):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(URL, timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        pg = br.new_page(viewport={"width": 1200, "height": 800})
        pg.add_init_script(script=f"({TRAP})({json.dumps(seed_from)})")
        pg.goto(URL, timeout=30000)
        pg.wait_for_timeout(600)
        early = pg.evaluate(REST)
        pg.wait_for_timeout(2600)
        late = pg.evaluate(REST)
        board = pg.evaluate("() => localStorage.getItem('aicoop_board_agy')")
        br.close()
    return early, late, json.loads(board) if board else None


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheOrderFollowsTheLiveBoard(unittest.TestCase):
    def test_a_stale_seed_does_not_freeze_the_order(self):
        base = _run()
        if base is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        _, truth, board = base
        self.assertGreaterEqual(len(truth), 3, "★ 前提：其余区至少 3 张")
        self.assertTrue(board, "★ 前提：真板子写进了 localStorage")
        stale = json.loads(json.dumps(board))
        ents = [e for e in (stale.get("queue") or []) + (stale.get("rest") or []) if e.get("aid") == truth[1]]
        self.assertTrue(ents, "★ 前提：板子里有其余区第二张（第一张多半是在用的，冷却改不动它的位置）")
        for e in ents:
            e["cool_min"] = 90                                   # 种子说它在冷却 ⇒ 排到后面
        early, late, _ = _run(stale)
        self.assertNotEqual(early, truth, "★ 前提：种子确实让第一帧排成了另一个样子")
        self.assertEqual(late, truth, f"★★ 真板子回来了，顺序仍冻在种子上：{late} ≠ {truth}")


if __name__ == "__main__":
    unittest.main()
