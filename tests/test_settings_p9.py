"""AICoop P9（设置页 S1，阶段 6）：7 组单列、指令表对得上现行 CLI、预设档位不改老用户的值、全页一个 ⓘ。"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import re
import shutil
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
CMDS_TS = ROOT / "codexbar" / "src" / "settingsCmds.ts"
KIT_TS = ROOT / "codexbar" / "src" / "components" / "settings" / "SetKit.tsx"
HARNESS = "http://127.0.0.1:3304/harness.html?nav=settings&notrans=1"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _node(path, expr):
    script = ("import('file://%s').then(m => { let v; try { v = (%s); } catch (e) { v = {__throw: String(e)}; }"
              " console.log(JSON.stringify(v === undefined ? null : v)); });" % (path.as_posix(), expr))
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip()]
    if not out:
        raise AssertionError(f"node 没有产出：{r.stderr[-600:]}")
    return json.loads(out[-1])


def _cli_cmds(path):
    """从 CLI 自己的 `CMDS = {...}` 表读子命令名（真源，不抄一份）。"""
    src = path.read_text(encoding="utf-8")
    m = re.search(r"^CMDS = \{(.*?)\}", src, re.S | re.M)
    return set(re.findall(r'"([a-z-]+)":\s*cmd_', m.group(1)))


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class TheCommandTableMatchesTheCli(unittest.TestCase):
    def test_every_subcommand_exists(self):
        rows = _node(CMDS_TS, "m.CMD_TABS.flatMap(t => t.rows.map(r => r.cmd))")
        known = {"codex-rotate": _cli_cmds(ROOT / "codex-rotate"), "agy-rotate": _cli_cmds(ROOT / "agy-rotate")}
        self.assertTrue(known["codex-rotate"] and known["agy-rotate"], "没读到 CLI 的 CMDS 表 —— 闸没有判别力")
        seen = 0
        for cmd in rows:
            parts = cmd.split()
            if parts[0] in known:
                seen += 1
                with self.subTest(cmd=cmd):
                    self.assertIn(parts[1], known[parts[0]], f"★ 「{cmd}」不是现行 CLI 的子命令（稿子写的不算数）")
        self.assertGreater(seen, 15)
        self.assertNotIn("codex-rotate pin --toggle <号>", rows, "codex 的 pin 没有 --toggle（那是 agy 的）")

    def test_top_level_tools_exist(self):
        for tool in ("relay-ctl", "grok-quota", "proxy/cxp", "proxy/cxd"):
            self.assertTrue((ROOT / tool).exists(), tool)

    def test_warning_rows_cannot_be_copied(self):
        got = _node(CMDS_TS, "m.CMD_TABS.flatMap(t => t.rows).map(r => [r.cmd, m.copyOf(r)])")
        by = dict((a, b) for a, b in got)
        self.assertIsNone(by["⚠ codex login / logout"], "★ 会吊销账号的那条给了复制钮")
        self.assertEqual(_node(CMDS_TS, "m.copyOf({cmd: 'a x / a y', desc: ''})"), "a x", "复制内容 = 去掉「 / …」的变体")
        self.assertNotIn("cx / cx next", by, "★ `cx` 不在 INSTALL.md 的软链里 —— 列出来用户敲了是 command not found")


class PresetsKeepOldValues(unittest.TestCase):
    def test_off_preset_value_gets_its_own_option(self):
        # SetKit.tsx 带 React import，不能整文件进 node —— 只取这个纯函数的源码跑（它自己零依赖）。
        src = KIT_TS.read_text(encoding="utf-8")
        fn = src[src.index("export function presetOpts"):]
        fn = fn[:fn.index("\n}\n") + 2].replace("export function", "function").replace(": readonly number[]", "").replace(": number[]", "").replace(": number", "")
        r = subprocess.run(["node", "-e", fn + "console.log(JSON.stringify([presetOpts([1,2,3,7],5), presetOpts([1,2,3,7],2)]))"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(r.stdout), [[1, 2, 3, 5, 7], [1, 2, 3, 7]], r.stderr[-300:])
        r = subprocess.run(["node", "-e", fn + "console.log(JSON.stringify([NaN, 0, -3, '5'].map(v => presetOpts([1,2,3,7], v))))"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(r.stdout), [[1, 2, 3, 7]] * 4, "★ 坏值不许长出一档「NaN 天」")


def _up():
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
        return Path(CHROME).exists()
    except Exception:
        return False


@unittest.skipUnless(_up(), "harness 3304 没起 —— skip 不是绿")
class Rendered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from test_settings_toggles import TRAP
        cls.TRAP = TRAP
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def _page(self, w=1200, h=900, seed=None):
        ctx = self.br.new_context(viewport={"width": w, "height": h})
        ctx.add_init_script(script=f"({self.TRAP})({json.dumps({'seed': seed} if seed else {})})")
        pg = ctx.new_page()
        pg.goto(HARNESS, timeout=30000)
        pg.wait_for_selector("[data-set-group]", timeout=15000)
        pg.wait_for_timeout(600)
        self.addCleanup(ctx.close)
        return pg

    def test_seven_groups_in_order_and_one_info(self):
        pg = self._page()
        r = pg.evaluate("() => [[...document.querySelectorAll('[data-set-group]')].map(g => g.dataset.setGroup), document.querySelectorAll('[data-set-info]').length]")
        self.assertEqual(r[0], ["general", "menubar", "hover", "pool", "sources", "platforms", "about"])
        self.assertEqual(r[1], 1, "★ S1：ⓘ 只留「缓存计入口径」一处")

    def test_no_row_overflows_at_860(self):
        pg = self._page(w=860, h=900)
        bad = pg.evaluate("""() => [...document.querySelectorAll('.set-row')].filter(r => r.scrollWidth > r.clientWidth + 1)
            .map(r => r.textContent.slice(0, 30))""")
        self.assertEqual(bad, [], "★ 860 宽下有设置行横向溢出")

    def test_pill_sits_under_the_selected_option(self):
        pg = self._page()
        r = pg.evaluate("""() => [...document.querySelectorAll('[data-seg] .set-pill')].map(p => {
            const seg = p.parentElement, sel = seg.querySelector('[aria-pressed=true]');
            const a = p.getBoundingClientRect(), b = sel.getBoundingClientRect();
            return Math.abs(a.left - b.left) + Math.abs(a.width - b.width); })""")
        self.assertGreater(len(r), 5)
        self.assertTrue(all(x < 1.5 for x in r), f"★ 选中块没压在选中项上：{r}")

    def test_an_old_off_preset_value_stays_selected(self):
        """★ 老用户设过「5 天」：改成档位后不许被悄悄改成 7，也不许没有一档是选中的。"""
        pg = self._page(seed={"subExpiryWarnDays": 5})
        r = pg.evaluate("() => [...document.querySelectorAll('[data-sub-warn] [data-seg-opt]')].map(b => [b.dataset.segOpt, b.getAttribute('aria-pressed')])")
        self.assertIn(["5", "true"], r)
        st = pg.evaluate("() => JSON.parse(localStorage.getItem('codexbar_settings')).subExpiryWarnDays")
        self.assertEqual(st, 5)
        pg.click("[data-sub-warn] [data-seg-opt='7']")
        pg.wait_for_timeout(150)
        # 存储读不了：种子包着 setItem，每次写都会被合并回 5（test_settings_toggles 的 TRAP）—— 看界面状态。
        r = pg.evaluate("() => [...document.querySelectorAll('[data-sub-warn] [data-seg-opt]')].map(b => [b.dataset.segOpt, b.getAttribute('aria-pressed')])")
        self.assertEqual(r, [["1", "false"], ["2", "false"], ["3", "false"], ["7", "true"]], "点了预设档 ⇒ 选中 7、临时档 5 收起")

    def test_scan_status_counts_only_ok_sources(self):
        """★ 「N 个源正常」只数 `ok`：未找到 / 没有会话文件不算（评审 P6-codex-2）。真源 = 页面拿到的同一份快照。"""
        pg = self._page()
        r = pg.evaluate("""async () => {
            const snap = JSON.parse(await window.__TAURI_INTERNALS__.invoke('read_traffic_snapshot'));
            const st = Object.values(snap.scan.sources).map(s => s.state);
            return [st, document.querySelector('[data-scan-status]').textContent]; }""")
        states, text = r
        self.assertTrue(any(x != "ok" and x != "disabled" for x in states), f"夹具里全是 ok —— 判不了：{states}")
        if "处少算" not in text:
            self.assertIn(f"{states.count('ok')} 个源正常", text)

    def test_unreadable_is_not_announced_as_off(self):
        """★ 读不到 ≠ 关：开关不许报 aria-checked=false，按下也不许有按压动画（评审 P6-gemini-4）。"""
        pg = self._page()
        r = pg.evaluate("""() => [...document.querySelectorAll('[role=switch]')].map(e => [e.getAttribute('aria-checked'), e.getAttribute('aria-disabled'), e.style.opacity])""")
        for checked, dis, op in r:
            if op == "0.5" and dis == "true":
                self.assertIsNone(checked, "读不到的开关报成了「关」")
        self.assertTrue(r, "页面上没有开关 —— 闸没有判别力")

    def test_no_divider_between_a_row_and_its_own_sub_block(self):
        pg = self._page()
        bad = pg.evaluate("""() => [...document.querySelectorAll('.set-card > .set-sub')].filter(s => {
            const p = s.previousElementSibling; return p && p.classList.contains('set-row') && getComputedStyle(s).borderTopWidth !== '0px'; }).length""")
        self.assertEqual(bad, 0)
        n = pg.evaluate("() => document.querySelectorAll('.set-card > .set-sub').length")
        self.assertGreater(n, 1, "页面上没有从属块 —— 闸没有判别力")

    def test_rules_fold_is_css_and_opens(self):
        pg = self._page()
        before = pg.evaluate("() => [getComputedStyle(document.querySelector('[data-cmd-panel]')).display, document.querySelectorAll('[data-cmd]').length]")
        self.assertEqual(before[0], "none", "默认收起")
        self.assertGreater(before[1], 0, "★ 收起时内容离开了 DOM —— §5c 要 CSS 显隐")
        pg.click("[data-cmd-rules]")
        pg.click("[data-cmd-tab=codex]")
        pg.wait_for_timeout(150)
        r = pg.evaluate("() => [getComputedStyle(document.querySelector('[data-cmd-panel]')).display, [...document.querySelectorAll('[data-cmd]')].map(e => e.textContent)]")
        self.assertEqual(r[0], "block")
        self.assertIn("codex-rotate login", r[1])
