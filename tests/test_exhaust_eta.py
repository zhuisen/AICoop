"""codex 5h「连续用还能撑多久」+ 续航只认周窗口（2026-10-15，用户点名做的 4）。

用户原话：「特别是codex，codex基本是几分钟用完的。按历史用完的次数去做预测」。

## 守的
1. `proxy._exhaust_events`：按号切窗口（回落 / 间隔 >5h），走到 ≥99 才算一次「用完」；
   配速只累加 ≤5 分钟的间隔（吃饭睡觉不算）；不足 20pp 的残段不算；不带 `w` 的旧 mark 只认 legacy 名单里的号。
2. `proxy._record_quota`：两个窗口都记 mark 且带 `w`；5h 跨进 ≥99 时往 `exhaust_log` 落一条。
3. `codex-rotate::_eta5h`：本号 ≥3 次用本号、否则借全池、全池也不够 ⇒ `None`（**不是 0**）。
4. ★★ `_runway` 只认周窗口 mark —— 旧版拿 Plus 的 5h 消耗去除周余量，续航低估约 4 倍。
5. 前端文案：`fmtEtaMin` / `eta5hTitle`；卡片与续航条都接上了。

全部打桩 `_mutate_state`，**不碰真 state.json**。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import json
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


PX = load("px_eta", ROOT / "proxy" / "proxy.py")
CR = load("cr_eta", ROOT / "codex-rotate")
T0 = 1_900_000_000.0


def window(aid, start, pcts, gap=10, w=300):
    """一段连续用的 mark：已用% 依次走过 `pcts`，相邻间隔 `gap` 秒。"""
    return [{"aid": aid, "t": start + i * gap, "from": a, "to": b, "w": w}
            for i, (a, b) in enumerate(zip(pcts, pcts[1:]))]


class ExhaustEvents(unittest.TestCase):
    def test_a_window_reaching_99_is_one_event_with_active_time(self):
        ev = PX._exhaust_events(window("A", T0, list(range(0, 101, 5))))
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["aid"], "A")
        self.assertEqual(ev[0]["pp"], 95, "首段的 from→to 没有前一点可量间隔，不计")
        self.assertAlmostEqual(ev[0]["active_s"], 190, delta=1)

    def test_a_window_that_never_reaches_99_is_not_an_event(self):
        self.assertEqual(PX._exhaust_events(window("A", T0, list(range(0, 96, 5)))), [],
                         "★★ 没用完也记成「用完」—— 配速会被拉快")

    def test_idle_gaps_are_not_active_time(self):
        ms = window("A", T0, list(range(0, 51, 5))) + window("A", T0 + 3600, list(range(50, 101, 5)))
        ev = PX._exhaust_events(ms)
        self.assertEqual(len(ev), 1, "★ 1 小时空档仍在同一窗口（<5h）")
        self.assertLess(ev[0]["active_s"], 400, "★★ 吃饭的一小时被算进了「连续用」")

    def test_a_drop_or_a_5h_gap_splits_windows(self):
        a = window("A", T0, [0, 40, 80])
        b = [{"aid": "A", "t": T0 + 30, "from": 80, "to": 2, "w": 300}] + window("A", T0 + 40, [2, 50, 99])
        ev = PX._exhaust_events(a + b)
        self.assertEqual([e["pp"] for e in ev], [49], "★ 回落之后是新窗口，前一段不能并进来")
        far = window("A", T0, [0, 40, 80]) + window("A", T0 + 6 * 3600, [80, 99])
        self.assertEqual(PX._exhaust_events(far), [], "★ 间隔 >5h 必然换了窗口，80→99 只走了 19pp")

    def test_tiny_tail_below_min_pp_is_ignored(self):
        self.assertEqual(PX._exhaust_events(window("A", T0, [85, 92, 99])), [])

    def test_weekly_marks_never_count(self):
        self.assertEqual(PX._exhaust_events(window("A", T0, list(range(0, 101, 5)), w=10080)), [])

    def test_legacy_marks_only_for_listed_accounts(self):
        ms = [{k: v for k, v in m.items() if k != "w"} for m in window("A", T0, list(range(0, 101, 5)))]
        self.assertEqual(PX._exhaust_events(ms), [], "★★ 不带 w 的旧 mark 可能是 Pro 的周窗口")
        self.assertEqual(len(PX._exhaust_events(ms, {"A"})), 1)


class _Clock:
    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now

    def __getattr__(self, k):
        return getattr(time, k)


class RecordQuotaWritesBothWindows(unittest.TestCase):
    clock = T0

    def run_headers(self, st, p, s):
        hs = [("x-codex-primary-used-percent", str(p)), ("x-codex-primary-window-minutes", "300"),
              ("x-codex-secondary-used-percent", str(s)), ("x-codex-secondary-window-minutes", "10080")]
        orig, real_time = PX._mutate_state, PX.time
        PX._mutate_state = lambda f: f(st)
        self.clock += 15        # ★ 真请求之间有间隔；同一秒里打完的话 active_s=0，事件本该被丢
        PX.time = _Clock(self.clock)
        try:
            PX._record_quota("A", hs, 200)
        finally:
            PX._mutate_state, PX.time = orig, real_time

    def test_marks_carry_w_for_both_windows_and_exhaust_is_logged(self):
        st = {"slots": {"A": {}}}
        self.run_headers(st, 0, 10)
        for i in range(1, 21):
            self.run_headers(st, 5 * i, 10 + i // 4)
        ws = {m["w"] for m in st["quota_marks"]}
        self.assertEqual(ws, {300, 10080}, "★★ 只记了一个窗口 / 没带 w —— 续航与预测都分不清单位")
        self.assertEqual(len(st.get("exhaust_log", [])), 1, "★★ 5h 跨进 ≥99 没落「用完」事件")
        self.assertEqual(st["exhaust_log"][0]["aid"], "A")

    def test_landing_exactly_on_99_counts(self):
        """★ 上游只回整数，最后一跳常是 …→99 然后 429 —— 不会再有 100 那一条。"""
        st = {"slots": {"A": {}}}
        self.run_headers(st, 0, 10)
        for p in list(range(5, 96, 5)) + [99]:
            self.run_headers(st, p, 10)
        self.assertEqual(len(st.get("exhaust_log", [])), 1)

    def test_no_event_before_crossing_99(self):
        st = {"slots": {"A": {}}}
        self.run_headers(st, 0, 10)
        for i in range(1, 20):
            self.run_headers(st, 5 * i, 10)
        self.assertEqual(st.get("exhaust_log", []), [])


class Eta(unittest.TestCase):
    def ev(self, aid, spp, n):
        return [{"aid": aid, "t": T0 + i, "active_s": spp * 100, "pp": 100} for i in range(n)]

    def test_own_history_when_enough(self):
        r = CR._eta5h(self.ev("A", 3.0, 3) + self.ev("B", 6.0, 5), "A", 50)
        self.assertEqual(r["scope"], "self")
        self.assertEqual(r["per_window_min"], 5.0)
        self.assertEqual(r["left_min"], 2.5)

    def test_falls_back_to_pool(self):
        r = CR._eta5h(self.ev("A", 3.0, 2) + self.ev("B", 6.0, 3), "A", 0)
        self.assertEqual(r["scope"], "pool")
        self.assertEqual(r["n"], 5)
        self.assertEqual(r["per_window_min"], 10.0, "中位数取 6.0 s/pp")
        self.assertEqual(r["left_min"], 10.0, "★ 已用 0% ⇒ 剩一整窗")
        self.assertEqual(CR._eta5h(self.ev("B", 6.0, 3), "B", 80)["left_min"], 2.0)

    def test_too_little_history_is_none_not_zero(self):
        self.assertIsNone(CR._eta5h(self.ev("A", 3.0, 2), "A", 10), "★★ 历史不够也给了数")

    def test_merge_dedups_by_aid_and_second(self):
        e = {"aid": "A", "t": T0 + 0.4, "active_s": 1, "pp": 30}
        self.assertEqual(len(CR._merge_exhaust([e], [dict(e, t=T0 + 0.1)], [dict(e, aid="B")])), 2)


class RunwayIgnoresNonWeeklyMarks(unittest.TestCase):
    def test_5h_and_legacy_marks_are_not_weekly_burn(self):
        now = T0
        weekly = [{"t": now - 20 * 3600 * (1 - i / 19), "from": 0, "to": 1, "w": 10080} for i in range(20)]
        five = [dict(m, w=300, to=5) for m in weekly]
        legacy = [{k: v for k, v in m.items() if k != "w"} for m in five]
        base = CR._runway(weekly, 50, [], now)["burn_pp_per_hour"]
        self.assertAlmostEqual(base, 1.0, places=1)
        self.assertEqual(CR._runway(weekly + five + legacy, 50, [], now)["burn_pp_per_hour"], base,
                         "★★★ 5h / 旧 mark 被当成周消耗 —— 续航低估约 4 倍的那个 bug")


def ts_eval(expr):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "eta5h.ts"
        f.write_text((SRC / "eta5h.ts").read_text(encoding="utf-8"), encoding="utf-8")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                            "import('%s').then(m => console.log(JSON.stringify(%s)))" % (f.as_posix(), expr)],
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def code(path):
    s = (SRC / path).read_text(encoding="utf-8")
    s = re.sub(r"\{/\*.*?\*/\}", "", s, flags=re.S)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)


class TheUi(unittest.TestCase):
    def test_minutes_format(self):
        self.assertEqual(ts_eval("[0.4, 1.9, 4, 59.6, 75].map(m.fmtEtaMin)"), ["<1m", "2m", "4m", "60m", "1h15m"])

    def test_title_says_whose_history_and_continuous_use(self):
        t = ts_eval('m.eta5hTitle({left_min:1.9,per_window_min:4,n:3,scope:"pool"})')
        for cue in ("全池", "3 次", "连续", "4m"):
            self.assertIn(cue, t)
        self.assertIn("这个号", ts_eval('m.eta5hTitle({left_min:1,per_window_min:4,n:5,scope:"self"})'))

    def test_only_the_pool_runway_shows_it(self):
        """★★ 用户 2026-10-15：「账号的连用≈4m，这些都要去除，只在 banner 全池续航展示就够了」。"""
        # 2026-10-19：全池续航从 RunwayHero 换到交接包 page5 的 `ov/OvHero::PoolHero`（「还能连续用」那栏的说明行）。
        hero = code("components/ov/OvHero.tsx")
        self.assertRegex(hero, r'eta \? <span data-eta5h="" title=\{eta5hTitle\(eta\)\}> · 5h 一窗≈\{fmtEtaMin\(eta\.per_window_min\)\}')
        self.assertRegex(hero, r'find\(\(e\) => e\?\.eta5h\?\.scope === "pool"\)', "★ 全池那块要取全池口径")
        self.assertGreaterEqual(hero.count("{etaSpan}"), 2, "★ 算得出 / 算不出续航两种说明里都要带上 5h 一窗")
        for f in ("components/AccountCard.tsx", "App.tsx", "components/ov/OvCard.tsx", "components/ov/Overview.tsx"):
            self.assertNotIn("eta5h", code(f), "★★ %s 又画回了每号的「连用≈」" % f)
        self.assertEqual(hero.count("data-eta5h"), 1, "★ 只在全池续航那一处")


if __name__ == "__main__":
    unittest.main()
