"""Claude 用量按「实际 API 调用」算：OTel 账本里、transcript 里没有的调用并进 scan.py（2026-10-19）。

## 起因（用户 2026-10-19 定的口径）
`requests.py` 今天 Claude 2057 次 / 539.85M，`scan.py` 只有 1513 次 / 398.46M。
多出的 547 次**不在任何 transcript 里**，只在 OTel 账本：`agent_summary` 511 次（139.6M）、
`web_fetch_apply` 17、`web_search_tool` 14、`compact` 5 —— Claude Code 的后台调用，真花额度。
两边都有的 1510 条按 requestId 逐条 token 相等。

## 守的不变量
- 只在 OTel 的计入；两边都有的不重复计、以 transcript 为准（它带 1h 缓存写拆分）。
- ★★ 缓存命中的 transcript 不会重读，对账集合仍然完整（requestId 随 row 进缓存）。
- 没有账本 = 旧口径，一个数都不变。
- 账本读失败不清零（CLAUDE.md §7.0b）。
- scan.py 与 requests.py 找的是**同一个**账本目录（含 `.dmg` 复制运行时）。

全部用临时目录夹具：`SOURCES` 收成单元素、`OTEL_ROOT` / `CACHE` 都指到 tmpdir，不碰真实 `~/.claude`。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "traffic"))
import scan  # noqa: E402

NOW = time.time()
T0 = NOW - 2 * 3600          # 今天以内（除非此刻在本地 00:00–02:00 —— 下面按日合计全窗口，不依赖落在哪天）


def iso(ep):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ep))


def tline(mid, rid, ep, i=3, cr=1000, cw=200, out=50, model="claude-opus-5-5"):
    o = {"type": "assistant", "timestamp": iso(ep),
         "message": {"id": mid, "model": model,
                     "usage": {"input_tokens": i, "cache_read_input_tokens": cr,
                               "cache_creation_input_tokens": cw, "output_tokens": out}}}
    if rid is not None:
        o["requestId"] = rid
    return json.dumps(o)


def span(rid, ep, i=3, cr=1000, cw=200, out=50, model="claude-opus-5-5", success=True, src="agent_summary"):
    return json.dumps({"t_start": ep - 2.5, "t_end": ep, "session.id": "s", "model": model,
                       "query_source_safe": src, "duration_ms": 2500, "input_tokens": i,
                       "output_tokens": out, "cache_read_tokens": cr, "cache_creation_tokens": cw,
                       "success": success, "attempt": 1, "request_id": rid})


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.proj = self.d / "projects"
        (self.proj / "p").mkdir(parents=True)
        self.otel = self.d / "otel-ledger"
        self.otel.mkdir()
        self.tr = self.proj / "p" / "s.jsonl"
        self.led = self.otel / "2026-10.jsonl"
        cl = next(x for x in scan.SOURCES if x["key"] == "claude")
        self.assertIs(cl.get("extra"), scan._claude_otel_rows, "★ Claude 源没挂 OTel 钩子")
        orig = (scan.SOURCES, scan.OTEL_ROOT, scan.CACHE)
        scan.SOURCES = (dict(cl, root=self.proj),)        # 单元素：其余源根本不存在
        scan.OTEL_ROOT = self.otel
        scan.CACHE = self.d / ".traffic-cache.json"

        def restore():
            scan.SOURCES, scan.OTEL_ROOT, scan.CACHE = orig
        self.addCleanup(restore)

    def put(self, path, *lines, mode="w"):
        with open(path, mode, encoding="utf-8") as fh:
            for ln in lines:
                fh.write(ln + "\n")

    def run_scan(self, use_cache=False):
        out, st = scan.scan(days=3, use_cache=use_cache)
        self.assertEqual(sorted(out), ["claude"], f"隔离没生效：{sorted(out)}")
        tot = {"total": 0, "rounds": 0, "cache_write": 0, "output": 0}
        for b in out["claude"]["days"].values():
            for k in tot:
                tot[k] += b[k]
        return tot, out["claude"], st


T = 3 + 1000 + 200 + 50       # 一条默认调用的 total


class OtelOnlyCallsAreCounted(_Fixture):
    def test_only_in_otel_is_added_and_shared_is_not_doubled(self):
        self.put(self.tr, tline("m1", "req_A", T0), tline("m2", "req_B", T0 + 60))
        self.put(self.led, span("req_A", T0 + 1), span("req_B", T0 + 61),
                 span("req_C", T0 + 120, cr=5000))                      # 只在 OTel（后台调用）
        tot, _, _ = self.run_scan()
        self.assertEqual(tot["rounds"], 3, "★★ 只在 OTel 的调用没进来，或两边都有的被重复计了")
        self.assertEqual(tot["total"], 2 * T + (3 + 5000 + 200 + 50))

    def test_transcript_wins_when_both_have_it(self):
        """两边都有时以 transcript 为准（带 1h 拆分）；OTel 给的数不许覆盖或叠加。"""
        self.put(self.tr, tline("m1", "req_A", T0, out=50))
        self.put(self.led, span("req_A", T0 + 1, out=999))
        tot, _, _ = self.run_scan()
        self.assertEqual((tot["rounds"], tot["output"]), (1, 50))

    def test_transcript_rows_without_request_id_keep_old_behaviour(self):
        self.put(self.tr, tline("m1", None, T0))
        tot, _, _ = self.run_scan()
        self.assertEqual((tot["rounds"], tot["total"]), (1, T))

    def test_zero_token_span_skipped_failed_span_with_tokens_counted(self):
        self.put(self.led, span("req_Z", T0, i=0, cr=0, cw=0, out=0),
                 span("req_F", T0 + 5, success=False))
        tot, _, _ = self.run_scan()
        self.assertEqual((tot["rounds"], tot["total"]), (1, T))

    def test_otel_rows_bucket_by_local_hour_of_t_end_and_drop_date_suffix(self):
        ep = T0 + 300
        self.put(self.led, span("req_H", ep, model="claude-haiku-5-5-20261001"))
        _, plat, _ = self.run_scan()
        h = time.strftime("%Y-%m-%dT%H", time.localtime(ep))
        self.assertEqual(plat["hours"][h]["rounds"], 1, "★ 小时桶没按本地时区的 t_end 落")
        d = time.strftime("%Y-%m-%d", time.localtime(ep))
        self.assertIn("claude-haiku-5-5", plat["days"][d]["models"])
        self.assertNotIn("cache_write_1h", plat["days"][d], "★ OTel 没有 1h 拆分，不许编一个")

    def test_parser_version_was_bumped(self):
        """★ row 多了 requestId：旧缓存里的行没有它，对账集合会是空的 ⇒ OTel 整本双计。"""
        self.assertGreaterEqual(scan.PARSER_V, 13)


class TheCacheKeepsDedupCorrect(_Fixture):
    def test_rerun_on_cache_hit_gives_the_same_result(self):
        self.put(self.tr, tline("m1", "req_A", T0))
        self.put(self.led, span("req_A", T0 + 1), span("req_C", T0 + 9))
        first, _, _ = self.run_scan(use_cache=True)
        again, _, st = self.run_scan(use_cache=True)
        self.assertEqual(st["scanned"] + st["incr"], 0, "前提：第二轮应全部命中缓存")
        self.assertEqual(again, first)
        self.assertEqual(again["rounds"], 2)

    def test_cached_transcript_still_dedups_a_span_that_arrives_later(self):
        """★★ 难点本体：transcript 走缓存命中（不重读），OTel 新到的同一条调用不许再计一次。"""
        self.put(self.tr, tline("m1", "req_A", T0), tline("m2", "req_B", T0 + 30))
        self.put(self.led, span("req_A", T0 + 1))
        self.run_scan(use_cache=True)
        self.put(self.led, span("req_B", T0 + 31), span("req_N", T0 + 90), mode="a")   # 账本追加
        tot, _, st = self.run_scan(use_cache=True)
        self.assertEqual(st["reused"], 1, "前提：transcript 这一轮必须是缓存命中")
        self.assertEqual(tot["rounds"], 3, "★★ 缓存命中的 transcript 丢了 requestId ⇒ req_B 双计")

    def test_ledger_append_is_picked_up(self):
        self.put(self.led, span("req_A", T0))
        self.run_scan(use_cache=True)
        self.put(self.led, span("req_B", T0 + 5), mode="a")
        tot, _, _ = self.run_scan(use_cache=True)
        self.assertEqual(tot["rounds"], 2, "★ 账本追加的新行没被读到（签名/增量）")


class NoLedgerMeansOldCaliber(_Fixture):
    def test_missing_ledger_equals_scan_without_the_hook(self):
        self.put(self.tr, tline("m1", "req_A", T0), tline("m2", None, T0 + 5, out=7))
        shutil.rmtree(self.otel)
        tot, _, st = self.run_scan()
        cl = scan.SOURCES[0]
        scan.SOURCES = ({k: v for k, v in cl.items() if k != "extra"},)
        old, _, _ = self.run_scan()
        self.assertEqual(tot, old)
        self.assertEqual(tot["rounds"], 2)
        self.assertEqual(st["read_failed"], 0, "没开 OTel 是常态，不是读失败")


class AReadFailureDoesNotZero(_Fixture):
    @unittest.skipIf(os.geteuid() == 0, "root 无视文件权限")
    def test_unreadable_ledger_keeps_the_cached_spans(self):
        self.put(self.led, span("req_A", T0), span("req_B", T0 + 5))
        first, _, _ = self.run_scan(use_cache=True)
        self.assertEqual(first["rounds"], 2)
        self.put(self.led, span("req_C", T0 + 9), mode="a")     # 签名变了 ⇒ 必须重读
        os.chmod(self.led, 0)
        self.addCleanup(os.chmod, self.led, 0o644)
        tot, _, _ = self.run_scan(use_cache=True)
        self.assertEqual(tot["rounds"], 2, "★★ 一次读失败把已有的数清零了")
        os.chmod(self.led, 0o644)
        tot, _, _ = self.run_scan(use_cache=True)
        self.assertEqual(tot["rounds"], 3, "读失败时旧签名必须保留，恢复后要能补上")


class BothModulesFindTheSameLedger(unittest.TestCase):
    """scan.py 与 requests.py 必须读同一个账本目录 —— 含 `.dmg` 复制运行时（`<store>/runtime/`）。"""

    def resolve(self, traffic_dir, **env):
        e = {k: v for k, v in os.environ.items() if k not in ("CODEX_ROTATE_STORE", "REQUESTS_OTEL_DIR")}
        e.update(env)
        code = ("import sys; sys.path.insert(0, %r); import scan, requests; "
                "print(scan.OTEL_ROOT); print(requests.roots()['otel'])" % str(traffic_dir))
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                           env=e, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        a, b = r.stdout.strip().splitlines()[-2:]
        return pathlib.Path(a), pathlib.Path(b)

    def test_clone_install(self):
        a, b = self.resolve(ROOT / "traffic")
        self.assertEqual(a, b)
        self.assertEqual(a, ROOT / "traffic" / "otel-ledger")

    def test_dmg_runtime_copy(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        rt = d / "runtime" / "traffic"
        rt.mkdir(parents=True)
        for f in (ROOT / "traffic").glob("*.py"):
            shutil.copy2(f, rt / f.name)
        shutil.copy2(ROOT / "portalock.py", d / "runtime" / "portalock.py")
        a, b = self.resolve(rt)
        self.assertEqual(a, b)
        self.assertEqual(a.resolve(), (d / "traffic" / "otel-ledger").resolve(),
                         "★ 复制运行时下账本在 <store>/traffic/otel-ledger，不在 runtime/ 里")

    def test_env_override_is_shared(self):
        a, b = self.resolve(ROOT / "traffic", REQUESTS_OTEL_DIR="/tmp/x-otel")
        self.assertEqual((a, b), (pathlib.Path("/tmp/x-otel"),) * 2)


class TestsThatRunTheClaudeSourceAlsoIsolateTheLedger(unittest.TestCase):
    """★ 同 AGY_ROOT 那次（`test_scan_wiring.py` docstring）：钩子读的是**模块常量**，只改源的 `root`
    隔离不了 —— 真账本照样并进夹具的结果。本文件落地当天就让 `test_claude_cache_write_1h` 红了一次。"""

    def test_every_claude_fixture_redirects_otel_root(self):
        import ast

        def redirects(tree):
            # ★ 只认**单目标**赋值 `scan.OTEL_ROOT = <夹具>`：`scan.SOURCES, scan.OTEL_ROOT = orig`
            #   是还原不是隔离，子串匹配会把它当成隔离（第一版就这么假绿过）。
            return any(isinstance(n, ast.Assign) and len(n.targets) == 1
                       and isinstance(n.targets[0], ast.Attribute) and n.targets[0].attr == "OTEL_ROOT"
                       for n in ast.walk(tree))

        bad = []
        for f in sorted((ROOT / "tests").glob("test_*.py")):
            src = f.read_text(encoding="utf-8")
            code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
            if 'x["key"] == "claude"' in code and "scan.SOURCES = (" in code and "scan.scan(" in code \
                    and not redirects(ast.parse(src)):
                bad.append(f.name)
        self.assertEqual(bad, [], "这些测试跑 Claude 源却没把 scan.OTEL_ROOT 指到夹具")


if __name__ == "__main__":
    unittest.main()
