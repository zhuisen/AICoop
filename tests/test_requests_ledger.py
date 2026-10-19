"""逐请求账本 `traffic/requests.py`：四家夹具 · 增量游标 · 去重 · 失败保留旧值 · 白名单 · `--live` 合计规则。

★ 全部数据源都指到临时目录（`REQUESTS_*` 环境变量），**不碰真实 `~/.codex` / `~/.claude` / agy / grok /
  `state.json` / `proxy.log`**。夹具里刻意塞了 `SECRET-…` 正文，用来证明正文永远不进账本、游标与 stdout。
"""
try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "traffic" / "requests.py"
spec = importlib.util.spec_from_file_location("requests_ledger", SCRIPT)
RQ = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RQ)

SECRETS = ("SECRET-PROMPT", "SECRET-TOOL-OUTPUT", "SECRET-ANSWER", "demo-leak@example.com")
NOW = time.time()
#: ★ 契约正本（PLAN §2.1 的 `requests[]` 形状）抄在这里**是刻意的**：拿 `RQ.KEYS` 自己比自己，
#:   往白名单里混一个内部键照样绿（变异实测）。改契约 = 两边一起改，并通知前端。
CONTRACT_KEYS = ("key", "platform", "t_start", "t_end", "model", "source", "session", "session_title",
                 "account", "input", "cached", "output", "reasoning", "ttft_ms", "gen_ms", "total_ms",
                 "tool_ms", "tps", "est", "session_req_n")
N_FIXTURE = 9           # codex 2 + claude 4（主会话 2 + 子 agent 2）+ agy 2 + grok 1
T0 = NOW - 900          # 夹具全部落在「15 分钟前」附近：一定在 2 天窗口内


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % int(round((t % 1) * 1000) % 1000)


def _line(t, typ, payload):
    # ★ 真实 rollout 是紧凑 JSON、`timestamp` 打头 —— 解析器的行首正则依赖这个形状。
    return json.dumps({"timestamp": _iso(t), "type": typ, "payload": payload},
                      separators=(",", ":"), ensure_ascii=False) + "\n"


# ── protobuf 编码（agy 夹具） ───────────────────────────────────────────────────

def _vint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _fv(f, v):
    return _vint(f << 3) + _vint(v)


def _fb(f, b):
    return _vint((f << 3) | 2) + _vint(len(b)) + b


def _ts(t):
    s = int(t)
    return _fv(1, s) + _fv(2, int(round((t - s) * 1e9)))


# ── 夹具 ───────────────────────────────────────────────────────────────────────

def codex_rollout(sess, t0, cwd="/x/proj-alpha", tail=True):
    """一轮两条响应：A（每轮第一条，官方首字覆盖）+ B（推理项打头，前面跑过 2 s 工具）。"""
    L = [
        _line(t0, "session_meta", {"id": sess, "cwd": cwd, "originator": "codex-tui", "source": "cli"}),
        _line(t0 + 0.1, "turn_context", {"turn_id": "t1", "model": "gpt-6-sol", "cwd": cwd}),
        _line(t0 + 1, "event_msg", {"type": "task_started", "turn_id": "t1"}),
        _line(t0 + 1.1, "response_item", {"type": "message", "role": "user",
                                          "content": [{"type": "input_text", "text": "SECRET-PROMPT"}]}),
        _line(t0 + 9, "response_item", {"type": "reasoning", "id": "rs_1"}),
        _line(t0 + 11, "response_item", {"type": "function_call", "id": "fc_1", "arguments": "SECRET-PROMPT"}),
        _line(t0 + 11.3, "token_usage_record", {
            "turn_id": "t1", "response_id": "resp_A" + sess[:4],
            "usage": {"input_tokens": 1000, "cached_input_tokens": 800, "output_tokens": 300,
                      "reasoning_output_tokens": 100, "total_tokens": 1300}}),
        _line(t0 + 13.4, "event_msg", {"type": "item_completed", "turn_id": "t1",
                                       "item": {"type": "CommandExecution", "duration": {"secs": 2, "nanos": 0},
                                                "aggregated_output": "SECRET-TOOL-OUTPUT"}}),
        _line(t0 + 13.5, "response_item", {"type": "function_call_output", "output": "SECRET-TOOL-OUTPUT"}),
        _line(t0 + 20, "response_item", {"type": "reasoning", "id": "rs_2"}),
        _line(t0 + 24, "response_item", {"type": "message", "role": "assistant",
                                         "content": [{"type": "output_text", "text": "SECRET-ANSWER"}]}),
        _line(t0 + 24.2, "token_usage_record", {
            "turn_id": "t1", "response_id": "resp_B" + sess[:4],
            "usage": {"input_tokens": 2000, "cached_input_tokens": 1500, "output_tokens": 500,
                      "reasoning_output_tokens": 100, "total_tokens": 2500}}),
    ]
    if tail:
        L.append(_line(t0 + 24.3, "event_msg", {"type": "task_complete", "turn_id": "t1",
                                                "time_to_first_token_ms": 7500, "duration_ms": 23300,
                                                "last_agent_message": "SECRET-ANSWER"}))
    return "".join(L)


def claude_lines(sess, t0, cwd="/x/proj-beta", rid1="req_1", rid2="req_2", agent=None):
    base = {"sessionId": sess, "cwd": cwd}
    if agent:
        base["agentId"] = agent

    def asst(t, rid, out, th):
        return json.dumps({**base, "type": "assistant", "requestId": rid, "message": {
            "id": "msg_" + rid, "model": "claude-opus-5-5", "content": [{"type": "text", "text": "SECRET-ANSWER"}],
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 200,
                      "output_tokens": out, "output_tokens_details": {"thinking_tokens": th}}},
            "timestamp": _iso(t)}, separators=(",", ":")) + "\n"

    def user(t):
        # ★ 真实 transcript 是紧凑 JSON；非 assistant 行的时间戳靠 `"timestamp":"` 字面量找。
        return json.dumps({**base, "type": "user", "message": {"role": "user", "content": "SECRET-PROMPT"},
                           "timestamp": _iso(t)}, separators=(",", ":")) + "\n"
    return (user(t0) + asst(t0 + 3, rid1, 0, 50) + asst(t0 + 5, rid1, 400, 50) + user(t0 + 8)
            + asst(t0 + 12, rid2, 100, 0) + asst(t0 + 14, rid2, 300, 0))


def otel_span(rid, sess, t0, t1, ttft, dur, out):
    return json.dumps({"t_start": t0, "t_end": t1, "request_id": rid, "session.id": sess,
                       "model": "claude-opus-5-5", "ttft_ms": ttft, "duration_ms": dur,
                       "input_tokens": 10, "output_tokens": out, "cache_read_tokens": 5000,
                       "cache_creation_tokens": 200, "user.email": "demo-leak@example.com"}) + "\n"


def agy_db(path, t0, title="/x/proj-gamma"):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE steps (idx integer PRIMARY KEY, step_type integer, status integer, metadata blob);
        CREATE TABLE gen_metadata (idx integer PRIMARY KEY, data blob, size integer DEFAULT 0);
        CREATE TABLE trajectory_metadata_blob (id text PRIMARY KEY, data blob);
    """)
    steps = [
        (0, 14, 3, _fb(1, _ts(t0 - 1))),
        (1, 15, 3, _fb(1, _ts(t0)) + _fb(7, _ts(t0 + 10))),
        (2, 132, 3, _fb(1, _ts(t0 + 10)) + _fb(32, _ts(t0 + 10.1)) + _fb(8, _ts(t0 + 13.1))
         + _fb(4, _fb(3, b"SECRET-TOOL-OUTPUT"))),
        (3, 15, 3, _fb(1, _ts(t0 + 13.3)) + _fb(7, _ts(t0 + 20))),
    ]
    con.executemany("INSERT INTO steps VALUES (?,?,?,?)", steps)

    def gen(lsi, usage, ttft, strm):
        inner = (_fb(4, usage) + _fb(11, _ts(ttft)) + _fb(12, _ts(strm)) + _fb(19, b"gemini-3.8-flash-n")
                 + _fb(20, _fb(1, b"last_step_index") + _fb(2, str(lsi).encode())))
        return _fb(1, inner)
    con.execute("INSERT INTO gen_metadata (idx, data) VALUES (0, ?)",
                (gen(0, _fv(2, 900) + _fv(3, 600) + _fv(5, 4000) + _fv(9, 200) + _fv(10, 400), 4.0, 6.0),))
    con.execute("INSERT INTO gen_metadata (idx, data) VALUES (1, ?)",
                (gen(2, _fv(2, 100) + _fv(3, 120) + _fv(5, 5000) + _fv(9, 100) + _fv(10, 20), 6.5, 0.2),))
    con.execute("INSERT INTO trajectory_metadata_blob VALUES ('main', ?)", (_fb(7, ("file://" + title).encode()),))
    con.commit()
    con.close()


def grok_session(d, t0):
    d.mkdir(parents=True)
    ev = [{"ts": _iso(t0), "type": "turn_started"}, {"ts": _iso(t0 + 0.5), "type": "loop_started", "loop_index": 0},
          {"ts": _iso(t0 + 3.5), "type": "first_token"},
          {"ts": _iso(t0 + 9), "type": "tool_completed", "tool_name": "x", "duration_ms": 1200},
          {"ts": _iso(t0 + 10), "type": "loop_started", "loop_index": 1},
          {"ts": _iso(t0 + 12), "type": "first_token"}]
    (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ev))
    up = {"timestamp": int(t0 + 30), "method": "_x.ai/session/update", "params": {
        "sessionId": d.name, "_meta": {"agentTimestampMs": int((t0 + 30) * 1000)},
        "update": {"sessionUpdate": "turn_completed", "prompt_id": "p1", "elapsed_ms": 30000,
                   "usage": {"inputTokens": 10000, "cachedReadTokens": 8000, "outputTokens": 2000,
                             "reasoningTokens": 500, "apiDurationMs": 25000,
                             "modelUsage": {"grok-4.7-build": {"outputTokens": 2000}}}}}}
    chunk = {"timestamp": int(t0 + 5), "method": "session/update", "params": {
        "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "SECRET-ANSWER"}}}}
    (d / "updates.jsonl").write_text(json.dumps(chunk) + "\n" + json.dumps(up) + "\n")


class Base(unittest.TestCase):
    """每条用例一套全新的临时数据源 + 账本目录。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="requests-ledger-test-"))
        t = self.tmp
        self.env = {
            "REQUESTS_LEDGER_DIR": str(t / "ledger"), "REQUESTS_CODEX_ROOT": str(t / "codex"),
            "REQUESTS_CLAUDE_ROOT": str(t / "claude"), "REQUESTS_OTEL_DIR": str(t / "otel"),
            "REQUESTS_AGY_DB_ROOT": str(t / "agy"), "REQUESTS_AGY_LOG_DIR": str(t / "agylog"),
            "REQUESTS_AGY_LEDGER": str(t / "agyledger.jsonl"), "REQUESTS_AGY_POOL": str(t / "pool.json"),
            "REQUESTS_GROK_ROOT": str(t / "grok"), "REQUESTS_PROXY_LOG": str(t / "proxy.log"),
            "REQUESTS_STATE": str(t / "state.json"),
        }
        self.patch = mock.patch.dict(os.environ, self.env)
        self.patch.start()
        for k in ("codex", "claude", "otel", "agy", "agylog", "grok"):
            (t / k).mkdir()
        # codex 会话 + 代理日志（resp_A 走号A，resp_B 对不上 ⇒ 直连）+ 脱敏 state
        self.sid = "01a14e53-0af7-7833-b7ff-bfec945c735a"
        self.rollout = t / "codex" / "2026" / ("rollout-2026-10-19T01-00-00-%s.jsonl" % self.sid)
        self.rollout.parent.mkdir(parents=True)
        self.rollout.write_text(codex_rollout(self.sid, T0))
        (t / "state.json").write_text(json.dumps({"slots": {"abcdef12-0000": {"label": "号A"}}}))
        tA = T0 + 11.3
        (t / "proxy.log").write_text("[proxy %s #resp_A%s] affinity resp_A → [号A#abcdef12]\n"
                                     % (time.strftime("%m-%d %H:%M:%S", time.localtime(tA)), self.sid[:4]))
        # claude：主会话（req_1 有 span、req_2 只有 transcript）+ 一个嵌在 workflows 下的子 agent
        self.csid = "11111111-2222-3333-4444-555555555555"
        proj = t / "claude" / "-x-proj-beta"
        proj.mkdir()
        (proj / (self.csid + ".jsonl")).write_text(claude_lines(self.csid, T0))
        sub = proj / self.csid / "subagents" / "workflows" / "wf_1"
        sub.mkdir(parents=True)
        (sub / "agent-abc.jsonl").write_text(claude_lines(self.csid, T0 + 100, rid1="req_3", rid2="req_4",
                                                          agent="abc"))
        (t / "otel" / time.strftime("%Y-%m.jsonl")).write_text(
            otel_span("req_1", self.csid, T0 + 0.5, T0 + 5, 1500, 4500, 400))
        # agy：一个会话库 + 启动日志（身份 + conv id + print 模式）+ 池
        self.conv = "c0594941-ef99-451c-905b-6783e98a3adc"
        agy_db(str(t / "agy" / (self.conv + ".db")), T0)
        lt = time.localtime(T0 - 60)
        log = t / "agylog" / time.strftime("cli-%Y%m%d_%H%M%S.log", lt)
        log.write_text("I%s 1 auth.go:1] applyAuthResult: email=demo1@example.com\n"
                       "I%s 1 printmode.go:1] Print mode: starting\nconversation %s\n"
                       % (time.strftime("%m%d %H:%M:%S.000000", lt), time.strftime("%m%d %H:%M:%S.000000", lt),
                          self.conv))
        (t / "pool.json").write_text(json.dumps({"accounts": {"s1": {"email": "demo1@example.com",
                                                                     "label": "号G"}}}))
        # grok
        grok_session(t / "grok" / "%2Fx%2Fproj-delta" / "01a14e2e-d73e-7e22-80d4-6152bdf3e025", T0)

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_json(self, now=None):
        return RQ.build_json(now or time.time(), 2)

    def by_key(self, out):
        return {r["key"]: r for r in out["requests"]}

    def ledger_lines(self):
        out = []
        for p in sorted((self.tmp / "ledger").glob("????-??.jsonl")):
            out += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
        return out


class FourPlatformsParse(Base):
    def test_codex_two_responses(self):
        r = self.by_key(self.run_json())
        a, b = r["codex:resp_A" + self.sid[:4]], r["codex:resp_B" + self.sid[:4]]
        # A：每轮第一条 ⇒ 起点 = task_started，首字 = 官方 7500 ms；结束 = 最后一个输出项（不是 usage 行）
        self.assertAlmostEqual(a["t_start"], T0 + 1, places=2)
        self.assertAlmostEqual(a["t_end"], T0 + 11, places=2)
        self.assertEqual(a["ttft_ms"], 7500)
        self.assertEqual(a["gen_ms"], 2500)
        self.assertEqual(a["tps"], 80.0, "可见输出 (300−100) ÷ 2.5 s")
        self.assertFalse(a["est"])
        self.assertIsNone(a["tool_ms"])
        self.assertEqual((a["input"], a["cached"], a["output"], a["reasoning"]), (1000, 800, 300, 100))
        self.assertEqual((a["model"], a["source"], a["session_title"], a["session_req_n"]),
                         ("gpt-6-sol", "交互", "proj-alpha", 1))
        self.assertEqual(a["account"], "号A")
        # B：起点 = 最后一条输入（工具输出）；首字 = 推理项写盘
        self.assertAlmostEqual(b["t_start"], T0 + 13.5, places=2)
        self.assertEqual(b["ttft_ms"], 6500)
        self.assertEqual(b["gen_ms"], 4000)
        self.assertEqual(b["tps"], 100.0)
        self.assertEqual(b["tool_ms"], 2000)
        self.assertEqual(b["session_req_n"], 2)
        self.assertEqual(b["account"], "直连")

    def test_claude_span_wins_transcript_falls_back(self):
        r = self.by_key(self.run_json())
        a = r["claude:req_1"]
        self.assertFalse(a["est"])
        self.assertEqual((a["ttft_ms"], a["gen_ms"], a["total_ms"]), (1500, 3000, 4500))
        self.assertEqual(a["tps"], 133.3)
        self.assertEqual((a["input"], a["cached"], a["output"], a["reasoning"]), (5210, 5000, 400, 50))
        self.assertEqual((a["session"], a["session_title"], a["session_req_n"], a["account"]),
                         (self.csid, "proj-beta", 1, "本机"))
        b = r["claude:req_2"]
        self.assertTrue(b["est"], "没有 span ⇒ transcript 估值")
        self.assertIsNone(b["ttft_ms"])
        self.assertAlmostEqual(b["t_start"], T0 + 8, places=2)
        self.assertEqual((b["total_ms"], b["tps"], b["session_req_n"]), (6000, 50.0, 2))
        sub = r["claude:req_3"]
        self.assertEqual(sub["session"], "agent-abc", "嵌套 workflows 下的子 agent 也要收，且是它自己的会话")

    def test_agy_db(self):
        r = self.by_key(self.run_json())
        a, b = r["agy:%s:0" % self.conv], r["agy:%s:1" % self.conv]
        self.assertEqual((a["ttft_ms"], a["gen_ms"], a["total_ms"]), (4000, 6000, 10000))
        self.assertEqual(a["tps"], 66.7, "f10 可见输出 400 ÷ streaming 6 s")
        self.assertFalse(a["est"])
        self.assertEqual((a["input"], a["cached"], a["output"], a["reasoning"]), (4900, 4000, 600, 200))
        self.assertEqual((a["model"], a["session_title"], a["session_req_n"]), ("gemini-3.8-flash", "proj-gamma", 1))
        self.assertEqual((a["account"], a["source"]), ("号G", "agy -p"))
        self.assertTrue(b["est"], "streaming 0.2 s < 0.3 s ⇒ 退回 output ÷ (ttft + streaming)")
        self.assertEqual(b["tps"], 17.9)
        self.assertEqual(b["tool_ms"], 3000)
        self.assertEqual(b["session_req_n"], 2)

    def test_grok_turn(self):
        r = self.by_key(self.run_json())
        g = r["grok:p1"]
        self.assertEqual((g["tps"], g["ttft_ms"], g["gen_ms"], g["total_ms"], g["tool_ms"]),
                         (80.0, 3000, 22000, 30000, 1200))
        self.assertEqual((g["input"], g["cached"], g["output"], g["reasoning"]), (10000, 8000, 2000, 500))
        self.assertEqual((g["session_title"], g["account"], g["model"]), ("proj-delta", "单号", "grok-4.7-build"))

    def test_contract_shape_and_order(self):
        out = self.run_json()
        self.assertEqual(set(out) >= {"v", "generated_at", "ok", "error", "stale_since", "requests", "days"}, True)
        self.assertTrue(out["ok"])
        ends = [r["t_end"] for r in out["requests"]]
        self.assertEqual(ends, sorted(ends, reverse=True), "按完成时刻倒序")
        for r in out["requests"]:
            self.assertEqual(tuple(r), CONTRACT_KEYS)
        n = out["days"]["today"]["n"] + out["days"]["yesterday"]["n"]
        self.assertEqual(n, len(out["requests"]))

    def test_cli_exit_zero_and_json(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--json"], capture_output=True, text=True,
                           env={**os.environ, **self.env}, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(json.loads(p.stdout)["requests"]), N_FIXTURE)


class IncrementalCursor(Base):
    def test_half_line_is_not_consumed_and_counters_carry(self):
        self.run_json()
        cur = json.loads((self.tmp / "ledger" / ".cursor.json").read_text())
        self.assertEqual(cur["files"][str(self.rollout)]["off"], self.rollout.stat().st_size)
        t1 = T0 + 60
        extra = (_line(t1, "event_msg", {"type": "task_started", "turn_id": "t2"})
                 + _line(t1 + 5, "response_item", {"type": "reasoning"})
                 + _line(t1 + 8, "response_item", {"type": "message", "role": "assistant"})
                 + _line(t1 + 8.1, "token_usage_record", {"turn_id": "t2", "response_id": "resp_C",
                                                          "usage": {"input_tokens": 5, "output_tokens": 50}}))
        cut = len(extra) - 20
        with open(self.rollout, "a") as fh:
            fh.write(extra[:cut])                          # 最后一行只写了一半
        out = self.by_key(self.run_json())
        self.assertNotIn("codex:resp_C", out, "半行不能被解析")
        off = json.loads((self.tmp / "ledger" / ".cursor.json").read_text())["files"][str(self.rollout)]["off"]
        self.assertEqual(off, self.rollout.stat().st_size - (cut - extra[:cut].rfind("\n") - 1),
                         "游标停在最后一个换行之后")
        with open(self.rollout, "a") as fh:
            fh.write(extra[cut:])
        c = self.by_key(self.run_json())["codex:resp_C"]
        self.assertEqual(c["session_req_n"], 3, "会话内序号跨运行接着数")
        self.assertEqual(c["model"], "gpt-6-sol", "跨行状态（模型）跨运行保留")

    def test_rewritten_file_is_reparsed_without_double_count(self):
        self.run_json()
        n0 = len(self.run_json()["requests"])
        self.rollout.write_text(codex_rollout(self.sid, T0))         # 同内容整份重写（换 inode）
        out = self.run_json()
        self.assertEqual(len(out["requests"]), n0, "按 key 去重：重解不双计")


class DedupAndOverride(Base):
    def test_unchanged_run_appends_nothing(self):
        self.run_json()
        n = len(self.ledger_lines())
        self.run_json()
        self.assertEqual(len(self.ledger_lines()), n, "没有变化 ⇒ 账本不追加")

    def test_newer_value_overrides_and_null_does_not_blank(self):
        self.rollout.write_text(codex_rollout(self.sid, T0, tail=False))   # 先没有 task_complete
        a = self.by_key(self.run_json())["codex:resp_A" + self.sid[:4]]
        self.assertEqual(a["ttft_ms"], 8000, "暂用推理项写盘时刻")
        with open(self.rollout, "a") as fh:
            fh.write(_line(T0 + 24.3, "event_msg", {"type": "task_complete", "turn_id": "t1",
                                                    "time_to_first_token_ms": 7500}))
        a = self.by_key(self.run_json())["codex:resp_A" + self.sid[:4]]
        self.assertEqual(a["ttft_ms"], 7500, "官方首字到了 ⇒ 新值覆盖")
        keys = [r["key"] for r in self.ledger_lines()]
        self.assertEqual(keys.count("codex:resp_A" + self.sid[:4]), 2, "账本只追加，读取按 key 取新值")
        m = RQ._merge({**{k: None for k in RQ.KEYS}, "key": "k", "account": "号A", "tps": 9.0},
                      {"key": "k", "account": None, "tps": 10.0})
        self.assertEqual((m["account"], m["tps"]), ("号A", 10.0), "新值里的 null 不覆盖旧值")

    def test_window_snapshot_rebuilds_from_ledger(self):
        a = self.by_key(self.run_json())
        (self.tmp / "ledger" / ".window.json").unlink()
        b = self.by_key(self.run_json())
        self.assertEqual(set(a), set(b))


class FailureKeepsOldValues(Base):
    """§7.0b：读失败 ⇒ 旧值保留、游标不前进、顶层 `ok:false` + `error` + `stale_since`（不随重试刷新）。"""

    def test_unreadable_source_keeps_records_and_marks_stale(self):
        first = self.by_key(self.run_json())
        codex_keys = {k for k in first if k.startswith("codex:")}
        self.assertTrue(codex_keys)
        with open(self.rollout, "a") as fh:                     # 失败期间又写了一条
            fh.write(_line(T0 + 70, "token_usage_record", {"turn_id": "t1", "response_id": "resp_D",
                                                           "usage": {"input_tokens": 1, "output_tokens": 9}}))
        os.chmod(self.rollout, 0)
        try:
            if os.access(self.rollout, os.R_OK):
                self.skipTest("以 root 跑：chmod 000 挡不住读")
            t_fail = time.time()
            out = self.run_json(t_fail)
            self.assertFalse(out["ok"])
            self.assertIn("codex", out["error"])
            self.assertEqual(out["stale_since"], t_fail)
            self.assertTrue(codex_keys <= set(self.by_key(out)), "★ 读失败不许把旧记录丢掉")
            self.assertTrue(any(k.startswith("claude:") for k in self.by_key(out)), "一家坏了不拖垮别家")
            again = self.run_json(t_fail + 30)
            self.assertEqual(again["stale_since"], t_fail, "连续失败不刷新 stale_since")
        finally:
            os.chmod(self.rollout, 0o644)
        ok = self.run_json()
        self.assertTrue(ok["ok"])
        self.assertIsNone(ok["stale_since"])
        self.assertIn("codex:resp_D", self.by_key(ok), "失败期间写下的那条恢复后要补上（游标没前进）")


class TheLedgerHoldsOnlyWhitelistedKeys(Base):
    def test_every_persisted_record_is_whitelisted_and_no_content_leaks(self):
        out = self.run_json()
        live = RQ.build_live(time.time())
        lines = self.ledger_lines()
        self.assertGreaterEqual(len(lines), N_FIXTURE)
        for r in lines:
            self.assertEqual(set(r), set(CONTRACT_KEYS),
                             "账本里出现了白名单外的键：%s" % (set(r) - set(CONTRACT_KEYS)))
        snap = json.loads((self.tmp / "ledger" / ".window.json").read_text())["records"]
        for r in snap.values():
            self.assertEqual(set(r), set(CONTRACT_KEYS))
        # 源文件路径（能认出项目目录）也不许进账本 / 快照 / 输出；游标按路径做键，不在此列。
        led = [p.read_text() for p in (self.tmp / "ledger").glob("????-??.jsonl")]
        led += [(self.tmp / "ledger" / ".window.json").read_text(), json.dumps(out), json.dumps(live)]
        for b in led:
            self.assertNotIn(str(self.tmp), b, "源文件路径进了账本 / 输出")
        blobs = [p.read_text(errors="replace") for p in (self.tmp / "ledger").iterdir() if p.is_file()]
        blobs += [json.dumps(out, ensure_ascii=False), json.dumps(live, ensure_ascii=False)]
        for s in SECRETS:
            for b in blobs:
                self.assertNotIn(s, b, "正文 / 邮箱进了账本、游标或输出")


class LiveAggregation(Base):
    def setUp(self):
        super().setUp()
        # 主 codex 会话这一轮还没写 task_complete ⇒ 在跑（判停看轮次结束标记，见 `TurnEndMarkers`）
        self.rollout.write_text(codex_rollout(self.sid, T0, tail=False))
        # 第二个 codex 会话：在跑，最近一条 t/s = 50
        self.sid2 = "02b14e53-0af7-7833-b7ff-bfec945c735b"
        p2 = self.rollout.parent / ("rollout-2026-10-19T02-00-00-%s.jsonl" % self.sid2)
        t = T0 + 200
        p2.write_text(_line(t, "event_msg", {"type": "task_started", "turn_id": "u1"})
                      + _line(t + 2, "response_item", {"type": "reasoning"})
                      + _line(t + 6, "response_item", {"type": "message", "role": "assistant"})
                      + _line(t + 6.1, "token_usage_record", {"turn_id": "u1", "response_id": "resp_E",
                                                              "usage": {"input_tokens": 10, "output_tokens": 200}}))
        # 第三个 codex 会话：在跑，但还没完成第一条响应
        self.sid3 = "03c14e53-0af7-7833-b7ff-bfec945c735c"
        (self.rollout.parent / ("rollout-2026-10-19T03-00-00-%s.jsonl" % self.sid3)).write_text(
            _line(time.time() - 5, "event_msg", {"type": "task_started", "turn_id": "w1"}))
        # claude / agy / grok 的文件都推到兜底窗口之外 ⇒ 不在跑
        old = time.time() - RQ.FALLBACK_SECS - 100
        for root in ("claude", "agy", "grok"):
            for dp, _d, fns in os.walk(self.tmp / root):
                for n in fns:
                    os.utime(os.path.join(dp, n), (old, old))

    def test_sum_within_one_ai_only_and_nulls_do_not_count(self):
        live = RQ.build_live(time.time())
        cx = live["platforms"]["codex"]
        self.assertTrue(cx["running"])
        self.assertEqual(cx["n_sessions"], 3)
        by = {s["id"]: s for s in cx["sessions"]}
        self.assertEqual(by[self.sid]["tps"], 100.0, "取会话**最近一条**已完成响应")
        self.assertEqual(by[self.sid2]["tps"], 50.0)
        self.assertIsNone(by[self.sid3]["tps"], "在跑但还没完成第一条响应 ⇒ null")
        self.assertEqual(cx["tps"], 150.0, "同一 AI 内相加，null 不计")
        cl = live["platforms"]["claude"]
        self.assertFalse(cl["running"])
        self.assertIsNone(cl["tps"], "不在跑 ⇒ 平台 t/s 为 null（不是别家的数，也不是 0）")
        self.assertGreater(cl["tokens_today"] + live["platforms"]["agy"]["tokens_today"], 0)
        self.assertNotIn("tps", live["today"].keys() - {"avg_tps"}, "today 不出现跨 AI 的 t/s 合计")
        on_disk = json.loads((self.tmp / "ledger" / ".live.json").read_text())
        self.assertEqual(on_disk["platforms"]["codex"]["tps"], 150.0)

    def test_all_null_active_sessions_give_null(self):
        for p in self.rollout.parent.glob("rollout-*.jsonl"):
            if self.sid3 not in p.name:
                old = time.time() - RQ.FALLBACK_SECS - 100
                os.utime(p, (old, old))
        cx = RQ.build_live(time.time())["platforms"]["codex"]
        self.assertEqual(cx["n_sessions"], 1)
        self.assertIsNone(cx["tps"])


class TurnEndMarkers(Base):
    """判停 = 轮次结束标记（用户 2026-10-19 拍板），不是「45 s 没写」。四家各一份：
    轮次进行中 ⇒ 在跑；写了结束标记 ⇒ **立刻**停（文件刚写过也停）；没写结束标记但超过兜底窗口 ⇒ 停；
    增量追加 / 缓存命中（文件没变、不重读）下状态照样对。
    ★ setUp 把 Base 的夹具全推到兜底窗口之外，每条用例只看自己新写的那个会话。"""

    def setUp(self):
        super().setUp()
        old = time.time() - RQ.FALLBACK_SECS - 100
        for dp, _d, fns in os.walk(self.tmp):
            for n in fns:
                os.utime(os.path.join(dp, n), (old, old))

    def live(self, plat, **kw):
        return RQ.build_live(time.time(), **kw)["platforms"][plat]

    def active(self, plat, sid, **kw):
        ss = {s["id"]: s for s in self.live(plat, **kw)["sessions"]}
        return bool(ss.get(sid, {}).get("active"))

    def append(self, path, text):
        with open(path, "a") as fh:
            fh.write(text)

    def age(self, path, secs):
        t = time.time() - secs
        os.utime(path, (t, t))

    # ── codex ──
    def codex(self):
        sid = "0c0c0c0c-0af7-7833-b7ff-bfec945c7300"
        f = self.rollout.parent / ("rollout-2026-10-19T05-00-00-%s.jsonl" % sid)
        t = time.time() - 30
        f.write_text(_line(t, "session_meta", {"id": sid, "cwd": "/x/p"})
                     + _line(t + 1, "event_msg", {"type": "task_started", "turn_id": "k1"})
                     + _line(t + 2, "response_item", {"type": "reasoning"}))
        return sid, f

    def test_codex_task_complete_stops_at_once(self):
        sid, f = self.codex()
        self.assertTrue(self.active("codex", sid), "task_started 之后、task_complete 之前 ⇒ 在跑")
        self.assertTrue(self.active("codex", sid), "缓存命中（文件没变）⇒ 仍在跑")
        self.append(f, _line(time.time(), "response_item", {"type": "function_call"}))
        self.assertTrue(self.active("codex", sid), "增量只读到非轮次行 ⇒ 状态从游标里带过来")
        self.append(f, _line(time.time(), "event_msg", {"type": "task_complete", "turn_id": "k1"}))
        self.assertFalse(self.active("codex", sid), "写了 task_complete ⇒ 立刻停（文件刚写过也停）")
        self.assertFalse(self.live("codex")["running"])

    def test_codex_turn_aborted_stops_and_stale_end_does_not(self):
        sid, f = self.codex()
        self.append(f, _line(time.time(), "event_msg", {"type": "task_complete", "turn_id": "k0"}))
        self.assertTrue(self.active("codex", sid), "别的轮的结束标记不收这一轮")
        self.append(f, _line(time.time(), "event_msg", {"type": "turn_aborted", "turn_id": "k1",
                                                        "reason": "interrupted"}))
        self.assertFalse(self.active("codex", sid), "Esc 中断写 turn_aborted ⇒ 停")
        self.append(f, _line(time.time(), "event_msg", {"type": "task_started", "turn_id": "k2"}))
        self.assertTrue(self.active("codex", sid), "新一轮开始 ⇒ 又在跑")

    def test_a_fresh_file_without_any_turn_event_is_not_running(self):
        sid = "0d0d0d0d-0af7-7833-b7ff-bfec945c7300"
        f = self.rollout.parent / ("rollout-2026-10-19T06-00-00-%s.jsonl" % sid)
        f.write_text(_line(time.time(), "session_meta", {"id": sid, "cwd": "/x/p"}))
        self.assertFalse(self.active("codex", sid), "刚写过但从没开过一轮（只有 session_meta）⇒ 不在跑")
        g = self.claude()
        g.write_text(self.claude_row("user", message={"role": "user", "content": "<command-name>/model</command-name>"}))
        self.assertFalse(self.active("claude", self.csid2), "只有本地命令回显 ⇒ 不在跑")

    def test_codex_no_end_marker_falls_back_after_window(self):
        sid, f = self.codex()
        self.age(f, RQ.FALLBACK_SECS + 5)
        self.assertFalse(self.active("codex", sid), "崩溃 / 被杀：没有结束标记，超过兜底窗口 ⇒ 停")
        self.assertTrue(self.active("codex", sid, fallback_secs=RQ.FALLBACK_SECS + 60),
                        "挡住它的是兜底窗口，不是别的")

    # ── claude ──
    def claude_row(self, typ, **kw):
        return json.dumps({"type": typ, "sessionId": self.csid2, "cwd": "/x/p", "timestamp": _iso(time.time()),
                           **kw}, separators=(",", ":")) + "\n"

    def claude_asst(self, rid, stop):
        return self.claude_row("assistant", requestId=rid, message={
            "model": "claude-opus-5-5", "stop_reason": stop, "content": [{"type": "text", "text": "SECRET-ANSWER"}],
            "usage": {"input_tokens": 1, "output_tokens": 5}})

    def claude(self):
        self.csid2 = "22222222-2222-3333-4444-555555555555"
        f = self.tmp / "claude" / "-x-proj-beta" / (self.csid2 + ".jsonl")
        f.write_text(self.claude_row("user", promptSource="typed", message={"role": "user", "content": "SECRET-PROMPT"}))
        return f

    def test_claude_prompt_opens_turn_duration_closes(self):
        f = self.claude()
        self.assertTrue(self.active("claude", self.csid2), "提示行一写下就在跑（不等第一条回复：实测中位 12 s 才到）")
        self.append(f, self.claude_asst("r1", "tool_use"))
        self.append(f, self.claude_row("user", message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "SECRET-TOOL-OUTPUT"}]}))
        self.assertTrue(self.active("claude", self.csid2))
        self.assertTrue(self.active("claude", self.csid2), "缓存命中 ⇒ 仍在跑")
        self.append(f, self.claude_row("system", subtype="stop_hook_summary"))
        self.assertTrue(self.active("claude", self.csid2), "stop_hook_summary 不算结束（子 agent 的 Stop 钩子也写它）")
        self.append(f, self.claude_row("system", subtype="turn_duration", durationMs=1234))
        self.assertFalse(self.active("claude", self.csid2), "写了 turn_duration ⇒ 立刻停")
        self.append(f, self.claude_row("user", message={"role": "user", "content": "<local-command-stdout/>"}))
        self.append(f, self.claude_row("user", isCompactSummary=True, message={"role": "user", "content": "x"}))
        self.assertFalse(self.active("claude", self.csid2), "本地命令回显 / 压缩摘要不开新一轮")

    def test_claude_end_turn_and_interrupt_close(self):
        f = self.claude()
        self.append(f, self.claude_asst("r1", "end_turn"))
        self.assertFalse(self.active("claude", self.csid2), "assistant end_turn（没有工具要跑）⇒ 停")
        self.append(f, self.claude_row("user", promptSource="typed", message={"role": "user", "content": "SECRET-PROMPT"}))
        self.append(f, self.claude_asst("r2", "tool_use"))
        self.assertTrue(self.active("claude", self.csid2))
        self.append(f, self.claude_row("user", interruptedMessageId="m2", message={
            "role": "user", "content": [{"type": "text", "text": "x"}]}))
        self.assertFalse(self.active("claude", self.csid2), "Esc 中断（带 interruptedMessageId 的那一行）⇒ 停")

    def test_claude_subagent_ends_on_end_turn(self):
        d = self.tmp / "claude" / "-x-proj-beta" / self.csid / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "agent-zz.jsonl"
        self.csid2 = self.csid
        f.write_text(self.claude_row("user", isSidechain=True, message={"role": "user", "content": "SECRET-PROMPT"}))
        self.assertTrue(self.active("claude", "agent-zz"), "子 agent 的提示行（isSidechain，没有 promptSource）开一轮")
        self.append(f, self.claude_asst("s1", None))
        self.append(f, self.claude_asst("s1", "tool_use"))
        self.assertTrue(self.active("claude", "agent-zz"))
        self.append(f, self.claude_asst("s2", "end_turn"))
        self.assertFalse(self.active("claude", "agent-zz"), "子 agent 不写 system 行：最后一条 end_turn 就是结束")

    def test_claude_no_end_marker_falls_back_after_window(self):
        f = self.claude()
        self.append(f, self.claude_asst("r1", "tool_use"))
        self.age(f, RQ.FALLBACK_SECS + 5)
        self.assertFalse(self.active("claude", self.csid2))

    # ── agy ──
    def agy(self, steps):
        conv = "a9a9a9a9-ef99-451c-905b-6783e98a3a00"
        path = self.tmp / "agy" / (conv + ".db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE steps (idx integer PRIMARY KEY, step_type integer, status integer, metadata blob)")
        con.executemany("INSERT INTO steps VALUES (?,?,?,NULL)", [(i, t, st) for i, (t, st) in enumerate(steps)])
        con.commit()
        con.close()
        return conv, path

    def agy_set(self, path, idx, t, st):
        con = sqlite3.connect(path)
        con.execute("INSERT OR REPLACE INTO steps VALUES (?,?,?,NULL)", (idx, t, st))
        con.commit()
        con.close()

    def test_agy_last_step_decides(self):
        conv, path = self.agy([(14, 3), (15, 8)])
        self.assertTrue(self.active("agy", conv), "模型步生成中（8）⇒ 在跑（还没写 gen_metadata 也算）")
        self.assertTrue(self.active("agy", conv), "缓存命中（签名没变）⇒ 仍在跑")
        self.agy_set(path, 1, 15, 3)
        self.agy_set(path, 2, 132, 2)
        self.assertTrue(self.active("agy", conv), "工具在跑 ⇒ 在跑")
        self.agy_set(path, 2, 132, 3)
        self.assertTrue(self.active("agy", conv), "工具跑完、下一步是模型 ⇒ 仍在跑")
        self.agy_set(path, 3, 15, 3)
        self.assertFalse(self.active("agy", conv), "最后一步是完成的模型回复 ⇒ 立刻停")
        self.agy_set(path, 4, 14, 3)
        self.agy_set(path, 5, 132, 6)
        self.assertFalse(self.active("agy", conv), "取消（6）⇒ 停")

    def test_agy_no_end_marker_falls_back_after_window(self):
        conv, path = self.agy([(14, 3), (15, 8)])
        self.age(path, RQ.FALLBACK_SECS + 5)
        self.assertFalse(self.active("agy", conv))

    # ── grok ──
    def grok(self):
        d = self.tmp / "grok" / "%2Fx%2Fp" / "0g0g0g0g-d73e-7e22-80d4-6152bdf3e000"
        d.mkdir(parents=True)
        f = d / "updates.jsonl"
        f.write_text(json.dumps({"method": "session/update", "params": {"update": {
            "sessionUpdate": "user_message_chunk", "content": {"text": "SECRET-PROMPT"}}}}) + "\n")
        return d.name, f

    def grok_done(self, stop):
        t = time.time()
        return json.dumps({"timestamp": int(t), "method": "_x.ai/session/update", "params": {
            "_meta": {"agentTimestampMs": int(t * 1000)}, "update": {
                "sessionUpdate": "turn_completed", "prompt_id": "g1", "stop_reason": stop, "elapsed_ms": 1000,
                "usage": {"outputTokens": 10, "apiDurationMs": 900}}}}) + "\n"

    def test_grok_turn_completed_stops_at_once(self):
        sid, f = self.grok()
        self.assertTrue(self.active("grok", sid), "user_message_chunk 之后 ⇒ 在跑")
        self.append(f, json.dumps({"method": "session/update", "params": {"update": {
            "sessionUpdate": "agent_message_chunk", "content": {"text": "SECRET-ANSWER"}}}}) + "\n")
        self.assertTrue(self.active("grok", sid), "增量只读到非轮次行 ⇒ 状态从游标里带过来")
        self.append(f, self.grok_done("cancelled"))
        self.assertFalse(self.active("grok", sid), "turn_completed（含 cancelled）⇒ 立刻停")

    def test_grok_no_end_marker_falls_back_after_window(self):
        sid, f = self.grok()
        self.age(f, RQ.FALLBACK_SECS + 5)
        self.assertFalse(self.active("grok", sid))

    def test_cursor_carries_open_and_old_cursors_are_reparsed(self):
        sid, f = self.codex()
        self.live("codex")
        cur = json.loads((self.tmp / "ledger" / ".cursor.json").read_text())
        self.assertEqual(cur["v"], RQ.CUR_V)
        self.assertIs(cur["files"][str(f)]["state"]["open"], True, "「轮次开着」随游标落盘")
        # 旧版游标（没有 open）必须作废重解，否则升级后正开着的会话一直显示停了
        cur["v"] = 1
        for e in cur["files"].values():
            (e.get("state") or {}).pop("open", None)
        (self.tmp / "ledger" / ".cursor.json").write_text(json.dumps(cur))
        self.assertTrue(self.active("codex", sid))

    def test_cli_accepts_both_window_flags(self):
        for flag in ("--fallback-secs", "--active-secs"):
            p = subprocess.run([sys.executable, str(SCRIPT), "--live", flag, "60"], capture_output=True, text=True,
                               env={**os.environ, **self.env}, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(p.stdout)["ok"], p.stdout[:300])


if __name__ == "__main__":
    unittest.main()
