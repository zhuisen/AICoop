"""Gemini 额度改走 `fetchAvailableModels` 兜底（用户 2026-10-16：「gemini 5h 显示上游没给数是什么意思？」）。

## 实测（2026-10-16 11:47 SGT，4 个零计费请求）
- `retrieveUserQuotaSummary` 从 05:06 起对 3 个号**都**只回「Claude and GPT models」一组 —— 换 3 种客户端身份
  （旧 UA / 本机 agy 1.3.6 darwin / 去掉 Client-Metadata）结果相同 ⇒ 不是我们的请求造成的。
- `fetchAvailableModels` 仍给每个 Gemini 模型带 `quotaInfo`（12 个模型同一个值、同一个 resetTime ⇒ 同一个 5h 池），
  但这个端点**一向没有周**（B53）。`tab_*` / `chat_*` 没有 `resetTime`（不限量），不是这个池。

## 守的
1. `gemini_group_from_models`：只取带 `resetTime` 的 gemini 模型，取最紧；有一个缺 `remainingFraction` ⇒ 整格读不到。
2. `fetch_quota`：摘要缺 Gemini 组才去补（有就不多发请求）；补的那次失败不影响摘要本身。
3. 同组缺桶也沿用（模型端点只给 5h ⇒ 周沿用上次读数并标 `seenAt`）。
4. 沿用超过 24h ⇒ 读不到（不让一份越来越旧的周读数一直冒充「几小时前」）。
5. 过期的沿用读数说「旧读数已过期」，不说「上游没给数」（后者是上游这一格缺数，原因与下一步都不同）。
   **不把「没数」默认成 100%**（用户提议，2026-10-16 讨论后不做）：周读不到时冒充满格，会把一个
   周只剩 40% 的号当满的挑走；5h 已经现读，未启动的窗口由锚点账本按证据标「未启动」。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agy import pool as P  # noqa: E402

T0 = 1_900_000_000


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def models_json(frac=0.9987, reset=T0 + 5 * 3600, drop_one=False):
    m = {k: {"quotaInfo": {"remainingFraction": frac, "resetTime": iso(reset)}}
         for k in ("gemini-2.5-pro", "gemini-3-flash", "gemini-3.8-flash-tiered")}
    if drop_one:
        del m["gemini-3-flash"]["quotaInfo"]["remainingFraction"]
    m["tab_flash_lite_preview"] = {"quotaInfo": {"remainingFraction": 0.1}}          # 不限量那类，无 resetTime
    m["gemini-unmetered-x"] = {"quotaInfo": {"remainingFraction": 0.05}}             # gemini 前缀但无 resetTime ⇒ 不是这个池
    m["claude-opus-5-5-high"] = {"quotaInfo": {"remainingFraction": 0.2, "resetTime": iso(reset)}}
    return {"models": m}


THIRD = {"displayName": "Claude and GPT models", "buckets": [
    {"bucketId": "3p-weekly", "window": "weekly", "remainingFraction": 1, "resetTime": iso(T0 + 7 * 86400)},
    {"bucketId": "3p-5h", "window": "5h", "remainingFraction": 1, "resetTime": iso(T0 + 5 * 3600)}]}
GEM = {"displayName": "Gemini Models", "buckets": [
    {"bucketId": "gemini-weekly", "window": "weekly", "remainingFraction": 0.40, "resetTime": iso(T0 + 5 * 86400)},
    {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 0.97, "resetTime": iso(T0 + 3600)}]}


class TheGroupBuiltFromModels(unittest.TestCase):
    def test_takes_only_gemini_models_with_a_reset(self):
        g = P.gemini_group_from_models(models_json(frac=0.9987))
        self.assertEqual(g["displayName"], "Gemini Models")
        self.assertEqual([b["bucketId"] for b in g["buckets"]], ["gemini-5h"])
        self.assertAlmostEqual(g["buckets"][0]["remainingFraction"], 0.9987,
                               msg="★ 混进了 tab_/claude/无 resetTime 的值（0.1 / 0.2 / 0.05）")
        self.assertEqual(g["buckets"][0]["resetTime"], iso(T0 + 5 * 3600))

    def test_one_model_without_a_number_makes_the_bucket_unknown(self):
        b = P.gemini_group_from_models(models_json(drop_one=True))["buckets"][0]
        self.assertNotIn("remainingFraction", b, "★★ 缺的那个可能正是 0（proto3 省略零值），不能拿别的模型冒充")

    def test_no_gemini_with_a_reset_means_no_group(self):
        self.assertIsNone(P.gemini_group_from_models({"models": {"tab_x": {"quotaInfo": {"remainingFraction": 1}}}}))
        self.assertIsNone(P.gemini_group_from_models({}))


class _Resp:
    def __init__(self, status, body):
        self.status, self._b = status, json.dumps(body).encode() if not isinstance(body, bytes) else body

    def read(self):
        return self._b


class TheFallbackIsWiredIntoFetchQuota(unittest.TestCase):
    def run_with(self, replies):
        calls = []
        replies = list(replies)

        class Conn:
            def __init__(self, *a, **k):
                pass

            def request(self, method, path, **kw):
                calls.append(path)

            def getresponse(self):
                return replies.pop(0)

            def close(self):
                pass

        old = P.HTTPSConnection
        P.HTTPSConnection = Conn
        try:
            return P.fetch_quota("tok"), calls
        finally:
            P.HTTPSConnection = old

    def test_summary_without_gemini_is_completed_from_models(self):
        n = P.SUMMARY_READS
        (groups, err), calls = self.run_with([_Resp(200, {"groups": [THIRD]})] * n + [_Resp(200, models_json(0.5))])
        self.assertFalse(err)
        # ★ B88：不再去生产 host 取周（那边是上一个窗口的旧账）。摘要读 n 次去抖（2026-10-26），模型端点只补一次。
        self.assertEqual(calls, [P.QUOTA_SUMMARY_PATH] * n + [P.MODELS_PATH])
        gem = [g for g in groups if g["displayName"].startswith("Gemini")]
        self.assertEqual(len(gem), 1, "★★★ 摘要缺 Gemini 时没去模型端点补")
        self.assertAlmostEqual(gem[0]["buckets"][0]["remainingFraction"], 0.5)

    def test_summary_with_gemini_sends_one_request(self):
        (groups, err), calls = self.run_with([_Resp(200, {"groups": [GEM, THIRD]})] * P.SUMMARY_READS)
        self.assertEqual(calls, [P.QUOTA_SUMMARY_PATH] * P.SUMMARY_READS, "★ 摘要里有 Gemini 还去模型端点多发请求")

    def test_a_failed_fallback_leaves_the_summary_alone(self):
        (groups, err), calls = self.run_with([_Resp(200, {"groups": [THIRD]})] * P.SUMMARY_READS
                                             + [_Resp(500, b"boom"), _Resp(500, b"boom")])
        self.assertFalse(err, "★ 补的那次失败不该让整次读数失败")
        self.assertEqual([g["displayName"] for g in groups], ["Claude and GPT models"])


class BucketsMissingFromAPresentGroupAreCarried(unittest.TestCase):
    def test_weekly_is_carried_when_models_only_give_5h(self):
        new = [THIRD, P.gemini_group_from_models(models_json(0.9))]
        out = P.carry_missing_groups([GEM, THIRD], T0 - 600, new, now=T0)
        b = {x["bucketId"]: x for g in out if g["displayName"].startswith("Gemini") for x in g["buckets"]}
        self.assertEqual(set(b), {"gemini-5h", "gemini-weekly"}, "★★★ 周被这次只给 5h 的读数抹掉了")
        self.assertAlmostEqual(b["gemini-5h"]["remainingFraction"], 0.9)
        self.assertNotIn("seenAt", b["gemini-5h"])
        self.assertEqual(b["gemini-weekly"]["remainingFraction"], 0.40)
        self.assertEqual(b["gemini-weekly"]["seenAt"], T0 - 600)

    def test_a_carried_reading_older_than_a_day_becomes_unknown(self):
        old = [dict(GEM, buckets=[dict(GEM["buckets"][0], seenAt=T0 - 86400 - 60)])]
        out = P.carry_missing_groups(old, T0 - 600, [THIRD], now=T0)
        wk = [x for g in out for x in g["buckets"] if x["bucketId"] == "gemini-weekly"][0]
        self.assertNotIn("remainingFraction", wk, "★★ 一份一天多以前的周读数还在冒充现值")
        self.assertEqual(wk["seenAt"], T0 - 86400 - 60)


class TheExpiredCarrySaysSo(unittest.TestCase):
    def test_both_surfaces_say_the_old_reading_expired(self):
        for f in ("AgyCard.tsx", "AgyRow.tsx"):
            with self.subTest(f=f):
                src = (ROOT / "codexbar" / "src" / "components" / f).read_text(encoding="utf-8")
                src = re.sub(r"\{/\*.*?\*/\}|/\*.*?\*/|//[^\n]*", "", src, flags=re.S)
                self.assertIn("row.seen_at ? AGY_EXPIRED_TITLE", src, "★★ %s 把过期的旧读数说成「上游没给数」" % f)
                if f == "AgyCard.tsx":   # 菜单栏那行只画「—」，没有可见文字
                    # 2026-10-19 总览重做：卡上那一格只有 48px，看得见的字缩成「已过期 / 没给数」，全句在 title。
                    self.assertIn('note: row.seen_at ? "已过期" : "没给数"', src, "★★ 卡片上看得见的那几个字还在说「上游没给数」")
        agy = (ROOT / "codexbar" / "src" / "agy.ts").read_text(encoding="utf-8")
        self.assertRegex(agy, r"export const AGY_EXPIRED_TITLE =\s*\n?\s*\"[^\"]*旧读数")


if __name__ == "__main__":
    unittest.main()
