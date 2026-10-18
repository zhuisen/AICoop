"""agy 5h 倒计时的真假 + 探针「探完 5h 启动了没有」（2026-10-15，用户：按第一种修 + 类似 codex 的探针用法）。

## 实测起因
云端 `retrieveUserQuotaSummary` 里**没用过的桶** `resetTime` 恒为「读数时刻 + 整窗」：
当天两个闲置号的 5h 都是 `reset − quota_at = 5.000h`，每 3 分钟刷新就往后挪 3 分钟；
历史采样 2902 次满格读数里 2773 次（95.6%）是这个形态。而用过的桶 reset 是钉死的
（用过的那个号 09:15 / 09:18 / 09:21 三次都是 14:14:27；历史连续读数 710/712 不动）。
本机 RPC 时代 `agy-quota::_note_anchors` 记过锚点账本、UI 能说「未启动」；改走云端后没接上。

## 这里守的
1. `agy-rotate quota` 按号按桶喂账本，判定落兄弟键 `quota_anchor`（自带 reset）；
   board / 卡 / 菜单栏据此把滑动的窗口说成「未启动」，钉死的照常倒计时。
2. `agy-rotate probe` 探前/探后各免费读一次 5h：**降了**才算窗口启动、才 `note_billed`；
   没降就如实说「未见下降」，不说启动了。
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agy import pool as P  # noqa: E402

SRC = ROOT / "codexbar" / "src"
T0 = 1_900_000_000


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def summary(now, frac5=1.0, reset5=None, fracw=0.98, resetw=T0 + 5 * 86400):
    """Gemini 5h + 周。`reset5=None` = 闲置桶（读数时刻 + 5h，跟着 now 滑）。"""
    return [{"displayName": "Gemini Models", "buckets": [
        {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": frac5,
         "resetTime": iso(reset5 if reset5 else now + 5 * 3600)},
        {"bucketId": "gemini-weekly", "window": "weekly", "remainingFraction": fracw,
         "resetTime": iso(resetw)}]}]


class FakeTime:
    def __init__(self, t):
        self.t = t

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def __getattr__(self, n):
        return getattr(time, n)


def load_cli():
    loader = importlib.machinery.SourceFileLoader("agy_rotate_anc", str(ROOT / "agy-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("CODEXBAR_QUOTA_ANCHORS")
        os.environ["CODEXBAR_QUOTA_ANCHORS"] = os.path.join(self.tmp.name, ".quota-anchors.json")
        self.cli = load_cli()
        self.clock = FakeTime(T0)
        self.cli.time = self.clock
        self.cli._log = lambda m: None
        self.cli._mark_live = lambda pool: None
        self.cli._refresh_one = lambda sub, a, pool, skew=120: ({"token": {"access_token": sub}}, "")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CODEXBAR_QUOTA_ANCHORS", None)
        else:
            os.environ["CODEXBAR_QUOTA_ANCHORS"] = self._old
        self.tmp.cleanup()

    def fake_p(self, pool, fetch, **extra):
        ns = dict(load=lambda: pool, fetch_quota=fetch, quota_by_group=P.quota_by_group, carry_missing_groups=P.carry_missing_groups,
                  _iso_ts=P._iso_ts, save=lambda p: None, _lock=lambda path: open(os.devnull),
                  POOL=None)
        ns.update(extra)
        self.cli.P = types.SimpleNamespace(**ns)


class TheCloudReadFeedsTheLedger(_Base):
    """三次读数（间隔 180s）：闲置 5h 每次都滑 ⇒ floating；用过的号 reset 钉死 ⇒ 不是 floating。"""

    def run_reads(self, n=3):
        pool = {"accounts": {"idle": {"label": "I"}, "used": {"label": "U"}}}
        fixed = T0 + 4 * 3600
        self.fake_p(pool, lambda tok, anchor=None: (summary(self.clock.t) if tok == "idle"
                                       else summary(self.clock.t, 0.97, fixed), ""))
        for _ in range(n):
            with redirect_stdout(io.StringIO()):
                self.cli.cmd_quota(["--json"])
            self.clock.t += 180
        return pool

    def test_the_idle_window_is_floating_and_carries_its_reset(self):
        a = self.run_reads()["accounts"]["idle"]
        v = a["quota_anchor"]["gemini-5h"]
        self.assertEqual(v["state"], "floating", "★★ 闲置窗口没被认出来 —— 卡上还是那个假倒计时")
        self.assertEqual(v["reset"], int(P._iso_ts(a["quota_summary"][0]["buckets"][0]["resetTime"])),
                         "★ 判定要自带它描述的 reset，前端靠它核身份")

    def test_a_used_window_is_not_floating(self):
        v = self.run_reads()["accounts"]["used"]["quota_anchor"]["gemini-5h"]
        self.assertNotEqual(v["state"], "floating", "★★ 钉死的窗口被说成未启动")

    def test_keys_are_per_account(self):
        """★ 云端按账号读 —— 一个号的滑动不能把另一个号的同名桶拖成 floating。"""
        pool = self.run_reads()
        self.assertNotEqual(pool["accounts"]["used"]["quota_anchor"]["gemini-5h"]["state"],
                            pool["accounts"]["idle"]["quota_anchor"]["gemini-5h"]["state"])

    def test_the_board_says_not_started_only_for_the_idle_one(self):
        pool = self.run_reads()
        b = P.board(pool, "idle", now=self.clock.t)
        five = lambda e: [w for w in e["wins"] if w["label"] == "5h"][0]["reset"]
        self.assertEqual(five(b["cur"]), "未启动")
        used = [e for e in b["queue"] + b["rest"] if e["aid"] == "used"][0]
        self.assertNotEqual(five(used), "未启动")
        self.assertRegex(five(used), r"\dh\d\dm")

    def test_board_ignores_a_verdict_for_another_reset(self):
        """★ 身份核对：判定说的是旧窗口时，不能拿来解释新窗口。"""
        pool = self.run_reads()
        a = pool["accounts"]["idle"]
        a["quota_anchor"]["gemini-5h"]["reset"] -= 3600
        five = [w for w in P.board(pool, "idle", now=self.clock.t)["cur"]["wins"] if w["label"] == "5h"][0]
        self.assertNotEqual(five["reset"], "未启动")


class TheProbeSaysWhetherThe5hWindowStarted(_Base):
    def run_probe(self, after_frac, ok=True, args=("S",)):
        pool = {"accounts": {"s": {"label": "S", "email": "s@x"}}}
        calls = []
        fixed = T0 + 5 * 3600 - 30

        def fetch(tok, anchor=None):
            calls.append(self.clock.t)
            if len(calls) == 1:
                return summary(self.clock.t), ""
            return summary(self.clock.t, after_frac, fixed if after_frac < 1 else None), ""
        self.fake_p(pool, fetch, claims=lambda x: {"sub": "s"}, read_live=lambda: None,
                    install_live=lambda c: "keyring")
        self.cli._probe_one = lambda label: (ok, "答「ok」" if ok else "agy 退出码 1", {"total_tokens": 15000}, "s@x")
        self.cli.PROBE_AFTER_GAP = 0
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.cli.cmd_probe(list(args))
        self.calls = calls
        return pool["accounts"]["s"], buf.getvalue()

    def test_a_drop_means_started_and_is_marked_billed(self):
        a, out = self.run_probe(0.996)
        q = a["last_probe"]["q5h"]
        self.assertEqual((q["before"], q["after"], q["started"]), (100.0, 99.6, True))
        self.assertIn("窗口已启动", out)
        v = a["quota_anchor"]["gemini-5h"]
        self.assertTrue(v.get("billed"), "★★ 探针启动的窗口没记成事实 —— UI 要再等 900s 才肯认")
        self.assertEqual(v["state"], "anchored")
        self.assertEqual(a["quota_summary"][0]["buckets"][0]["remainingFraction"], 0.996,
                         "★ 探后读数要落进池里（同 codex 探针写回 quota）")

    def test_no_drop_is_said_plainly_and_not_marked(self):
        a, out = self.run_probe(1.0)
        q = a["last_probe"]["q5h"]
        self.assertFalse(q["started"])
        self.assertIn("未见下降", out)
        self.assertNotIn("窗口已启动", out, "★★ 没证到却说启动了")
        self.assertFalse(a["quota_anchor"]["gemini-5h"].get("billed"))
        self.assertEqual(len(self.calls), 1 + self.cli.PROBE_AFTER_TRIES,
                         "★ 没读到下降时要按次数重读（入账可能有延迟），不是读一次就下结论")

    def test_a_failed_probe_never_marks_billed_even_if_5h_moved(self):
        a, _ = self.run_probe(0.996, ok=False)
        self.assertFalse(a["quota_anchor"]["gemini-5h"].get("billed"),
                         "★★ 探针没成功（或归属不符）却把窗口记成我们启动的")

    def test_json_carries_q5h(self):
        _, out = self.run_probe(0.996, args=("S", "--json"))
        r = json.loads(out.strip().splitlines()[-1])
        self.assertTrue(r[0]["q5h"]["started"])


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


def ts_code(p):
    s = (SRC / p).read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//[^\n]*", "", s)


class TheUiCarriesIt(unittest.TestCase):
    def test_to_snapshot_passes_the_anchor_through(self):
        code = ts_code("hooks/useAgyPool.ts")
        i = code.index("function toSnapshot(")
        self.assertIn("anchor: (b.bucketId && a.quota_anchor?.[b.bucketId]) || undefined",
                      code[i:code.index("\n}\n", i)], "★★ 判定写了没人传 —— 卡上仍是假倒计时")

    def test_the_toast_says_started_only_when_it_dropped(self):
        started = run_agy_ts('m.agyProbeToast([{label:"S",ok:true,note:"",q5h:{before:100,after:99.6,reset:%d,started:true}}])' % T0)
        self.assertIn("窗口已启动", started)
        self.assertIn("100.0% → 99.6%", started)
        flat = run_agy_ts('m.agyProbeToast([{label:"S",ok:true,note:"",q5h:{before:100,after:100,reset:null,started:false}}])')
        self.assertNotIn("已启动", flat)
        self.assertIn("未见下降", flat)
        none = run_agy_ts('m.agyProbeToast([{label:"S",ok:true,note:"",q5h:null}])')
        self.assertIn("没读到", none)
        bad = run_agy_ts('m.agyProbeToast([{label:"S",ok:false,note:"agy 退出码 1",q5h:null}])')
        self.assertTrue(bad.startswith("✗"))

    def test_the_all_pool_toast_counts(self):
        r = run_agy_ts('m.agyProbeToast([{label:"A",ok:true,note:"",q5h:{before:100,after:99,reset:1,started:true}},'
                       '{label:"B",ok:true,note:"",q5h:{before:100,after:100,reset:1,started:false}},'
                       '{label:"C",ok:false,note:"x",q5h:null}])')
        self.assertIn("2/3 可用", r)
        self.assertIn("已启动 1 个", r)
        self.assertIn("C", r)

    def test_the_gui_probe_asks_for_json_and_shows_the_toast(self):
        self.assertIn('["probe", label, "--json"]', ts_code("hooks/useAgyPool.ts"))
        self.assertEqual(ts_code("App.tsx").count("showToast(agyProbeToast(r), 8000)"), 2)


if __name__ == "__main__":
    unittest.main()
