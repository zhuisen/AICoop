"""设置页「数据源状态」块（B85 · 用户 2026-10-16 选的 A）—— 真 bundle 端到端。

## 守的
1. 快照带 `scan.sources` 且有问题 ⇒ 块渲染出来，少算的是 warn（琥珀）、没找到的是 info，warn 在前，
   文案就是 `scanHealth.ts::sourceNotes` 的原话（codex 没解压器那条带 `brew install zstd`）。
2. 全部正常 ⇒ 只有一行「N 个源全部正常」，没有任何 note。
3. 旧快照没有 `sources` ⇒ 整块不画 —— **读不到 ≠ 没问题**，绝不说「全部正常」。

快照经 init script 拦 `read_traffic_snapshot` 替换 `scan.sources`，不改 harness 的内联快照。
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

PROBLEMS = {
    "openclaw": {"state": "not_found", "name": "OpenClaw", "root": "~/.openclaw/agents", "files": 0},
    "codex": {"state": "read_failed", "name": "Codex", "root": "~/.codex/sessions", "files": 1712,
              "read_failed": 1675, "no_decoder": 1675, "unparsed": {}},
    "claude": {"state": "ok", "name": "Claude", "root": "~/.claude/projects", "files": 10,
               "read_failed": 0, "no_decoder": 0, "unparsed": {}},
}
HEALTHY = {"claude": PROBLEMS["claude"],
           "kimi": dict(PROBLEMS["claude"], name="Kimi", root="~/.kimi-code/sessions"),
           "agy": {"state": "disabled", "name": "Antigravity", "root": "~/.gemini"}}

#: `__TAURI_INTERNALS__` 由 harness.html 在 bundle 之前赋值；用 setter 截住它，包一层 invoke。
TRAP = """(sources) => {
  let inner;
  Object.defineProperty(window, '__TAURI_INTERNALS__', { configurable: true,
    get() { return inner; },
    set(v) { const orig = v.invoke.bind(v);
      v.invoke = async (c, a, o) => { const r = await orig(c, a, o);
        if (c !== 'read_traffic_snapshot' || !r) return r;
        const d = JSON.parse(r);
        if (sources === null) delete d.scan.sources; else d.scan.sources = sources;
        return JSON.stringify(d); };
      inner = v; } });
}"""
PROBE = """() => { const b = document.querySelector('[data-source-status]');
  if (!b) return null;
  return { head: b.firstElementChild.textContent,
           notes: [...b.querySelectorAll('[data-source-note]')].map(e => [e.dataset.sourceNote, e.textContent,
                    getComputedStyle(e).color]) }; }"""


def _render(sources):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return "skip"
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        ctx = br.new_context(viewport={"width": 1200, "height": 800})
        ctx.add_init_script(script=f"({TRAP})({json.dumps(sources, ensure_ascii=False)})")
        pg = ctx.new_page()
        pg.goto(HARNESS, timeout=30000)
        pg.wait_for_timeout(2200)
        mounted = pg.evaluate("document.body.innerText.includes('扫描新数据源')")
        out = pg.evaluate(PROBE)
        br.close()
    return mounted, out


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheSettingsPageSaysWhatTheScanSaw(unittest.TestCase):
    def _get(self, sources):
        r = _render(sources)
        if r == "skip":
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        mounted, out = r
        self.assertTrue(mounted, "★ 前提：设置页真的渲染了（「扫描新数据源」在页面上）")
        return out

    def test_problems_are_listed_warn_first(self):
        out = self._get(PROBLEMS)
        self.assertIsNotNone(out, "★★ 有问题却没画「数据源状态」")
        levels = [n[0] for n in out["notes"]]
        self.assertEqual(levels, ["warn", "info"], out)
        self.assertIn("未计入 1675 个压缩会话", out["notes"][0][1])
        self.assertIn("brew install zstd", out["notes"][0][1])
        self.assertIn("rgb(224, 144, 28)", out["notes"][0][2], "★ 少算了要是琥珀")
        self.assertNotIn("rgb(224, 144, 28)", out["notes"][1][2], "★ 没装 OpenClaw 不该是告警色")
        self.assertIn("~/.openclaw/agents", out["notes"][1][1])

    def test_all_healthy_is_one_quiet_line(self):
        out = self._get(HEALTHY)
        self.assertIsNotNone(out)
        self.assertEqual(out["notes"], [])
        self.assertIn("2 个源全部正常", out["head"], "★ 停用的不算进「正常」的个数")

    def test_an_old_snapshot_draws_nothing(self):
        self.assertIsNone(self._get(None), "★★ 没有 sources 字段却说了话 —— 读不到 ≠ 没问题")


if __name__ == "__main__":
    unittest.main()
