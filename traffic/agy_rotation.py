#!/usr/bin/env python3
"""Gemini（agy）的「代理轮换」数据 —— 与 `rotation.py::collect` **同形**，日志页直接复用泳道。

## 为什么需要一份单独的（用户 2026-09-24：「代理轮换也改成 codex 和 gemini 两个版块」）

agy 没有代理，所以没有 `proxy.log` 那样的逐请求记录。能诚实拿到的只有两样：
  · **会话**：agy 每次启动写一份 `~/.gemini/antigravity-cli/log/cli-YYYYMMDD_HHMMSS.log`，
    其中 `applyAuthResult: email=…` 是 agy **自己**认证成了哪个号（与探针归属同源的证据）；
    一个长会话中途被钥匙串写回换了身份时，同一份日志里会出现第二条 `applyAuthResult` ——
    按它切段，不把整场会话记在第一个号头上。
  · **换号记录**：`agy.log` 里 `auto 自动切到 / 恢复成你选的 / 借用已停用的` 与 `switch →`。

## 按号 token（2026-10-14 接上；此前恒 0）
  agy 的会话库 `conversations/<conv>.db` 有逐次 token（`scan._scan_agy_db`），但不带账号。
  **会话 id 会写进启动它的那份 `cli-*.log`**，而那份日志的 `applyAuthResult` 就是身份 ——
  所以归属是 **conv id 精确 join**，与 codex 泳道的 `response_id` 同一条纪律，不按时间猜。
  实测 4/4 对上（其中 2 个是用 `agy --as` 指定号跑的已知样本）。
  · 一份日志中途换了身份：按这一条生成的时间戳落到那份日志的哪一段。
  · conv 不在窗口内任何日志里（日志被轮转 / 从 IDE 起的 agy）、或落点对出两个号：**不归属**，
    计入 `responses_seen - responses_with_tokens`。合计因此是**下界**，前端写「已归属」。
  · token = 未缓存输入 + 缓存读 + 输出（与 codex 泳道 `total_tokens` 同口径，含缓存读）。

## 不做的
  · 泳道时段 = **agy 以这个号的身份在运行**（启动到日志最后一次写入），不是「在消耗」。

纯模块：只读本机日志与池文件，不联网、不碰凭证、不写任何东西。
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rotation as R  # noqa: E402  —— 复用配色 / 自然日切分，别抄第二份

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = Path(os.environ.get("AGY_LOG_DIR",
                              str(Path.home() / ".gemini" / "antigravity-cli" / "log")))
DB_ROOT = Path(os.environ.get("AGY_DB_ROOT",
                              str(Path.home() / ".gemini" / "antigravity-cli" / "conversations")))
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
#: 生成时间戳与日志段边界的容差（秒）。段的终点是日志 mtime，生成落盘与日志写入不是同一刻。
_EDGE = 5
_NAME = re.compile(r"cli-(\d{8})_(\d{6})\.log$")
_AUTH = re.compile(r"^I(\d{2})(\d{2}) (\d{2}):(\d{2}):(\d{2})\.\d+\s+\d+ \S+\] applyAuthResult: email=([^\s,]+)",
                   re.M)
_EV = re.compile(r"^\[agy (\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\] (.*)$")
_EV_KIND = (("auto 自动切到", "auto"), ("auto 恢复成你选的", "wanted"),
            ("auto 借用已停用的", "borrow"), ("switch →", "manual"))


def _store():
    return Path(os.environ.get("AGY_POOL_STORE") or os.environ.get("CODEX_ROTATE_STORE") or ROOT)


def _pool():
    try:
        return json.loads((_store() / ".agy-pool.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sessions(start, end, log_dir=None, conv_files=None):
    """→ (segments, unattributed, earliest)。每段 `{email, start, end, file}`，已按身份变化切开。

    `conv_files`（可选 dict）顺手填 `{会话 id: {日志文件名…}}` —— token 归属用，省一遍读盘。
    """
    d = log_dir or LOG_DIR
    segs, unattr, earliest = [], 0, None
    try:
        files = list(d.glob("cli-*.log"))
    except OSError:
        return [], 0, None
    for f in files:
        m = _NAME.search(f.name)
        if not m:
            continue
        try:
            t0 = time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))
            t1 = f.stat().st_mtime
        except (OSError, ValueError):
            continue
        earliest = t0 if earliest is None else min(earliest, t0)
        if t1 < start or t0 > end:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if conv_files is not None:
            for cid in set(_UUID.findall(text)):
                conv_files.setdefault(cid, set()).add(f.name)
        year = int(m.group(1)[:4])
        auths = []
        for a in _AUTH.finditer(text):
            mo, da, hh, mi, ss, email = a.groups()
            try:
                ts = time.mktime((year, int(mo), int(da), int(hh), int(mi), int(ss), 0, 0, -1))
            except (OverflowError, ValueError):
                continue
            if not auths or auths[-1][1] != email:
                auths.append((ts, email))
        if not auths:
            unattr += 1                      # ★ 认不出身份就不归属 —— 不猜
            continue
        for i, (ts, email) in enumerate(auths):
            s = max(t0, ts if i else t0)
            e = auths[i + 1][0] if i + 1 < len(auths) else t1
            s, e = max(s, start), min(e, end)
            if e > s:
                segs.append({"email": email, "start": s, "end": e, "file": f.name})
    segs.sort(key=lambda x: x["start"])
    return segs, unattr, earliest


def switch_events(start, end, store=None):
    """`agy.log` 里的换号记录 → `[(ts, kind, label, line)]`。"""
    out = []
    try:
        lines = ((store or _store()) / "agy.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    year = time.localtime(end).tm_year
    for ln in lines:
        m = _EV.match(ln)
        if not m:
            continue
        mo, da, hh, mi, ss, body = m.groups()
        kind = next((k for (p, k) in _EV_KIND if body.startswith(p)), None)
        if not kind:
            continue
        ts = time.mktime((year, int(mo), int(da), int(hh), int(mi), int(ss), 0, 0, -1))
        if ts > end + 86400:                 # 跨年：日志不带年份
            ts = time.mktime((year - 1, int(mo), int(da), int(hh), int(mi), int(ss), 0, 0, -1))
        if start <= ts <= end:
            lab = re.search(r"\[([^\]]+)\]", body)
            out.append((ts, kind, lab.group(1) if lab else None, body))
    return out


def generations(start, end, db_root=None):
    """窗口内每一次生成 → `([(ts, conv, model, uncached_in, cache_read, output)], unreadable)`。

    ★ 复用 `scan._scan_agy_db`（时间戳 join、f9 不加等坑都在那里），不抄第二份。
    ★ 按 db **与 `-wal`** 的 mtime 预筛：这些库是 WAL 模式，写入落在 `-wal`，主库 mtime 不动。
    """
    root = db_root or DB_ROOT
    out, bad = [], 0
    try:
        paths = list(root.glob("*.db"))
    except OSError:
        return out, bad
    S = None
    for p in paths:
        try:
            mt = p.stat().st_mtime
            w = p.with_name(p.name + "-wal")
            if w.exists():
                mt = max(mt, w.stat().st_mtime)
        except OSError:
            continue
        if mt < start:
            continue
        if S is None:
            import scan as S                      # noqa: N813 —— 延迟导入：没有库时不付这份成本
        try:
            rows = S._scan_agy_db(str(p))
        except Exception:                         # noqa: BLE001 —— 一个坏库不该让整页没数
            bad += 1
            continue
        # ★ 模型名与用量页同一套归一（`scan._agy_canon`），否则同一个 Flash 在这里又是另一个名字。
        out.extend((r[0], r[1], S._agy_canon(r[2])) + tuple(r[3:]) for r in rows if start <= r[0] <= end)
    return out, bad


def _union(spans):
    """区间并集的总长（秒）。"""
    tot, cur_s, cur_e = 0.0, None, None
    for a, b in sorted(spans):
        if cur_e is None or a > cur_e:
            if cur_e is not None:
                tot += cur_e - cur_s
            cur_s, cur_e = a, b
        else:
            cur_e = max(cur_e, b)
    if cur_e is not None:
        tot += cur_e - cur_s
    return tot


def collect(hours=24.0, now=None, log_dir=None, store=None, db_root=None, gens=None):
    now = time.time() if now is None else now
    end, start = now, now - hours * 3600
    pool = _pool() if store is None else json.loads((store / ".agy-pool.json").read_text(encoding="utf-8"))
    accs = pool.get("accounts") or {}
    by_email = {(a.get("email") or "").lower(): (sub, a) for sub, a in accs.items()}
    conv_files = {}
    raw, unattr, earliest = sessions(start, end, log_dir, conv_files)
    if gens is None:
        gens, _unreadable = generations(start, end, db_root)
    evs_raw = switch_events(start, end, store)

    def label_of(email):
        hit = by_email.get(email.lower())
        return hit[1].get("label") if hit else email.split("@")[0]

    segs = []
    for i, s in enumerate(raw):
        acc = label_of(s["email"])
        prev = segs[-1]["acc"] if segs else None
        reason = "window_start" if prev is None else "same"
        if prev is not None and prev != acc:
            logged = [e for e in evs_raw if s["start"] - 180 <= e[0] <= s["start"] + 5 and e[2] == acc]
            reason = ("borrow" if logged and logged[-1][1] == "borrow"
                      else "switch" if logged else "drift")
        segs.append({"acc": acc, "start": s["start"], "end": s["end"], "requests": 1, "tokens": 0,
                     "by_model": {}, "enter_reason": reason,
                     "current": s["end"] >= now - 90})

    # ★★ token 归属：conv id → 写过它的日志 → 那份日志里此刻的身份段。对不上 / 对出两个号就不归属。
    placed = []                                   # (段下标, ts, model, tokens)
    for (ts, conv, model, i_tok, cr_tok, o_tok) in gens:
        files = conv_files.get(conv) or ()
        hits = [k for k, r in enumerate(raw)
                if r["file"] in files and r["start"] - _EDGE <= ts <= r["end"] + _EDGE]
        if not hits or len({segs[k]["acc"] for k in hits}) != 1:
            continue
        k = min(hits, key=lambda k: 0 if raw[k]["start"] <= ts <= raw[k]["end"]
                else min(abs(ts - raw[k]["start"]), abs(ts - raw[k]["end"])))
        placed.append((k, ts, model, i_tok + cr_tok + o_tok))
    for (k, _ts, model, tok) in placed:
        segs[k]["tokens"] += tok
        segs[k]["by_model"][model] = segs[k]["by_model"].get(model, 0) + tok
    for s in segs:
        s["by_model"] = sorted(({"model": m, "tokens": v} for m, v in s["by_model"].items()),
                               key=lambda x: -x["tokens"])
    labels = sorted({s["acc"] for s in segs} | {a.get("label") for a in accs.values() if a.get("label")})
    colors = R.assign_colors(labels)
    in_pool = {a.get("label") for a in accs.values()}

    def quota_pct(lab):
        for a in accs.values():
            if a.get("label") == lab:
                r = ((a.get("quota") or {}).get("gemini") or {}).get("remaining")
                return round(r * 100) if isinstance(r, (int, float)) else None
        return None

    accounts = []
    for lab in labels:
        mine = [s for s in segs if s["acc"] == lab]
        if not mine and lab not in in_pool:
            continue
        tok = sum(s["tokens"] for s in mine)
        models = {}
        for s in mine:
            for m in s["by_model"]:
                models[m["model"]] = models.get(m["model"], 0) + m["tokens"]
        top = max(models.items(), key=lambda kv: kv[1]) if models else None
        accounts.append({"acc": lab, "plan": "", "color": colors.get(lab, "#2dd4bf"), "tokens": tok,
                         "requests": len(mine),
                         "top_model": ({"model": top[0], "share": top[1] / tok} if top and tok else None),
                         "quota_pct": quota_pct(lab),
                         **({"retired": True} if lab not in in_pool else {})})

    TEXT = {"auto": "自动切到", "wanted": "恢复成你选的", "borrow": "借用已停用的", "manual": "手动切换到"}
    events = [{"t": t, "type": "switch", "from": None, "to": lab, "reason": k,
               "text": f"{TEXT[k]} {lab} · 下次启动 agy 生效", "accs": [lab] if lab else []}
              for (t, k, lab, _b) in evs_raw]
    for i, s in enumerate(segs):
        if i and s["enter_reason"] == "drift":
            events.append({"t": s["start"], "type": "failover", "from": segs[i - 1]["acc"], "to": s["acc"],
                           "reason": "drift",
                           "text": f"{segs[i - 1]['acc']} → {s['acc']} · 没有换号记录 —— "
                                   f"多半是某个仍在跑的 agy 把钥匙串写回了自己的身份",
                           "accs": [segs[i - 1]["acc"], s["acc"]]})
    events.sort(key=lambda e: -e["t"])

    days = R._day_bounds(start, end)
    rows = []
    for lab in [a["acc"] for a in accounts]:
        cells = []
        for (_d, d0, d1) in days:
            # ★ 取**并集**不是求和：本机常有好几个 agy 同时以同一个号在跑（实测一天求和出 139633s，
            #   超过一天的 86400s）。「在岗」问的是这段时间里有没有它，不是它被开了几次。
            secs = _union([(max(s["start"], d0), min(s["end"], d1))
                           for s in segs if s["acc"] == lab and s["end"] > d0 and s["start"] < d1])
            n = sum(1 for s in segs if s["acc"] == lab and d0 <= s["start"] < d1)
            tok = sum(t for (k, ts, _m, t) in placed if segs[k]["acc"] == lab and d0 <= ts < d1)
            if earliest is not None and d1 <= earliest:
                cells.append("unknown")
            else:
                cells.append({"secs": int(secs), "requests": n, "tokens": tok}
                             if (secs or n or tok) else None)
        rank = None
        for i, sub in enumerate(pool.get("pinned") or []):
            if (accs.get(sub) or {}).get("label") == lab:
                rank = i
        rows.append({"acc": lab, "rank": rank,
                     "rotate_off": any(a.get("rotate_off") for a in accs.values() if a.get("label") == lab),
                     "cells": cells})

    changes = sum(1 for i in range(1, len(segs)) if segs[i]["acc"] != segs[i - 1]["acc"])
    dwell = [s["end"] - s["start"] for s in segs]
    covered = earliest is not None and earliest <= start
    tot_tok = sum(t for (_k, _ts, _m, t) in placed)
    return {
        "ok": True, "platform": "agy", "generated_at": int(now),
        "window": {"start": start, "end": end, "hours": hours},
        "accounts": accounts, "segments": segs, "markers": [], "events": events,
        "log": [{"t": t, "text": b} for (t, _k, _l, b) in sorted(evs_raw, reverse=True)][:200],
        "daily": {"days": [d[0] for d in days], "rows": rows, "relay": [0] * len(days)},
        "kpi": {"tokens": tot_tok, "requests": len(segs),
                "avg_tokens": (tot_tok / len(segs)) if segs else 0, "rotations": changes,
                "avg_dwell": (sum(dwell) / len(dwell)) if dwell else 0, "cool_429": 0,
                "stream_err": 0, "pro_segs": 0, "pro_secs": 0},
        # ★ `responses_*` 在这一版数的是**生成**（每次请求一条），`responses_unplaced` 仍是认不出身份的**会话**
        #   （前端两句话分开说）。没有一条生成时 `attributed_pct` 为 None —— 「没有可归属的」≠「0% 归属」。
        "coverage": {"responses_seen": len(gens), "responses_with_tokens": len(placed),
                     "responses_unplaced": unattr,
                     "attributed_pct": (len(placed) / len(gens)) if gens else None, "undated_lines": 0, "in_window_lines": len(raw),
                     "tail_truncated": False, "window_covered": covered, "tail_bytes": 0,
                     "covers_from": earliest, "log_begins_at": earliest,
                     "log_begins_reason": "ok" if earliest else "unreadable"},
    }


if __name__ == "__main__":
    hrs = 24.0
    if "--hours" in sys.argv:
        hrs = float(sys.argv[sys.argv.index("--hours") + 1])
    sys.stdout.write(json.dumps(collect(hrs), ensure_ascii=False))
