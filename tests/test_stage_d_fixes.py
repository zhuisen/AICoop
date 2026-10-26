"""阶段 D（§6 设置 + §8 托盘 / 悬停面板 + §9 刘海）—— 全方面评审 2026-10-22 的修复闸。逐条对应
`~/Downloads/aicoop_full_review_20261022/SUMMARY.md` §6 / §8 / §9。

Connector 用 `test_connector.Sandbox`（HOME 侧目录全在 tmpdir，不碰真 `~/.codex`）；纯逻辑用 node 直接跑零 import 模块；
Rust / 组件的接线用剥掉注释后的源码形态断言（真窗口行为 harness 拍不到，见各条说明）。
"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

try:
    from . import _isolation  # noqa: F401  ★ 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
RS = ROOT / "codexbar" / "src-tauri" / "src"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
import connector  # noqa: E402
from test_connector import Sandbox, USER_CONFIG  # noqa: E402


def code(path):
    s = Path(path).read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/\"'])//[^\n]*", "", s)


def node(mod, expr, prelude=""):
    script = "import('file://%s').then(async (m) => { %s console.log(JSON.stringify(await (%s))); });" % (
        (SRC / mod).as_posix(), prelude, expr)
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    out = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if not out:
        raise AssertionError("node 没有产出：%s" % r.stderr[-600:])
    return json.loads(out[-1])


def contrast(a, b):
    def lum(h):
        h = h.lstrip("#")
        c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    x, y = lum(a), lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


# ── §6 设置 ────────────────────────────────────────────────────────────────────────────────

class ManagedBlocksAreJudgedByContent(Sandbox):
    """§6「看到托管标记就判已完成，不比内容」（与 B77 同族）。"""

    def _stale(self, path):
        txt = path.read_text(encoding="utf-8")
        path.write_text(txt.replace("supports_websockets = false", "supports_websockets = false\n# 旧版本写的", 1),
                        encoding="utf-8")

    def test_a_fresh_block_is_done(self):
        self.cfg.write_text(USER_CONFIG, encoding="utf-8")
        self.apply("runtime", "provider", "profile")
        self.assertEqual(self.step("provider")["state"], "done")
        self.assertEqual(self.step("profile")["state"], "done")

    def test_a_drifted_provider_block_is_todo(self):
        self.cfg.write_text(USER_CONFIG, encoding="utf-8")
        self.apply("runtime", "provider")
        self._stale(self.cfg)
        self.assertEqual(self.step("provider")["state"], "todo", "★ 托管区内容变了仍报「已完成」")

    def test_a_drifted_profile_block_is_todo(self):
        self.apply("runtime", "profile")
        self._stale(self.home / "rotateproxy.config.toml")
        self.assertEqual(self.step("profile")["state"], "todo")

    def test_reapplying_fixes_it(self):
        self.cfg.write_text(USER_CONFIG, encoding="utf-8")
        self.apply("runtime", "provider")
        self._stale(self.cfg)
        self.apply("runtime", "provider")
        self.assertEqual(self.step("provider")["state"], "done")
        self.assertEqual(self.cfg.read_text(encoding="utf-8").count(connector.MARK_BEGIN), 1)


class Coalesce(unittest.TestCase):
    """§6「useIntegration / 接入面板没有合流：每条 state-changed 起一个 python」。"""

    def test_calls_during_a_run_collapse_into_one_trailing_run(self):
        got = node("coalesce.ts", "out", prelude="""
          let n = 0, release = [];
          const go = m.coalesce(() => { n++; return new Promise((r) => release.push(r)); });
          for (let i = 0; i < 20; i++) go();
          const one = n; release.shift()(); await new Promise((r) => setTimeout(r, 0));
          const two = n; release.shift()(); await new Promise((r) => setTimeout(r, 0));
          const out = [one, two, n];""")
        self.assertEqual(got, [1, 2, 2], "★ 20 次调用应当只跑 1 次 + 1 次尾随")

    def test_a_failing_run_does_not_block_later_ones(self):
        got = node("coalesce.ts", "out", prelude="""
          let n = 0;
          process.on('unhandledRejection', () => {});
          const go = m.coalesce(async () => { n++; throw new Error('x'); });
          go(); await new Promise((r) => setTimeout(r, 0)); go(); await new Promise((r) => setTimeout(r, 0));
          const out = n;""")
        self.assertEqual(got, 2, "★ 一次失败把后面的读取永久堵死")

    def test_both_callers_use_it(self):
        self.assertRegex(code(SRC / "hooks" / "useIntegration.ts"), r"const reload = useMemo\(\(\) => coalesce\(")
        self.assertRegex(code(SRC / "components" / "ConnectorPanel.tsx"), r"const load = useMemo\(\(\) => coalesce\(")


class ConnectorPicksSurviveRefresh(unittest.TestCase):
    """§6「每次 state-changed 都重置接入勾选」。"""

    S = [{"id": "provider", "state": "todo", "optional": False}, {"id": "wrapper", "state": "todo", "optional": True}]

    def test_unchanged_steps_keep_the_users_pick(self):
        got = node("connectorPicks.ts", "m.mergePicks(%s, %s, %s, false)" % (
            json.dumps({"provider": False, "wrapper": True}), json.dumps(self.S), json.dumps(self.S)))
        self.assertEqual(got, {"provider": False, "wrapper": True})

    def test_a_step_whose_state_changed_returns_to_default(self):
        new = [dict(self.S[0], state="done"), self.S[1]]
        got = node("connectorPicks.ts", "m.mergePicks(%s, %s, %s, false)" % (
            json.dumps({"provider": True, "wrapper": True}), json.dumps(self.S), json.dumps(new)))
        self.assertEqual(got, {"provider": False, "wrapper": True})

    def test_the_panel_merges_instead_of_resetting(self):
        s = code(SRC / "components" / "ConnectorPanel.tsx")
        self.assertIn("mergePicks(prev, prevSteps, p.steps, !!p.blocked)", s)


class UpdateCheckKnowsPrereleases(unittest.TestCase):
    """§6「检查更新丢掉预发布后缀：beta 用户在正式版发布后被判成已是最新」。"""

    CASES = [
        ("v1.12.0", "1.12.0-beta.1", True),
        ("v1.12.0", "1.12.0", False),
        ("v1.12.0", "1.12.0+44", False),
        ("v0.10.0", "0.9.0", True),
        ("v1.12.0-beta.2", "1.12.0-beta.1", True),
        ("v1.12.0-beta.10", "1.12.0-beta.9", True),
        ("v1.12.0-rc.1", "1.12.0-beta.9", True),
        ("v1.12.0-beta.1", "1.12.0", False),
        ("v1.11.9", "1.12.0-beta.1", False),
    ]

    def test_cases(self):
        got = node("semver.ts", "%s.map(([a, b]) => m.isNewer(a, b))" % json.dumps([[a, b] for a, b, _ in self.CASES]))
        self.assertEqual(got, [w for _, _, w in self.CASES])

    def test_the_page_uses_it(self):
        s = code(SRC / "pages" / "SettingsPage.tsx")
        self.assertIn('import { isNewer } from "../semver";', s)
        self.assertNotIn("function isNewer(", s, "页面里不许再留一份按 parseInt 比的旧实现")


class SettingsRowsSayWhatHappened(unittest.TestCase):
    def test_claude_otel_partial_has_a_warning(self):
        st = {"ok": True, "state": "partial", "ui": "partial", "error": None, "conflicts": [], "settings": "x",
              "receiver": {"last_post_at": None, "listening": None, "error": None, "port_open": None}}
        got = node("claudeOtel.ts", "m.claudeOtelWarn(%s, null)" % json.dumps(st))
        self.assertTrue(got and got.startswith("⚠"), got)

    def test_borrow_write_failure_is_shown_and_unknown_is_not_written(self):
        s = code(SRC / "pages" / "SettingsPage.tsx")
        for fn, var in (("toggleBorrow", "borrow"), ("toggleAgyBorrow", "agyBorrow")):
            body = s[s.index("const %s = useCallback(" % fn):]
            body = body[:body.index("}, [")]
            self.assertIn("if (%s == null) return;" % var, body, "★ 读不到时 `!null` 会写成「开」")
            self.assertRegex(body, r"catch \(e: unknown\) \{\s*setBorrowErr\(")
        self.assertIn("const borrowDesc = borrowErr ?", s)

    def test_source_status_follows_scans(self):
        s = code(SRC / "pages" / "SettingsPage.tsx")
        self.assertRegex(s, r'listen\("traffic-updated", read\)', "★「数据源状态」写着自动更新，实际只读一次")


# ── §8 托盘 + 悬停面板 ─────────────────────────────────────────────────────────────────────

class HidingTheLastCellKeepsTheUndo(unittest.TestCase):
    """§8（三方一致）「最后一格隐藏到重置之后，面板再也打不开，撤销入口跟着消失」。"""

    def test_the_grid_draws_snoozed_rows_without_cells(self):
        s = code(SRC / "components" / "IdleGrid.tsx")
        self.assertIn("const snoozed = data?.snoozed ?? [];", s)
        self.assertIn('const isOpen = mode === "open" && (cells.length > 0 || snoozed.length > 0);', s)

    def test_rust_is_told_about_the_snoozed_rows(self):
        s = code(SRC / "hooks" / "useIdleTray.ts")
        self.assertIn("cells: next.cells.length + (next.snoozed?.length ?? 0)", s)

    def test_an_empty_open_panel_closes(self):
        s = code(RS / "tps_hover.rs")
        self.assertRegex(s, r'if idle && !idle_has_cells\(\) \{\s*close\(&app, "empty"\);\s*break;')


class FrozenSlotsKeepTheHiddenOne(unittest.TestCase):
    """§8「隐藏一家会改写冻结的常驻位，到期回来时顺序变了」。"""

    def test_merge(self):
        got = node("idleTray.ts", 'm.mergeFrozen(["claude", "agy"], ["claude", "codex"], ["agy"])')
        self.assertEqual(got, ["claude", "agy", "codex"])

    def test_the_hidden_one_is_back_in_place(self):
        """端到端：冻结表 [A, S, R]，S 回来后 `pickIdleSlots` 取前两位 ⇒ [A, S]。"""
        ps = [{"key": k, "remaining": [50], "requests": 1, "tokens": 1, "lastUsedAt": None} for k in ("claude", "agy", "codex")]
        got = node("idleTray.ts", 'm.pickIdleSlots(%s, { slots: 2, rankBy: "tokens", pinned: [], now: 0, keep: ["claude", "agy", "codex"] }).map((s) => s.key)'
                   % json.dumps(ps))
        self.assertEqual(got, ["claude", "agy"])

    def test_the_hook_uses_it(self):
        self.assertIn("keep: mergeFrozen(keep, resident, snoozed.map((z) => z.key))", code(SRC / "hooks" / "useIdleTray.ts"))


class CodexSnoozesUntilItsRealReset(unittest.TestCase):
    """§8（三方一致）「Codex 隐藏到重置一律 5 h」。"""

    def test_the_hook_passes_the_reset(self):
        self.assertIn("mainReset.current = { codex: w5?.resetsAtSec ?? null,", code(SRC / "hooks" / "useIdleTray.ts"))

    def test_only_an_anchored_window_has_a_reset_time(self):
        s = code(SRC / "helpers.ts")
        self.assertIn('resetsAtSec: st === "anchored" && typeof w.resets_at === "number" ? w.resets_at : null,', s)


class LiveErrorsAreShown(unittest.TestCase):
    """§8「没人监听 tps-live-error，面板继续画旧 t/s」；「--live 挂住后托盘冻在最后一帧」。"""

    def test_the_hook_listens(self):
        self.assertRegex(code(SRC / "hooks" / "useLive.ts"), r'listen<string>\("tps-live-error", \(ev\) => \{ setError\(')

    def test_the_panel_marks_old_numbers(self):
        s = code(SRC / "TpsHover.tsx")
        self.assertIn("const { live, error: liveErr } = useLive();", s)
        self.assertIn("{liveErr && live && <span className=\"hv-stale\" data-hover-stale", s)

    def test_live_runs_with_a_timeout(self):
        s = code(RS / "lib.rs")
        body = s[s.index("fn run_live_blocking()"):]
        body = body[:body.index("\n}")]
        self.assertIn("run_py_script_timeout(&requests_script(), &[\"--live\"], LIVE_TIMEOUT)", body)


class LightThemeTextIsReadable(unittest.TestCase):
    """§8「浅色主题下『撤销』#2dd4bf 1.86:1；Codex 数字 #0E9F8E 3.30:1」。从源里现读，不抄一份。"""

    def _vars(self, css, theme):
        block = re.search(r'\[data-theme="%s"\] \{([\s\S]*?)\n\}' % theme, css)
        return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block.group(1)))

    def test_hover_panel_text_colours(self):
        css = (SRC / "tpsHover.css").read_text(encoding="utf-8")
        for theme, bg in (("light", "#ffffff"), ("dark", "#10161d")):
            v = self._vars(css, theme)
            for k in ("hv-acc", "hv-warn"):
                self.assertGreaterEqual(contrast(v[k], bg), 4.5, "%s %s %s" % (theme, k, v[k]))
        self.assertIn(".ig-undo { color: var(--ig-acc);", css)
        accs = re.findall(r"--ig-acc:\s*(#[0-9a-fA-F]{6})", css)
        self.assertEqual(len(accs), 2)
        self.assertGreaterEqual(min(contrast(accs[0], "#1c2128"), contrast(accs[1], "#ffffff")), 4.5)

    def test_platform_numbers_on_white(self):
        s = (SRC / "live.ts").read_text(encoding="utf-8")
        vals = re.findall(r'numLight: "(#[0-9A-Fa-f]{6})"', s)
        self.assertEqual(len(vals), 4)
        for h in vals:
            self.assertGreaterEqual(contrast(h, "#ffffff"), 4.5, h)


class TrayAndPanelPlumbing(unittest.TestCase):
    """§8 其余几条（Rust 侧，真机像素 TCC 截不到 ⇒ 守接线）。"""

    def test_silhouette_follows_the_logo_size(self):
        self.assertIn("const S: f64 = crate::tray_idle::LOGO * 2.0;", code(RS / "tray_pill.rs"))

    def test_reopen_clears_the_old_hover(self):
        self.assertIn('useEffect(() => { if (mode === "open") setHovKey(null); }, [mode]);', code(SRC / "components" / "IdleGrid.tsx"))

    def test_each_panel_keeps_its_own_height(self):
        s = code(RS / "tps_hover.rs")
        self.assertNotRegex(s, r"\bPANEL_H\b(?!_)")
        self.assertIn("let slot = if w.is_some() { &PANEL_H_IDLE } else { &PANEL_H_RUN };", s)

    def test_the_tray_under_the_cursor_is_used(self):
        s = code(RS / "tps_hover.rs")
        self.assertIn("msg_send![class!(NSEvent), mouseLocation]", s[s.index("fn read_tray"):])

    def test_a_late_enter_is_not_lost(self):
        s = code(RS / "tps_hover.rs")
        self.assertRegex(s, r"POLLER\.store\(false, Ordering::SeqCst\);\s*if PHASE\.load\(Ordering::SeqCst\) == DWELL \{ on_enter\(&app\); \}")

    def test_last_unsubscribe_forgets_the_live_verdict(self):
        s = code(RS / "activity.rs")
        body = s[s.index("pub fn unsubscribe"):]
        body = body[:body.index("\n}")]
        self.assertIn("*g = None;", body)

    def test_the_doc_admits_the_mtime_poll(self):
        self.assertIn("poll_open_writers", (ROOT / ".claude" / "rules" / "ui.md").read_text(encoding="utf-8"))


@unittest.skipIf(not Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").exists(), "没有 Chrome")
class AllHiddenStillOffersUndoRendered(unittest.TestCase):
    """真 bundle：一格都没有、只剩「已隐藏」行时，面板照样打开、撤销点得到（先正面证明它渲染出来了）。"""

    @classmethod
    def setUpClass(cls):
        from test_idle_tray_wiring import BASE, CHROME, TRAP
        cls.BASE, cls.TRAP = BASE, TRAP
        try:
            import urllib.request
            urllib.request.urlopen(BASE + "harness.html", timeout=2).read(1)
        except Exception:
            raise unittest.SkipTest("harness 3304 没起 —— skip 不是绿")
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def test_the_undo_row_is_visible_with_zero_cells(self):
        ctx = self.br.new_context(viewport={"width": 520, "height": 300})
        self.addCleanup(ctx.close)
        ctx.add_init_script(script=f"({self.TRAP})({{}})")
        pg = ctx.new_page()
        pg.goto(self.BASE + "harness-tpshover.html?hv=idle&hvcells=0&hvsnoozed=1", timeout=30000)
        pg.wait_for_timeout(1800)
        r = pg.evaluate("""() => { const n = document.querySelector('[data-idle-snoozed=grok]'); const u = document.querySelector('[data-idle-undo=grok]');
          const shell = n && n.parentElement;
          return { cells: document.querySelectorAll('[data-idle-cell]').length, note: !!n, op: n && getComputedStyle(n).opacity,
                   shellOp: shell && getComputedStyle(shell).opacity, h: shell && shell.getBoundingClientRect().height,
                   undoH: u && u.getBoundingClientRect().height }; }""")
        self.assertEqual(r["cells"], 0, "夹具没清空格子 —— 下面的断言没打中")
        self.assertTrue(r["note"], "★ 「已隐藏」行没渲染")
        self.assertEqual((r["op"], r["shellOp"]), ("1", "1"), "★ 全藏了面板不显示 ⇒ 撤销入口消失")
        self.assertGreater(r["h"], 20)
        self.assertGreater(r["undoH"], 0)
        pg.click("[data-idle-undo=grok]")
        pg.wait_for_timeout(200)
        ev = pg.evaluate("() => window.__calls.filter(c => c.c === 'plugin:event|emit').map(c => [c.a.event, c.a.payload])")
        self.assertIn(["idle-snooze", {"key": "grok", "undo": True}], [list(x) for x in ev])


# ── §9 刘海 ───────────────────────────────────────────────────────────────────────────────

class NotchClaudeExpiresAtReset(unittest.TestCase):
    """§9「Claude 过了重置点仍显示旧窗口的额度（旧的 5% 还会告警）；两份实现不一致」。"""

    def test_one_rule(self):
        now = 1_800_000_000_000
        got = node("idleTray.ts", "[m.claudeRem({ idle: false, resetsAt: %d, rem: 5 }, %d), m.claudeRem({ idle: false, resetsAt: %d, rem: 5 }, %d),"
                   " m.claudeRem({ idle: true, resetsAt: %d, rem: 100 }, %d), m.claudeRem(null, %d)]"
                   % (now // 1000 - 1, now, now // 1000 + 60, now, now // 1000 - 1, now, now))
        self.assertEqual(got, [None, 5, 100, None])

    def test_both_callers_share_it(self):
        self.assertNotRegex(code(SRC / "hooks" / "useIdleTray.ts"), r"function claudeRem\(")
        s = code(SRC / "NotchHud.tsx")
        body = s[s.index("function claudeWin("):]
        body = body[:body.index("\n}")]
        self.assertIn("claudeNow(w, Date.now(), week)", body)
        self.assertIn("claudeWin(claudeQ?.fiveH ?? null, st, claudeQ?.week ?? null)", s)
        self.assertIn("claudeNow(claude?.fiveH, now, claude?.week ?? null)", code(SRC / "hooks" / "useIdleTray.ts"))

    def test_collapsed_notch_reads_claude_without_a_timer(self):
        """§9 存疑（核实成立）：原来只在展开时读 ⇒ 没展开过时 Claude <10% 光晕不变红。"""
        s = code(SRC / "NotchHud.tsx")
        self.assertIn("useEffect(() => { readClaude(); }, [readClaude]);", s)
        self.assertIn("useEffect(() => { if (act.claude) readClaude(); }, [act.claude, live, readClaude]);", s)
        self.assertEqual(s.count("setInterval"), 1, "PushNotPoll：只许展开时那一个倒计时")


class NotchIdleShowsHiddenAndWarnings(unittest.TestCase):
    """§9「刘海空闲格没有『已隐藏 · 撤销』，也不显示周额度告警」。"""

    def test_height_counts_the_notes(self):
        got = node("notchIdle.ts", "[m.notchGrid(0, 0).h, m.notchGrid(0, 1).h > 0, m.notchGrid(4, 1).h - m.notchGrid(4, 0).h]")
        self.assertEqual(got[0], 0)
        self.assertTrue(got[1], "★ 全藏了也要有高度，否则撤销入口画不出来")
        self.assertGreater(got[2], 0)

    def test_grid_renders_both(self):
        s = code(SRC / "components" / "NotchIdleGrid.tsx")
        self.assertIn("data-notch-idle-snoozed", s)
        self.assertIn("data-notch-idle-undo", s)
        self.assertIn("data-notch-idle-week", s)
        self.assertIn("emit(IDLE_SNOOZE_EVENT, { key, undo })", s)
        self.assertIn("snooze(z.key, true)", s, "撤销 = undo: true（2026-10-24 起与 × 共用 `snooze`）")

    def test_hud_passes_them_and_does_not_dismiss_while_notes_remain(self):
        s = code(SRC / "NotchHud.tsx")
        self.assertIn("snoozed={idleSnoozed} warns={idleData?.warns ?? []}", s)
        self.assertIn("!idleCells.length && !idleSnoozed.length) invoke(\"notch_dismiss\")", s)


class NotchFollowsScreenChanges(unittest.TestCase):
    """§9 存疑：插拔显示器时不监听屏幕参数变更（原来只靠下一次鼠标移动）。"""

    def test_observer_installed_and_removed(self):
        s = code(RS / "notch.rs")
        self.assertIn('NSString::from_str("NSApplicationDidChangeScreenParametersNotification")', s)
        self.assertIn("msg_send![center, removeObserver: &*obj]", s)
        self.assertRegex(s, r"\*GEOM\.lock\(\)\.unwrap\(\) = None; reconcile\(&a3\);")


# ── 阶段 D 两方评审的补修 ────────────────────────────────────────────────────────────────────

class StageDReviewFollowups(unittest.TestCase):
    """codex gpt-6.1-sol + agy gemini-4-argon-high 对阶段 D 的意见（`~/Downloads/aicoop_fix_20261022/stageD/`）。
    行为闸在别处：B2 → `test_stage_c_fixes.AgyLanes`；B4 → `test_stage_c_fixes` 的 `ringRatio`；合流 → `cargo test coalesce_after`。"""

    def test_integration_coalesces_across_webviews(self):
        s = code(RS / "lib.rs")
        self.assertIn("coalesce_after(&INTEGRATION_LAST, asked, run_integration)", s)
        self.assertRegex(s, r"if \*started >= asked \{ return r\.clone\(\); \}")

    def test_live_and_json_wait_for_the_lock_with_a_deadline(self):
        s = code(RS / "lib.rs")
        self.assertNotIn("REQUESTS_LOCK.lock()", s, "★ 等锁不能没有时限")
        self.assertIn("let _g = requests_lock(LIVE_TIMEOUT)?;", s)
        self.assertIn("let _g = requests_lock(JSON_TIMEOUT)?;", s)
        self.assertIn('run_py_script_timeout(&requests_script(), &["--json"], JSON_TIMEOUT)', s)

    def test_a_live_result_after_unsubscribe_is_dropped(self):
        s = code(RS / "activity.rs")
        self.assertIn("LIVE_GEN.fetch_add(1, Ordering::SeqCst);", s)
        i = s.index("let res = crate::run_live_blocking();")
        j = s.index("*g = act;", i)
        seg = s[i:j]
        # ★ 阶段 E 评审 codex：检查与写回要在同一把锁里（拿锁 → 核代次 → 写回），退订也拿这把锁推代次
        self.assertLess(seg.index("let mut g = LIVE_ACT.lock().unwrap();"),
                        seg.index("if LIVE_GEN.load(Ordering::SeqCst) != gen {"), "★ 代次检查必须在锁里、写回之前")
        u = s[s.index("pub fn unsubscribe("):]
        u = u[:u.index("\n}\n")]
        self.assertLess(u.index("let mut g = LIVE_ACT.lock().unwrap();"), u.index("LIVE_GEN.fetch_add(1, Ordering::SeqCst);"),
                        "★ 退订推代次也要在同一把锁里")
        # ★ 阶段 F 评审 codex：解锁后退订仍能插到 emit／on_live 之前 ⇒ 发布锁罩住整段，退订先拿它
        k = s.index("crate::tray_pill::on_activity_only(&app, a.as_array());", i)
        self.assertLess(s.index("let _pub = LIVE_PUB.lock().unwrap();", i), s.index("if LIVE_GEN.load(Ordering::SeqCst) != gen {", i))
        self.assertNotIn("drop(_pub)", s[i:k], "★ 发布锁要持到 on_live / on_activity_only 之后")
        self.assertLess(u.index("let _pub = LIVE_PUB.lock().unwrap();"), u.index("let mut g = LIVE_ACT.lock().unwrap();"),
                        "★ 退订先拿发布锁，再拿 LIVE_ACT（与工作线程同序）")

    def test_tray_fallback_matches_both_axes(self):
        s = code(RS / "tps_hover.rs")
        self.assertIn("(f.origin.x - p.x).abs() < 1.0 && (pf.size.height - (f.origin.y + f.size.height) - p.y).abs() < 1.0", s)

    def test_notch_idle_height_floor_fits_one_note_row(self):
        s = code(RS / "notch.rs")
        self.assertIn("h.clamp(if idle { IDLE_H_MIN } else { 80.0 }, CARD_H_MAX)", s)
        floor = float(re.search(r"const IDLE_H_MIN: f64 = ([\d.]+);", s).group(1))
        one_note = node("notchIdle.ts", "m.notchGrid(0, 1).h")
        self.assertLessEqual(floor, one_note, "★ 下限高过一行「已隐藏」，下面又是一块透明吃点击区")

    def test_notch_wakes_at_claude_resets(self):
        s = code(SRC / "NotchHud.tsx")
        self.assertIn("for (const w of [claudeQ?.fiveH, claudeQ?.week]) if (w && !w.idle && w.resetsAt) times.push(w.resetsAt);", s)
        self.assertIn("}, [state, agyShownSnap, claudeQ, tick]);", s)

    def test_relay_card_money_on_white(self):
        s = code(SRC / "components" / "relay" / "ModelSparkCard.tsx")
        m = re.search(r'实扣 <b style=\{\{ color: t\.isDark \? "#E0A21C" : "(#[0-9a-fA-F]{6})" \}\}>', s)
        self.assertTrue(m, "★ 浅色白底上的「实扣」还是 #E0A21C（2.24:1）")
        self.assertGreaterEqual(contrast(m.group(1), "#ffffff"), 4.5)


if __name__ == "__main__":
    unittest.main()
