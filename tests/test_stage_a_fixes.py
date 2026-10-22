"""阶段 A（总览 + 菜单栏）—— 全方面评审 2026-10-22 的修复闸。逐条对应 `~/Downloads/aicoop_full_review_20261022/SUMMARY.md` §1 / §7。

行为闸优先（CLI 在临时 store 里真跑、纯 TS 用 node 直接跑）；只有组件内部状态的几条用源码形态闸，
断言前剥注释（verification.md 空守卫形态 ④ / ⑫）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"


def code(rel):
    s = (SRC / rel).read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/\"'])//[^\n]*", "", s)


def node(mod, expr):
    script = "import('file://%s').then(m => { console.log(JSON.stringify(%s)); });" % ((SRC / mod).as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script], capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip()]
    if not out:
        raise AssertionError("node 没有产出：%s" % r.stderr[-600:])
    return json.loads(out[-1])


class RemoveCli(unittest.TestCase):
    """§1「删除直连号会自动复活」+「删号后 pinned 留着 aid」。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cbx_stageA_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        os.makedirs(os.path.join(self.dir, "auth"))
        os.makedirs(os.path.join(self.dir, "home"))
        for aid in ("a1", "a2"):
            with open(os.path.join(self.dir, "auth", aid + ".json"), "w") as fh:
                json.dump({"tokens": {"access_token": "TESTONLY-" + aid, "account_id": aid}}, fh)
        self.write({"active": "a1", "pinned": ["a2", "a1"], "slots": {
            "a1": {"label": "plusA", "plan": "plus", "file": "a1.json"},
            "a2": {"label": "plusB", "plan": "plus", "file": "a2.json"}}})

    def write(self, st):
        with open(os.path.join(self.dir, "state.json"), "w") as fh:
            json.dump(st, fh)

    def state(self):
        with open(os.path.join(self.dir, "state.json")) as fh:
            return json.load(fh)

    def live(self, aid):
        with open(os.path.join(self.dir, "home", "auth.json"), "w") as fh:
            json.dump({"tokens": {"access_token": "TESTONLY-" + aid, "account_id": aid}}, fh)

    def cli(self, *args):
        env = dict(os.environ, CODEX_ROTATE_STORE=self.dir, CODEX_HOME=os.path.join(self.dir, "home"))
        return subprocess.run([sys.executable, str(ROOT / "codex-rotate"), *args],
                              capture_output=True, text=True, env=env, timeout=60)

    def test_the_account_in_auth_json_cannot_be_removed(self):
        self.live("a1")
        r = self.cli("remove", "plusA")
        self.assertNotEqual(r.returncode, 0, "★ 删掉了 auth.json 里那个号 —— 下次 autosync 会以新名字把它收回来")
        self.assertIn("switch", r.stdout + r.stderr, "拒绝时要说下一步敲什么")
        self.assertIn("a1", self.state()["slots"])

    def test_removing_another_account_also_drops_it_from_the_pins(self):
        self.live("a1")
        r = self.cli("remove", "plusB")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.state()
        self.assertNotIn("a2", st["slots"])
        self.assertEqual(st.get("pinned"), ["a1"], "★ 置顶里还留着删掉的号")

    def test_an_unreadable_auth_json_also_refuses(self):
        """阶段 A 评审：读不出 auth.json 时按「未知」放行 ⇒ 仍能删掉当前号。读不到 ≠ 不是它。"""
        with open(os.path.join(self.dir, "home", "auth.json"), "w") as fh:
            fh.write("{not json")
        r = self.cli("remove", "plusA")
        self.assertNotEqual(r.returncode, 0, "★ auth.json 读不出却照删")
        self.assertIn("a1", self.state()["slots"])

    def test_a_stale_pin_does_not_break_pin_toggle(self):
        """老 state 可能已经留着删掉的 aid：`pin --toggle` 不许 KeyError。"""
        st = self.state()
        st["pinned"] = ["gone", "a1"]
        self.write(st)
        r = self.cli("pin", "--toggle", "plusB")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_pin_computes_under_the_lock(self):
        """阶段 A 评审：`pin` 在锁外算好列表再整份写回 ⇒ 与 `remove` 交错时把删掉的 aid 写回去。
        在 `_mutate_state` 拿锁之前把 a2 从 state 里删掉（模拟另一个进程的 remove），toggle a1 后 pinned 里不许有 a2。"""
        import importlib.machinery
        import importlib.util
        os.environ["CODEX_ROTATE_STORE"] = self.dir
        self.addCleanup(os.environ.pop, "CODEX_ROTATE_STORE", None)
        loader = importlib.machinery.SourceFileLoader("cr_stageA_pin", str(ROOT / "codex-rotate"))
        m = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(m)
        self.assertEqual(str(m.STORE), self.dir, "夹具没隔离")
        self.write({"active": "a1", "pinned": ["a2"], "slots": {
            "a1": {"label": "plusA", "plan": "plus", "file": "a1.json"},
            "a2": {"label": "plusB", "plan": "plus", "file": "a2.json"}}})
        real = m._mutate_state

        def racing(fn):
            st = self.state()
            st["slots"].pop("a2"); st["pinned"] = []
            self.write(st)
            return real(fn)
        m._mutate_state = racing
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            m.cmd_pin(["--toggle", "plusA"])
        self.assertEqual(self.state().get("pinned"), ["a1"], "★ 锁外算好的列表把并发删掉的 a2 写回去了")


class PureLogic(unittest.TestCase):
    def test_cross_midnight_segment_is_split_by_time(self):
        """§1「卡片今日 token 把跨午夜那一段整段算进今天」：前一半在昨天 ⇒ 只算一半。"""
        d0 = 1_800_000_000_000
        got = node("overview.ts", "Object.fromEntries(m.lastUseByAcct([{acc:'x', start:%d, end:%d, tokens:1000}, {acc:'y', start:%d, end:%d, tokens:500}], %d))"
                   % (d0 / 1000 - 600, d0 / 1000 + 600, d0 / 1000 + 10, d0 / 1000 + 20, d0))
        self.assertEqual(got["x"]["today"], 500, "★ 跨午夜整段记进了今天")
        self.assertEqual(got["y"]["today"], 500, "整段都在今天 ⇒ 全算")

    def test_one_window_boundary_for_cards_and_rows(self):
        """§1「卡片与菜单栏窗口分档边界不一致」：1 天窗口两处都归长窗。"""
        self.assertEqual(node("helpers.ts", "[300, 1439, 1440, 10080, 0].map(m.winSlot)"), ["5h", "5h", "w", "w", None])
        for rel in ("components/AccountCard.tsx", "components/AccountRow.tsx", "components/ov/Overview.tsx", "components/relay/PoolDetail.tsx"):
            with self.subTest(rel=rel):
                body = code(rel)
                self.assertIn("winSlot(", body)
                self.assertNotRegex(body, r"mins (<|>=) 1000|mins >= 10000|m (<|>=) 1440", "★ 又写了一份自己的界线")


class ComponentShapes(unittest.TestCase):
    def test_credit_card_is_picked_by_id_with_no_fallback(self):
        body = code("components/ov/CreditChip.tsx")
        self.assertIn("setPickId(", body)
        self.assertNotIn("list[pick] ?? list[0]", body, "★ 选中的卡不在了就退回第一张 —— 用掉的不是用户选的")
        self.assertRegex(body, r"if \(picked && !busy && !sent\.current\)")

    def test_a_failed_dawn_read_is_not_off(self):
        body = code("hooks/useDawnStatus.ts")
        self.assertNotIn("setRec({})", body, "★ 读失败画成「关」，掩盖定时探针仍在花钱")
        self.assertRegex(body, r"if \(rec && !stale\) await write\(", "不知道开关状态（或只有旧读数）时不许盲写")

    def test_the_overview_auto_switch_reads_the_store(self):
        body = code("App.tsx")
        self.assertIn("const next = !getSettings().autoSwitchEnabled;", body)
        self.assertIn("patchSettings({ autoSwitchEnabled: next })", body)

    def test_concurrent_actions_keep_their_spinners(self):
        body = code("hooks/useStore.ts")
        self.assertIn("inflight.current.push(actionId)", body)
        self.assertNotIn("announce(null)", body, "★ 先结束的动作把跨窗镜像整个熄掉")

    def test_agy_auto_toggle_rolls_back(self):
        body = code("hooks/useAgyPool.ts")
        self.assertIn("setErr(String(e).slice(0, 200)); setAutoOn(!on); return false;", body, "命令失败要拨回")
        i = body.index("const setAuto = useCallback")
        seg = body[i:body.index("}, [read]);", i)]
        self.assertNotIn("runThen(", seg, "★ 阶段 B 评审：回读 / 广播失败也算失败 ⇒ 已成功的开关被拨回")

    def test_shortcuts_wait_for_modals(self):
        self.assertIn("modalOpen()", code("hooks/useKeyboard.ts"))
        self.assertIn('modalOpen("cmdk")', code("components/ov/Overview.tsx"))

    def test_refresh_toasts_wait_for_the_result(self):
        for rel in ("MenuBar.tsx", "components/ov/Overview.tsx"):
            with self.subTest(rel=rel):
                body = code(rel)
                self.assertNotRegex(body, r"agyPool\.refresh\(\);\s*(p\.)?showToast", "★ 子进程还没跑完就报「已刷新」")
                self.assertNotRegex(body, r"refreshGrok\(\);\s*(p\.)?showToast")

    def test_menubar_agy_switch_reports_the_result(self):
        self.assertRegex(code("MenuBar.tsx"), r"agyPool\.switchTo\(a\.label\)\.then\(\(ok\)")

    def test_menubar_codex_row_marks_stale_readings(self):
        self.assertIn("dim: a.quotaStale", code("components/AccountRow.tsx"))

    def test_sub_expiry_days_come_from_settings(self):
        for rel in ("MenuBar.tsx", "components/ov/Overview.tsx"):
            with self.subTest(rel=rel):
                self.assertIn("getSettings().subExpiryWarnDays", code(rel))

    def test_card_warn_days_agree_between_cli_and_ui(self):
        cli = re.search(r"^CREDIT_EXPIRY_WARN_DAYS = ([\d.]+)", (ROOT / "codex-rotate").read_text(), re.M)
        ui = re.search(r"export const CARD_WARN_DAYS = (\d+)", (SRC / "helpers.ts").read_text())
        self.assertEqual(float(cli.group(1)), float(ui.group(1)), "★ 重置卡快作废的阈值 CLI 与界面不一致")

    def test_dead_accounts_never_count_as_best(self):
        self.assertRegex(code("components/ov/Overview.tsx"), r'const gBest = gMain\.filter\(\(a\) => [^\n]*gState\(a\) !== "dead"')


class AgyProbeLock(unittest.TestCase):
    """阶段 A 评审：Gemini 探针完全无锁。agy 探非当值号要换钥匙串，两个探针同时跑会互相冲掉 ⇒ 全局锁。"""

    def test_a_second_probe_is_skipped_while_one_runs(self):
        import fcntl
        import importlib.machinery
        import importlib.util
        import types
        d = tempfile.mkdtemp(prefix="cbx_agyprobe_")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        loader = importlib.machinery.SourceFileLoader("agy_rotate_stageA", str(ROOT / "agy-rotate"))
        cli = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(cli)
        pool = {"accounts": {"s": {"label": "S", "email": "s@x"}}}
        cli.P = types.SimpleNamespace(load=lambda: pool, POOL=Path(d) / ".agy-pool.json",
                                      merge_back=lambda *a, **k: pool, claims=lambda x: {"sub": "s"},
                                      read_live=lambda: None, fetch_quota=lambda *a, **k: (None, ""))
        cli._log = lambda m: None
        cli._mark_live = lambda p: "s"
        cli._refresh_one = lambda *a, **k: (None, "stub")
        billed = []
        cli._probe_one = lambda label: (billed.append(label), (True, "ok", None, "s@x"))[1]
        held = open(Path(d) / ".agy-probe.lock", "w")
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()) as out:
            r = cli.cmd_probe(["S"])
        self.assertIsNone(r)
        self.assertEqual(billed, [], "★★ 另一个进程正在探，这里又起了一次计费探针")
        self.assertIn("跳过", out.getvalue())
        held.close()
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_probe(["S"])
        self.assertEqual(billed, ["S"], "已知阳性：没人占锁时照常探")


class StageAReviewShapes(unittest.TestCase):
    def test_dawn_reading_is_scoped_to_its_platform(self):
        body = code("hooks/useDawnStatus.ts")
        self.assertIn("got && got.kind === kind ? got.rec : null", body, "★ 切平台后沿用上一家的定时状态")
        self.assertIn('if (!last) throw new Error("empty")', body, "空输出被当成 {}（画成「关」且可点）")
        ov = code("components/ov/Overview.tsx")
        self.assertIn('<DawnChip key="codex"', ov)
        self.assertIn('<DawnChip key="agy"', ov)

    def test_direct_codex_account_is_refused_before_the_confirm(self):
        self.assertRegex(code("components/ov/Overview.tsx"), r"remove: \(a: Account\) => a\.aid === p\.currentNode\s*\?\s*p\.showToast")

    def test_menubar_refresh_busy_follows_the_platform(self):
        self.assertIn('const refreshing = plat === "gemini" ? agyPool.busy : plat === "grok" ? grokBusy', code("MenuBar.tsx"))

    def test_grok_refresh_success_means_a_usable_snapshot(self):
        self.assertIn("okOf: (s) => (s.accounts ?? []).some((a) => a.available)", code("hooks/useGrokQuota.ts"))
        self.assertIn("return judge(d);", code("hooks/useQuotaSidecar.ts"))


if __name__ == "__main__":
    unittest.main()
