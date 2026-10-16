"""Gemini 周额度从生产 host 补（B83，用户 2026-10-16：「gemini 卡片周额度的字体变灰了」）。

## 实测（2026-10-16 ~18:40 SGT，零计费）
- `daily-cloudcode-pa` 摘要仍只回 Claude/GPT 组（05:06 起，B82）；周只能沿用 ⇒ 卡片整行降不透明度。
- 生产 host `cloudcode-pa` 的同一个请求回 Gemini 组，**周**是真数：3 个号与 daily 最后一次读数差 ≤1pp，
  A / B 号 的周 reset 与锚点账本钉住的**逐秒相同**（Δ=0s）；agy 自己 `/usage` 状态栏 B 号 `📅 1%` 对得上。
- 同一份响应里 B 号 的 **5h** 是「1.0、reset = 现在+5h」，而模型端点与 agy 状态栏都说已用 2% ⇒ 生产 host 的 5h 不取。

## 守的
1. 只取 `gemini-weekly`；5h 仍来自模型端点。
2. reset ≈ 现在 + 7 天（B69 空账本的签名）⇒ 不采信。
3. 锚点账本里本窗口已 anchored ⇒ reset 对不上就不采信。
4. 桶在、`remainingFraction` 缺席 ⇒ 返回读不到的桶，不丢、不补 1.0。
5. 接线：`fetch_quota` 在摘要缺 Gemini 时去生产 host 取；两个写 `quota_summary` 的调用点都把锚点传进去。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import ast
import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agy import pool as P  # noqa: E402

T0 = 1_900_000_000
WK_RESET = T0 + 116 * 3600


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def prod(wk_frac=0.9864, wk_reset=WK_RESET, drop_frac=False):
    wk = {"bucketId": "gemini-weekly", "window": "weekly", "remainingFraction": wk_frac, "resetTime": iso(wk_reset)}
    if drop_frac:
        del wk["remainingFraction"]
    return {"groups": [
        # ★ 5h 排在前面：只取「第一个桶」的实现在这里会拿错（变异实测，周在前时这条闸是空的）。
        {"displayName": "Gemini Models", "buckets": [
            {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 1, "resetTime": iso(T0 + 5 * 3600)}, wk]},
        {"displayName": "Claude and GPT models", "buckets": [
            {"bucketId": "3p-weekly", "window": "weekly", "remainingFraction": 1, "resetTime": iso(T0 + 7 * 86400)}]}]}


ANCHORED = {"gemini-weekly": {"state": "anchored", "reset": WK_RESET}}


class TheWeeklyBucketFromProd(unittest.TestCase):
    def test_takes_only_the_weekly_bucket(self):
        b = P.gemini_weekly_from_prod(prod(), ANCHORED, now=T0)
        self.assertEqual(b["bucketId"], "gemini-weekly", "★★ 取错了桶 —— 生产 host 的 5h 不能信")
        self.assertAlmostEqual(b["remainingFraction"], 0.9864)
        self.assertEqual(b["source"], P.API_HOST)

    def test_an_empty_ledger_week_is_refused(self):
        self.assertIsNone(P.gemini_weekly_from_prod(prod(1, T0 + 7 * 86400), None, now=T0),
                          "★★★ reset = 现在+7天 是 B69 空账本的签名，采信它就是画一个假的满格")

    def test_a_reset_that_disagrees_with_the_pinned_window_is_refused(self):
        self.assertIsNone(P.gemini_weekly_from_prod(prod(wk_reset=WK_RESET + 3 * 3600), ANCHORED, now=T0),
                          "★★ 与账本钉住的周窗口对不上，不是同一个窗口")
        self.assertIsNotNone(P.gemini_weekly_from_prod(prod(wk_reset=WK_RESET + 60), ANCHORED, now=T0),
                             "★ 容差内的抖动不该被拒")

    def test_without_a_pin_a_real_reset_is_taken(self):
        self.assertIsNotNone(P.gemini_weekly_from_prod(prod(0.3876), {}, now=T0))

    def test_a_missing_fraction_stays_unknown(self):
        b = P.gemini_weekly_from_prod(prod(drop_frac=True), ANCHORED, now=T0)
        self.assertIsNotNone(b, "★ 桶在就要留着（= 读不到），丢掉会让旧值继续冒充")
        self.assertNotIn("remainingFraction", b, "★★ 缺的可能正是 0，不能补成任何数")

    def test_no_gemini_group_or_past_reset_gives_none(self):
        self.assertIsNone(P.gemini_weekly_from_prod({"groups": prod()["groups"][1:]}, None, now=T0))
        self.assertIsNone(P.gemini_weekly_from_prod(prod(wk_reset=T0 - 1), None, now=T0))


class _Resp:
    def __init__(self, status, body):
        self.status, self._b = status, json.dumps(body).encode() if not isinstance(body, bytes) else body

    def read(self):
        return self._b


class TheWeeklyIsWiredIntoFetchQuota(unittest.TestCase):
    def run_with(self, replies, anchor=None):
        calls, replies = [], list(replies)

        class Conn:
            def __init__(self, host, *a, **k):
                self.host = host

            def request(self, method, path, **kw):
                calls.append((self.host, path))

            def getresponse(self):
                return replies.pop(0)

            def close(self):
                pass

        old_conn, old_time = P.HTTPSConnection, P.time.time
        P.HTTPSConnection, P.time.time = Conn, (lambda: T0)
        try:
            return P.fetch_quota("tok", anchor), calls
        finally:
            P.HTTPSConnection, P.time.time = old_conn, old_time

    def models(self, frac):
        return {"models": {"gemini-3-flash": {"quotaInfo": {"remainingFraction": frac, "resetTime": iso(T0 + 9000)}}}}

    def test_weekly_from_prod_and_5h_from_models(self):
        third = {"displayName": "Claude and GPT models", "buckets": []}
        (groups, err), calls = self.run_with([_Resp(200, {"groups": [third]}), _Resp(200, self.models(0.97)),
                                              _Resp(200, prod())], ANCHORED)
        self.assertFalse(err)
        self.assertIn((P.API_HOST, P.QUOTA_SUMMARY_PATH), calls, "★★★ 没去生产 host 取周")
        gem = [g for g in groups if g["displayName"] == "Gemini Models"]
        self.assertEqual(len(gem), 1)
        b = {x["bucketId"]: x for x in gem[0]["buckets"]}
        self.assertAlmostEqual(b["gemini-weekly"]["remainingFraction"], 0.9864)
        self.assertAlmostEqual(b["gemini-5h"]["remainingFraction"], 0.97,
                               msg="★★ 5h 被生产 host 的 1.0 顶掉了")

    def test_weekly_alone_still_makes_a_group(self):
        (groups, err), _ = self.run_with([_Resp(200, {"groups": [{"displayName": "Claude and GPT models"}]}),
                                          _Resp(500, b"x"), _Resp(200, prod())], ANCHORED)
        gem = [g for g in groups if g["displayName"] == "Gemini Models"]
        self.assertEqual([x["bucketId"] for x in gem[0]["buckets"]], ["gemini-weekly"])

    def test_both_write_paths_pass_the_anchor(self):
        tree = ast.parse((ROOT / "agy-rotate").read_text(encoding="utf-8"))
        hits = []
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            src = ast.get_source_segment((ROOT / "agy-rotate").read_text(encoding="utf-8"), fn) or ""
            if "carry_missing_groups(" not in src and "quota_summary" not in src:
                continue
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "fetch_quota"):
                    hits.append((fn.name, len(n.args) + len(n.keywords)))
        self.assertTrue(hits, "★ 选择器一个调用点都没命中")
        for name, nargs in hits:
            self.assertGreaterEqual(nargs, 2, "★★ %s 写 quota_summary 却没把锚点传给 fetch_quota" % name)


if __name__ == "__main__":
    unittest.main()
