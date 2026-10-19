"""云端额度摘要**偶尔整组缺失**时，沿用上次那组、标成旧读数（用户 2026-10-16：「我用 agy 第二个账号，
现在的 5h 和周额度都是不正确的」）。

## 实测（本机 agy.log，dbk = 当值号，同一个号几分钟内来回变）
    01:40:52 quota [dbk] ✓ gemini 98.1%、claude 100.0%
    01:43:56 quota [dbk] ✓ claude 100.0%          ← 整个「Gemini Models」组没回来
    01:47:26 quota [dbk] ✓ gemini 98.0%、claude 100.0%
`_store_quota` 把整份摘要**替换**掉 ⇒ Gemini 两个桶消失：
- 卡片 `agyWinRows` 按窗口取各组最小值，于是画出 **Claude/GPT 那组的 5h 100% / 周 100%（周重置 10-22）**；
- 选号投影 `quota.gemini` 也没了 ⇒ 「读不到排最后」，自动切号会无故把这个号挪走。
违反的是 CLAUDE.md §7.0b 第 3 问：**这次没返回的子字段沿用旧值，不置空**。

## 守的
1. 新读数缺某组 ⇒ 沿用上次那组，每个桶带 `seenAt`（上次读数时刻）；新读数里有的组照常覆盖。
2. 沿用桶的重置时刻已过 ⇒ 值改成「读不到」（`remainingFraction` 缺省 ⇒ `—`），不拿已重置窗口的旧数冒充。
3. 选号投影跟着沿用（不因一组缺失就把号排到最后）。
4. 沿用不叠加：连续缺失时 `seenAt` 保持**第一次**看到的时刻，不被刷新成「刚刚」。
5. 读失败（err）仍不写数字（原契约不变）。
6. 前端把 `seenAt` 带成 `seen_at`（卡片据此降级显示）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agy import pool as P  # noqa: E402

T0 = 1_900_000_000


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def gem(f5=0.98, r5=T0 + 2 * 3600, fw=0.40, rw=T0 + 5 * 86400):
    return {"displayName": "Gemini Models", "buckets": [
        {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": f5, "resetTime": iso(r5)},
        {"bucketId": "gemini-weekly", "window": "weekly", "remainingFraction": fw, "resetTime": iso(rw)}]}


def third(now):
    return {"displayName": "Claude and GPT models", "buckets": [
        {"bucketId": "3p-5h", "window": "5h", "remainingFraction": 1, "resetTime": iso(now + 5 * 3600)},
        {"bucketId": "3p-weekly", "window": "weekly", "remainingFraction": 1, "resetTime": iso(now + 7 * 86400)}]}


class _Clock:
    def __init__(self, t):
        self.t = t

    def time(self):
        return self.t

    def __getattr__(self, n):
        return getattr(time, n)


class TheMissingGroupIsCarried(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("CODEXBAR_QUOTA_ANCHORS")
        os.environ["CODEXBAR_QUOTA_ANCHORS"] = os.path.join(self.tmp.name, ".quota-anchors.json")
        loader = importlib.machinery.SourceFileLoader("agy_rotate_carry", str(ROOT / "agy-rotate"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.cli = importlib.util.module_from_spec(spec)
        loader.exec_module(self.cli)
        self.clock = _Clock(T0)
        self.cli.time = self.clock

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CODEXBAR_QUOTA_ANCHORS", None)
        else:
            os.environ["CODEXBAR_QUOTA_ANCHORS"] = self._old
        self.tmp.cleanup()

    def store(self, a, groups, err=""):
        return self.cli._store_quota("sub-b", a, groups, err)

    def gemini_buckets(self, a):
        g = [x for x in a.get("quota_summary") or [] if x["displayName"].startswith("Gemini")]
        return {b["bucketId"]: b for b in (g[0]["buckets"] if g else [])}

    def test_a_missing_group_keeps_last_values_marked_old(self):
        a = {"label": "dbk"}
        self.store(a, [gem(), third(T0)])
        self.clock.t = T0 + 180
        self.store(a, [third(T0 + 180)])
        b = self.gemini_buckets(a)
        self.assertEqual(set(b), {"gemini-5h", "gemini-weekly"}, "★★★ Gemini 组被这次缺失整个抹掉了")
        self.assertEqual(b["gemini-weekly"]["remainingFraction"], 0.40)
        self.assertEqual(b["gemini-5h"]["seenAt"], T0, "★★ 沿用的桶没标上次读数时刻 —— 旧数会被当成刚读到的")
        self.assertEqual(b["gemini-weekly"]["seenAt"], T0)
        self.assertAlmostEqual(a["quota"]["gemini"]["remaining"], 0.40, msg="★★ 选号投影丢了 Gemini ⇒ 这个号被排到最后")

    def test_present_groups_still_overwrite(self):
        a = {"label": "dbk"}
        self.store(a, [gem(), third(T0)])
        self.clock.t = T0 + 180
        self.store(a, [gem(f5=0.50, fw=0.30), third(T0 + 180)])
        b = self.gemini_buckets(a)
        self.assertEqual(b["gemini-weekly"]["remainingFraction"], 0.30)
        self.assertNotIn("seenAt", b["gemini-5h"], "★ 这次读到了还标成旧读数")
        n = sum(1 for g in a["quota_summary"] if g["displayName"].startswith("Gemini"))
        self.assertEqual(n, 1, "★ 这次读到的组又被补进一份旧的 —— 同名两组，选号投影取到哪份看顺序")

    def test_a_carried_bucket_past_its_reset_becomes_unknown(self):
        a = {"label": "dbk"}
        self.store(a, [gem(r5=T0 + 600), third(T0)])
        self.clock.t = T0 + 900
        self.store(a, [third(T0 + 900)])
        b = self.gemini_buckets(a)
        self.assertNotIn("remainingFraction", b["gemini-5h"], "★★ 窗口已重置还拿旧数冒充")
        self.assertEqual(b["gemini-weekly"]["remainingFraction"], 0.40, "周窗口没过重置，应沿用")
        self.assertIsNone(a["quota"]["gemini"]["remaining"], "一格读不到 ⇒ 整组「不知道」（同 quota_by_group 契约）")

    def test_carrying_twice_keeps_the_first_seen_time(self):
        a = {"label": "dbk"}
        self.store(a, [gem(), third(T0)])
        for dt in (180, 360):
            self.clock.t = T0 + dt
            self.store(a, [third(T0 + dt)])
        self.assertEqual(self.gemini_buckets(a)["gemini-weekly"]["seenAt"], T0, "★ 连续缺失把旧读数刷成了「刚刚」")

    def test_a_failed_read_still_writes_no_numbers(self):
        a = {"label": "dbk"}
        self.store(a, [gem(), third(T0)])
        self.clock.t = T0 + 180
        self.store(a, None, err="HTTP 500")
        self.assertIsNone(a["quota"])
        self.assertIsNone(a["quota_summary"])


class EveryWritePathCarries(unittest.TestCase):
    def test_each_summary_write_is_preceded_by_the_carry(self):
        """`quota`（经 `_store_quota`）与 `health` 两条路都写摘要；漏一条，那条路就照旧整份替换。"""
        lines = (ROOT / "agy-rotate").read_text(encoding="utf-8").splitlines()
        code = [re.sub(r"#.*", "", l) for l in lines]
        writes = [i for i, l in enumerate(code) if re.search(r'a\["quota_summary"\]\s*=', l)]
        self.assertGreaterEqual(len(writes), 2, "写入点比预期少 —— 闸可能没找对地方")
        for i in writes:
            with self.subTest(line=i + 1):
                self.assertTrue(any("carry_missing_groups(" in code[j] for j in range(max(0, i - 4), i)),
                                "★★ agy-rotate:%d 写摘要前没沿用缺失的组" % (i + 1))


class TheFrontendKeepsTheMarker(unittest.TestCase):
    def test_seen_at_reaches_the_card(self):
        src = (ROOT / "codexbar" / "src" / "hooks" / "useAgyPool.ts").read_text(encoding="utf-8")
        body = src[src.index("function toSnapshot("):]
        body = re.sub(r"//[^\n]*", "", body[:body.index("\n}\n")])
        self.assertRegex(body, r"seen_at:\s*typeof b\.seenAt === \"number\" \? b\.seenAt : undefined",
                         "★★ 后端标了旧读数，前端没接 —— 卡片照常按新数画")

    def test_card_and_menubar_row_both_dim_it(self):
        # ★ 2026-10-19（交接包 4f）：菜单栏行的外形在 `mb/QuotaRow`：AgyRow 标 `dim: !!row.seen_at`，
        #   QuotaRow 照同一个值降到 .62。两半都要在，缺哪一半都是「把旧读数画成现值」。
        # 总览卡（2026-10-19 起 `ov/OvCard::OvWinRow`）同一个形状：AgyCard 标 `dim`，OvWinRow 照它降到 .62。
        for f, needle in (("AgyCard.tsx", "dim: !!row.seen_at"),
                          ("ov/OvCard.tsx", "opacity: w.dim ? .62 : 1"),
                          ("AgyRow.tsx", "dim: !!row.seen_at"),
                          ("mb/QuotaRow.tsx", "opacity: w.dim ? .62 : 1")):
            with self.subTest(f=f):
                src = (ROOT / "codexbar" / "src" / "components" / f).read_text(encoding="utf-8")
                src = re.sub(r"\{/\*.*?\*/\}|/\*.*?\*/|//[^\n]*", "", src, flags=re.S)
                self.assertIn(needle, src, "★★ %s 把沿用的旧读数画成现值" % f)


if __name__ == "__main__":
    unittest.main()
