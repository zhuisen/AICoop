#!/usr/bin/env python3
"""逐请求账本：每条模型响应一行 —— 用量 · 首字 · 生成 · 速度（Codex / Claude / Gemini(agy) / Grok）。

    requests.py --json [--days 2]          最近 N 个本地自然日的请求 + 今天/昨天指标
    requests.py --live [--fallback-secs 600]  在跑的会话与 t/s（同时原子写 requests-ledger/.live.json）

契约正本：`scratch/redesign_20261019/PLAN.md` §2.1。

★ 安全线与 `traffic/` 相同：**stdlib、不联网、不读凭证、不读正文**。各家文件里的正文（对话、工具输出）
  只会在 `json.loads` 时短暂进内存，**任何正文都不会被保留、打印或落盘** —— 落盘的只有 `KEYS` 里那些字段
  （`_whitelist` 是唯一的落盘出口，闸 `tests/test_requests_ledger.py::TheLedgerHoldsOnlyWhitelistedKeys`）。
  会话标题只取 cwd 的 basename，不读标题正文。

## 数据源（前一轮定稿）

| 平台 | 每条请求 | 时间 |
|---|---|---|
| codex | rollout 的 `token_usage_record`（每条响应一条，带 `response_id`） | 行时间戳；首字 = 本响应第一个输出项写盘时刻（每轮第一条用 `task_complete.time_to_first_token_ms` 覆盖） |
| claude | OTel 账本 `claude_code.llm_request` span（主）；没 span 的退回 transcript（同 `requestId` 最后一行） | span 的 `ttft_ms`/`duration_ms`；transcript 只有行时间戳 ⇒ `est=true` |
| agy | 会话库 `gen_metadata`（descriptor 实证的字段号，见 `.claude/rules/traffic.md`） | `f1.f11` 首字 · `f1.f12` 流式时长 · 模型步 `created_at`/`finished_generating_at` |
| grok | `updates.jsonl` 的 `turn_completed`（一轮 prompt 一条） | `elapsed_ms`、`usage.apiDurationMs`；首字取 `events.jsonl` 的 `first_token − loop_started` |

## t/s 公式（每家一条，`est` 的口径统一：**分母里含首字时间** = 拿不到纯生成时长 = 估）

* codex  = 可见输出 ÷ (响应结束 − 第一个输出项)。可见输出 = `output − reasoning`：推理 token 产生在
           第一个输出项**之前**（推理项写盘时才算"首字"），留在分子里会虚高（实测中位 157 vs 102 t/s）。
           生成段 < 0.3 s 或可见输出为 0 ⇒ 退回 输出 ÷ 整条响应时长，`est=true`。
* claude = output ÷ ((duration_ms − ttft_ms)/1000)；transcript 退回 output ÷ (末行 − 触发行)，`est=true`。
* agy    = usage `f3`(输出，**含 thinking**) ÷ streaming_duration（≥ 0.3 s 且可见输出 `f10` > 0 时）；
           否则 output ÷ (ttft + streaming)，`est=true`。thinking 在 streaming 段里生成（与 codex 相反、与 claude 同）：
           2026-10-21 实测 439 条 est=false，按模型 × thinking 占比分组，f3÷streaming 组间一致
           （argon <20% / 20–50% / >50% = 138 / 230 / 157，flash 426 / 474 / 625），f10÷streaming 在 thinking
           占比 >50% 的组掉到 33 / 26（用户看到的「Gemini 3 t/s」= 95 可见 ÷ 31.4 s，那条 thinking 2854）。
* grok   = outputTokens ÷ (apiDurationMs/1000)（一轮里所有模型调用的 API 时间之和）。
* 任何分母 ≤ 0、或输出为 0 ⇒ `tps = null`（不写 0：0 t/s 会把均速拉低，而那条请求根本没生成）。

## 增量与落盘（§7.0b 三问）

* 游标 `.cursor.json`：每个追加型文件记 `(inode, offset, 前 64 字节锚点哈希)`；只消费到最后一个 `\\n`
  （半行不消费）。锚点对不上 / 文件变短 / 换 inode ⇒ 这个文件从头重解（按 `key` 去重，不会双计）。
  agy 库记已处理的 `gen_metadata.idx`；`.zst` 记签名，变了整份重解。
* 账本 `YYYY-MM.jsonl`（按 `t_end` 的本地月份）**只追加**；读取按 `key` 去重、新值覆盖，**新值里的 null
  不覆盖旧值**（§7.0b 第 3 问）。`.window.json` 是窗口内记录的物化视图（丢了从账本重建）。
* 读失败：那个文件的游标**不前进**（下次重试），旧记录原样保留，顶层 `ok:false` + `error` + `stale_since`
  （第一次失败的时刻，连续失败不刷新）。"没装这个 CLI"（根目录不存在）是合法的空，不算失败。

## 判停（`--live` 的 `active`；用户 2026-10-19 拍板「改用轮次结束标记」）

会话在跑 = 这个文件**最后一个轮次事件是「开始」**（`state["open"] is True`）**且** mtime 在 `FALLBACK_SECS` 内。
写了结束标记 ⇒ 立刻不在跑，不再等「N 秒没写」。`open` 随游标状态保存，缓存命中（文件没变、不重读）时照样知道。
结构字段才算数（type / subtype / 键是否存在 / 状态码），**不读正文**。各家标记（2026-10-19 在本机真实数据上核过）：

| 平台 | 开始 | 结束 |
|---|---|---|
| codex | `event_msg` `task_started` | `task_complete` · `turn_aborted`（Esc，`reason: interrupted`）；turn_id 对得上才收（对不上 = 旧轮的尾巴） |
| claude | 提示行（user、非 meta、带 `promptSource` 键或 `isSidechain: true`）· 工具结果行 · 非终止的 assistant 行 | `system`/`turn_duration` · 中断行（带 `interruptedMessageId` 键）· assistant `stop_reason ∈ {end_turn, stop_sequence, max_tokens}`（子 agent 只有这一条：它不写 system 行） |
| agy | 最后一步不是下面两种 | 最后一步 `step_type=15` 且 `status=3`（模型回复完成）· `status ∈ {5 清除, 6 取消}` |
| grok | `updates.jsonl` `user_message_chunk` | `turn_completed`（`stop_reason` end_turn / cancelled / error 都收） |

不开也不收的：Claude 的本地命令回显行（没有 `promptSource`）、压缩摘要行（`isCompactSummary`，手动 /compact 之后
没有回复）、`stop_hook_summary`（实测 32/2140 次后面还跟着模型继续调工具 —— 子 agent 的 Stop 钩子也写它）。
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from calendar import timegm
from pathlib import Path

try:
    import fcntl                       # POSIX
except ModuleNotFoundError:            # Windows —— 语义等价的 LockFileEx 兼容层,见 portalock.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import portalock as fcntl          # noqa: N813

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import scan as S            # noqa: E402  —— _pb / _zstd_text / _agy_db_sig / _agy_model：别抄第二份
import rotation as R        # noqa: E402  —— proxy.log 的 response_id → 账号 join
import agy_rotation as AR   # noqa: E402  —— cli-*.log 的身份段（conv id 精确 join）

V = 1
PLATFORMS = ("codex", "claude", "agy", "grok")      # 固定顺序 Codex → Claude → Gemini → Grok

#: ★★ 落盘白名单 —— 账本 / 窗口快照里**只能**出现这些键。加字段必须改这里，且不得是正文。
KEYS = ("key", "platform", "t_start", "t_end", "model", "source", "session", "session_title",
        "account", "input", "cached", "output", "reasoning", "ttft_ms", "gen_ms", "total_ms",
        "tool_ms", "tps", "est", "session_req_n")

MIN_GEN_S = 0.3              # 生成段短于它就不当分母（毫秒级的段除出来是噪音）
ANCHOR = 64
DISCOVER_EVERY = 0           # 每次都全量发现（实测四家合计 < 70 ms）；留着这个钩子以备变慢
#: 游标版本（与输出契约的 `V` 分开）。2 = 游标状态里加了 `open`（轮次开着没）；旧游标作废、全量重解一次。
#: 3 = agy t/s 分子改成 f3（2026-10-21）；全量重解一次，按 `key` 覆盖旧记录里的错数。
CUR_V = 3
#: ★ 判停的兜底窗口：轮次开着、但这么久没写过文件 ⇒ 当它停了（崩溃 / 被杀 / Ctrl-C 没来得及写结束标记）。
#:   取 10 分钟的依据（2026-10-19 实测 Claude transcript 一轮之内相邻两次写入的静默间隔，n=95684）：
#:   p50 0.1 s · p90 10 s · p99 99 s · p99.9 600 s（长工具调用 / 子 agent / 等权限）。
#:   原来的「45 s 没写 = 停了」在 p99 之前就会把长工具调用误判成停，停手后又要等满 45 s 才熄；
#:   现在正常停手靠结束标记立刻熄，这个窗口只兜「没写结束标记」的那几种，宁长勿短。
FALLBACK_SECS = 600

# ── 路径（每次现读环境变量：测试在调用前设置） ──────────────────────────────────

_CODE_ROOT = _HERE.parent


def _store():
    return Path(os.environ.get("CODEX_ROTATE_STORE")
                or (_CODE_ROOT.parent if _CODE_ROOT.name == "runtime" else _CODE_ROOT))


def _env_path(name, default):
    v = os.environ.get(name)
    return Path(v) if v else default


def roots():
    home = Path.home()
    st = _store()
    return {
        "ledger": _env_path("REQUESTS_LEDGER_DIR", st / "traffic" / "requests-ledger"),
        "codex": _env_path("REQUESTS_CODEX_ROOT",
                           Path(os.environ.get("CODEX_HOME") or (home / ".codex")) / "sessions"),
        "claude": _env_path("REQUESTS_CLAUDE_ROOT",
                            Path(os.environ.get("CLAUDE_CONFIG_DIR") or (home / ".claude")) / "projects"),
        "otel": _env_path("REQUESTS_OTEL_DIR", st / "traffic" / "otel-ledger"),
        "agy": _env_path("REQUESTS_AGY_DB_ROOT", home / ".gemini" / "antigravity-cli" / "conversations"),
        "agy_log": _env_path("REQUESTS_AGY_LOG_DIR", home / ".gemini" / "antigravity-cli" / "log"),
        "agy_ledger": _env_path("REQUESTS_AGY_LEDGER", st / "traffic" / "agy-ledger" / "usage.jsonl"),
        "agy_pool": _env_path("REQUESTS_AGY_POOL", st / ".agy-pool.json"),
        "grok": _env_path("REQUESTS_GROK_ROOT",
                          Path(os.environ.get("GROK_HOME") or (home / ".grok")) / "sessions"),
        "proxy_log": _env_path("REQUESTS_PROXY_LOG", st / "proxy" / "proxy.log"),
        "state": _env_path("REQUESTS_STATE", st / "state.json"),
    }


# ── 小工具 ─────────────────────────────────────────────────────────────────────

_ISO = re.compile(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?")


def _iso(s):
    """UTC ISO（`…Z`，可带毫秒）→ epoch 秒（浮点）。不认 → None。"""
    if isinstance(s, (bytes, bytearray)):
        s = s.decode("ascii", "replace")
    m = _ISO.match(s or "")
    if not m:
        return None
    g = m.groups()
    t = timegm((int(g[0]), int(g[1]), int(g[2]), int(g[3]), int(g[4]), int(g[5]), 0, 0, 0))
    return t + (float("0." + g[6]) if g[6] else 0.0)


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _i0(d, k):
    v = d.get(k) if isinstance(d, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _div(num, secs):
    """t/s；分子 ≤ 0 或分母 < `MIN_GEN_S` ⇒ None（见模块 docstring 末条公式）。

    ★ 下限对**所有**分母生效，不只生成段：毫秒级的分母除出来是几千上万 t/s 的噪音（实测 Claude span
      `duration − ttft` 28 ms / 516 token ⇒ 18,429 t/s），一条就能把均值拉飞。
    """
    if not num or num <= 0 or secs is None or secs < MIN_GEN_S:
        return None
    return round(num / secs, 1)


def _ms(secs):
    return None if secs is None else int(round(secs * 1000))


def _base(p):
    p = (p or "").rstrip("/\\")
    return re.split(r"[/\\]", p)[-1] if p else None


def _short(sid):
    return (sid or "")[:8] or None


def _whitelist(rec):
    """★★ 唯一的落盘出口：内部记录带着 `_rid`/`_conv` 之类的 join 字段，这里全部剥掉。"""
    return {k: rec.get(k) for k in KEYS}


def _merge(old, new):
    """按 key 合并：新值覆盖旧值，**但新值里的 None 不覆盖旧值**（§7.0b 第 3 问）。"""
    if old is None:
        return _whitelist(new)
    out = dict(old)
    for k in KEYS:
        v = new.get(k)
        if v is not None:
            out[k] = v
    return out


def _atomic_write(path, text):
    tmp = "%s.tmp%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


def _local_midnight(now, days_back=0):
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - days_back, 0, 0, 0, 0, 0, -1))


def _hash(b):
    return hashlib.sha1(b).hexdigest()[:16]


class ReadFail(Exception):
    """读失败（≠ 没有数据）。这个文件的游标不前进，旧记录保留。"""


# ── 追加型文件的增量读取 ────────────────────────────────────────────────────────

def _tail_lines(path, st, ent, consume):
    """把 `ent` 之后新追加的**完整行**喂给 `consume(lines_iter, fresh)`，返回新的游标条目。

    `fresh=True` ⇒ 从头读（首次 / 文件被改写），解析器要丢掉旧的跨行状态。
    ★ 半行不消费：最后一行没有 `\\n` 就停在它前面，下次从那里接着读。
    """
    off, fresh = 0, True
    try:
        fh = open(path, "rb")
    except OSError as e:
        raise ReadFail("打不开 %s: %s" % (S._tilde(path), e.strerror or e)) from e
    with fh:
        if ent and ent.get("ino") == st.st_ino and 0 < (ent.get("off") or 0) <= st.st_size:
            o = ent["off"]
            a0 = max(0, o - ANCHOR)
            try:
                fh.seek(a0)
                anc = fh.read(o - a0)
            except OSError as e:
                raise ReadFail("读不了 %s: %s" % (S._tilde(path), e)) from e
            if _hash(anc) == ent.get("anc"):
                off, fresh = o, False
        if not fresh and off == st.st_size:
            return ent                                   # 没有新内容
        fh.seek(off)
        pos = [off]

        def lines():
            try:
                for line in fh:
                    if not line.endswith(b"\n"):
                        break                            # 半行：不消费
                    pos[0] += len(line)
                    yield line
            except OSError as e:
                raise ReadFail("读不了 %s: %s" % (S._tilde(path), e)) from e

        state = consume(lines(), fresh)
        new_off = pos[0]
        a0 = max(0, new_off - ANCHOR)
        fh.seek(a0)
        anc = fh.read(new_off - a0)
    return {"ino": st.st_ino, "off": new_off, "anc": _hash(anc), "mtime": st.st_mtime,
            "state": state}


# ── Codex ──────────────────────────────────────────────────────────────────────

_CODEX_HEAD = re.compile(
    rb'^\{"timestamp":"([^"]+)",(?:"ordinal":\d+,)?"type":"([a-z_]+)"(?:,"payload":\{"type":"([A-Za-z_]+)")?')
#: 模型**输出**项。其余 response_item（工具输出、user/developer 消息、agent_message）都是本次请求的输入。
_CODEX_OUT = {b"reasoning", b"function_call", b"custom_tool_call", b"local_shell_call",
              b"web_search_call", b"image_generation_call", b"tool_search_call", b"mcp_call"}
_CODEX_MODEL_ITEMS = (b'"type":"Reasoning"', b'"type":"AgentMessage"')
_ROLLOUT_ID = re.compile(r"rollout-[\dT:-]+-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl")


def _codex_timing(rec, ttft_at):
    """codex 的 ttft/gen/tps（公式见模块 docstring）。

    `ttft_at` = 首字时刻：本响应的第一个输出项**是推理项**时取它的写盘时刻（推理项在推理结束、可见输出
    开始流式时才落盘）。第一个输出项不是推理项时它就是整条响应的最后一项（工具调用是整项写盘的），
    那个时刻不是首字 ⇒ 传 None，退回整条估值。已有官方首字（`rec["ttft_ms"]`）时也传 None。
    """
    t0, t1 = rec["t_start"], rec["t_end"]
    total = (t1 - t0) if (t0 is not None and t1 is not None) else None
    ttft = rec.get("ttft_ms")
    if ttft_at is not None and t0 is not None:
        ttft = _ms(max(0.0, ttft_at - t0))
    gen = (total - ttft / 1000.0) if (total is not None and ttft is not None) else None
    if gen is not None and gen < 0:
        gen = None
    vis = (rec["output"] or 0) - (rec["reasoning"] or 0)
    if gen is not None and gen >= MIN_GEN_S and vis > 0:
        tps, est = _div(vis, gen), False
    else:
        tps, est = _div(rec["output"], total), True
    rec.update(ttft_ms=ttft, gen_ms=_ms(gen), total_ms=_ms(total), tps=tps, est=est)
    return rec


def _codex_close(state, payload):
    """结束标记收的是**当前这一轮**：turn_id 对不上（旧轮的尾巴晚到）就不收。任一边没有 turn_id 时照收。"""
    tid = payload.get("turn_id") if isinstance(payload, dict) else None
    if tid is None or state.get("turn") is None or tid == state["turn"]:
        state["open"] = False


def _codex_consume(path, lines, fresh, state, horizon, emit):
    if fresh or not state:
        m = _ROLLOUT_ID.search(Path(path).name)
        state = {"sess": m.group(1) if m else Path(path).name, "title": None, "src": None,
                 "model": None, "turn": None, "turn_t0": None, "turn_n": 0, "req": None,
                 "first": None, "rfirst": False, "last": None, "tool": 0, "n": 0, "pend": {}, "open": None}
    for line in lines:
        h = _CODEX_HEAD.match(line[:256])
        if not h:
            continue
        ts = _iso(h.group(1))
        if ts is None:
            continue
        typ, pt = h.group(2), h.group(3)
        if typ == b"response_item":
            is_out = pt in _CODEX_OUT or (pt == b"message" and b'"role":"assistant"' in line[:400])
            if is_out:
                if state["first"] is None:
                    state["first"], state["rfirst"] = ts, pt == b"reasoning"
                state["last"] = ts
            elif state["first"] is None:
                state["req"] = ts
            continue
        if typ == b"token_usage_record":
            try:
                p = json.loads(line).get("payload") or {}
            except ValueError:
                continue
            u = p.get("usage") if isinstance(p.get("usage"), dict) else {}
            rid = p.get("response_id") if isinstance(p.get("response_id"), str) else None
            state["n"] += 1
            first_in_turn = state["turn_n"] == 0 and state["turn_t0"] is not None
            t0 = state["turn_t0"] if first_in_turn else (state["req"] or state["turn_t0"])
            rec = {
                "key": "codex:" + (rid or "%s:%d" % (state["sess"], state["n"])),
                # ★ 结束 = 最后一个输出项写盘时刻，不是这行的时刻：实测 token_usage_record 常在工具
                #   **开始执行之后**才写（比最后一项晚 0.1~0.6 s），拿它当结束会把工具时间算进生成段。
                "platform": "codex", "t_start": t0, "t_end": state["last"] or ts, "model": state["model"],
                "source": "exec" if state["src"] == "exec" else "交互",
                "session": state["sess"], "session_title": state["title"] or _short(state["sess"]),
                "account": None, "input": _i0(u, "input_tokens"), "cached": _i0(u, "cached_input_tokens"),
                "output": _i0(u, "output_tokens"), "reasoning": _int(u.get("reasoning_output_tokens")),
                "tool_ms": (state["tool"] if state["turn_n"] else None),
                "session_req_n": state["n"],
                "_file": path,                    # 内部字段：只给排障用，`_whitelist` 会剥掉
            }
            _codex_timing(rec, state["first"] if state["rfirst"] else None)
            if first_in_turn and state["turn"]:
                pend = state["pend"]
                pend[state["turn"]] = _whitelist(rec)
                for k in list(pend)[:-8]:
                    del pend[k]
            state["turn_n"] += 1
            state.update(req=ts, first=None, rfirst=False, last=None, tool=0)
            if rec["t_end"] >= horizon:
                emit(rec)
            continue
        if typ == b"event_msg":
            if pt == b"task_started":
                try:
                    p = json.loads(line).get("payload") or {}
                except ValueError:
                    continue
                tid = p.get("turn_id") or (p.get("turn_attribution") or {}).get("turn_id")
                state.update(turn=tid, turn_t0=ts, turn_n=0, req=ts, first=None, rfirst=False, last=None, tool=0,
                             open=True)
                continue
            if pt == b"task_complete":
                try:
                    p = json.loads(line).get("payload") or {}
                except ValueError:
                    continue
                _codex_close(state, p)
                rec = state["pend"].pop(p.get("turn_id"), None)
                ttft = _int(p.get("time_to_first_token_ms"))
                if rec is not None and ttft is not None:
                    # ★ 每轮第一条响应换成 codex 自己量的首字（从 task_started 起算，与 t_start 同一起点）。
                    rec["ttft_ms"] = ttft
                    _codex_timing(rec, None)
                    if rec["t_end"] >= horizon:
                        emit(rec)
                if state["first"] is None:
                    state["req"] = ts
                continue
            if pt == b"turn_aborted":                       # Esc 中断：codex 写它而不写 task_complete
                try:
                    _codex_close(state, json.loads(line).get("payload") or {})
                except ValueError:
                    pass
            if pt == b"item_completed" and any(x in line[:400] for x in _CODEX_MODEL_ITEMS):
                # 模型项的完成事件紧挨着对应的 response_item 写盘 —— 是输出，不能把请求起点推到这里。
                if state["first"] is None:
                    state["first"], state["rfirst"] = ts, b'"type":"Reasoning"' in line[:400]
                state["last"] = ts
                continue
            if pt == b"item_completed":
                # 工具项（命令 / 改文件 / MCP…）：累计到「喂给下一条请求」的工具耗时。
                try:
                    p = json.loads(line).get("payload") or {}
                except ValueError:
                    continue
                it = p.get("item") if isinstance(p.get("item"), dict) else {}
                d = it.get("duration")
                ms = None
                if isinstance(d, dict) and isinstance(d.get("secs"), int):
                    ms = d["secs"] * 1000 + (d.get("nanos") or 0) // 1_000_000
                elif isinstance(p.get("started_at_ms"), int) and isinstance(p.get("completed_at_ms"), int):
                    ms = max(0, p["completed_at_ms"] - p["started_at_ms"])
                if ms:
                    state["tool"] += ms
            if state["first"] is None and pt != b"token_count":
                state["req"] = ts
            continue
        if typ == b"session_meta":
            try:
                p = json.loads(line).get("payload") or {}
            except ValueError:
                continue
            if state["src"] is None:
                state["src"] = "exec" if (p.get("originator") == "codex_exec" or p.get("source") == "exec") else "cli"
            if state["title"] is None and isinstance(p.get("cwd"), str):
                state["title"] = _base(p["cwd"])
        elif typ == b"turn_context":
            try:
                p = json.loads(line).get("payload") or {}
            except ValueError:
                continue
            if isinstance(p.get("model"), str) and p["model"]:
                state["model"] = p["model"]
            if state["title"] is None and isinstance(p.get("cwd"), str):
                state["title"] = _base(p["cwd"])
        if state["first"] is None:
            state["req"] = ts
    return state


def _codex_files(root):
    out = []
    if not root.is_dir():
        return out
    for dp, _dn, fns in os.walk(root):
        for n in fns:
            if n.startswith("rollout-") and (n.endswith(".jsonl") or n.endswith(".jsonl.zst")):
                p = Path(dp) / n
                if S._codex_keep(p):
                    out.append(p)
    return out


def _do_codex(cur, rt, horizon, emit, err, seen):
    root = rt["codex"]
    try:
        files = _codex_files(root)
    except OSError as e:
        err.append("读不了 %s: %s" % (S._tilde(root), e))
        return
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime < horizon:
            continue
        k = str(p)
        seen[k] = ("codex", st.st_mtime)
        ent = cur["files"].get(k)
        try:
            if p.name.endswith(".zst"):
                sig = [st.st_mtime_ns, st.st_size]
                if ent and ent.get("sig") == sig:
                    continue
                try:
                    text = S._zstd_text(str(p))
                except S.ScanReadError as e:
                    raise ReadFail(str(e)) from e
                state = _codex_consume(k, iter(text.encode("utf-8").splitlines(True)), True, None,
                                       horizon, emit)
                cur["files"][k] = {"sig": sig, "mtime": st.st_mtime, "state": state}
            else:
                old = (ent or {}).get("state")
                cur["files"][k] = _tail_lines(
                    k, st, ent, lambda it, fresh: _codex_consume(k, it, fresh, old, horizon, emit))
        except ReadFail as e:
            err.append(str(e))


# ── Claude ─────────────────────────────────────────────────────────────────────

def _claude_consume(path, lines, fresh, state, horizon, tr, touched):
    if fresh or not state:
        stem = Path(path).stem
        state = {"sess": None if "subagents" not in Path(path).parts else stem,
                 "title": None, "n": 0, "last_in": None, "cur": None, "open": None}
    for line in lines:
        o = None
        if b'"requestId"' in line or b'"type":"assistant"' in line or b'"subtype":"turn_duration"' in line:
            try:
                o = json.loads(line)
            except ValueError:
                o = None
        if isinstance(o, dict) and o.get("type") == "system" and o.get("subtype") == "turn_duration":
            state["open"] = False                         # 本轮结束（主会话；子 agent 不写 system 行）
            continue
        if isinstance(o, dict) and o.get("type") == "assistant":
            m = o.get("message") if isinstance(o.get("message"), dict) else {}
            state["open"] = m.get("stop_reason") not in _CLAUDE_STOP
            rid = o.get("requestId")
            u = m.get("usage") if isinstance(m.get("usage"), dict) else None
            ts = _iso(o.get("timestamp"))
            if not isinstance(rid, str) or u is None or ts is None:
                continue
            if state["sess"] is None and isinstance(o.get("sessionId"), str):
                state["sess"] = o["sessionId"]
            if state["title"] is None and isinstance(o.get("cwd"), str):
                state["title"] = _base(o["cwd"])
            i, cr, cw, out = (_i0(u, "input_tokens"), _i0(u, "cache_read_input_tokens"),
                              _i0(u, "cache_creation_input_tokens"), _i0(u, "output_tokens"))
            otd = u.get("output_tokens_details")
            th = _int(otd.get("thinking_tokens")) if isinstance(otd, dict) else None
            c = state["cur"]
            if c and c["rid"] == rid:
                c.update(t1=ts, i=i, cr=cr, cw=cw, out=out, th=th)
            else:
                if not (i or cr or cw or out):
                    continue                              # `<synthetic>` 等本地占位
                state["n"] += 1
                c = state["cur"] = {"rid": rid, "t0": state["last_in"], "tf": ts, "t1": ts,
                                    "i": i, "cr": cr, "cw": cw, "out": out, "th": th, "n": state["n"]}
            model = m.get("model")
            c["model"] = S._DATED.sub("", model) if isinstance(model, str) else c.get("model")
            if ts >= horizon:
                tr[rid] = {"sess": state["sess"], "title": state["title"], **{k: v for k, v in c.items() if k != "rid"}}
                touched.add(rid)
            continue
        # 估值起点 = 最后一条 **user** 行（用户输入 / 工具结果 = 触发这次请求的那一行）。
        # ★ 不收 attachment/system/progress：它们可能在请求发出**之后**才写，起点被推迟 ⇒ 分母变小、t/s 虚高。
        if b'"type":"user"' not in line or (isinstance(o, dict) and o.get("type") != "user"):
            continue
        _claude_user_turn(state, line, o)
        j = line.rfind(b'"timestamp":"')
        if j >= 0:
            ts = _iso(line[j + 13:j + 40])
            if ts is not None:
                state["last_in"] = ts
    return state


#: assistant 的这些 `stop_reason` = 模型不再继续（没有待跑的工具）。不收 `refusal`：实测拒答后会换模型接着答
#: （`model_refusal_fallback`）。`tool_use` / null（同一条消息的中间块）= 还在跑。
_CLAUDE_STOP = ("end_turn", "stop_sequence", "max_tokens")


def _claude_user_turn(state, line, o):
    """user 行对轮次的作用（只看结构键，见模块 docstring「判停」表）。"""
    if b'"type":"tool_result"' in line:
        state["open"] = True                              # 工具跑完了，下一步是模型（不必解析这种大行）
        return
    if not isinstance(o, dict):
        try:
            o = json.loads(line)
        except ValueError:
            return
    if not isinstance(o, dict) or o.get("type") != "user" or o.get("isMeta"):
        return
    if "interruptedMessageId" in o:
        state["open"] = False                             # Esc 中断：Claude Code 写这一行，不写 turn_duration
    elif not o.get("isCompactSummary") and ("promptSource" in o or o.get("isSidechain") is True):
        state["open"] = True                              # 新一轮的提示（子 agent 的提示行没有 promptSource）


def _otel_consume(lines, spans, horizon, touched):
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        rid = r.get("request_id")
        t1 = r.get("t_end")
        if not isinstance(rid, str) or not isinstance(t1, (int, float)) or t1 < horizon:
            continue
        spans[rid] = {"t0": r.get("t_start"), "t1": t1, "ttft": _int(r.get("ttft_ms")),
                      "dur": _int(r.get("duration_ms")), "i": _i0(r, "input_tokens"),
                      "cr": _i0(r, "cache_read_tokens"), "cw": _i0(r, "cache_creation_tokens"),
                      "out": _i0(r, "output_tokens"),
                      "model": S._DATED.sub("", r["model"]) if isinstance(r.get("model"), str) else None,
                      "sess": r.get("session.id") if isinstance(r.get("session.id"), str) else None}
        touched.add(rid)
    return None


def _claude_rec(rid, t, sp, span_n):
    """span（实测）优先，transcript 退回估值。会话字段一律以 transcript 为准（子 agent 是它自己的会话）。"""
    base = {"key": "claude:" + rid, "_rid": rid, "platform": "claude", "source": "Claude Code", "account": "本机",
            "reasoning": (t or {}).get("th"), "tool_ms": None}
    if sp:
        i, cr, cw, out = sp["i"], sp["cr"], sp["cw"], sp["out"]
        dur, ttft = sp["dur"], sp["ttft"]
        gen = (dur - ttft) if (dur is not None and ttft is not None and dur >= ttft) else None
        # ★ 分子是**全部输出（含 thinking）**：实测 thinking 在首字之后流式产出 —— 带 thinking > 50% 的 88 条
        #   output/gen 中位 98 t/s，与无 thinking 的 93 条（131）同量级；扣掉 thinking 只剩 28，对不上。
        # ★ 生成段 < 0.3 s 不当分母：实测 528 条 span 里 118 条 `duration − ttft` ≤ 300 ms（整段几乎一次到达），
        #   直接除出来最高 75,875 t/s。退回 output ÷ duration，`est=true`。
        if gen is not None and gen >= MIN_GEN_S * 1000:
            tps, est = _div(out, gen / 1000.0), False
        else:
            tps, est = _div(out, dur / 1000.0 if dur is not None else None), True
        sess = (t or {}).get("sess") or sp["sess"]
        base.update(t_start=sp["t0"], t_end=sp["t1"], model=sp["model"] or (t or {}).get("model"),
                    ttft_ms=ttft, gen_ms=gen, total_ms=dur, tps=tps, est=est,
                    session=sess, session_title=(t or {}).get("title") or _short(sess),
                    session_req_n=(t or {}).get("n") or span_n.get(rid))
    else:
        i, cr, cw, out = t["i"], t["cr"], t["cw"], t["out"]
        t0 = t["t0"] if t["t0"] is not None else t["tf"]
        total = t["t1"] - t0
        base.update(t_start=t0, t_end=t["t1"], model=t.get("model"), ttft_ms=None, gen_ms=None,
                    total_ms=_ms(total) if total >= 0 else None, tps=_div(out, total), est=True,
                    session=t["sess"], session_title=t["title"] or _short(t["sess"]),
                    session_req_n=t["n"])
    base.update(input=i + cr + cw, cached=cr, output=out)
    return base


def _claude_files(root):
    out = []
    if not root.is_dir():
        return out
    with os.scandir(root) as it:
        projs = [e.path for e in it if e.is_dir(follow_symlinks=False)]
    for pd in projs:
        try:
            with os.scandir(pd) as it:
                for e in it:
                    if e.is_file(follow_symlinks=False) and e.name.endswith(".jsonl"):
                        out.append(Path(e.path))
                    elif e.is_dir(follow_symlinks=False):
                        # ★ 子 agent 不止一层：workflow 起的在 `subagents/workflows/<wf>/agent-*.jsonl`
                        #   （实测 6725 个在第 7 层、432 个在第 5 层）。只看一层会静默漏掉前者。
                        sub = os.path.join(e.path, "subagents")
                        if os.path.isdir(sub):
                            for dp, _dn, fns in os.walk(sub):
                                out.extend(Path(dp) / n for n in fns if n.endswith(".jsonl"))
        except OSError:
            continue
    return out


def _do_claude(cur, rt, horizon, emit, err, seen):
    tr = cur.setdefault("claude_tr", {})
    spans = cur.setdefault("claude_otel", {})
    touched = set()
    od = rt["otel"]
    if od.is_dir():
        for p in sorted(od.glob("*.jsonl")):
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime < horizon:
                continue
            k = str(p)
            try:
                cur["files"][k] = _tail_lines(k, st, cur["files"].get(k),
                                              lambda it, fresh: _otel_consume(it, spans, horizon, touched))
            except ReadFail as e:
                err.append(str(e))
    root = rt["claude"]
    try:
        files = _claude_files(root)
    except OSError as e:
        err.append("读不了 %s: %s" % (S._tilde(root), e))
        files = []
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime < horizon:
            continue
        k = str(p)
        seen[k] = ("claude", st.st_mtime)
        ent = cur["files"].get(k)
        old = (ent or {}).get("state")
        try:
            cur["files"][k] = _tail_lines(
                k, st, ent, lambda it, fresh: _claude_consume(k, it, fresh, old, horizon, tr, touched))
        except ReadFail as e:
            err.append(str(e))
    for tbl in (tr, spans):
        for rid in [r for r, v in tbl.items() if (v.get("t1") or 0) < horizon]:
            del tbl[rid]
    if not touched:
        return
    # 只有 span 没有 transcript 的请求：会话内序号按 span 的完成先后数。
    by_sess = {}
    for rid, sp in spans.items():
        by_sess.setdefault(sp["sess"], []).append((sp["t1"], rid))
    span_n = {}
    for lst in by_sess.values():
        for n, (_t, rid) in enumerate(sorted(lst), 1):
            span_n[rid] = n
    for rid in touched:
        t, sp = tr.get(rid), spans.get(rid)
        if t or sp:
            emit(_claude_rec(rid, t, sp, span_n))


# ── Gemini（agy 会话库） ────────────────────────────────────────────────────────

def _pb_ts(b):
    """protobuf Timestamp / Duration（f1 秒 + f2 纳秒）→ 浮点秒。读不出 → None。"""
    if not isinstance(b, (bytes, bytearray)):
        return None
    d = S._pb(bytes(b))
    s = d.get(1, [0])[0]
    n = d.get(2, [0])[0]
    if not isinstance(s, int) or not isinstance(n, int):
        return None
    return s + n / 1e9


def _pb1(d, f):
    v = d.get(f)
    return v[0] if v else None


def _agy_title(con, conv):
    try:
        row = con.execute("SELECT data FROM trajectory_metadata_blob LIMIT 1").fetchone()
    except sqlite3.Error:
        row = None
    if row and row[0]:
        d = S._pb(bytes(row[0]))
        cands = [_pb1(d, 7)]
        f1 = _pb1(d, 1)
        if isinstance(f1, (bytes, bytearray)):
            cands.append(_pb1(S._pb(bytes(f1)), 1))
        for c in cands:
            if isinstance(c, (bytes, bytearray)):
                s = urllib.parse.unquote(bytes(c).decode("utf-8", "replace"))
                s = s[7:] if s.startswith("file://") else s
                b = _base(s)
                if b and s.startswith("/"):
                    return b
    return _short(conv)


def _agy_open(last):
    """最后一步 (step_type, status) → 轮次开着没。没有步 ⇒ None（没开过）。

    收：模型回复步（15）完成（3）· 清除（5）/ 取消（6）。其余都算开着 —— 用户输入（14）、工具（132）、
    系统（101）、checkpoint（23）、错误（17，实测后面跟着重试的 15）、工具出错（status 7，错误会喂回模型）、
    生成中（8）/ 运行中（2）/ 等待（9）。实测本机最近 150 个库最后一步：(15,3) 139 个。
    """
    if not last:
        return None
    stype, status = last
    return not ((stype == 15 and status == 3) or status in (5, 6))


def _agy_db(path, ent, horizon, emit):
    """→ 新游标条目。只读 `idx` 大于上次的 `gen_metadata`；对应的模型步与其前的工具步按 idx 范围取。"""
    conv = Path(path).stem
    stt = dict((ent or {}).get("state") or {"gidx": -1, "n": 0, "last_ms": -1, "title": None})
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=2.0)
    except sqlite3.Error as e:
        raise ReadFail("打不开 %s: %s" % (S._tilde(path), e)) from e
    try:
        try:
            last = con.execute("SELECT step_type, status FROM steps ORDER BY idx DESC LIMIT 1").fetchone()
        except sqlite3.Error as e:
            if "no such table" not in str(e).lower():
                raise ReadFail("查不了 %s: %s" % (S._tilde(path), e)) from e
            last = None
        stt["open"] = _agy_open(last)
        try:
            gens = con.execute("SELECT idx, data FROM gen_metadata WHERE idx > ? ORDER BY idx",
                               (stt["gidx"],)).fetchall()
        except sqlite3.Error as e:
            if "no such table" in str(e).lower():
                return stt                            # 新库还没写 gen_metadata：合法的空
            raise ReadFail("查不了 %s: %s" % (S._tilde(path), e)) from e
        if stt.get("title") is None:
            stt["title"] = _agy_title(con, conv)
        parsed = []
        for gidx, blob in gens:
            if not blob:
                parsed.append((gidx, None))
                continue
            top = S._pb(bytes(blob))
            inner = S._pb(bytes(top[1][0])) if isinstance(_pb1(top, 1), (bytes, bytearray)) else {}
            lsi = None
            for kv in inner.get(20, []):
                if isinstance(kv, (bytes, bytearray)):
                    d = S._pb(bytes(kv))
                    if _pb1(d, 1) == b"last_step_index" and isinstance(_pb1(d, 2), (bytes, bytearray)):
                        t = _pb1(d, 2).decode("ascii", "replace")
                        lsi = int(t) if t.lstrip("-").isdigit() else None
            parsed.append((gidx, (inner, lsi)))
        need = [x[1][1] for x in parsed if x[1] and x[1][1] is not None]
        steps = {}
        if need:
            try:
                for idx, stype, status, md in con.execute(
                        "SELECT idx, step_type, status, metadata FROM steps WHERE idx > ? AND idx <= ? "
                        "ORDER BY idx", (stt["last_ms"], max(need) + 1)):
                    steps[idx] = (stype, status, md)
            except sqlite3.Error as e:
                raise ReadFail("查不了 %s: %s" % (S._tilde(path), e)) from e
    finally:
        con.close()
    for gidx, item in parsed:
        if item is None or item[1] is None:
            stt["gidx"] = gidx                         # 空行 / 没有 last_step_index：跳过（不猜时间戳）
            continue
        inner, lsi = item
        sidx = lsi + 1
        step = steps.get(sidx)
        md = S._pb(bytes(step[2])) if step and step[2] else {}
        created = _pb_ts(_pb1(md, 1))
        fin = _pb_ts(_pb1(md, 7))
        ttft = _pb_ts(_pb1(inner, 11))
        strm = _pb_ts(_pb1(inner, 12))
        if created is None or (fin is None and (ttft is None or strm is None)):
            break                                      # 还在生成 / 模型步没写完：停在这里，下次接着读
        t_end = fin if fin is not None else created + (ttft or 0) + (strm or 0)
        tool = 0
        for i in range(stt["last_ms"] + 1, sidx):
            s = steps.get(i)
            if s and s[0] == 132 and s[2]:
                m2 = S._pb(bytes(s[2]))
                a, b = _pb_ts(_pb1(m2, 32)), _pb_ts(_pb1(m2, 8))
                if a is not None and b is not None and b >= a:
                    tool += b - a
        u = S._pb(bytes(inner[4][0])) if isinstance(_pb1(inner, 4), (bytes, bytearray)) else {}
        g = lambda f: (_pb1(u, f) if isinstance(_pb1(u, f), int) else 0)  # noqa: E731
        i_tok, cr, out, think, vis = g(2), g(5), g(3), g(9), g(10)
        # ★ 分子是 f3（含 thinking）：thinking 在 streaming 段里生成，只拿 f10 可见输出会把 thinking 多的响应
        #   压到 1/4（2026-10-21 实测 439 条，见模块 docstring）。`vis` 只用来判「真的生成了可见内容」。
        if strm is not None and strm >= MIN_GEN_S and vis > 0:
            tps, est = _div(out, strm), False
        else:
            tps, est = _div(out, (ttft or 0) + (strm or 0)), True
        mraw = _pb1(inner, 19)
        model = S._agy_canon(S._agy_model(bytes(mraw).decode("utf-8", "replace")
                                          if isinstance(mraw, (bytes, bytearray)) else None))
        stt["n"] += 1
        stt["gidx"], stt["last_ms"] = gidx, sidx
        if t_end < horizon:
            continue
        emit({"key": "agy:%s:%d" % (conv, gidx), "_file": path, "platform": "agy", "t_start": created, "t_end": t_end,
              "model": model, "source": None, "session": conv, "session_title": stt["title"],
              "account": None, "input": i_tok + cr, "cached": cr, "output": out,
              "reasoning": think if (_pb1(u, 9) is not None) else None,
              "ttft_ms": _ms(ttft), "gen_ms": _ms(strm), "total_ms": _ms(t_end - created),
              "tool_ms": int(round(tool * 1000)) if stt["n"] > 1 else None,
              "tps": tps, "est": est, "session_req_n": stt["n"]})
    return stt


def _do_agy(cur, rt, horizon, emit, err, seen):
    root = rt["agy"]
    if not root.is_dir():
        return
    try:
        names = os.listdir(root)
    except OSError as e:
        err.append("读不了 %s: %s" % (S._tilde(root), e))
        return
    for n in names:
        if not n.endswith(".db"):
            continue
        p = root / n
        try:
            mt, sig = S._agy_db_sig(p, p.stat())
        except OSError:
            continue
        if mt < horizon:
            continue
        k = str(p)
        seen[k] = ("agy", mt)
        ent = cur["files"].get(k)
        if ent and ent.get("sig") == sig:
            continue
        try:
            state = _agy_db(k, ent, horizon, emit)
            cur["files"][k] = {"sig": sig, "mtime": mt, "state": state}
        except (ReadFail, sqlite3.Error) as e:
            err.append(str(e))


# ── Grok ───────────────────────────────────────────────────────────────────────

_GROK_EV = (b'"turn_started"', b'"loop_started"', b'"first_token"', b'"tool_completed"')


def _grok_events(lines, fresh, state):
    if fresh or not state:
        state = {"turns": []}
    turns = state["turns"]
    for line in lines:
        if not any(x in line for x in _GROK_EV):
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if not isinstance(o, dict):
            continue
        typ, ts = o.get("type"), _iso(o.get("ts"))
        if ts is None:
            continue
        if typ == "turn_started" or not turns:
            turns.append({"t0": ts if typ == "turn_started" else None, "loop0": None, "ft": None, "tool": 0})
            del turns[:-8]
            if typ == "turn_started":
                continue
        t = turns[-1]
        if typ == "loop_started" and t["loop0"] is None:
            t["loop0"] = ts
        elif typ == "first_token" and t["ft"] is None:
            t["ft"] = ts
        elif typ == "tool_completed" and isinstance(o.get("duration_ms"), int):
            t["tool"] += o["duration_ms"]
    return state


def _grok_updates(lines, fresh, state, sess, title, ev, horizon, emit):
    if fresh or not state:
        state = {"n": 0, "open": None}
    for line in lines:
        start = b'"user_message_chunk"' in line
        if not start and b'"turn_completed"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        prm = o.get("params") if isinstance(o, dict) and isinstance(o.get("params"), dict) else {}
        up = prm.get("update") if isinstance(prm.get("update"), dict) else {}
        if up.get("sessionUpdate") == "user_message_chunk":
            state["open"] = True                          # 新一轮的提示
            continue
        if up.get("sessionUpdate") != "turn_completed":
            continue
        state["open"] = False                             # end_turn / cancelled / error 都是这一轮结束了
        u = up.get("usage") if isinstance(up.get("usage"), dict) else {}
        meta = prm.get("_meta") if isinstance(prm.get("_meta"), dict) else {}
        t_end = (meta["agentTimestampMs"] / 1000.0 if isinstance(meta.get("agentTimestampMs"), int)
                 else float(o["timestamp"]) if isinstance(o.get("timestamp"), (int, float)) else None)
        if t_end is None:
            continue
        el = _int(up.get("elapsed_ms"))
        t0 = t_end - el / 1000.0 if el is not None else None
        api = _int(u.get("apiDurationMs"))
        state["n"] += 1
        # 对上 events.jsonl 里这一轮：turn_started 落在 [t0 − 5s, t_end] 里的最后一个。
        turn = None
        for t in (ev or {}).get("turns", []):
            if t["t0"] is not None and t0 is not None and t0 - 5 <= t["t0"] <= t_end:
                turn = t
        ttft = None
        if turn and turn["ft"] is not None:
            ref = turn["loop0"] if turn["loop0"] is not None else turn["t0"]
            if ref is not None and turn["ft"] >= ref:
                ttft = _ms(turn["ft"] - ref)
        mu = u.get("modelUsage") if isinstance(u.get("modelUsage"), dict) else {}
        model = max(mu, key=lambda m: _i0(mu[m], "outputTokens")) if mu else None
        out = _i0(u, "outputTokens")
        pid = up.get("prompt_id") if isinstance(up.get("prompt_id"), str) else "%s:%d" % (sess, state["n"])
        if t_end < horizon:
            continue
        emit({"key": "grok:" + pid, "_file": sess, "platform": "grok", "t_start": t0, "t_end": t_end, "model": model,
              "source": "grok CLI", "session": sess, "session_title": title, "account": "单号",
              "input": _i0(u, "inputTokens"), "cached": _i0(u, "cachedReadTokens"), "output": out,
              "reasoning": _int(u.get("reasoningTokens")), "ttft_ms": ttft,
              "gen_ms": (api - ttft) if (api is not None and ttft is not None and api >= ttft) else None,
              "total_ms": el, "tool_ms": turn["tool"] if turn else None,
              "tps": _div(out, api / 1000.0 if api is not None else None), "est": False,
              "session_req_n": state["n"]})
    return state


def _do_grok(cur, rt, horizon, emit, err, seen):
    root = rt["grok"]
    if not root.is_dir():
        return
    try:
        cwds = [e for e in os.scandir(root) if e.is_dir(follow_symlinks=False)]
    except OSError as e:
        err.append("读不了 %s: %s" % (S._tilde(root), e))
        return
    for cd in cwds:
        title = _base(urllib.parse.unquote(cd.name))
        try:
            sdirs = [e for e in os.scandir(cd.path) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for sd in sdirs:
            up, evp = Path(sd.path) / "updates.jsonl", Path(sd.path) / "events.jsonl"
            try:
                ust = up.stat()
            except OSError:
                continue
            try:
                est_ = evp.stat()
            except OSError:
                est_ = None
            mt = max(ust.st_mtime, est_.st_mtime if est_ else 0)
            if mt < horizon:
                continue
            seen[str(up)] = ("grok", mt)
            try:
                ek = str(evp)
                if est_ is not None:
                    eold = (cur["files"].get(ek) or {}).get("state")
                    cur["files"][ek] = _tail_lines(ek, est_, cur["files"].get(ek),
                                                   lambda it, fresh: _grok_events(it, fresh, eold))
                ev = (cur["files"].get(ek) or {}).get("state")
                uk = str(up)
                uold = (cur["files"].get(uk) or {}).get("state")
                ent = _tail_lines(uk, ust, cur["files"].get(uk),
                                  lambda it, fresh: _grok_updates(it, fresh, uold, sd.name, title, ev,
                                                                  horizon, emit))
                ent["sess"], ent["title"] = sd.name, title
                cur["files"][uk] = ent
            except ReadFail as e:
                err.append(str(e))


SOURCES = (("codex", _do_codex), ("claude", _do_claude), ("agy", _do_agy), ("grok", _do_grok))


# ── 账本 ───────────────────────────────────────────────────────────────────────

class Store:
    def __init__(self, d):
        self.d = Path(d)
        self.d.mkdir(parents=True, exist_ok=True)
        self.lock_fh = None

    def lock(self):
        self.lock_fh = open(self.d / ".lock", "a+")
        fcntl.flock(self.lock_fh.fileno(), fcntl.LOCK_EX)

    def unlock(self):
        if self.lock_fh:
            try:
                fcntl.flock(self.lock_fh.fileno(), fcntl.LOCK_UN)
            finally:
                self.lock_fh.close()
                self.lock_fh = None

    def month_files(self, since):
        out = []
        for p in sorted(self.d.glob("????-??.jsonl")):
            y, m = int(p.stem[:4]), int(p.stem[5:7])
            end = time.mktime((y + (m == 12), m % 12 + 1, 1, 0, 0, 0, 0, 0, -1))
            if end > since:
                out.append(p)
        return out

    def rebuild(self, since):
        """窗口快照丢了 / 坏了 ⇒ 从月账本重建（按 key 去重、新值覆盖、null 不覆盖）。"""
        recs = {}
        for p in self.month_files(since):
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        try:
                            r = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(r, dict) and isinstance(r.get("key"), str) \
                                and (r.get("t_end") or 0) >= since:
                            recs[r["key"]] = _merge(recs.get(r["key"]), r)
            except OSError as e:
                raise ReadFail("读不了账本 %s: %s" % (S._tilde(p), e)) from e
        return recs

    def append(self, recs):
        by_month = {}
        for r in recs:
            by_month.setdefault(time.strftime("%Y-%m", time.localtime(r["t_end"])), []).append(r)
        for month, rows in by_month.items():
            with open(self.d / ("%s.jsonl" % month), "a", encoding="utf-8") as fh:
                fh.write("".join(json.dumps(_whitelist(r), ensure_ascii=False) + "\n" for r in rows))


def update(now, days, rt=None, join=False):
    """增量解析四家 →（可选）账号 join → 合并进窗口快照 + 追加账本。返回 (records, cursor, seen)。调用方须持锁。

    `join=True` 只在 `--json` 时用：要读 proxy.log / cli-*.log，`--live` 不需要账号。
    ★ join 放在**追加账本之前**：先 join 再写，一条新记录只落一行（不会先写一行「账号 null」再补一行）。
    """
    rt = rt or roots()
    st = Store(rt["ledger"])
    horizon = _local_midnight(now, max(1, days) - 1)
    cur = _load_json(st.d / ".cursor.json", {})
    if cur.get("v") != CUR_V or cur.get("horizon") is None or horizon < cur["horizon"]:
        # 首次 / 换版本 / 要的窗口比上次更早 ⇒ 游标作废、全量重解（账本里的旧记录不动）。
        cur = {"v": CUR_V, "horizon": horizon, "files": {}, "errors": cur.get("errors") or {}}
    cur["horizon"] = horizon
    cur.setdefault("files", {})
    snap_err = None
    snap = _load_json(st.d / ".window.json", {})
    recs = snap.get("records") if snap.get("v") == V and isinstance(snap.get("records"), dict) else None
    if recs is None:
        try:
            recs = st.rebuild(horizon)
        except ReadFail as e:
            recs, snap_err = {}, str(e)
    fresh = {}

    def emit(r):
        fresh[r["key"]] = _merge(fresh.get(r["key"]), r)

    seen = {}
    errs = {}
    for plat, fn in SOURCES:
        e = []
        try:
            fn(cur, rt, horizon, emit, e, seen)
        except Exception as ex:                      # noqa: BLE001 —— 一家坏了不许拖垮另外三家
            e.append("%s: %s" % (type(ex).__name__, ex))
        if e:
            errs[plat] = e
    if snap_err:
        errs.setdefault("ledger", []).append(snap_err)
    changed = {}
    for k, r in fresh.items():
        m = _merge(recs.get(k), r)
        if m != recs.get(k):
            recs[k] = m
            changed[k] = m
    recs = {k: v for k, v in recs.items() if (v.get("t_end") or 0) >= horizon}
    if join:
        for fn in (_join_codex, _join_agy):
            try:
                for r in fn(recs, rt, now, horizon):
                    changed[r["key"]] = r
            except Exception:                         # noqa: BLE001 —— 账号是附加信息：join 坏了不影响列表
                pass
    if changed:
        st.append(list(changed.values()))
    # 失败态：第一次失败的时刻保留到恢复为止（连续失败不刷新 stale_since）。
    old_err = cur.get("errors") or {}
    cur["errors"] = {p: {"error": "；".join(v)[:400],
                         "since": (old_err.get(p) or {}).get("since") or now} for p, v in errs.items()}
    # 游标里只留窗口内还在动的文件（窗口外的文件下次被改写时会从头重解，按 key 去重）。
    cur["files"] = {k: v for k, v in cur["files"].items() if (v.get("mtime") or 0) >= horizon}
    _atomic_write(st.d / ".window.json",
                  json.dumps({"v": V, "records": {k: _whitelist(v) for k, v in recs.items()}},
                             ensure_ascii=False))
    _atomic_write(st.d / ".cursor.json", json.dumps(cur, ensure_ascii=False))
    return recs, cur, seen


def _meta(cur):
    errs = cur.get("errors") or {}
    if not errs:
        return {"ok": True, "error": None, "stale_since": None}
    return {"ok": False,
            "error": "；".join("%s: %s" % (p, v["error"]) for p, v in sorted(errs.items())),
            "stale_since": min(v["since"] for v in errs.values())}


# ── 账号 join（只在 --json 时做：要读 proxy.log / cli-*.log，live 不需要账号） ──────────

def _join_codex(recs, rt, now, horizon):
    todo = [r for r in recs.values() if r["platform"] == "codex"]
    if not todo:
        return []
    text, info = R._tail_covering(str(rt["proxy_log"]), horizon, now)
    slots = {}
    try:
        with open(rt["state"], encoding="utf-8") as fh:
            slots = {aid: {"label": s.get("label"), "label_history": s.get("label_history")}
                     for aid, s in (json.load(fh).get("slots") or {}).items() if isinstance(s, dict)}
    except (OSError, ValueError, AttributeError):
        pass
    owner = {}
    if text is not None:
        _rq, owner, *_ = R.scan_proxy_log(text, now, horizon, now + 60, resolve=R.make_resolver(slots))
    out = []
    for r in todo:
        rid = r["key"][6:]
        acc = owner.get(rid)
        if acc is None:
            # ★ 「对不上」≠「直连」：日志读不到 / 日志没覆盖到那一刻 / 响应刚写完代理还没落行，都写 null。
            cov = info.get("covers_from")
            if text is None or (cov is not None and r["t_end"] < cov and not info.get("covered")) \
                    or now - r["t_end"] < 15:
                acc = None
            else:
                acc = "直连"
        if acc is not None and acc != r.get("account"):
            r["account"] = acc
            out.append(r)
    return out


def _join_agy(recs, rt, now, horizon):
    todo = [r for r in recs.values() if r["platform"] == "agy"]
    if not todo:
        return []
    conv_files = {}
    try:
        segs, _u, _e = AR.sessions(horizon - 86400, now + 60, rt["agy_log"], conv_files)
    except Exception:                                 # noqa: BLE001 —— 账号是附加信息，坏了写 null
        segs = []
    pool = _load_json(rt["agy_pool"], {})
    by_email = {(a.get("email") or "").lower(): a.get("label")
                for a in (pool.get("accounts") or {}).values() if isinstance(a, dict)}
    printed = set()
    for f in {f for fs in conv_files.values() for f in fs}:
        try:
            with open(Path(rt["agy_log"]) / f, "rb") as fh:
                if b"Print mode" in fh.read():
                    printed.add(f)
        except OSError:
            pass
    led = set()
    try:
        with open(rt["agy_ledger"], "rb") as fh:
            for line in fh:
                m = re.search(rb'"conv":\s*"([0-9a-f-]{36})"', line)
                if m:
                    led.add(m.group(1).decode())
    except OSError:
        pass
    out = []
    for r in todo:
        conv, ts = r["session"], r["t_end"]
        files = conv_files.get(conv) or set()
        hits = {s["email"] for s in segs
                if s["file"] in files and s["start"] - AR._EDGE <= ts <= s["end"] + AR._EDGE}
        acc = None
        if len(hits) == 1:
            e = hits.pop()
            acc = by_email.get(e.lower()) or e.split("@")[0]
        src = "agy -p" if (files & printed or conv in led) else ("agy 交互" if files else None)
        ch = False
        if acc is not None and acc != r.get("account"):
            r["account"], ch = acc, True
        if src is not None and src != r.get("source"):
            r["source"], ch = src, True
        if r.get("source") is None:
            r["source"], ch = "agy 交互", True
        if ch:
            out.append(r)
    return out


# ── 输出 ───────────────────────────────────────────────────────────────────────

def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _day_stats(rs):
    """次数 · 均速 · 首字中位（秒）· token（输入 + 输出，含缓存命中）。

    ★ 「均速」`avg_tps` 取逐条 t/s 的**中位数**（null 不计），不是算术平均：重尾分布下一条短响应就能把
      均值拉偏几倍；按 token 加权又要各家同一个分母，而四家的分子分母口径本来就不同（见模块 docstring）。
    """
    tps = [r["tps"] for r in rs if r.get("tps") is not None]
    ttft = [r["ttft_ms"] / 1000.0 for r in rs if r.get("ttft_ms") is not None]
    return {"n": len(rs), "avg_tps": round(_median(tps), 1) if tps else None,
            "ttft_median_s": round(_median(ttft), 2) if ttft else None,
            "tokens": sum((r.get("input") or 0) + (r.get("output") or 0) for r in rs)}


def build_json(now, days=2, rt=None):
    rt = rt or roots()
    st = Store(rt["ledger"])
    st.lock()
    try:
        recs, cur, _seen = update(now, days, rt, join=True)
    finally:
        st.unlock()
    rows = sorted((_whitelist(r) for r in recs.values()), key=lambda r: -(r["t_end"] or 0))
    t_today, t_yday = _local_midnight(now, 0), _local_midnight(now, 1)
    days_out = {}
    for name, a, b in (("today", t_today, now + 86400), ("yesterday", t_yday, t_today)):
        rs = [r for r in rows if a <= r["t_end"] < b]
        d = {"date": time.strftime("%Y-%m-%d", time.localtime(a)), **_day_stats(rs)}
        d["platforms"] = {p: _day_stats([r for r in rs if r["platform"] == p]) for p in PLATFORMS}
        days_out[name] = d
    return {"v": V, "generated_at": int(now), **_meta(cur), "requests": rows, "days": days_out}


def _session_of(path, ent):
    stt = (ent or {}).get("state") or {}
    if "sess" in (ent or {}):
        return ent["sess"], ent.get("title")
    if path.endswith(".db"):
        return Path(path).stem, stt.get("title")
    return stt.get("sess") or Path(path).stem, stt.get("title")


def _turn_open(ent):
    """游标里记的「这个文件最后一个轮次事件是开始」。没记过 / 是结束 ⇒ False。"""
    return ((ent or {}).get("state") or {}).get("open") is True


def build_live(now, fallback_secs=FALLBACK_SECS, rt=None):
    """在跑 = 轮次开着（没写结束标记）且 `fallback_secs` 内写过（见模块 docstring「判停」）。"""
    rt = rt or roots()
    st = Store(rt["ledger"])
    st.lock()
    try:
        recs, cur, seen = update(now, 2, rt)
    finally:
        st.unlock()
    t_today = _local_midnight(now, 0)
    today = [r for r in recs.values() if r["t_end"] >= t_today]
    plats = {}
    for p in PLATFORMS:
        sess = {}
        for path, (plat, mt) in seen.items():
            if plat != p:
                continue
            ent = cur["files"].get(path)
            sid, title = _session_of(path, ent)
            if not sid:
                continue
            s = sess.setdefault(sid, {"id": sid, "title": title or _short(sid), "tps": None, "tokens": 0,
                                      "last_t_end": None, "active": False, "_last": None})
            if _turn_open(ent) and mt >= now - fallback_secs:
                s["active"] = True
        for r in today:
            if r["platform"] != p or not r.get("session"):
                continue
            s = sess.setdefault(r["session"], {"id": r["session"], "title": r.get("session_title")
                                               or _short(r["session"]), "tps": None, "tokens": 0,
                                               "last_t_end": None, "active": False, "_last": None})
            s["tokens"] += (r.get("input") or 0) + (r.get("output") or 0)
            if s["_last"] is None or r["t_end"] > s["_last"]["t_end"]:
                s["_last"] = r
            if r.get("tps") is not None and not r.get("est") and (
                    s.get("_meas") is None or r["t_end"] > s["_meas"]["t_end"]):
                s["_meas"] = r
        lst = []
        for s in sess.values():
            last, meas = s.pop("_last"), s.pop("_meas", None)
            if last is not None:
                # ★★ 速度取最近一条**实测**（用户 2026-10-21「数字偏低」）：Claude 的 transcript 占位估值
                #   约 2 s 后才被 OTel 实测覆盖，`agent_summary` 旁路请求只能估（p50 5.1）且挂在主会话上 ——
                #   直接取最新一条，就是让这些估值盖住上一条实测。一条实测都没有才退回估值。
                s["last_t_end"], s["tps"] = last["t_end"], (meas or last).get("tps")
                if s["title"] is None:
                    s["title"] = last.get("session_title")
            if s["active"] or last is not None:
                lst.append(s)
        lst.sort(key=lambda s: (not s["active"], -(s["last_t_end"] or 0)))
        act = [s for s in lst if s["active"]]
        tv = [s["tps"] for s in act if s["tps"] is not None]
        # ★ 只在同一个 AI 内相加；在跑但还没完成第一条响应的会话 tps 是 null，不计。
        plats[p] = {"running": bool(act), "n_sessions": len(act),
                    "tps": round(sum(tv), 1) if tv else None,
                    "tokens_today": sum((r.get("input") or 0) + (r.get("output") or 0)
                                        for r in today if r["platform"] == p),
                    "sessions": lst[:20]}
    ds = _day_stats(today)
    out = {"v": V, "generated_at": int(now), **_meta(cur), "platforms": plats,
           "today": {"tokens": ds["tokens"], "avg_tps": ds["avg_tps"], "n": ds["n"]}}
    try:
        _atomic_write(Path(rt["ledger"]) / ".live.json", json.dumps(out, ensure_ascii=False))
    except OSError:
        pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--json", action="store_true")
    g.add_argument("--live", action="store_true")
    ap.add_argument("--days", type=int, default=2)
    # `--active-secs` 是旧名（2026-10-19 前它是「N 秒没写 = 停了」）；现在两个名字都是兜底窗口。
    ap.add_argument("--fallback-secs", "--active-secs", dest="fallback_secs", type=float, default=FALLBACK_SECS)
    a = ap.parse_args(argv)
    now = time.time()
    try:
        out = build_live(now, a.fallback_secs) if a.live else build_json(now, max(1, a.days))
    except Exception as e:                           # noqa: BLE001 —— 退出码恒 0：Err 在前端会被读成「没数据」
        out = {"v": V, "generated_at": int(now), "ok": False, "error": "%s: %s" % (type(e).__name__, e),
               "stale_since": now}
        out.update({"platforms": {}, "today": {"tokens": 0, "avg_tps": None, "n": 0}} if a.live
                   else {"requests": [], "days": {}})
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
