"""t/s 三方评审修正（2026-10-22，计划 `~/Downloads/aicoop_tps_review_20261022/PLAN.md`，用户拍板）。

逐条行为闸，全部打在 `traffic/requests.py` 的生产函数上（不抄公式）：
Codex 首字取开头连续推理项的最后一项 · Claude span 整包守卫 · Grok 估值 · agy 缺 ttft 估值 ·
速度字段整组替换 · 首字中位只取实测 · 「今日 · 均」不跨 AI。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("req_fix", ROOT / "traffic" / "requests.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def codex_state():
    return {"first": None, "rfirst": False, "rlead": None, "rrun": False}


class CodexUsesTheLastLeadingReasoningItem(unittest.TestCase):
    def rec(self):
        return {"t_start": 0.0, "t_end": 6.0, "output": 1000, "reasoning": 600, "ttft_ms": None}

    def test_two_reasoning_items_then_text(self):
        st = codex_state()
        for ts, r in ((1.0, True), (3.0, True), (4.0, False), (5.0, True)):
            R._codex_out(st, ts, r)
        self.assertEqual((st["first"], st["rlead"]), (1.0, 3.0), "首字 = 开头连续推理的最后一项，后面插进来的推理不算")
        got = R._codex_timing(self.rec(), st["rlead"])
        self.assertEqual((got["ttft_ms"], got["tps"], got["est"]), (3000, 133.3, False), "400 可见 ÷ (6 − 3) s")

    def test_first_item_not_reasoning_has_no_ttft(self):
        st = codex_state()
        R._codex_out(st, 2.0, False)
        R._codex_out(st, 3.0, True)
        self.assertIsNone(st["rlead"])


class ClaudeBufferedSpansAreEstimates(unittest.TestCase):
    def span(self, dur, ttft, out):
        return {"i": 1, "cr": 0, "cw": 0, "out": out, "dur": dur, "ttft": ttft, "t0": 0.0, "t1": dur / 1000.0,
                "model": "m", "sess": "s"}

    def test_buffered_span_is_demoted(self):
        r = R._claude_rec("rid", None, self.span(10000, 9600, 300), {})
        self.assertTrue(r["est"], "生成段 400 ms 只占 4% 且 750 t/s ⇒ 整包（低于上限，只有「快 + 短」挡得住）")
        self.assertEqual(r["tps"], 30.0)

    def test_a_short_normal_tool_use_stays_measured(self):
        """★ 本机实测：单用占比会把一半 Claude 实测砍掉 —— tool_use 输出短、首字长，生成段本来就短。"""
        r = R._claude_rec("rid", None, self.span(5000, 4000, 120), {})
        self.assertEqual((r["tps"], r["est"]), (120.0, False))

    def test_streamed_span_is_measured(self):
        r = R._claude_rec("rid", None, self.span(10000, 3000, 700), {})
        self.assertEqual((r["tps"], r["est"]), (100.0, False))

    def test_over_the_ceiling_is_demoted(self):
        r = R._claude_rec("rid", None, self.span(1000, 0, 5000), {})
        self.assertTrue(r["est"], "> TPS_CEIL 的「实测」不可信")


class AgyMissingTtftIsAnEstimate(unittest.TestCase):
    def test_missing_ttft(self):
        self.assertEqual(R.agy_tps(500, 400, None, 5), (100.0, True))
        self.assertEqual(R.agy_tps(500, 400, 1.0, 5), (100.0, False))


class GrokIsAlwaysAnEstimate(unittest.TestCase):
    def test_source(self):
        src = (ROOT / "traffic" / "requests.py").read_text(encoding="utf-8")
        body = src[src.index("def _grok_updates("):src.index("def _do_grok(")]
        body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        self.assertRegex(body, r'"tps": _div\(out, api / 1000\.0[^)]*\), "est": True')


class SpeedFieldsAreReplacedTogether(unittest.TestCase):
    OLD = {"key": "k", "platform": "claude", "tps": 120.0, "est": False, "ttft_ms": 900, "gen_ms": 5000,
           "total_ms": 5900, "account": "本机"}

    def test_a_new_null_speed_replaces_the_old_number(self):
        got = R._merge(dict(self.OLD), {"key": "k", "tps": None, "est": True, "ttft_ms": None, "total_ms": 5900})
        self.assertEqual((got["tps"], got["est"], got["ttft_ms"]), (None, True, None), "旧算法的 120 复活了")

    def test_a_partial_update_keeps_the_speed(self):
        got = R._merge(dict(self.OLD), {"key": "k", "account": "plus1"})
        self.assertEqual((got["tps"], got["account"]), (120.0, "plus1"), "只补账号的更新不许抹掉速度")


class TtftMedianAndTodayAverage(unittest.TestCase):
    def test_ttft_median_ignores_estimates(self):
        rs = [{"tps": 100.0, "est": False, "ttft_ms": 2000}, {"tps": 20.0, "est": True, "ttft_ms": 12000},
              {"tps": 25.0, "est": True, "ttft_ms": 14000}]
        self.assertEqual(R._day_stats(rs)["ttft_median_s"], 2.0)

    def test_live_today_average_is_not_cross_ai(self):
        src = (ROOT / "traffic" / "requests.py").read_text(encoding="utf-8")
        body = src[src.index("def build_live("):src.index("def main(")]
        body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotRegex(body, r'"avg_tps": ds\["avg_tps"\]', "「今日 · 均」又把四家混在一起取中位")
        self.assertIn("if len(meas_p) == 1 else None", body)


if __name__ == "__main__":
    unittest.main()
