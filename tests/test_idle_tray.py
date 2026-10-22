"""空闲托盘「选谁上菜单栏」（AICoop 交接包 2026-10-21 · `11_idle/P11_Spec` §2 / `P11_Final` ①）。

纯逻辑在 `codexbar/src/idleTray.ts`（零 import），这里用 `node --experimental-strip-types` 跑真文件。
夹具取自 `P11_Final` 画板的那张表（Codex 1240 请求 67% · Claude 860 40% · Gemini 310 86% ·
Kimi 22 70% · DeepSeek 9 6% · Grok 未接入），画板给出的结果是「Codex 常驻 · Claude 常驻 · DeepSeek 插队」。
"""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURE = ROOT / "codexbar" / "src" / "idleTray.ts"
H = 3600 * 1000
NOW = 1_800_000_000_000


def _node(expr):
    script = ("import('file://%s').then(m => { const v = (%s); console.log(JSON.stringify(v)); });"
              % (PURE.as_posix(), expr))
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip()[:1] in "[{\"tfn0123456789-"]
    if not out:
        raise AssertionError("node 没有产出结果：\nstdout=%s\nstderr=%s" % (r.stdout, r.stderr[-800:]))
    return json.loads(out[-1])


def P(key, req, tok, rem, ago_h):
    return {"key": key, "requests": req, "tokens": tok, "remaining": rem,
            "lastUsedAt": None if ago_h is None else NOW - int(ago_h * H)}


BOARD = [
    P("codex", 1240, 8.8e9, [67, 80], 0.2),
    P("claude", 860, 11.2e9, [40], 1.5),
    P("agy", 310, 4.3e8, [86], 3),
    P("kimi", 22, 3e7, [70], 240),
    P("deepseek", 9, 1e5, [6], 96),
    P("grok", 0, 0, [], 24 * 7 + 1),
]


def pick(ps, slots=3, by="requests", pinned=(), now=NOW, keep=None):
    o = {"slots": slots, "rankBy": by, "pinned": list(pinned), "now": now}
    if keep is not None:
        o["keep"] = keep
    return _node("m.pickIdleSlots(%s, %s)" % (json.dumps(ps), json.dumps(o)))


class PickIdleSlots(unittest.TestCase):
    def test_the_board_example(self):
        got = pick(BOARD)
        self.assertEqual([(s["key"], s["kind"]) for s in got],
                         [("codex", "resident"), ("claude", "resident"), ("deepseek", "insert")],
                         "★★ 与 P11_Final 画板的结果不一致")
        self.assertEqual([s["red"] for s in got], [False, False, True], "★ 只有剩 <10% 的那家带红点")
        self.assertEqual(got[0]["remaining"], 67, "★ 一家的数 = 各窗口里剩得最少的那个")

    def test_without_a_low_one_the_most_recent_takes_the_dynamic_slot(self):
        ps = [p for p in BOARD if p["key"] != "deepseek"]
        got = pick(ps)
        self.assertEqual([s["key"] for s in got], ["codex", "claude", "agy"], "★ 动态位 = 24h 内最近用过的非常驻")

    def test_dynamic_slot_stays_empty_rather_than_padding(self):
        ps = [P("codex", 10, 1, [50], 0.1), P("claude", 5, 1, [50], 0.1), P("kimi", 1, 1, [50], 30)]
        self.assertEqual([s["key"] for s in pick(ps)], ["codex", "claude"], "★★ 24h 外的不凑数，胶囊变窄")

    def test_two_slots_means_residents_only(self):
        self.assertEqual([s["key"] for s in pick(BOARD, slots=2)], ["codex", "claude"])

    def test_pinned_wins_and_never_more_than_two(self):
        got = pick(BOARD, pinned=["kimi", "agy", "grok"])
        self.assertEqual([s["key"] for s in got[:2]], ["agy", "kimi"], "★★ 固定的优先（最多 2 家），常驻按排名降序")
        self.assertTrue(all(s["pinned"] for s in got[:2]))
        self.assertEqual(got[2]["key"], "deepseek", "插队仍然只抢动态位")

    def test_rank_by_tokens(self):
        got = pick(BOARD, by="tokens")
        self.assertEqual([s["key"] for s in got[:2]], ["claude", "codex"], "★ 排序依据 = Token 数时 Claude 在前")

    def test_low_but_unused_does_not_insert(self):
        ps = [P("codex", 10, 1, [50], 0.1), P("claude", 5, 1, [50], 0.1), P("grok", 0, 0, [3], None)]
        self.assertEqual([s["key"] for s in pick(ps)], ["codex", "claude"], "★ 插队要求统计窗口内用过")

    def test_unknown_quota_is_gray_not_full_or_empty(self):
        got = _node("m.tightest([])"), _node("m.tightest([null, null])"), _node("m.tightest([30, 80])")
        self.assertEqual(got, (None, None, 30), "★★ 读不到 = null（整只灰色剪影），绝不当 100 或 0")

    def test_one_unknown_window_makes_the_platform_unknown(self):
        self.assertIsNone(_node("m.tightest([null, 100])"),
                          "★★ 有一个窗口读不到 ⇒ 最紧的那个可能就是它 ⇒ 未知（同 `agyTightest`；丢掉 null 会把 [未知, 100] 画成满）")

    def test_red_dot_uses_the_displayed_integer(self):
        self.assertEqual(_node("[m.isLow(9.6), m.isLow(9.4), m.isLow(null), m.isLow(0)]"), [False, True, False, True])


class FrozenResidents(unittest.TestCase):
    def test_kept_residents_hold_their_order_within_the_day(self):
        got = pick(BOARD, by="tokens", keep=["codex", "claude"])
        self.assertEqual([s["key"] for s in got[:2]], ["codex", "claude"],
                         "★★ 白天不换位：按 token 排 Claude 在前，但今天冻结的顺序是 Codex、Claude")

    def test_a_kept_one_that_vanished_is_refilled_by_rank(self):
        ps = [p for p in BOARD if p["key"] != "codex"]
        got = pick(ps, keep=["codex", "claude"])
        self.assertEqual([s["key"] for s in got[:2]], ["claude", "agy"], "冻结的那家没了 ⇒ 按排名补")

    def test_pinned_still_beats_kept(self):
        got = pick(BOARD, keep=["codex", "claude"], pinned=["kimi"])
        self.assertEqual(sorted(s["key"] for s in got[:2]), ["codex", "kimi"], "★ 固定的永远优先")


class UsageOf(unittest.TestCase):
    def test_window_sums_and_last_hour(self):
        now = _node("new Date(2026, 9, 21, 15, 30).getTime()")
        p = {"days": {"2026-10-21": {"total": 100, "rounds": 3}, "2026-10-08": {"total": 7, "rounds": 1},
                      "2026-10-07": {"total": 999, "rounds": 99}},
             "hours": {"2026-10-21T09": {"total": 50, "rounds": 1}, "2026-10-21T14": {"total": 0, "rounds": 0},
                       "2026-10-20T23": {"total": 5, "rounds": 1}}}
        got = _node("m.usageOf(%s, 14, %d)" % (json.dumps(p), now))
        self.assertEqual((got["requests"], got["tokens"]), (4, 107), "★ 14 天窗口含今天往回 13 天，10-07 在窗口外")
        self.assertEqual(got["lastUsedAt"], _node("new Date(2026, 9, 21, 10).getTime()"),
                         "★ 最近一次 = 最后一个有 token 的小时桶的末尾（14 点那格是 0，不算）")

    def test_missing_platform_is_unused_not_an_error(self):
        self.assertEqual(_node("m.usageOf(undefined, 14, 0)"), {"requests": 0, "tokens": 0, "lastUsedAt": None})


def cells(ps, slots, scope="used", mx=4, unconnected=False, by="requests"):
    return _node("m.panelCells(%s, %s, %s)" % (json.dumps(ps), json.dumps(slots), json.dumps(
        {"scope": scope, "max": mx, "showUnconnected": unconnected, "rankBy": by})))


def PI(key, req, rem, main, ago_h=1, reset="↻ 1h00m"):
    p = P(key, req, req * 1000, rem, ago_h)
    p.update({"main": main, "reset": reset})
    return p


PANEL = [PI("codex", 1240, [67, 80], 67), PI("claude", 860, [40], 40), PI("agy", 310, [86], 86),
         PI("kimi", 22, [], None, reset=""), PI("deepseek", 9, [6], None, reset=""), PI("grok", 0, [], None, None, "")]


class PanelCells(unittest.TestCase):
    def setUp(self):
        self.bar = pick([p for p in PANEL])

    def test_menubar_ones_first_then_by_rank_and_unconnected_hidden(self):
        got = cells(PANEL, self.bar)
        self.assertEqual([c["key"] for c in got], ["codex", "claude", "deepseek", "agy"],
                         "★★ 托盘那几家在前（顺序同托盘），其余按排名接；Kimi 未接入默认不显示")
        self.assertEqual([c["inBar"] for c in got], [True, True, True, False])
        self.assertEqual(got[2]["main"], None, "★ 托盘里的那家读不到 5h 也照样显示，大数字写 —")

    def test_scope_bar_and_all(self):
        self.assertEqual([c["key"] for c in cells(PANEL, self.bar, scope="bar")], ["codex", "claude", "deepseek"])
        got = cells(PANEL, self.bar, scope="all", mx=8, unconnected=True)
        self.assertEqual([c["key"] for c in got], ["codex", "claude", "deepseek", "agy", "kimi", "grok"],
                         "全部 + 显示未接入：没用过的 grok 也在，排最后")

    def test_max_four_and_low_flag(self):
        self.assertEqual(len(cells(PANEL, self.bar, scope="all", mx=4, unconnected=True)), 4)
        low = cells([PI("codex", 5, [9.4], 9.4)], [])
        self.assertTrue(low[0]["low"], "剩 9.4% 显示 9 ⇒ 红")


class Rerank(unittest.TestCase):
    def test_only_across_midnight_while_idle_and_not_hovered(self):
        day = _node("m.dayKey(%d)" % NOW)
        self.assertTrue(_node("m.shouldRerank(null, %d, false, true)" % NOW), "第一次总是要")
        self.assertFalse(_node("m.shouldRerank(%s, %d, true, false)" % (json.dumps(day), NOW)), "同一天不重算")
        nxt = NOW + 24 * H
        self.assertTrue(_node("m.shouldRerank(%s, %d, true, false)" % (json.dumps(day), nxt)))
        self.assertFalse(_node("m.shouldRerank(%s, %d, false, false)" % (json.dumps(day), nxt)), "★ 有 AI 在跑时不换")
        self.assertFalse(_node("m.shouldRerank(%s, %d, true, true)" % (json.dumps(day), nxt)), "★ 鼠标在托盘上不换")


class RanksByTokensByDefault(unittest.TestCase):
    """用户 2026-10-22「空闲时展示的 AI 不是按最近 14 天使用 token 量最多的排序吗？不是的话要这样按照」。
    设置整份写盘 ⇒ 老用户存着旧默认「请求数」，必须迁移一次；迁移后再选「请求数」要保留。"""

    def setUp(self):
        import re
        src = (ROOT / "codexbar/src/pages/SettingsPage.tsx").read_text(encoding="utf-8")
        self.src = re.sub(r"//[^\n]*", "", re.sub(r"/\*[\s\S]*?\*/", "", src))

    def test_default_is_tokens_over_14_days(self):
        d = self.src[self.src.index("const DEFAULTS"):]
        d = d[:d.index("};")]
        self.assertRegex(d, r'idleRankBy:\s*"tokens",')
        self.assertRegex(d, r"idleDays:\s*14,")

    def test_stored_old_default_is_migrated_once(self):
        load = self.src[self.src.index("function load()"):]
        load = load[:load.index("function save(")]
        self.assertRegex(load, r'if \(!raw\.idleRankMigrated\) \{ raw\.idleRankBy = "tokens"; raw\.idleRankMigrated = true; \}')
        self.assertLess(load.index("idleRankMigrated"), load.index("...raw"), "迁移要在合并进结果之前")


if __name__ == "__main__":
    unittest.main()
