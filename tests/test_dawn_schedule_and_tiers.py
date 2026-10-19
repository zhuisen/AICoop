"""定时探针「可选时间 + 区间内随机」+ 总览工具栏胶囊 + agy 档位（2026-10-15，用户）。

用户原话：「定时的功能在设置移动到总览，各 AI 版块上。对 codex、agy 新增定时的功能开关」·
「定时支持选择时间，逻辑还是按 random，例如我选择 6:00，那就 6:00～6:03 的 random 时间去定时探针」·
「agy 的账号，pro 和 ultra 需要有不同的显示」（拍板：只画 ULTRA）。

## 这里守的
1. `dawn_sched.py`：偏移落在 [0, 180)、**同一天同一家恒定**（launchd 每分钟问、app 每 10 分钟问，
   两边必须看到同一秒）、换一天会变；非法时间拒收不改写成 06:00。
2. 两个 CLI 的到点分支：没到点就走、差不到一分钟就睡到那一秒、`--no-wait` 不睡、`--tick` 空转不出声。
3. agy dawn：默认关；**先占天再探**（探针被调用那一刻盘上已是 running）；并发 3 个只进 1 个；
   停用轮换 / 失效的号不探；探针崩了记 failed。**不跑真探针** —— `cmd_probe` 全程打桩。
4. agy 档位：`plan_of` 认 ultra/pro；`_maybe_tier` 一天一次、读不到留旧值。
5. 接线：胶囊在总览、设置页那行已撤；两份安装脚本都装 agydawn 且带 `AGY_POOL_STORE`；
   Rust 白名单 / 日志页 / bundle 资源都认得新东西。
"""
import datetime
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

try:
    from . import _isolation  # noqa: F401  ★ 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
sys.path.insert(0, str(ROOT))
from agy import pool as P  # noqa: E402


def load_ds():
    spec = importlib.util.spec_from_file_location("dawn_sched_t", str(ROOT / "dawn_sched.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_script(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def stub_ds(left):
    """真 `dawn_sched` 的形状，只把 `due_at` 换成「距现在 `left` 秒」—— 到点分支与钟解耦。"""
    real = load_ds()
    return types.SimpleNamespace(parse_time=real.parse_time, window_text=real.window_text,
                                 DEFAULT_TIME=real.DEFAULT_TIME, WAIT_SECS=real.WAIT_SECS,
                                 due_at=lambda rec, kind, day=None: time.time() + left)


def code(p):
    s = Path(p).read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//[^\n]*", "", s)


# ── 1. 到点判据 ─────────────────────────────────────────────────────────
class TheJitterIsFixedPerDay(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.pop("CODEX_ROTATE_DAWN_JITTER", None)
        self.DS = load_ds()

    def tearDown(self):
        if self._old is not None:
            os.environ["CODEX_ROTATE_DAWN_JITTER"] = self._old

    def test_in_range_and_stable_within_a_day(self):
        days = [datetime.date(2026, 10, 1) + datetime.timedelta(d) for d in range(60)]
        js = [self.DS.jitter(d, "codex") for d in days]
        self.assertTrue(all(0 <= j < 180 for j in js), "★ 偏移跑出了「6:00～6:03」")
        self.assertEqual([self.DS.jitter(d, "codex") for d in days], js,
                         "★★ 同一天两次问到的偏移不同 —— launchd 与 app 补跑会看到两个时刻")
        self.assertGreater(len(set(js)), 20, "★ 偏移不随天变 —— 那不是随机，是挪了个固定时刻")

    def test_due_at_is_the_chosen_minute_plus_the_offset(self):
        d = datetime.date(2026, 10, 15)
        base = time.mktime(datetime.datetime(2026, 10, 15, 7, 30).timetuple())
        self.assertEqual(self.DS.due_at({"time": "07:30"}, "agy", d), base + self.DS.jitter(d, "agy"))
        base6 = time.mktime(datetime.datetime(2026, 10, 15, 6, 0).timetuple())
        self.assertEqual(self.DS.due_at({}, "agy", d), base6 + self.DS.jitter(d, "agy"),
                         "没设时间 = 06:00（老用户的行为不变）")

    def test_zero_override_means_no_jitter(self):
        os.environ["CODEX_ROTATE_DAWN_JITTER"] = "0"
        self.assertEqual(self.DS.jitter(datetime.date(2026, 10, 15), "codex"), 0)

    def test_parse_time_rejects_rather_than_guessing(self):
        self.assertEqual(self.DS.parse_time("6:05"), "06:05")
        for bad in ("24:00", "06:60", "6", "abc", "", None, "06:00:00"):
            self.assertIsNone(self.DS.parse_time(bad), "★ %r 被收下了 —— 应拒收，不默默改成 06:00" % (bad,))

    def test_window_text(self):
        self.assertEqual(self.DS.window_text({"time": "06:00"}), "06:00–06:03")
        self.assertEqual(self.DS.window_text({"time": "23:59"}), "23:59–00:02")


# ── 2. codex CLI 的到点分支 ─────────────────────────────────────────────
class CodexDueBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("CODEX_ROTATE_STORE")
        os.environ["CODEX_ROTATE_STORE"] = self.tmp.name
        self.cli = load_script("cr_dawn_sched", ROOT / "codex-rotate")
        self.st = {"slots": {"a1": {"label": "p1", "plan": "plus"}},
                   "dawn_probe": {"enabled": True, "time": "06:00"}}
        self.cli._state = lambda: json.loads(json.dumps(self.st))
        self.cli._mutate_state = lambda f: f(self.st)
        self.ran = []
        self.slept = []
        self.cli.time = types.SimpleNamespace(time=time.time, sleep=self.slept.append,
                                              strftime=time.strftime)
        self.cli._dawn_targets = lambda s: self.ran.append("targets") or []

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CODEX_ROTATE_STORE", None)
        else:
            os.environ["CODEX_ROTATE_STORE"] = self._old
        self.tmp.cleanup()

    def run_cli(self, left, *args):
        self.cli._dawn_sched = lambda: stub_ds(left)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.cli.cmd_dawn_probe(list(args))
        return buf.getvalue()

    def test_far_from_due_does_nothing(self):
        out = self.run_cli(3600)
        self.assertEqual(self.ran, [], "★★ 没到点就跑了")
        self.assertIn("未到点", out)

    def test_tick_is_silent_when_idle(self):
        self.assertEqual(self.run_cli(3600, "--tick"), "", "★ `--tick` 空转出声 —— 日志每分钟多一行")
        self.st["dawn_probe"]["enabled"] = False
        self.assertEqual(self.run_cli(-1, "--tick"), "")

    def test_close_to_due_sleeps_until_then_runs(self):
        self.run_cli(30)
        self.assertEqual(len(self.slept), 1)
        self.assertAlmostEqual(self.slept[0], 30, delta=2)
        self.assertEqual(self.ran, ["targets"], "差不到一分钟要睡到那一秒再跑")

    def test_no_wait_never_sleeps(self):
        self.run_cli(30, "--no-wait")
        self.assertEqual((self.slept, self.ran), ([], []), "★ app 内补跑持着 IPC，不能睡")

    def test_past_due_runs(self):
        self.run_cli(-5, "--tick")
        self.assertEqual(self.ran, ["targets"])

    def test_time_round_trip_and_status(self):
        self.run_cli(0, "--time", "7:05")
        self.assertEqual(self.st["dawn_probe"]["time"], "07:05")
        r = json.loads(self.run_cli(0, "--status").strip().splitlines()[-1])
        self.assertEqual((r["time"], r["window"]), ("07:05", "07:05–07:08"))
        self.assertIn("due_at", r)
        with self.assertRaises(SystemExit):
            self.run_cli(0, "--time", "25:00")
        self.assertEqual(self.st["dawn_probe"]["time"], "07:05", "★ 非法时间不许落盘")


# ── 3. agy CLI ──────────────────────────────────────────────────────────
class _AgyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cli = load_script("agy_rotate_dawn", ROOT / "agy-rotate")
        self._pool_path = P.POOL
        P.POOL = Path(self.tmp.name) / ".agy-pool.json"
        self.cli.P = P
        self.cli._log = lambda m: None
        self.calls = []
        self.slept = []
        # ★ 不打桩的话，「未到点也照跑」那种退化会在这里真睡一小时 —— 挂住不是红。
        self.cli.time = types.SimpleNamespace(
            **{k: getattr(time, k) for k in ("time", "strftime", "localtime", "gmtime", "mktime")},
            sleep=self.slept.append)

    def tearDown(self):
        P.POOL = self._pool_path
        self.tmp.cleanup()

    def put(self, pool):
        P.save(pool)

    def run_cli(self, left, *args, probe=None):
        self.cli._dawn_sched = lambda: stub_ds(left)

        def fake_probe(subs):
            self.calls.append((list(subs), P.load().get("dawn_probe", {}).get("state")))
            if probe:
                return probe(subs)
            return [(s, True, "", None, {"started": True}) for s in subs]
        self.cli.cmd_probe = fake_probe
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.cli.cmd_dawn_probe(list(args))
        return buf.getvalue()


POOL3 = {"accounts": {"a": {"label": "A"}, "b": {"label": "B", "rotate_off": True},
                      "c": {"label": "C"}}}


class AgyDawn(_AgyBase):
    def test_off_by_default(self):
        self.put(json.loads(json.dumps(POOL3)))
        self.run_cli(-1)
        self.assertEqual(self.calls, [], "★★★ 默认就在花钱")

    def test_claims_the_day_before_probing(self):
        self.put({**json.loads(json.dumps(POOL3)), "dawn_probe": {"enabled": True}})
        self.run_cli(-1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1], "running",
                         "★★★ 探针被调用时盘上还没占天 —— 并发窗口里就是整池双重计费")
        d = P.load()["dawn_probe"]
        self.assertEqual((d["state"], d["ok"], d["total"], d["started"]), ("done", 2, 2, 2))
        self.assertEqual(d["date"], time.strftime("%Y-%m-%d"))

    def test_only_rotating_accounts_are_probed(self):
        pool = json.loads(json.dumps(POOL3))
        pool["accounts"]["c"]["auth_dead"] = True
        pool["dawn_probe"] = {"enabled": True}
        self.put(pool)
        orig = P.is_dead
        self.addCleanup(setattr, P, "is_dead", orig)
        P.is_dead = lambda a: bool(a.get("auth_dead"))
        self.run_cli(-1)
        self.assertEqual(self.calls[0][0], ["a"], "★★ 停用轮换 / 失效的号也被探了（花钱）")

    def test_not_due_and_already_done_do_nothing(self):
        self.put({**json.loads(json.dumps(POOL3)), "dawn_probe": {"enabled": True}})
        self.run_cli(3600)
        self.assertEqual((self.calls, self.slept), ([], []), "★★ 没到点就跑了 / 在进程里睡一小时")
        self.assertNotIn("date", P.load()["dawn_probe"], "★ 没到点却占了天 —— 今天就再也不会跑了")
        self.run_cli(-1)
        self.run_cli(-1)
        self.assertEqual(len(self.calls), 1, "★★ 一天跑了两次")

    def test_running_elsewhere_blocks_even_force(self):
        self.put({**json.loads(json.dumps(POOL3)), "dawn_probe": {
            "enabled": True, "date": time.strftime("%Y-%m-%d"), "state": "running", "at": int(time.time())}})
        self.run_cli(-1, "--force")
        self.assertEqual(self.calls, [], "★★★ --force 插进了另一个正在跑的进程")

    def test_crash_is_recorded_as_failed(self):
        self.put({**json.loads(json.dumps(POOL3)), "dawn_probe": {"enabled": True}})

        def boom(subs):
            raise RuntimeError("agy 崩了")
        with self.assertRaises(RuntimeError):
            self.run_cli(-1, probe=boom)
        d = P.load()["dawn_probe"]
        self.assertEqual(d["state"], "failed")
        self.assertEqual(d["date"], time.strftime("%Y-%m-%d"), "★ 崩了不许抹掉占天 —— 可能已经花过钱")

    def test_close_to_due_sleeps_then_runs_and_no_wait_never_sleeps(self):
        self.put({**json.loads(json.dumps(POOL3)), "dawn_probe": {"enabled": True}})
        self.run_cli(30, "--no-wait")
        self.assertEqual((self.calls, self.slept), ([], []), "★ app 内补跑持着 IPC，不能睡")
        self.run_cli(30)
        self.assertEqual(len(self.slept), 1)
        self.assertAlmostEqual(self.slept[0], 30, delta=2)
        self.assertEqual(len(self.calls), 1, "差不到一分钟要睡到那一秒再跑")

    def test_tick_is_silent_and_time_round_trips(self):
        self.put({**json.loads(json.dumps(POOL3)), "dawn_probe": {"enabled": True}})
        self.assertEqual(self.run_cli(3600, "--tick"), "")
        self.run_cli(0, "--time", "21:30")
        r = json.loads(self.run_cli(0, "--status").strip().splitlines()[-1])
        self.assertEqual((r["time"], r["window"], r["targets_today"]), ("21:30", "21:30–21:33", ["A", "C"]))


class AgyDawnConcurrency(unittest.TestCase):
    """真进程并发：3 个同时起，只有 1 个进得了探针。`cmd_probe` 在子进程里打桩（不花钱）。"""

    def test_three_at_once_probe_once(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".agy-pool.json").write_text(json.dumps(
                {**POOL3, "dawn_probe": {"enabled": True}}), encoding="utf-8")
            hits = Path(d, "hits")
            drv = Path(d, "drv.py")
            drv.write_text(textwrap.dedent("""
                import importlib.machinery, importlib.util, sys, time
                loader = importlib.machinery.SourceFileLoader("ar", sys.argv[1])
                spec = importlib.util.spec_from_loader("ar", loader)
                m = importlib.util.module_from_spec(spec); loader.exec_module(m)
                def probe(subs):
                    with open(sys.argv[2], "a") as fh: fh.write("x\\n")
                    time.sleep(0.5)
                    return [(s, True, "", None, None) for s in subs]
                m.cmd_probe = probe
                m._log = lambda s: None
                m.cmd_dawn_probe(["--no-wait"])
            """), encoding="utf-8")
            env = dict(os.environ, AGY_POOL_STORE=d, CODEX_ROTATE_DAWN_JITTER="0", AGY_KEYRING="0")
            Path(d, ".agy-pool.json").write_text(json.dumps(
                {**POOL3, "dawn_probe": {"enabled": True, "time": "00:00"}}), encoding="utf-8")
            ps = [subprocess.Popen([sys.executable, str(drv), str(ROOT / "agy-rotate"), str(hits)],
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
            for p in ps:
                p.communicate(timeout=60)
            self.assertEqual(hits.read_text().count("x"), 1, "★★★ 并发进了不止一个 —— 整池双重计费")


# ── 4. agy 档位 ─────────────────────────────────────────────────────────
class AgyTier(unittest.TestCase):
    def test_plan_of(self):
        self.assertEqual(P.plan_of("g1-ultra-lite-tier"), "ultra")
        self.assertEqual(P.plan_of("g1-pro-tier"), "pro")
        self.assertEqual(P.plan_of(None), "free")
        self.assertEqual(P.plan_of("g1-mystery"), "g1-mystery", "认不出的不许猜成 pro")

    def setUp(self):
        self.cli = load_script("agy_rotate_tier", ROOT / "agy-rotate")
        self.n = 0

    def with_fetch(self, result):
        def f(tok):
            self.n += 1
            if isinstance(result, Exception):
                raise result
            return result
        self.cli.P = types.SimpleNamespace(fetch_tier=f, TIER_TTL=P.TIER_TTL)

    def test_reads_once_a_day(self):
        self.with_fetch(({"id": "g1-ultra-lite-tier", "name": "Google AI Ultra", "plan": "ultra"}, ""))
        a = {}
        cred = {"token": {"access_token": "t"}}
        self.cli._maybe_tier(a, cred, now=1000)
        self.assertEqual((a["plan"], a["tier"]["name"], self.n), ("ultra", "Google AI Ultra", 1))
        self.cli._maybe_tier(a, cred, now=1000 + 3600)
        self.assertEqual(self.n, 1, "★ 每 3 分钟的额度刷新都去读档位 —— 一天一次就够")
        self.cli._maybe_tier(a, cred, now=1000 + P.TIER_TTL + 1)
        self.assertEqual(self.n, 2)

    def test_failure_keeps_the_old_value(self):
        a = {"plan": "ultra", "tier": {"id": "g1-ultra-lite-tier", "name": "Google AI Ultra", "at": 0}}
        for bad in ((None, "档位 HTTP 500"), OSError("down")):
            self.with_fetch(bad)
            self.cli._maybe_tier(a, {"token": {"access_token": "t"}}, now=P.TIER_TTL * 3)
            self.assertEqual(a["plan"], "ultra", "★★ 读不到把 Ultra 清成了别的（读不到 ≠ 没有）")

    def test_board_carries_plan(self):
        pool = {"accounts": {"u": {"label": "U", "plan": "ultra"}, "p": {"label": "Pp", "plan": "pro"}}}
        b = P.board(pool, "u", now=time.time())
        ents = [b["cur"]] + b["queue"] + b["rest"]
        self.assertEqual({e["aid"]: e.get("plan") for e in ents}, {"u": "ultra", "p": "pro"})


def run_agy_ts(expr):
    src = (SRC / "agy.ts").read_text(encoding="utf-8")
    src, n = re.subn(r'from "\./helpers"', 'from "%s"' % (SRC / "helpers.ts").as_posix(), src)
    assert n == 1
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "agy.ts"
        f.write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                            "import('%s').then(m => console.log(JSON.stringify(%s)))" % (f.as_posix(), expr)],
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def run_dawn_ts(expr):
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                        "import('%s').then(m => console.log(JSON.stringify(%s)))" % ((SRC / "dawn.ts").as_posix(), expr)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


# ── 5. 前端 + 接线 ──────────────────────────────────────────────────────
class TheUi(unittest.TestCase):
    def test_only_ultra_gets_a_badge(self):
        """用户拍板「只画 ULTRA」：Pro 是大多数，画出来只是噪音（同 codex 只画 PRO 的理由）。"""
        self.assertEqual(run_agy_ts('["ultra","pro","free",undefined,"ULTRA"].map(m.agyBadgePlan)'),
                         ["ultra", "", "", "", ""])

    def test_ultra_badge_is_wired_on_all_three_surfaces(self):
        # 2026-10-19：旧续航条（RunwayHero）随总览重做删除；新顶部三栏照交接包 13 不画套餐徽章 ——
        #   当前号的 ULTRA 就在它自己那张卡上（卡片网格总在 hero 正下方）。剩两个 surface。
        for p in ("components/AgyCard.tsx", "components/AgyRow.tsx"):
            self.assertRegex(code(SRC / p), r"agyBadgePlan\(", p)
        self.assertGreaterEqual(len(re.findall(r"plan=\{a\.plan\}", code(SRC / "components" / "ov" / "Overview.tsx"))), 1)
        self.assertGreaterEqual(len(re.findall(r"plan=\{a\.plan\}", code(SRC / "MenuBar.tsx"))), 1)

    def test_catch_up_waits_for_the_random_minute(self):
        f = 'm.dawnCatchUpDue({enabled:true,date:"2026-10-14",due_at:1000},"2026-10-15",%d)'
        self.assertFalse(run_dawn_ts(f % 999), "★ 补跑跳过了随机偏移")
        self.assertTrue(run_dawn_ts(f % 1000))
        self.assertFalse(run_dawn_ts('m.dawnCatchUpDue({enabled:true,date:"2026-10-15",due_at:1},"2026-10-15",9)'))
        self.assertFalse(run_dawn_ts('m.dawnCatchUpDue({enabled:false,due_at:1},"2026-10-15",9)'))

    def test_the_chip_is_on_both_tabs_and_left_settings(self):
        app = code(SRC / "components" / "ov" / "Overview.tsx")   # 2026-10-19 起头部在总览组件里
        self.assertIn('<DawnChip t={p.t} kind="codex"', app)
        self.assertIn('<DawnChip t={p.t} kind="agy"', app)
        settings = code(SRC / "pages" / "SettingsPage.tsx")
        for gone in ("dawn-probe", "dawnDesc", "toggleDawn"):
            self.assertNotIn(gone, settings, "★ 设置页还留着一份 —— 两处开关迟早分叉")

    def test_the_chip_label_is_short_and_has_no_emoji(self):
        chip = code(SRC / "components" / "DawnChip.tsx")
        self.assertRegex(chip, r"定时 \{rec == null \? \"—\" : on \? \"开\" : \"关\"\}")
        self.assertNotIn("⏰", chip, "设计语言不用 emoji 当图标")
        self.assertIn("<svg", chip)
        self.assertIn('type="time"', chip, "点开才有时间选择")
        # ★ 像素里实测过：`title` 原样露出 `**还没有任何一次运行记录**`（tooltip 不渲染 markdown）。
        self.assertRegex(chip, r'const desc = dawnDesc\(rec, kind\)\.replace\(/\\\*\\\*/g, ""\);')
        self.assertIn("title={desc}", chip)

    def test_catch_up_runs_both_kinds_without_waiting(self):
        hook = code(SRC / "hooks" / "useDawnProbe.ts")
        # ★ 两家各一处 —— 只查「出现过」会被 codex 那一处单独兜绿。
        self.assertIn('invoke("run_rotate", { args: ["dawn-probe", "--no-wait"] })', hook)
        self.assertIn('invoke("run_agy_rotate", { args: ["dawn-probe", "--no-wait"] })', hook)
        self.assertIn("dawnCatchUpDue", hook)


class Wiring(unittest.TestCase):
    def test_both_installers_install_agydawn_with_the_store(self):
        sh = (ROOT / "scripts" / "install-launchd.sh").read_text(encoding="utf-8")
        i = sh.index("emit agydawn")
        self.assertIn('agy-rotate" dawn-probe --tick', sh[i:i + 400])
        self.assertIn("StartInterval", sh[i:i + 400])
        # ★ 打在代码形态上：上面那行注释里也写着 AGY_POOL_STORE（verification.md 形态⑫）。
        env_line = [ln for ln in sh[:i].splitlines() if ln.startswith("ENV_EXTRA=")][-1]
        self.assertIn("<key>AGY_POOL_STORE</key><string>$STORE</string>", env_line)
        ps = (ROOT / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")
        self.assertRegex(ps, r'Name = "agydawn";[^\n]*AGY_POOL_STORE = \$Store')
        self.assertRegex(ps, r'-notin @\("dawnprobe",\s*"agydawn"\)', "★ 装 ≠ 现在就跑一次计费任务")

    def test_rust_allows_and_logs_it(self):
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        # ★ 只看 `run_agy_rotate` 那份白名单 —— codex 的 `ALLOWED_CMDS` 早就有 dawn-probe。
        i = rs.index("fn run_agy_rotate")
        agy_allowed = re.search(r"const ALLOWED: &\[&str\] = &\[([^\]]*)\]", rs[i:]).group(1)
        self.assertIn('"dawn-probe"', agy_allowed, "★★ 胶囊点了开关，Rust 侧拒绝执行")
        self.assertIn('("agydawn", "agydawn.log")', rs)

    def test_the_bundle_ships_dawn_sched(self):
        conf = json.loads((ROOT / "codexbar" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        res = conf["bundle"]["resources"]
        self.assertEqual(res.get("../../dawn_sched.py"), "scripts/dawn_sched.py",
                         "★★ 装好的 app 里两个 CLI 都会在 `_dawn_sched()` 那一行炸")


if __name__ == "__main__":
    unittest.main()
