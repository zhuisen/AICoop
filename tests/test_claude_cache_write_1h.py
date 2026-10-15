"""Claude 缓存写的 1h 档按 2× 输入价计（2026-10-15，用户点名做的 ★1）。

## 实测起因（本机最近 60 个 transcript，55,505 条带 usage 的记录）
`usage.cache_creation` 里分 `ephemeral_1h_input_tokens` / `ephemeral_5m_input_tokens`：
**1h 档 625.9M、5m 档 0** —— Claude Code 现在的缓存写**全是 1h 档**。
而 `rates.ts` 一律按 5m 档（1.25× 输入）计，1h 档官方是 **2×** ⇒ 这一类费用少算 1.6 倍。
旧注释「transcript 区分不出来」是错的：字段一直在。

## 口径
- `cache_write_1h` 是 `cache_write` 的**子集**，不是第五类 —— token 总量一个都不变，只改价。
- 以 `cache_creation_input_tokens` 为准，1h 份额**钳到不超过它**：实测 18 条记录总数是 0
  而明细里 1h 有数（同一个 message.id 的残缺副本），不钳就会凭空多出 token 的钱。
- 只有 >0 时才写进 row / 桶，别家的输出形状不变。
- 缓存口径 `none` 把 `cache_write` 清零时，1h 份额跟着归零（`costOf` 里 `min(1h, cw)`），
  否则会算出负的 5m 档。
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "traffic"))
import scan  # noqa: E402

SRC = ROOT / "codexbar" / "src"


def line(mid, cw, h1=None, m5=0, model="claude-opus-5-5", ts="2026-10-15T01:00:00Z"):
    u = {"input_tokens": 3, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": cw,
         "output_tokens": 50}
    if h1 is not None:
        u["cache_creation"] = {"ephemeral_1h_input_tokens": h1, "ephemeral_5m_input_tokens": m5}
    return json.dumps({"type": "assistant", "timestamp": ts,
                       "message": {"id": mid, "model": model, "usage": u}})


class TheParserKeepsThe1hShare(unittest.TestCase):
    def rows(self, *ls):
        return scan._scan_claude_lines(ls)

    def test_1h_share_rides_in_position_8(self):
        r = self.rows(line("a", 4000, h1=4000))["a"]
        self.assertEqual(r[scan.IDX_CW], 4000)
        self.assertEqual(r[8], 4000, "★★ 1h 份额没带出来 —— 费用还是按 1.25× 算")

    def test_5m_only_or_no_breakdown_adds_nothing(self):
        self.assertEqual(len(self.rows(line("a", 4000, h1=0, m5=4000))["a"]), 6)
        self.assertEqual(len(self.rows(line("b", 4000))["b"]), 6, "老 transcript 没有明细：形状不变")

    def test_share_is_clamped_to_the_total(self):
        """★ 实测 18 条：总数 0、明细 1h 有数。总数才是 token 的权威。"""
        r = self.rows(line("a", 100, h1=5778), line("b", 0, h1=557))
        self.assertEqual(r["a"][8], 100)
        self.assertEqual(len(r["b"]), 6, "★ 总数 0 ⇒ 1h 份额钳成 0，不带第 9 位")


class TheBucketCarriesIt(unittest.TestCase):
    def run_scan(self, text):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "p").mkdir()
        (d / "p" / "s.jsonl").write_text(text, encoding="utf-8")
        cl = next(x for x in scan.SOURCES if x["key"] == "claude")
        fake = dict(cl, root=d)
        orig = scan.SOURCES
        scan.SOURCES = (fake,)
        try:
            out, _ = scan.scan(days=3650, use_cache=False)
        finally:
            scan.SOURCES = orig
        self.assertEqual(sorted(out), ["claude"])
        return out["claude"]

    def test_day_bucket_and_model_carry_the_share_and_totals_are_unchanged(self):
        txt = "\n".join([line("a", 4000, h1=4000), line("b", 1000, h1=0, m5=1000),
                         line("c", 2000, h1=1500, m5=500, model="claude-sonnet-5-5")]) + "\n"
        p = self.run_scan(txt)
        days = p["days"] if isinstance(p, dict) and "days" in p else p
        b = [v for v in (days.values() if isinstance(days, dict) else days) if v.get("total")]
        self.assertEqual(len(b), 1, b)
        b = b[0]
        self.assertEqual(b["cache_write"], 7000)
        self.assertEqual(b.get("cache_write_1h"), 5500, "★★ 桶里没有 1h 份额")
        self.assertEqual(b["models"]["claude-opus-5-5"].get("cache_write_1h"), 4000)
        self.assertEqual(b["models"]["claude-sonnet-5-5"].get("cache_write_1h"), 1500)
        self.assertEqual(b["total"], 3 * 3 + 3 * 1000 + 7000 + 3 * 50, "★ 1h 是子集：总量不许变")

    def test_parser_version_was_bumped(self):
        """★ 改了 rows 里存什么必须 +1，否则此生不再变 mtime 的 transcript 永远沿用旧结果。"""
        self.assertGreaterEqual(scan.PARSER_V, 12)


def ts_eval(expr):
    src = (SRC / "rates.ts").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "rates.ts"
        f.write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                            "import('%s').then(m => console.log(JSON.stringify(%s)))" % (f.as_posix(), expr)],
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class TheCostUsesTwiceTheInputPrice(unittest.TestCase):
    T = '{uncached_in:0,cache_read:0,cache_write:1e6,output:0%s}'

    def cost(self, extra, model="claude-opus-5-5"):
        return ts_eval('m.costOf(%s, "%s", "claude")' % (self.T % extra, model))

    def test_1h_is_2x_input_and_5m_stays_1_25x(self):
        self.assertAlmostEqual(self.cost(""), 5.0, msg="没有明细：照旧 5m 档（$5/M = 1.25×$4）")
        self.assertAlmostEqual(self.cost(",cache_write_1h:1e6"), 8.0, msg="★★ 1h 档应是 2×$4 = $8/M")
        self.assertAlmostEqual(self.cost(",cache_write_1h:4e5"), 0.6 * 5 + 0.4 * 8)

    def test_share_never_exceeds_cache_write(self):
        """★ `none` 口径把 cache_write 清零时，1h 份额不许留下来算出负的 5m 档。"""
        self.assertAlmostEqual(
            ts_eval('m.costOf({uncached_in:0,cache_read:0,cache_write:0,output:0,cache_write_1h:1e6},"claude-opus-5-5","claude")'),
            0.0)


class TheSumKeepsIt(unittest.TestCase):
    def test_sum_buckets_adds_the_share_at_both_levels(self):
        """★ 多日窗口靠 `sumBuckets` 拼起来；漏加一层，那一层的费用就退回 1.25×。"""
        src = (SRC / "traffic.ts").read_text(encoding="utf-8")
        for dep in ("rates", "theme"):
            src = src.replace('from "./%s"' % dep, 'from "%s"' % (SRC / ("%s.ts" % dep)).as_posix())
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "traffic.ts"
            f.write_text(src, encoding="utf-8")
            b = ('{uncached_in:0,cache_read:0,cache_write:10,output:0,total:10,rounds:1,cache_write_1h:%d,'
                 'models:{"claude-opus-5-5":{uncached_in:0,cache_read:0,cache_write:10,output:0,total:10,rounds:1,cache_write_1h:%d}}}')
            expr = "(() => { const s = m.sumBuckets([%s, %s, %s]); return [s.cache_write_1h, s.models['claude-opus-5-5'].cache_write_1h]; })()" % (
                b % (4, 4), b % (6, 6), '{uncached_in:1,cache_read:0,cache_write:0,output:0,total:1,rounds:1,models:{}}')
            r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                                "import('%s').then(m => console.log(JSON.stringify(%s)))" % (f.as_posix(), expr)],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), [10, 10])


if __name__ == "__main__":
    unittest.main()
