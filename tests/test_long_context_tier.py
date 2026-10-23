"""长上下文档 + Grok 自报费用 + `[1m]` 归一（2026-10-23 token 审查，用户「都修」）。

## 实测起因
- Codex 有 16.3% 的输入 token 落在提示词 > 272K 的请求里；OpenAI 长档输入 / 缓存读 ×2、输出 ×1.5，原来一律按短档 ⇒ 低估。
- Claude Opus 5.5 有 88.7% 的输入落在 > 200K 的请求里 —— 但官方 4.6 起 **1M 全窗口标准价**（Haiku 5.5 除外），
  所以它**不该**进长档。这条用例防的是「好心」给 Claude 加长档。
- Grok 一条记录是一轮（130 轮 = 1,580 次调用），看不到单次提示词；它自报的实扣 `costUsdTicks`（1 USD = 1e10 tick）
  合计 $47.6，牌价估 $153.5 ⇒ 有自报就用自报。

## 口径
- 门槛在 `scan.py::LONG_CTX`，单价在 `rates.ts` 各模型的 `long`；**两边必须同一组模型、同一个门槛**（本文件第一类）。
- `long` / `rep` 是模型桶里的**子集**，只决定价格，token 总量一个都不变。
- 缓存口径去掉某一类时，子集钳到当前各类（`clampTo`），自报费用按牌价比例缩放。
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


def ts_eval(expr, mod="rates"):
    src = (SRC / ("%s.ts" % mod)).read_text(encoding="utf-8")
    for dep in ("rates", "theme"):
        src = src.replace('from "./%s"' % dep, 'from "%s"' % (SRC / ("%s.ts" % dep)).as_posix())
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / ("%s.ts" % mod)
        f.write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                            "import('%s').then(m => console.log(JSON.stringify(%s)))" % (f.as_posix(), expr)],
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class TheTwoSidesAgree(unittest.TestCase):
    def test_same_models_same_thresholds(self):
        ts = ts_eval("Object.fromEntries(Object.entries(m.RATES).filter(([k, v]) => v.long).map(([k, v]) => [k, v.long.over]))")
        self.assertTrue(ts, "已知阳性：rates.ts 里得有带 long 的模型")
        self.assertEqual(ts, scan.LONG_CTX, "★ 前端有长档价、后端不按门槛拆（或反过来）⇒ 那个模型的长请求按短档计")

    def test_claude_models_after_4_6_have_no_long_tier(self):
        """官方：4.6 起（Haiku 5.5 除外）1M 全窗口标准价。"""
        for m in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-opus-4-6"):
            self.assertNotIn(m, scan.LONG_CTX)
        self.assertEqual(scan.LONG_CTX["claude-haiku-5-5"], 100_000)


def codex_line(ts, inp, cached, out):
    return json.dumps({"timestamp": ts, "type": "event_msg", "payload": {
        "type": "token_count", "info": {"last_token_usage": {"input_tokens": inp, "cached_input_tokens": cached,
                                                              "output_tokens": out, "total_tokens": inp + out},
                                        "total_token_usage": {"total_tokens": inp + out}}}})


class TheBucketSplitsLongRequests(unittest.TestCase):
    def run_scan(self, key, rel, text):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        f = d / rel
        f.parent.mkdir(parents=True)
        f.write_text(text, encoding="utf-8")
        src = next(x for x in scan.SOURCES if x["key"] == key)
        orig = scan.SOURCES, scan.OTEL_ROOT, scan.CACHE, scan.LOCAL_CFG
        scan.SOURCES = (dict(src, root=d),)
        scan.OTEL_ROOT = d / "otel-ledger"                # 不读真 OTel 账本
        scan.CACHE, scan.LOCAL_CFG = d / "cache.json", d / "sources.local.json"   # 不碰真缓存 / 本机源配置
        try:
            out, _ = scan.scan(days=3650, use_cache=False)
        finally:
            scan.SOURCES, scan.OTEL_ROOT, scan.CACHE, scan.LOCAL_CFG = orig
        bs = [v for v in out[key]["days"].values() if v.get("total")]
        self.assertEqual(len(bs), 1, bs)
        return bs[0]

    def test_codex_request_over_272k_lands_in_long(self):
        meta = json.dumps({"type": "session_meta", "payload": {"id": "s", "model_provider": "openai"}})
        ctx = json.dumps({"timestamp": "2026-10-15T01:00:00Z", "type": "turn_context", "payload": {"model": "gpt-6.1-sol"}})
        txt = "\n".join([meta, ctx, codex_line("2026-10-15T01:00:01Z", 300_000, 250_000, 900),
                         codex_line("2026-10-15T01:00:02Z", 272_000, 200_000, 100)]) + "\n"
        b = self.run_scan("codex", "2026/10/15/rollout-2026-10-15T01-00-00-x.jsonl", txt)
        m = b["models"]["gpt-6.1-sol"]
        self.assertEqual(m.get("long"), {"uncached_in": 50_000, "cache_read": 250_000, "cache_write": 0, "output": 900},
                         "★ 只有 > 272K 那条进长档；正好 272K 的不算（官方「>272K」）")
        self.assertEqual(m["total"], 300_000 + 900 + 272_000 + 100, "★ 子集：总量不变")

    def test_grok_self_reported_cost_rides_along(self):
        up = {"timestamp": 1792000000, "method": "_x.ai/session/update", "params": {"update": {
            "sessionUpdate": "turn_completed", "usage": {"modelUsage": {"grok-4.7-build": {
                "inputTokens": 10_000, "cachedReadTokens": 8_000, "outputTokens": 500, "costUsdTicks": 123_000_000}}}}}}
        b = self.run_scan("grok", "%2Fx%2Fp/s1/updates.jsonl", json.dumps(up) + "\n")
        rep = b["models"]["grok-4.7-build"].get("rep")
        self.assertEqual(rep, {"uncached_in": 2_000, "cache_read": 8_000, "cache_write": 0, "output": 500,
                               "usd": 0.0123}, "★ 1 USD = 1e10 tick")

    def test_codex_rows_before_the_first_turn_context_get_its_model(self):
        """`codex exec` 0.146/0.147 在第一条 turn_context 之前就写 token_count（本机 36 个文件 37.4M 落成 unknown）。"""
        meta = json.dumps({"type": "session_meta", "payload": {"id": "s", "model_provider": "openai"}})
        ctx = json.dumps({"timestamp": "2026-10-15T01:00:05Z", "type": "turn_context", "payload": {"model": "gpt-5.6-sol"}})
        txt = "\n".join([meta, codex_line("2026-10-15T01:00:01Z", 1000, 0, 10), ctx,
                         codex_line("2026-10-15T01:00:09Z", 2000, 0, 20)]) + "\n"
        b = self.run_scan("codex", "2026/10/15/rollout-2026-10-15T01-00-00-y.jsonl", txt)
        self.assertEqual(set(b["models"]), {"gpt-5.6-sol"})
        self.assertEqual(b["models"]["gpt-5.6-sol"]["total"], 1010 + 2020)

    def test_1m_suffix_is_the_same_model(self):
        self.assertEqual(scan._DATED.sub("", "claude-opus-5-5[1m]"), "claude-opus-5-5")
        self.assertEqual(scan._DATED.sub("", "claude-haiku-4-5-20251001"), "claude-haiku-4-5")

    def test_parser_version_was_bumped(self):
        self.assertGreaterEqual(scan.PARSER_V, 15)


C = "{uncached_in:%s,cache_read:%s,cache_write:0,output:%s%s}"


class TheCostUsesTheLongPrices(unittest.TestCase):
    def cost(self, t, model, plat):
        return ts_eval('m.costOf(%s, "%s", "%s")' % (t, model, plat))

    def test_long_part_is_priced_at_the_long_tier(self):
        # gpt-6.1-sol：短 $2 / $0.10 / $10，长 $4 / $0.20 / $15
        short = self.cost(C % ("1e6", "1e6", "1e6", ""), "gpt-6.1-sol", "codex")
        self.assertAlmostEqual(short, 2 + 0.1 + 10)
        half = self.cost(C % ("1e6", "1e6", "1e6", ",long:{uncached_in:5e5,cache_read:5e5,cache_write:0,output:5e5}"),
                         "gpt-6.1-sol", "codex")
        self.assertAlmostEqual(half, (2 + 0.1 + 10) / 2 + (4 + 0.2 + 15) / 2)

    def test_long_subset_is_clamped_by_the_cache_mode(self):
        """`noRead` 把 cache_read 清零：长档子集的缓存读跟着归零，不能算出负的短档。"""
        c = self.cost(C % ("1e6", "0", "0", ",long:{uncached_in:0,cache_read:9e6,cache_write:0,output:0}"),
                      "gpt-6.1-sol", "codex")
        self.assertAlmostEqual(c, 2.0)

    def test_claude_opus_has_no_long_tier_even_with_a_long_subset(self):
        c = self.cost(C % ("1e6", "0", "0", ",long:{uncached_in:1e6,cache_read:0,cache_write:0,output:0}"),
                      "claude-opus-5-5", "claude")
        self.assertAlmostEqual(c, 4.0)

    def test_haiku_5_5_is_priced_and_has_its_long_tier(self):
        self.assertAlmostEqual(self.cost(C % ("1e6", "0", "1e6", ""), "claude-haiku-5-5", "claude"), 0.1 + 0.5)
        self.assertAlmostEqual(self.cost(C % ("1e6", "0", "1e6", ",long:{uncached_in:1e6,cache_read:0,cache_write:0,output:1e6}"),
                                         "claude-haiku-5-5", "claude"), 0.5 + 2.5)

    def test_self_reported_cost_replaces_the_list_price(self):
        rep = ",rep:{uncached_in:1e6,cache_read:0,cache_write:0,output:1e6,usd:0.5}"
        self.assertAlmostEqual(self.cost(C % ("1e6", "0", "1e6", rep), "grok-4.7-build", "grok"), 0.5)
        # 一半有自报：另一半按牌价（grok-4.7-build $2 / $6）
        half = ",rep:{uncached_in:5e5,cache_read:0,cache_write:0,output:5e5,usd:0.5}"
        self.assertAlmostEqual(self.cost(C % ("1e6", "0", "1e6", half), "grok-4.7-build", "grok"), 0.5 + 1 + 3)

    def test_self_reported_cost_scales_with_the_cache_mode(self):
        """缓存读被口径去掉 ⇒ 自报费用按「去掉后 / 去掉前」的牌价比例缩放。"""
        rep = ",rep:{uncached_in:1e6,cache_read:1e6,cache_write:0,output:0,usd:1}"
        full = self.cost(C % ("1e6", "1e6", "0", rep), "grok-4.7-build", "grok")
        no_read = self.cost(C % ("1e6", "0", "0", rep), "grok-4.7-build", "grok")
        self.assertAlmostEqual(full, 1.0)
        self.assertAlmostEqual(no_read, 2.0 / 2.5, msg="牌价：输入 $2 + 缓存读 $0.5 ⇒ 去掉缓存读剩 2/2.5")


class TheSumKeepsTheSubsets(unittest.TestCase):
    def test_sum_buckets_adds_long_and_rep(self):
        mb = ('{uncached_in:1,cache_read:0,cache_write:0,output:1,total:2,rounds:1,'
              'long:{uncached_in:1,cache_read:0,cache_write:0,output:1},rep:{uncached_in:1,cache_read:0,cache_write:0,output:1,usd:0.25}}')
        b = '{uncached_in:1,cache_read:0,cache_write:0,output:1,total:2,rounds:1,models:{"x":%s}}' % mb
        got = ts_eval("(() => { const s = m.sumBuckets([%s, %s]).models.x; return [s.long, s.rep]; })()" % (b, b), "traffic")
        self.assertEqual(got, [{"uncached_in": 2, "cache_read": 0, "cache_write": 0, "output": 2},
                               {"uncached_in": 2, "cache_read": 0, "cache_write": 0, "output": 2, "usd": 0.5}])


if __name__ == "__main__":
    unittest.main()
