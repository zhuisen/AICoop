#!/usr/bin/env python3
"""「Claude 实测速度」开关：把 12 个 OTel 环境变量合并进 Claude Code 的 `settings.json` → `env`。

开了之后 Claude Code 把每次请求的耗时与 token 发到本机接收端（`traffic/otel_receiver.py`，服务 `otel`），
不含对话内容（内容开关四个都写成 0，接收端另有字段白名单）。Claude Code 只在启动时读 `env`，
所以只对**新开的**会话生效。

## 硬边界（同 `connector.py` 的托管块：用户的文件，我们只碰自己那几行）

- ★★★ **只解析结构、只碰这 12 个键。** `settings.json` 的 `env` 里可能有 API key / token。
  任何输出（stdout / 报错 / 备份以外的文件）都**不含任何值**，冲突也只报键名。
- ★★ **不覆盖别人的配置。** `env` 里已有指向别处的 `OTEL_*`，或这 12 个键里任何一个的值与我们不同
  ⇒ 判「冲突」，一个字节都不写。
- ★★ **关 = 只删我们写的键，且值仍等于我们写的那份才删。** 「我们写的」记在 `<store>/.claude-otel-env.json`
  （`added`）。没有这份记录、但 12 个键全在且值全对 ⇒ 视为我们的（2026-10-18 本机试运行是手工写进去的）。
- ★ 写之前把原文件**逐字节**备份到 `<store>/backups/claude-settings/`（留最近 5 份，0600）；
  写法是同目录临时文件 + `os.replace`；写前再读一次，期间被别的程序改过就放弃（不合并别人的半截写入）。
- ★ 保留其它所有键与顺序；缩进沿用原文件。`settings.json` 是 symlink（dotfiles）时写到它指向的真文件。

用法：python3 claude_otel_env.py status|enable|disable [--json]
测试隔离：`CLAUDE_CONFIG_DIR`（同 Claude Code 自己的变量）、`CODEX_ROTATE_STORE`、`REQUESTS_OTEL_DIR`、
`CLAUDE_OTEL_PORT_PROBE=0`（不探端口）。
"""
import json
import os
import re
import socket
import stat
import sys
import time
from pathlib import Path

PORT = 4318
ENDPOINT = "http://127.0.0.1:%d/v1/traces" % PORT

#: 我们写的 12 个键与值。顺序 = 写入顺序。★ 改这里要同步 `docs/INSTALL.md`「Claude 实测速度」一节。
OURS = {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    "OTEL_TRACES_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/json",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": ENDPOINT,
    "OTEL_TRACES_EXPORT_INTERVAL": "1000",
    "OTEL_METRICS_EXPORTER": "none",
    "OTEL_LOGS_EXPORTER": "none",
    "OTEL_LOG_USER_PROMPTS": "0",
    "OTEL_LOG_ASSISTANT_RESPONSES": "0",
    "OTEL_LOG_TOOL_DETAILS": "0",
    "OTEL_LOG_TOOL_CONTENT": "0",
}
KEEP_BACKUPS = 5

_CODE_ROOT = Path(__file__).resolve().parent


class SettingsError(Exception):
    """可以原样给用户看的错误。★ 文案里绝不放 settings.json 的任何值。"""


# ── 路径（每次现读环境变量：测试在调用前设置） ──────────────────────────────────

def settings_path():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")) / "settings.json"


def _store():
    return Path(os.environ.get("CODEX_ROTATE_STORE")
                or (_CODE_ROOT.parent if _CODE_ROOT.name == "runtime" else _CODE_ROOT))


def _record_path():
    return _store() / ".claude-otel-env.json"


def _backup_dir():
    return _store() / "backups" / "claude-settings"


def _otel_dir():
    """与 `traffic/otel_receiver.py::default_dir` / `requests.py::roots()["otel"]` 同一条规则。"""
    v = os.environ.get("REQUESTS_OTEL_DIR")
    return Path(v) if v else _store() / "traffic" / "otel-ledger"


def _display(p):
    home = str(Path.home())
    s = str(p)
    return "~" + s[len(home):] if home and s.startswith(home) else s


# ── 读 ───────────────────────────────────────────────────────────────────────

def _load():
    """→ (真实路径, 原始字节 | None, 文档 dict)。文件不存在 = 空文档，不是错误。"""
    real = settings_path()
    if real.is_symlink():
        real = real.resolve()
    try:
        raw = real.read_bytes()
    except FileNotFoundError:
        return real, None, {}
    except OSError as e:
        raise SettingsError("读不到 %s（%s）" % (_display(real), type(e).__name__))
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise SettingsError("%s 不是合法 JSON，没有改动" % _display(real))
    if not isinstance(doc, dict):
        raise SettingsError("%s 顶层不是对象，没有改动" % _display(real))
    env = doc.get("env")
    if env is not None and not isinstance(env, dict):
        raise SettingsError("%s 里的 env 不是对象，没有改动" % _display(real))
    return real, raw, doc


def classify(env):
    """→ (相等的键, 冲突的键)。纯函数。★ 只比较、不返回任何值。"""
    equal, conflicts = [], []
    for k, v in (env or {}).items():
        if k in OURS:
            (equal if v == OURS[k] else conflicts).append(k)
        elif k.startswith("OTEL_"):
            conflicts.append(k)
    return equal, conflicts


def _read_record():
    try:
        rec = json.loads(_record_path().read_text(encoding="utf-8"))
        return rec if isinstance(rec, dict) else None
    except (OSError, ValueError):
        return None


def _port_open():
    if os.environ.get("CLAUDE_OTEL_PORT_PROBE") == "0":
        return None
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.3):
            return True
    except OSError:
        return False


def receiver_status():
    """接收端现状：`.status.json`（收到过没有 / 起不来的原因）+ 端口上有没有人在听。"""
    try:
        st = json.loads((_otel_dir() / ".status.json").read_text(encoding="utf-8"))
        st = st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        st = {}
    return {"last_post_at": st.get("last_post_at"),
            "listening": st.get("listening"),
            "error": st.get("last_error") if st.get("listening") is False else None,
            "port_open": _port_open()}


def status():
    try:
        real, _, doc = _load()
    except SettingsError as e:
        return {"ok": False, "state": "error", "ui": "error", "error": str(e), "conflicts": [],
                "settings": _display(settings_path()), "receiver": receiver_status()}
    equal, conflicts = classify(doc.get("env"))
    if conflicts:
        state = "conflict"
    elif len(equal) == len(OURS):
        state = "on"
    elif equal:
        state = "partial"
    else:
        state = "off"
    rcv = receiver_status()
    ui = state if state != "on" else (
        "on_down" if rcv["port_open"] is False or rcv["error"]
        else "on_receiving" if rcv["last_post_at"] else "on_waiting")
    return {"ok": True, "state": state, "ui": ui, "error": None, "conflicts": conflicts,
            "settings": _display(real), "receiver": rcv}


# ── 写 ───────────────────────────────────────────────────────────────────────

def _indent_of(raw):
    if raw is None:
        return 2
    m = re.match(r"\{[ \t]*\r?\n([ \t]+)\S", raw.decode("utf-8", "replace"))
    if not m:
        return 2
    ws = m.group(1)
    return ws if "\t" in ws else len(ws)


def _backup(raw):
    d = _backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    name = "settings-%s-%d.json" % (time.strftime("%Y%m%d-%H%M%S"), os.getpid())
    fd = os.open(str(d / name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    olds = sorted(p for p in d.glob("settings-*.json") if p.is_file())
    for p in olds[:-KEEP_BACKUPS]:
        try:
            p.unlink()
        except OSError:
            pass
    return d / name


def _atomic_write(real, doc, before):
    """同目录临时文件 + `os.replace`。★ 写前再读一次：与 `before` 不同 = 期间有人改过 ⇒ 放弃。"""
    try:
        cur = real.read_bytes()
    except FileNotFoundError:
        cur = None
    if cur != before:
        raise SettingsError("%s 刚被别的程序改过，没有写入；请再试一次" % _display(real))
    text = json.dumps(doc, indent=_indent_of(before), ensure_ascii=False)
    if before is None or before.endswith(b"\n"):
        text += "\n"
    real.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(real.stat().st_mode) if before is not None else 0o600
    tmp = real.with_name(".%s.codexbar-%d.tmp" % (real.name, os.getpid()))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(real))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _write_record(rec):
    p = _record_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(p))


def enable():
    real, raw, doc = _load()
    env = doc.get("env")
    equal, conflicts = classify(env)
    if conflicts:
        raise SettingsError("已有别的 OTel 配置（%s），没有改动" % "、".join(conflicts))
    missing = [k for k in OURS if k not in (env or {})]
    if not missing:
        return {"changed": False}
    if raw is not None:
        _backup(raw)
    env_created = env is None
    new_env = dict(env or {})
    for k in missing:
        new_env[k] = OURS[k]
    doc = dict(doc)
    doc["env"] = new_env
    _atomic_write(real, doc, raw)
    rec = _read_record() or {}
    added = list(dict.fromkeys(list(rec.get("added") or []) + missing))
    _write_record({"added": added, "env_created": bool(rec.get("env_created")) or env_created,
                   "enabled_at": time.time()})
    return {"changed": True, "added": missing}


def disable():
    real, raw, doc = _load()
    env = doc.get("env")
    if not isinstance(env, dict):
        env = {}
    rec = _read_record()
    if rec is not None:
        owned = [k for k in (rec.get("added") or []) if k in OURS]
    else:
        equal, conflicts = classify(env)
        # ★ 没有记录：只有「12 个全在、值全对、没有冲突」才认作我们的（试运行手写的那份）。
        owned = list(OURS) if (len(equal) == len(OURS) and not conflicts) else []
    drop = [k for k in owned if env.get(k) == OURS[k]]
    if drop:
        if raw is not None:
            _backup(raw)
        new_env = {k: v for k, v in env.items() if k not in drop}
        doc = dict(doc)
        if not new_env and rec is not None and rec.get("env_created"):
            doc.pop("env", None)
        else:
            doc["env"] = new_env
        _atomic_write(real, doc, raw)
    try:
        _record_path().unlink()
    except OSError:
        pass
    return {"changed": bool(drop), "removed": drop}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    if cmd not in ("status", "enable", "disable"):
        print("用法：claude_otel_env.py status|enable|disable [--json]", file=sys.stderr)
        return 2
    out = {}
    try:
        if cmd == "enable":
            out = enable()
        elif cmd == "disable":
            out = disable()
        res = dict(status(), **out)
    except SettingsError as e:
        res = dict(status(), ok=False, error=str(e))
    except Exception as e:  # ★ 只报类型名：异常文本可能带出文件内容
        res = dict(status(), ok=False, error="%s（%s）" % ("写入失败" if cmd != "status" else "读取失败",
                                                          type(e).__name__))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
