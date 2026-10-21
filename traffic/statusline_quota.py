#!/usr/bin/env python3
"""状态栏额度转写（2026-10-19）：把 Claude Code / agy 状态栏 payload 里的**额度**落盘给 CodexBar。

两家 CLI 每次重画状态栏都会把一份 JSON 喂给用户自己的状态栏脚本；脚本在后台把同一份
payload 转给 `--ingest`。我们只取额度字段，原子合并写 `traffic/statusline-ledger/<platform>.json`。

★ 不联网、不读凭证 —— 与 `traffic/` 的安全线一致。
★★ **字段白名单写死**。payload 里还有 `cwd` / `transcript_path` / `session_id` /
   `email`（agy）/ `model` 等，白名单之外一律不落盘，连键名都不写。读旧文件时也再过一遍
   白名单，手改或损坏的文件带不进别的键。
★★ **只增不减**（CLAUDE.md §7.0b）：某个窗口 / bucket / 子字段这次没给 ⇒ 沿用旧值，
   绝不写空。Claude Code 会在 `resets_at` 过后丢掉那个窗口，那是「这次没给」不是「变成 0」；
   `--read` 用 `expired` 说出来，不替它编一个数。
★ `--ingest` 挂在状态栏的热路径旁边：任何异常静默退出 0，**绝不影响状态栏**。
   只 import stdlib 里最轻的几个模块，整个调用 < 50 ms（`tests/test_statusline_quota.py` 量过）。
★ 不加锁：每次写都先读旧文件再合并，并发时后写者赢。两个会话同时写最坏丢掉对方这一拍，
   下一次重画就补回来。

用法：
  … | python3 -I statusline_quota.py --ingest claude|agy
  python3 -I statusline_quota.py --read
"""
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ★ 数据目录的推法与 `agy_quota_sampler.py` 相同：认 `CODEX_ROTATE_STORE`；脚本住在
#   `<store>/runtime/`（`.dmg` 经 Connector 接入）时数据在上一级（B85）。
_STORE = os.environ.get("CODEX_ROTATE_STORE") or (
    os.path.dirname(ROOT) if os.path.basename(ROOT) == "runtime" else ROOT)

PLATFORMS = ("claude", "agy")
CLAUDE_WINDOWS = ("five_hour", "seven_day")
# Claude.app 记录不带重置时间，只能拿窗口长度判它是否一定已过期（见 `read_all`）。
PLAN_USAGE_WINDOW_SECS = {"five_hour": 5 * 3600, "seven_day": 7 * 86400}
MAX_STDIN = 1 << 20
MAX_BUCKETS = 32
_BUCKET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$")
_TIER = re.compile(r"^[A-Za-z0-9 ._+-]{1,32}$")


def ledger_dir():
    return os.environ.get("STATUSLINE_LEDGER_DIR") or os.path.join(_STORE, "traffic", "statusline-ledger")


def plan_usage_path():
    return os.environ.get("CLAUDE_PLAN_USAGE_PATH") or os.path.expanduser(
        "~/Library/Application Support/Claude/plan-usage-history.json")


# ── 值校验（不合格 = 这次没给，不是 0）────────────────────────────────────────

def _num(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v != v or v < lo or v > hi:          # NaN / 越界
        return None
    return v


def _epoch(v):
    v = _num(v, 1, 1 << 45)
    if v is None:
        return None
    return int(v / 1000) if v > 1e11 else int(v)   # 毫秒也认


def _iso(v):
    return v if isinstance(v, str) and _ISO.match(v) else None


# ── 白名单清洗（新 payload 与旧文件走同一套）──────────────────────────────────

def _clean_claude_window(w):
    if not isinstance(w, dict):
        return None
    out = {}
    pct = _num(w.get("used_pct"), 0, 1000)
    rs = _epoch(w.get("resets_at"))
    cap = _epoch(w.get("captured_at"))
    if pct is not None:
        out["used_pct"] = pct
    if rs is not None:
        out["resets_at"] = rs
    if cap is not None:
        out["captured_at"] = cap
    return out or None


def _clean_agy_bucket(b):
    if not isinstance(b, dict):
        return None
    out = {}
    rf = _num(b.get("remaining_fraction"), 0, 1)
    rt = _iso(b.get("reset_time"))
    cap = _epoch(b.get("captured_at"))
    if rf is not None:
        out["remaining_fraction"] = rf
    if rt is not None:
        out["reset_time"] = rt
    if cap is not None:
        out["captured_at"] = cap
    return out or None


def clean_ledger(platform, d):
    """旧文件 -> 只含白名单键的 dict。"""
    if not isinstance(d, dict):
        return {}
    out = {}
    cap = _epoch(d.get("captured_at"))
    if cap is not None:
        out["captured_at"] = cap
    if platform == "claude":
        for w in CLAUDE_WINDOWS:
            c = _clean_claude_window(d.get(w))
            if c:
                out[w] = c
    else:
        tier = d.get("plan_tier")
        if isinstance(tier, str) and _TIER.match(tier):
            out["plan_tier"] = tier
        bs = d.get("buckets")
        if isinstance(bs, dict):
            cb = {}
            for name, b in bs.items():
                c = _clean_agy_bucket(b)
                if c and isinstance(name, str) and _BUCKET.match(name) and len(cb) < MAX_BUCKETS:
                    cb[name] = c
            if cb:
                out["buckets"] = cb
    return out


# ── 合并（纯函数）───────────────────────────────────────────────────────────

def merge_claude(old, payload, now):
    """返回 (新 dict, 有没有抓到东西)。没抓到 ⇒ 调用方不写盘。"""
    out = clean_ledger("claude", old)
    rl = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(rl, dict):
        return out, False
    got_any = False
    for w in CLAUDE_WINDOWS:
        cur = rl.get(w)
        if not isinstance(cur, dict):
            continue                         # 这次没给 ⇒ 沿用旧值
        pct = _num(cur.get("used_percentage"), 0, 1000)
        rs = _epoch(cur.get("resets_at"))
        if pct is None and rs is None:
            continue
        prev = out.get(w) or {}
        prs = prev.get("resets_at")
        # ★ 闲置会话重画状态栏时，payload 里是**它自己最后一次响应时**的额度，可能早已过时。
        #   窗口身份 = resets_at：比已记的更早 ⇒ 那是旧窗口的读数，丢弃；
        #   同一窗口里已用% 只升不降（窗口内用量不会退回），更低的读数同样是过时会话给的。
        #   ⚠️ 后一条依赖「同一 resets_at 内单调」，若服务端会回补，代价是偏高直到重置 —— 不会偏低。
        if rs is not None and prs is not None:
            if rs < prs:
                continue
            if rs == prs and pct is not None and prev.get("used_pct") is not None \
                    and pct < prev["used_pct"]:
                continue
        new = dict(prev)
        if pct is not None:
            new["used_pct"] = pct
        if rs is not None:
            new["resets_at"] = rs
        elif prs is not None and prs <= now:
            new.pop("resets_at", None)       # 旧窗口已过，旧重置时刻不能挂到新读数上
        new["captured_at"] = now
        out[w] = new
        got_any = True
    if got_any:
        out["captured_at"] = now
    return out, got_any


def merge_agy(old, payload, now):
    out = clean_ledger("agy", old)
    if not isinstance(payload, dict):
        return out, False
    got_any = False
    tier = payload.get("plan_tier")
    if isinstance(tier, str) and _TIER.match(tier):
        out["plan_tier"] = tier
        got_any = True
    q = payload.get("quota")
    if isinstance(q, dict):
        buckets = dict(out.get("buckets") or {})
        for name, b in q.items():
            if not (isinstance(name, str) and _BUCKET.match(name) and isinstance(b, dict)):
                continue
            if name not in buckets and len(buckets) >= MAX_BUCKETS:
                continue
            rf = _num(b.get("remaining_fraction"), 0, 1)
            rt = _iso(b.get("reset_time"))
            if rt is None:
                ris = _num(b.get("reset_in_seconds"), 0, 400 * 86400)
                if ris is not None:
                    rt = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + ris))
            if rf is None and rt is None:
                continue
            new = dict(buckets.get(name) or {})
            if rf is not None:
                new["remaining_fraction"] = rf
            if rt is not None:
                new["reset_time"] = rt
            new["captured_at"] = now
            buckets[name] = new
            got_any = True
        if buckets:
            out["buckets"] = buckets
    if got_any:
        out["captured_at"] = now
    return out, got_any


# ── 读写 ─────────────────────────────────────────────────────────────────────

class _Unreadable(Exception):
    pass


def _load(path):
    """不存在 / 损坏 ⇒ {}；**存在但读不了**（权限、I/O）⇒ 抛 `_Unreadable`，
    调用方据此**不写** —— 读不到的旧值不能被这次的半份数据覆盖（§7.0b ①）。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_STDIN)
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise _Unreadable(str(e))
    try:
        d = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {}                            # 我们自己的文件写坏了：没有可保留的值
    return d if isinstance(d, dict) else {}


def _atomic_write(path, obj):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, ".%s.%d.tmp" % (os.path.basename(path), os.getpid()))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def ingest(platform, raw, now=None, ldir=None):
    """返回 True = 写了盘。"""
    if platform not in PLATFORMS:
        return False
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return False
    now = int(time.time()) if now is None else int(now)
    path = os.path.join(ldir or ledger_dir(), platform + ".json")
    old = _load(path)
    merged, got = (merge_claude if platform == "claude" else merge_agy)(old, payload, now)
    if not got:
        return False
    _atomic_write(path, merged)
    return True


def _plan_usage_newest(path):
    """Claude.app 的 `plan-usage-history.json` -> 最新一条 (t 秒, fh, sd)，读不到 None。

    已知形状（2026-10-19 只看了键与类型）：`{"version":2,"samples":[{"t":<ms>,"org":str,
    "u":{"fh":int,"sd":int}}]}`，`fh` = 5h 已用%、`sd` = 周已用%。也容忍按 org 分组的
    `{<org>: [samples…]}`。形状不认识就当没有，不猜。"""
    try:
        with open(path, "rb") as f:
            d = json.loads(f.read(8 << 20).decode("utf-8"))
    except (OSError, ValueError):
        return None
    lists = []
    if isinstance(d, dict):
        if isinstance(d.get("samples"), list):
            lists.append(d["samples"])
        else:
            lists.extend(v for v in d.values() if isinstance(v, list))
    elif isinstance(d, list):
        lists.append(d)
    best = None
    for lst in lists:
        for s in lst:
            if not isinstance(s, dict) or not isinstance(s.get("u"), dict):
                continue
            t = _epoch(s.get("t"))
            fh = _num(s["u"].get("fh"), 0, 1000)
            sd = _num(s["u"].get("sd"), 0, 1000)
            if t is None or (fh is None and sd is None):
                continue
            if best is None or t > best[0]:
                best = (t, fh, sd)
    return best


def _window_out(w, now):
    if not w or w.get("used_pct") is None:
        return None
    rs = w.get("resets_at")
    return {"used_pct": w["used_pct"], "resets_at": rs,
            "captured_at": w.get("captured_at"),
            "expired": bool(rs is not None and rs <= now)}


def read_all(now=None, ldir=None, plan_path=None):
    now = int(time.time()) if now is None else int(now)
    ldir = ldir or ledger_dir()
    out = {}

    claude = {"source": "none", "captured_at": None, "five_hour": None, "seven_day": None, "error": None}
    try:
        sl = clean_ledger("claude", _load(os.path.join(ldir, "claude.json")))
    except _Unreadable as e:
        sl, claude["error"] = {}, "statusline ledger unreadable: %s" % e
    has_sl = any(sl.get(w) for w in CLAUDE_WINDOWS)
    pu = _plan_usage_newest(plan_path or plan_usage_path())
    if has_sl and not (pu and pu[0] > sl.get("captured_at", 0)):
        claude.update(source="statusline", captured_at=sl.get("captured_at"),
                      five_hour=_window_out(sl.get("five_hour"), now),
                      seven_day=_window_out(sl.get("seven_day"), now))
    elif pu:
        t, fh, sd = pu
        # ★ 这份没有重置时间，但窗口长度是定的：读数比窗口还老 ⇒ 它所在的窗口**一定**已经重置过，
        #   这个「已用」属于旧窗口，标 `expired`（前端据此写 —，不当现值）。2026-10-21 实测：
        #   Claude.app 停在 6 周前的一条，刘海照样画成 38% / 92%，与实际对不上。
        mk = lambda p, win: None if p is None else {"used_pct": p, "resets_at": None, "captured_at": t,
                                                    "expired": now - t >= win}
        claude.update(source="plan-usage-history", captured_at=t,
                      five_hour=mk(fh, PLAN_USAGE_WINDOW_SECS["five_hour"]),
                      seven_day=mk(sd, PLAN_USAGE_WINDOW_SECS["seven_day"]))
    out["claude"] = claude

    agy = {"source": "none", "captured_at": None, "plan_tier": None, "buckets": {}, "error": None}
    try:
        al = clean_ledger("agy", _load(os.path.join(ldir, "agy.json")))
    except _Unreadable as e:
        al, agy["error"] = {}, "statusline ledger unreadable: %s" % e
    if al.get("buckets") or al.get("plan_tier"):
        agy.update(source="statusline", captured_at=al.get("captured_at"),
                   plan_tier=al.get("plan_tier"), buckets=al.get("buckets") or {})
    out["agy"] = agy
    return out


def main(argv):
    if len(argv) >= 3 and argv[1] == "--ingest":
        try:
            raw = sys.stdin.buffer.read(MAX_STDIN + 1)
            if 0 < len(raw) <= MAX_STDIN:
                ingest(argv[2], raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            # 这里吞掉是对的：它挂在状态栏旁边，唯一的用户是仪表盘。坏 payload / 磁盘满 /
            # 目录没权限都不能变成状态栏里的一行报错；仪表盘那边把「没有 / 过期」显示成 —。
            pass
        return 0
    if len(argv) >= 2 and argv[1] == "--read":
        print(json.dumps(read_all(), ensure_ascii=False))
        return 0
    sys.stderr.write(__doc__.split("用法：", 1)[1])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
