"""阶段 B（消耗 + 请求）—— 全方面评审 2026-10-22 的修复闸。逐条对应 `~/Downloads/aicoop_full_review_20261022/SUMMARY.md` §2 / §5。

全部用临时目录夹具（`SOURCES` 收成单元素、`OTEL_ROOT` / `CACHE` 指到 tmpdir），不碰真实 `~/.claude`。
"""
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

try:
    from . import _isolation  # noqa: F401  ★ 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "traffic"))
import scan  # noqa: E402
from test_scan_claude_otel import T0, _Fixture, span, tline  # noqa: E402


def with_stat_failing(case, target):
    real = pathlib.Path.stat
    target = str(target)

    def stat(self, *a, **kw):
        if str(self) == target:
            raise PermissionError(13, "fixture", target)
        return real(self, *a, **kw)
    with mock.patch.object(pathlib.Path, "stat", stat):
        return case.run_scan(use_cache=True)


class EveryFileParserRaisesOnARead(unittest.TestCase):
    """§2「解析器遇到 OSError 返回空，空结果连同签名进缓存」：打不开 ⇒ 抛，不返回空。"""

    PARSERS = ("_scan_claude_file", "_scan_grok_file", "_scan_kimi_file", "_scan_openclaw_file",
               "_scan_reasonix_file", "_scan_agy_file", "_scan_codex_file", "_scan_otel_file")

    def test_unopenable_file_raises(self):
        gone = pathlib.Path("/nonexistent-cbx-stageB/x.jsonl")
        for name in self.PARSERS:
            with self.subTest(parser=name):
                with self.assertRaises(scan.ScanReadError, msg="★★ %s 打不开时返回了空 —— 会被签名钉成 0" % name):
                    getattr(scan, name)(gone)

    def test_the_list_covers_every_parser_in_sources(self):
        """新加一个源时这张表也要跟着长，否则它不受上面那条闸保护。"""
        used = {s["parse"].__name__ for s in scan.SOURCES if callable(s.get("parse"))}
        self.assertTrue(used, "SOURCES 一个解析器都没读到 —— 闸是空的")
        self.assertLessEqual(used - {"_scan_dsh_file", "_scan_agy_db"}, set(self.PARSERS))


class OtelReadFailureIsCounted(_Fixture):
    """§2「Claude OTel 读失败沿用缓存，但不计 read_failed，数据源仍报 ok」。"""

    @unittest.skipIf(os.geteuid() == 0, "root 无视文件权限")
    def test_unreadable_ledger_marks_the_source(self):
        self.put(self.tr, tline("m1", "req_A", T0))
        self.put(self.led, span("req_B", T0 + 5))
        self.run_scan(use_cache=True)
        self.put(self.led, span("req_C", T0 + 9), mode="a")
        os.chmod(self.led, 0)
        self.addCleanup(os.chmod, self.led, 0o644)
        tot, _, st = self.run_scan(use_cache=True)
        self.assertEqual(tot["rounds"], 2, "旧值必须沿用")
        self.assertGreaterEqual(st["read_failed"], 1, "★★ OTel 读失败没进 read_failed")
        self.assertEqual(st["sources"]["claude"]["state"], "read_failed", "★★ 数据源状态仍报 ok")

    def test_stat_failure_on_the_ledger_keeps_the_cached_spans(self):
        self.put(self.led, span("req_B", T0 + 5))
        first, _, _ = self.run_scan(use_cache=True)
        self.assertEqual(first["rounds"], 1)
        tot, _, st = with_stat_failing(self, self.led)
        self.assertEqual(tot["rounds"], 1, "★★ OTel 账本 stat 失败把已有的数清零了")
        self.assertGreaterEqual(st["read_failed"], 1)


class StatFailureKeepsTheOldCache(_Fixture):
    """§2「stat() 失败直接 continue：旧缓存不沿用，也不计 read_failed」。"""

    def test_transcript_stat_failure(self):
        self.put(self.tr, tline("m1", "req_A", T0), tline("m2", "req_B", T0 + 60))
        first, _, _ = self.run_scan(use_cache=True)
        self.assertEqual(first["rounds"], 2)
        tot, _, st = with_stat_failing(self, self.tr)
        self.assertEqual(tot["rounds"], 2, "★★ stat 失败让这个会话这一轮消失了")
        self.assertGreaterEqual(st["read_failed"], 1, "★★ stat 失败没进 read_failed")
        self.assertEqual(st["sources"]["claude"]["state"], "read_failed")
        files = json.loads(scan.CACHE.read_text(encoding="utf-8")).get("files", {})
        self.assertIn(str(self.tr), files, "★ stat 失败那一轮把旧缓存丢了 —— 下一轮从零重读")




# ── §5 请求 ─────────────────────────────────────────────────────────────────────
import subprocess  # noqa: E402
import time  # noqa: E402

import test_requests_ledger as TRL  # noqa: E402

RQ = TRL.RQ
SRC = ROOT / "codexbar" / "src"


def code(rel):
    import re
    s = (SRC / rel).read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/\"'])//[^\n]*", "", s)


def node(mod, expr):
    script = "import('file://%s').then(m => { console.log(JSON.stringify(%s)); });" % ((SRC / mod).as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script], capture_output=True, text=True,
                       timeout=60, cwd=ROOT)
    out = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if not out:
        raise AssertionError("node 没有产出：%s" % r.stderr[-600:])
    return json.loads(out[-1])


class RequestFailuresAreScoped(TRL.Base):
    def test_failed_names_the_platform(self):
        """§5「一家源报错，四家整表一起降透明度」：后端说清是哪一家。"""
        self.run_json()
        os.chmod(self.rollout, 0)
        try:
            if os.access(self.rollout, os.R_OK):
                self.skipTest("root")
            out = self.run_json()
        finally:
            os.chmod(self.rollout, 0o644)
        self.assertEqual(out["failed"], ["codex"], "★ 没说是哪一家读失败")
        self.assertEqual(self.run_json()["failed"], [], "恢复后清掉")

    def test_a_crash_does_not_invent_a_stale_time(self):
        """§5「读失败时把旧数据说成新的」：顶层异常时 stale_since 不能写成 now。"""
        import contextlib
        import io
        with mock.patch.object(RQ, "build_json", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stdout(io.StringIO()) as buf:
            RQ.main(["--json"])
        out = json.loads(buf.getvalue())
        self.assertFalse(out["ok"])
        self.assertIsNone(out["stale_since"], "★ 不知道从什么时候读不到，却写成了此刻")
        self.assertEqual(out["failed"], ["*"])

    def test_stat_error_is_reported_not_skipped(self):
        """§5「metadata stat / scandir 失败被跳过，不进 errs」。"""
        target = str(self.rollout)
        real = pathlib.Path.stat

        def stat(p, *a, **kw):
            if str(p) == target:
                raise PermissionError(13, "fixture", target)
            return real(p, *a, **kw)
        with mock.patch.object(pathlib.Path, "stat", stat):
            out = self.run_json()
        self.assertIn("codex", out.get("failed") or [], "★★ 读不到被当成了没有")

    def test_a_vanished_file_is_not_a_failure(self):
        """已知阴性：列目录之后被删了（FileNotFoundError）是常态，不报读失败。"""
        target = str(self.rollout)
        real = pathlib.Path.stat

        def stat(p, *a, **kw):
            if str(p) == target:
                raise FileNotFoundError(2, "gone", target)
            return real(p, *a, **kw)
        with mock.patch.object(pathlib.Path, "stat", stat):
            out = self.run_json()
        self.assertNotIn("codex", out.get("failed") or [])


class TheWindowIsNotOverwrittenAfterAFailedRebuild(TRL.Base):
    def test_snap_err_skips_the_window_write(self):
        """§5「`.window.json` 坏了、rebuild 又失败时照样写出新的 window，两天历史丢失」。"""
        self.run_json()
        win = self.tmp / "ledger" / ".window.json"
        win.write_text("{broken")
        with mock.patch.object(RQ.Store, "rebuild", side_effect=RQ.ReadFail("fixture")):
            self.run_json()
        self.assertEqual(win.read_text(), "{broken", "★★ 重建失败时把只有这一轮的窗口写了下去")


class RelayRequestsAreNotDirect(TRL.Base):
    def test_relay_affinity_line_maps_to_the_relay(self):
        """§5「走中转站的请求被记成「直连」」：代理给中转站也写归属行，账本记「中转站·名字」。"""
        rid = "resp_B" + self.sid[:4]
        tB = TRL.T0 + 40
        with open(self.tmp / "proxy.log", "a") as fh:
            fh.write("[proxy %s #%s] affinity %s → [TokenDun@relay]\n"
                     % (time.strftime("%m-%d %H:%M:%S", time.localtime(tB)), rid, rid[:18]))
        recs = self.by_key(self.run_json(TRL.T0 + 600))
        hit = [r for k, r in recs.items() if k.startswith("codex:resp_B")]
        self.assertTrue(hit, "夹具里没有 resp_B —— 闸是空的")
        self.assertEqual(hit[0]["account"], "中转站·TokenDun", "★★ 中转站的请求被记成了直连")

    def test_relay_owners_never_enter_the_lanes(self):
        import rotation as R
        text = "[proxy 10-22 10:00:00 #resp_X1] affinity resp_X1 → [TokenDun@relay]\n"
        now = time.mktime(time.strptime("2026-10-22 10:05:00", "%Y-%m-%d %H:%M:%S"))
        relay = {}
        _rq, owner, *_ = R.scan_proxy_log(text, now, now - 3600, now + 60, relay_owner=relay)
        self.assertEqual(owner, {}, "★ 中转站进了账号泳道的归属")
        self.assertEqual(relay, {"resp_X1": "TokenDun"})

    def test_proxy_writes_the_line_for_relay_too(self):
        body = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        i = body.index("def _finish(")
        seg = body[i:body.index("    def _proxy(self):", i)]
        self.assertNotIn("if aid and not got:", seg, "★ 中转站档又整段跳过了归属行")
        self.assertIn('_plog(f"affinity {rid[:18]} → [{label}]", rid)', seg)


class RequestsShapes(unittest.TestCase):
    def test_incremental_state_is_copied(self):
        body = (ROOT / "traffic" / "requests.py").read_text(encoding="utf-8")
        self.assertEqual(body.count('copy.deepcopy((ent or {}).get("state"))'), 2)
        self.assertEqual(body.count('copy.deepcopy((cur["files"].get('), 2)

    def test_a_middle_generation_without_timestamps_is_skipped(self):
        body = (ROOT / "traffic" / "requests.py").read_text(encoding="utf-8")
        i = body.index("if created is None or (fin is None and (ttft is None or strm is None)):")
        self.assertIn("if pi < len(parsed) - 1:", body[i:i + 400], "★ 中间那次永远缺时间戳 ⇒ 游标永不前进")

    def test_first_failure_keeps_payload_null(self):
        self.assertIn("setPayload((prev) => (p.requests.length ? p : prev));", code("hooks/useRequests.ts"))

    def test_row_dims_follow_the_platform(self):
        got = node("requests.ts", "[m.rowStale(['codex'],'codex'), m.rowStale(['codex'],'claude'), m.rowStale(['*'],'grok'), m.rowStale(null,'codex')]")
        self.assertEqual(got, [True, False, True, False])
        self.assertIn("const rd = rowStale(failed, x.platform) ? STALE_OPACITY : 1;", code("pages/RequestsPage.tsx"))

    def test_no_unit_after_a_dash(self):
        body = code("pages/RequestsPage.tsx")
        self.assertIn("{value !== DASH && <span", body)
        self.assertIn("{x.avgTps != null && <span", body)


# ── §2 页面 ─────────────────────────────────────────────────────────────────────

class TokenPageShapes(unittest.TestCase):
    def test_hover_signature_has_no_values(self):
        body = code("components/tk/TkArea.tsx")
        self.assertIn('const sig = `${n}|${labels[0] ?? ""}|${target.keys.join(",")}`;', body,
                      "★ 悬停签名里带数值 ⇒ 心跳刷新时浮层自己消失")
        self.assertIn("}, [dataSig]);", body, "动画仍要跟着数值走")

    def test_platform_switch_resets_class_isolation(self):
        self.assertIn("setIsoCls(new Set()); }", code("pages/PlatformPage.tsx"))

    def test_no_asterisk_on_a_dash(self):
        self.assertIn("{L > 0 && est && m.total > 0 && <span", code("pages/PlatformPage.tsx"))

    def test_price_warnings_share_one_window(self):
        d = {"platforms": {"codex": {"days": {"2026-10-22": {"models": {"a": {"total": 5}}},
                                              "2026-09-01": {"models": {"old": {"total": 5}}}}},
                           "claude": {"days": {"2026-10-21": {"models": {"b": {"total": 1}}}}}}}
        got = node("rates.ts", "[m.recentModels(%s, '2026-10-22'), m.recentModels(%s, '2026-10-22', 'claude')]"
                   % (json.dumps(d), json.dumps(d)))
        self.assertEqual(sorted(x["model"] for x in got[0]), ["a", "b"], "30 天外的不算")
        self.assertEqual([x["model"] for x in got[1]], ["b"])
        for rel in ("pages/TrafficPage.tsx", "pages/PlatformPage.tsx"):
            with self.subTest(rel=rel):
                self.assertIn("recentModels(data, today", code(rel), "★ 两页价格待核又各算各的窗口")


# ── 阶段 B 评审（codex + gemini）补修 ───────────────────────────────────────────

class StageBReviewFollowUps(unittest.TestCase):
    def test_a_rerun_keeps_force(self):
        body = code("hooks/useTraffic.ts")
        self.assertIn("rerun.current = force ? 2 : Math.max(rerun.current, 1)", body)
        self.assertIn("void scanRef.current?.(f);", body, "★ 手动 ↻ 撞上在途扫描时补跑丢了 force")

    def test_late_answers_go_to_their_own_window(self):
        body = code("hooks/useTraffic.ts")
        self.assertIn("if (lastDays.current === DEFAULT_DAYS) adopt(parse(raw));", body, "★ 广播回读不看窗口")
        self.assertIn("else if (d) byWindow.current.set(days, d);", body, "★ 跨窗口的小时补扫结果被丢掉、键又留着")

    def test_read_time_moves_only_on_success(self):
        self.assertNotIn("setReadAt(toMs(p.stale_since))", code("hooks/useRequests.ts"),
                         "★ 把「从什么时候开始读不到」当成「数据是什么时候的」")

    def test_skipped_agy_probe_is_said_out_loud(self):
        self.assertIn('if (!rs.length) return "⏭ 另一个进程正在跑 Gemini 探针', code("agy.ts"))
        self.assertIn("?.skipped ? [] : null", code("hooks/useAgyPool.ts"))
        self.assertIn('{"skipped": True', (ROOT / "agy-rotate").read_text(encoding="utf-8"))

    def test_menubar_height_key_is_versioned(self):
        self.assertIn('const H_KEY = "codexbar_mb_h_base";', code("MenuBar.tsx"),
                      "★ 换了含义（不含在跑条）却沿用旧键 ⇒ 在跑条加两次")


class WalkErrorsAreReported(TRL.Base):
    def test_a_subdir_that_cannot_be_listed_is_a_failure(self):
        """阶段 B 评审：`os.walk` 默认吞掉子目录读错误 ⇒ 整棵会话树静默消失。"""
        real = os.walk

        def walk(top, *a, **kw):
            on = kw.get("onerror")
            if on is not None and str(top).endswith("codex"):
                on(PermissionError(13, "fixture", str(top) + "/2026"))
            return real(top, *a, **kw)
        with mock.patch.object(RQ.os, "walk", walk):
            out = self.run_json()
        self.assertIn("codex", out.get("failed") or [], "★★ 子目录读不了被当成了没有")


if __name__ == "__main__":
    unittest.main()
