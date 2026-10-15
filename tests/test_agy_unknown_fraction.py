"""agy 桶在、`remainingFraction` 却缺席 ⇒ **读不到**，不是丢掉、不是满、不是空（2026-10-15）。

## 为什么要防一个从没见过的形状

proto3 JSON 会省略零值字段 ⇒ 见底的桶可能**根本不带** `remainingFraction`；
而上游客户端的缺省又是 1.0（满格）。两种读法方向相反，只有「不知道」在两边都成立。

旧实现把它**跳过**：同组剩下那个桶于是成了「最紧」—— 周额度见底、5h 还有 90% 的号
被画成 90%、被选号器当成有余量挑走，且没有任何一处报错。
截至 2026-10-15 `agy.log` 里 2889 次额度读数从未出现过这个形状（最低 79.4%），
所以这是**预防**，不是修复一个观测到的事故。
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agy import pool as P  # noqa: E402

SRC = ROOT / "codexbar" / "src"
RESET = "2099-01-01T00:00:00Z"


def gem(*fracs):
    """一个 Gemini 组；`None` = 那个桶不带 `remainingFraction`。"""
    wins = ["5h", "weekly"]
    out = []
    for i, f in enumerate(fracs):
        b = {"bucketId": "gemini-%s" % wins[i], "window": wins[i], "resetTime": RESET}
        if f is not None:
            b["remainingFraction"] = f
        out.append(b)
    return {"displayName": "Gemini Models", "buckets": out}


def acc(summary, label):
    return {"label": label, "quota_summary": summary, "quota": P.quota_by_group(summary)}


def ts_code(p):
    s = (SRC / p).read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//[^\n]*", "", s)


def run_agy_ts(expr, quota):
    """在 node 里跑 `agy.ts` 的真函数。它 import `./helpers` 不带扩展名，node ESM 认不出，
    所以拷一份把那一行改成绝对路径 —— 只改 import 行，函数体一字不动。"""
    src = (SRC / "agy.ts").read_text(encoding="utf-8")
    src, n = re.subn(r'from "\./helpers"', 'from "%s"' % (SRC / "helpers.ts").as_posix(), src)
    assert n == 1, "agy.ts 的 helpers import 形状变了"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "agy.ts"
        f.write_text(src, encoding="utf-8")
        script = "import('%s').then(m => { const q = %s; console.log(JSON.stringify(%s)); })" % (
            f.as_posix(), json.dumps(quota), expr)
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", script],
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class TheProjectionSaysUnknown(unittest.TestCase):
    def test_a_missing_bucket_makes_the_group_unknown_not_the_other_buckets_number(self):
        q = P.quota_by_group([gem(0.9, None)])
        self.assertIn("gemini", q, "★★ 整组被丢了 —— 读不到被折叠成「没有这一组」")
        self.assertIsNone(q["gemini"]["remaining"],
                          "★★ 缺的那格可能正是 0，不能拿 5h 的 90% 冒充最紧")

    def test_all_known_still_takes_the_tightest(self):
        self.assertEqual(P.quota_by_group([gem(0.9, 0.4)])["gemini"]["remaining"], 0.4)


class ThePickerTreatsItAsUnknown(unittest.TestCase):
    def test_known_capacity_is_picked_over_an_unknown_bucket(self):
        pool = {"accounts": {"unk": acc([gem(0.99, None)], "U"), "known": acc([gem(0.3, 0.3)], "K")}}
        self.assertEqual(P.pick(pool, None)[0], "known",
                         "★★ 一格读不到的号被当成 99% 抢在有读数的号前面")

    def test_unknown_is_not_exhausted(self):
        """读不到 ≠ 见底：它仍能在别人都不可用时被挑（同 codex 的「未知排最后」，不是踢出去）。"""
        a = acc([gem(0.99, None)], "U")
        self.assertFalse(P.is_exhausted(a))
        self.assertEqual(P.pick({"accounts": {"unk": a}}, None)[0], "unk")


class TheBoardShowsADash(unittest.TestCase):
    def test_the_window_stays_with_rem_none_and_tightest_is_unknown(self):
        pool = {"accounts": {"a": acc([gem(0.9, None)], "A")}}
        e = P.board(pool, "a", now=0)["cur"]
        wk = [w for w in e["wins"] if w["label"] == "周"]
        self.assertEqual(len(wk), 1, "★★ 周那一格被丢了 —— 用户看到的是「没有周窗口」")
        self.assertIsNone(wk[0]["rem"])
        self.assertIsNone(e["tightest"], "★★ 最紧不知道时 tightest 必须是 None，不是 90")


class TheFrontendKeepsTheBucket(unittest.TestCase):
    Q = {"groups": [{"name": "Gemini Models", "buckets": [
        {"bucket_id": "gemini-5h", "window": "5h", "remaining_percent": 90, "reset_at": None},
        {"bucket_id": "gemini-weekly", "window": "weekly", "remaining_percent": None, "reset_at": None}]}]}

    def test_tightest_is_the_unknown_bucket(self):
        r = run_agy_ts("m.agyTightest(q).b.remaining_percent", self.Q)
        self.assertIsNone(r, "★★ 环上画了 90 —— 缺的那格可能正是 0")

    def test_the_week_row_is_unknown_not_dropped(self):
        rows = run_agy_ts("m.agyWinRows(q).map(r => [r.label, r.remaining])", self.Q)
        self.assertIn(["周", None], rows)
        self.assertIn(["5h", 90], rows)

    def test_to_snapshot_does_not_filter_buckets_out(self):
        code = ts_code("hooks/useAgyPool.ts")
        i = code.index("function toSnapshot(")
        body = code[i:code.index("\n}\n", i)]
        self.assertNotIn('.filter((b) => typeof b.remainingFraction === "number")', body,
                         "★★ toSnapshot 又在丢没有数的桶")
        self.assertRegex(body, r'typeof b\.remainingFraction === "number"\s*\?[^:]+:\s*null',
                         "★ 没有数的桶要落成 null（读不到），不是默认值")

    def test_both_surfaces_render_a_dash_with_the_shared_reason(self):
        for f in ("components/AgyCard.tsx", "components/AgyRow.tsx"):
            with self.subTest(f=f):
                code = ts_code(f)
                self.assertIn("title={row ? AGY_UNKNOWN_TITLE", code,
                              "★ 读不到的那一行没说出原因（两个 surface 共用一句）")


if __name__ == "__main__":
    unittest.main()
