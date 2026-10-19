#!/usr/bin/env python3
"""Claude Code OTel 追踪的本机接收端（2026-10-18 试运行；2026-10-19 起是正式服务 `otel`）。

Claude Code 开了 `OTEL_TRACES_EXPORTER=otlp` + `http/json` 后，每条请求结束会把
`claude_code.llm_request` span 推到这里。我们只收、只写盘，不发起任何请求。

★ 只监听 127.0.0.1。不联网、不读凭证 —— 与 `traffic/` 的安全线一致。
★★ **字段白名单**：span 里还带 `user.email` / `user.account_uuid` / `organization.id`，
   interaction span 里有 `user_prompt`。白名单之外的属性一律不落盘，连键名都不写。
   内容开关（`OTEL_LOG_USER_PROMPTS` 等）哪天被误开，正文也进不了磁盘。
★ 账本只追加：`traffic/otel-ledger/YYYY-MM.jsonl`（按 span 结束时刻的本地月份）。
   读取方按 `request_id` 去重。
★ 只认 JSON。收到 protobuf 回 415 并记进 `.status.json` —— 说明配置不对，要让它看得见。
★ 常驻由 `scripts/install-launchd.sh` / `install-windows.ps1` 的 `otel` 服务管（`--dir <store>/traffic/otel-ledger`）。
  **绑定端口本身就是单实例锁**：第二份起不来。起不来时把原因写进 `.status.json`
  （`listening: false` + `last_error`）和 stderr，并以非 0 退出 —— 绝不静默。
  4318 是 OTLP/HTTP 的标准端口，用户自己的收集器很可能已经占着它。
★ 账本目录与 `requests.py::roots()["otel"]` / `scan.py::OTEL_ROOT` **同一条规则**
  （`REQUESTS_OTEL_DIR` > `<store>/traffic/otel-ledger`）。`.dmg` 布局下代码在 `<store>/runtime/`，
  按 `__file__` 推目录会写进运行时副本，读的人永远读不到（闸 `tests/test_store_root_dmg_layout.py`）。

用法：python3 otel_receiver.py [--port 4318] [--dir <store>/traffic/otel-ledger]
"""
import errno
import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SPAN_NAME = "claude_code.llm_request"
KEEP = (
    "request_id", "gen_ai.response.id", "session.id", "model",
    "ttft_ms", "first_content_ms", "duration_ms",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens",
    "stop_reason", "attempt", "success", "status_code", "error_class",
    "query_source", "query_source_safe", "speed", "effort",
)
INT_KEYS = {"ttft_ms", "first_content_ms", "duration_ms", "input_tokens", "output_tokens",
            "cache_read_tokens", "cache_creation_tokens", "attempt", "status_code"}
MAX_BODY = 8 * 1024 * 1024
PORT = 4318

_CODE_ROOT = Path(__file__).resolve().parent.parent


def default_dir():
    """账本目录。规则逐条对齐 `requests.py::roots()["otel"]`。"""
    v = os.environ.get("REQUESTS_OTEL_DIR")
    if v:
        return Path(v)
    store = Path(os.environ.get("CODEX_ROTATE_STORE")
                 or (_CODE_ROOT.parent if _CODE_ROOT.name == "runtime" else _CODE_ROOT))
    return store / "traffic" / "otel-ledger"


def _read_status(root):
    try:
        st = json.loads((Path(root) / ".status.json").read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_status_file(root, st):
    root = Path(root)
    tmp = root / (".status.json.tmp%d" % os.getpid())
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, root / ".status.json")


def _val(v):
    """OTLP AnyValue -> python 值。只取标量；复合值不要。"""
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        try:
            return int(v["intValue"])
        except (TypeError, ValueError):
            return None
    if "doubleValue" in v:
        return v["doubleValue"]
    if "boolValue" in v:
        return v["boolValue"]
    return None


def extract(payload):
    """OTLP/JSON traces 负载 -> (要落盘的记录, 忽略的 span 数)。纯函数。"""
    recs, ignored = [], 0
    for rs in payload.get("resourceSpans") or []:
        for ss in rs.get("scopeSpans") or []:
            for sp in ss.get("spans") or []:
                if sp.get("name") != SPAN_NAME:
                    ignored += 1
                    continue
                attrs = {}
                for a in sp.get("attributes") or []:
                    k = a.get("key")
                    if k in KEEP:
                        v = _val(a.get("value") or {})
                        if k in INT_KEYS and isinstance(v, str) and v.lstrip("-").isdigit():
                            v = int(v)
                        attrs[k] = v
                try:
                    t0 = int(sp.get("startTimeUnixNano") or 0) / 1e9 or None
                    t1 = int(sp.get("endTimeUnixNano") or 0) / 1e9 or None
                except (TypeError, ValueError):
                    t0 = t1 = None
                recs.append({"t_start": t0, "t_end": t1, **attrs})
    return recs, ignored


class Ledger:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        # ★ `last_post_at` 跨重启沿用（§7.0b「读不到 ≠ 没有」）：重启一次就清空的话，
        #   设置页会把「收到过数据」误报成「还没收到」。计数器是本进程的，照旧从 0 开始。
        prev = _read_status(self.root)
        self.status = {"pid": os.getpid(), "started_at": time.time(), "posts": 0,
                       "spans_kept": 0, "spans_ignored": 0, "other_signals": 0,
                       "rejected": 0, "last_post_at": prev.get("last_post_at"), "last_error": None,
                       "listening": None, "port": None}

    def _write_status(self):
        _write_status_file(self.root, self.status)

    def note(self, **kw):
        with self.lock:
            for k, v in kw.items():
                if isinstance(v, int) and not isinstance(v, bool) and k in self.status \
                        and isinstance(self.status[k], int):
                    self.status[k] += v
                else:
                    self.status[k] = v
            self._write_status()

    def append(self, recs):
        with self.lock:
            by_month = {}
            for r in recs:
                month = time.strftime("%Y-%m", time.localtime(r.get("t_end") or time.time()))
                by_month.setdefault(month, []).append(r)
            for month, rows in by_month.items():
                with open(self.root / ("%s.jsonl" % month), "a", encoding="utf-8") as f:
                    f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def make_handler(ledger):
    class H(BaseHTTPRequestHandler):
        def _reply(self, code, body=b"{}"):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                ledger.note(rejected=1, last_error="body too large: %d" % n)
                return self._reply(413)
            body = self.rfile.read(n)
            ctype = self.headers.get("Content-Type", "")
            if self.path != "/v1/traces":
                ledger.note(other_signals=1, last_post_at=time.time())
                return self._reply(200)
            if "json" not in ctype:
                ledger.note(rejected=1, last_error="not json: %s" % ctype)
                return self._reply(415)
            try:
                recs, ignored = extract(json.loads(body))
            except Exception as e:
                ledger.note(rejected=1, last_error="%s: %s" % (type(e).__name__, e))
                return self._reply(400)
            if recs:
                ledger.append(recs)
            ledger.note(posts=1, spans_kept=len(recs), spans_ignored=ignored,
                        last_post_at=time.time())
            self._reply(200)

        def log_message(self, *a):
            pass

    return H


def bind_failed(root, port, exc):
    """端口起不来：原因进 `.status.json`（**合并**，不清掉别的字段）+ stderr。返回退出码。

    ★ 合并而不是整份重写：占着端口的可能正是另一份接收端（同一个账本目录），
      整份重写会把它的 `last_post_at` 抹掉，设置页就误报「还没收到」。
    """
    root = Path(root)
    inuse = getattr(exc, "errno", None) in (errno.EADDRINUSE, 10048)
    msg = ("端口 %d 已被别的程序占用（可能是你自己的 OTel 收集器，或另一份接收端）" % port
           if inuse else "端口 %d 打不开：%s: %s" % (port, type(exc).__name__, exc))
    try:
        root.mkdir(parents=True, exist_ok=True)
        st = _read_status(root)
        st.update({"listening": False, "port": port, "last_error": msg, "error_at": time.time()})
        _write_status_file(root, st)
    except OSError:
        pass
    print("otel_receiver: %s" % msg, file=sys.stderr, flush=True)
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--dir", default=None)
    a = ap.parse_args(argv)
    root = Path(a.dir) if a.dir else default_dir()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), None)
    except OSError as e:
        return bind_failed(root, a.port, e)
    ledger = Ledger(root)
    srv.RequestHandlerClass = make_handler(ledger)
    ledger.note(last_error=None, listening=True, port=a.port, error_at=None)
    print("otel_receiver listening 127.0.0.1:%d -> %s" % (a.port, root), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
