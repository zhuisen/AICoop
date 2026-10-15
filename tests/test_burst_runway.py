"""全池续航改按「连续使用时间」算（2026-10-15，用户：「全池续航≈98.6 小时，为什么还是那么多？
实际使用下来会出现不到半小时几张账号额度都没了，应该要按这种情况去分配」→ 选「改续航显示」）。

## 实测（当天，`codex-rotate next` + 带 `w` 的 quota_marks）
- 一个 Plus 号 5h 从满到 0 ≈ **连续 4 分钟**（3 次用完事件）。
- 1pp 的 5h ≈ **0.156pp** 的周（2 个号、77pp 的 5h，~2h 数据）⇒ 一整窗 5h ≈ 周的 15–16%。
- ⇒ 此刻全池能连续用 ≈ 16 分钟，之后等 ~2.5h 回满；本周还能连续用 ≈ 2.4 小时。
- 旧的「99.5 小时」= 周剩余 ÷ 近 2.1h **含空闲**的平均速度：对连续干活没有意义。

## 守的
1. `_wk_per_5h`：只拿**有 5h 窗口**的号算比值；5h 消耗不足 `BURST_MIN_5H_PP` ⇒ `None`（不是 0）。
2. `_burst`：现在能连续用 = Σ min(5h 剩余可用分钟, 周剩余可用分钟)；本周 = Σ 周剩余可用分钟；
   回满 = 5h 没满的号里最早的重置；比值缺失时周那半 `None`、5h 那半照算。
3. `next --json` 带出 `burst`。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    loader = importlib.machinery.SourceFileLoader("cr_burst", str(ROOT / "codex-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


CR = _load()
NOW = 1_900_000_000.0


def mk(aid, w, pcts, t0=NOW - 3600):
    return [{"aid": aid, "t": t0 + i, "from": a, "to": b, "w": w} for i, (a, b) in enumerate(zip(pcts, pcts[1:]))]


class Ratio(unittest.TestCase):
    def test_weekly_pp_per_5h_pp(self):
        ms = mk("A", 300, list(range(0, 61))) + mk("A", 10080, list(range(0, 10)))   # 60 → 9
        self.assertAlmostEqual(CR._wk_per_5h(ms), 0.15)

    def test_pro_weekly_marks_are_not_mixed_in(self):
        """★ Pro 没有 5h 窗口，它的周消耗混进来会把比值拉歪（Pro 周预算大 7 倍）。"""
        ms = mk("A", 300, list(range(0, 61))) + mk("A", 10080, list(range(0, 10))) \
            + mk("P", 10080, list(range(0, 41)))
        self.assertAlmostEqual(CR._wk_per_5h(ms), 0.15)

    def test_too_little_5h_burn_is_none_not_zero(self):
        self.assertIsNone(CR._wk_per_5h(mk("A", 300, list(range(0, 20))) + mk("A", 10080, [0, 3])))

    def test_resets_and_unwindowed_marks_do_not_count(self):
        ms = mk("A", 300, list(range(0, 61))) + mk("A", 10080, list(range(0, 10))) \
            + [{"aid": "A", "t": NOW, "from": 100, "to": 0, "w": 300},
               {"aid": "A", "t": NOW, "from": 0, "to": 50}]
        self.assertAlmostEqual(CR._wk_per_5h(ms), 0.15)


def acct(left, per=4.0, wk=100, rem5=100, r5=None, usable=True):
    return {"eta": {"left_min": left, "per_window_min": per} if left is not None else None,
            "wk": wk, "rem5": rem5, "r5": r5, "usable": usable}


class Burst(unittest.TestCase):
    def test_now_and_week_in_continuous_minutes(self):
        b = CR._burst([acct(4.0), acct(4.0), acct(0.5, rem5=12, wk=86)], 0.156, NOW)
        self.assertAlmostEqual(b["now_min"], 8.5)
        # 周 pp 每分钟 = 0.156 × 100 / 4 = 3.9 ⇒ (100+100+86)/3.9
        self.assertAlmostEqual(b["week_min"], 286 / 3.9, places=1)

    def test_weekly_caps_the_5h_share(self):
        """★★ 5h 满格但周只剩 2% 的号，连续用不了 4 分钟。"""
        b = CR._burst([acct(4.0, wk=2)], 0.156, NOW)
        self.assertAlmostEqual(b["now_min"], 2 / 3.9, delta=0.05)

    def test_cooling_accounts_count_for_the_week_and_refill_but_not_now(self):
        b = CR._burst([acct(4.0), acct(2.0, rem5=50, wk=84, r5=NOW + 9000, usable=False)], 0.156, NOW)
        self.assertAlmostEqual(b["now_min"], 4.0, msg="★ 冷却中的号（如刚吃 429）此刻挑不到，不算进「现在能用」")
        self.assertAlmostEqual(b["week_min"], 184 / 3.9, places=1)
        self.assertAlmostEqual(b["refill_h"], 2.5)

    def test_refill_is_the_earliest_unfull_window(self):
        b = CR._burst([acct(4.0, r5=NOW + 3600), acct(1.0, rem5=25, r5=NOW + 7200),
                       acct(0.0, rem5=0, r5=NOW + 5400, usable=False)], 0.156, NOW)
        self.assertAlmostEqual(b["refill_h"], 1.5, msg="★ 满格号的 reset 不算「回满」")

    def test_no_ratio_keeps_the_5h_half(self):
        b = CR._burst([acct(4.0), acct(2.0)], None, NOW)
        self.assertAlmostEqual(b["now_min"], 6.0)
        self.assertIsNone(b["week_min"], "★ 比值样本不够 ⇒ 周那半说不知道，不是 0")

    def test_no_history_at_all_is_none(self):
        self.assertIsNone(CR._burst([acct(None)], 0.156, NOW))


class Wired(unittest.TestCase):
    def test_next_json_carries_burst(self):
        src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
        body = src[src.index("def cmd_next"):src.index("def _merge_exhaust")]
        self.assertIn('"burst": _burst(', body)


if __name__ == "__main__":
    unittest.main()
