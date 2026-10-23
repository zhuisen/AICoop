#!/usr/bin/env python3
"""harness 的固定夹具：**脱敏快照 + 日期平移**（2026-10-23，用户「CI 跑 UI 闸」+「本机 UI 闸别再随真实数据漂」）。

为什么要它：`make_harness.py` 原来只读本机真实的 `state.json` 与 `.traffic-latest.json`。
· CI 的干净 checkout 上两份都没有 ⇒ 66 个用到 harness 的测试文件在 CI 上大多 skip。
· 本机也会漂：重置卡过期、号被停用，闸就因为数据变了而红，与代码无关（2026-10-23 一轮里 3 条）。

做法：
· `capture`：从本机真实数据拍一份，**只去掉能认人的**（account_id、邮箱、姓名、改名历史、头像链接、
  探针原话），结构 / 额度 / 套餐 / 重置卡 / 用量全部保真（用设计稿假数据量不出真实排版，见 `redacted_state`）。
  记下拍摄时刻 `_anchor`。标签（qq55 / Egan …）保留：测试按它们找号，且早已出现在入库的测试里。
· `load_*`：读夹具时把时间平移到「现在」。夹具不冻日期（`~/.claude/rules/testing-discipline.md`）——
  否则过一周重置卡全部过期、额度快照全部陈旧，又回到漂的老路。
  · state：epoch 数一律平移整段秒差（state 里没有落在 epoch 量级的计数，`capture` 断言过）；ISO 时刻同。
  · 用量快照：**只按键名**平移（`generated_at` / `since` / `first` / `last`）+ 日期键按整天平移 ——
    token 计数会落在 epoch 量级（实测 claude 一天 cache_read 1.9e9），按数值平移会改坏它们。

用法：`python3 codexbar/uishot/fixture_tool.py capture`（刷新夹具时才跑；产物要人看一眼再提交）。
"""
import datetime
import json
import pathlib
import re
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
DIR = HERE / "fixture"
# ★ 不叫 `state.json`：`.gitignore` 第 3 行全局挡这个名字（真池子文件，不许入库），别为夹具放松它
STATE, TRAFFIC = DIR / "pool-state.json", DIR / "traffic.json"

EPOCH_LO, EPOCH_HI = 1.6e9, 2.1e9
_ISO = re.compile(r"^(\d{4}-\d\d-\d\d)T(\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)?$")
_DAYKEY = re.compile(r"^(\d{4}-\d\d-\d\d)(T\d\d)?$")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_CARD = re.compile(r"RateLimitResetCredit_[0-9a-f]{16,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
#: state 里能认人、又不影响排版的字段：整键删掉（只用于 state —— 用量快照的 `name` 是平台名）
DROP_KEYS = {"name", "label_history", "profile_image_url", "description", "detail"}
#: 用量快照里按键名平移的时刻字段
TRAFFIC_TIME_KEYS = {"generated_at", "since", "first", "last"}


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _shift_iso(s, dt):
    m = _ISO.match(s)
    if not m:
        return s
    day, hms, frac, tz = m.groups()
    t = datetime.datetime.fromisoformat("%sT%s%s" % (day, hms, frac or "")).replace(
        tzinfo=datetime.timezone.utc if tz in (None, "Z") else datetime.datetime.strptime(tz.replace(":", ""), "%z").tzinfo)
    t = t + datetime.timedelta(seconds=dt)
    out = t.strftime("%Y-%m-%dT%H:%M:%S") + (t.strftime(".%f")[: len(frac)] if frac else "")
    return out + (tz or "")


def _shift_day(s, days):
    m = _DAYKEY.match(s)
    if not m:
        return s
    d = datetime.date.fromisoformat(m.group(1)) + datetime.timedelta(days=days)
    return d.isoformat() + (m.group(2) or "")


def shift_state(o, dt, days):
    """state：epoch 数与 ISO 时刻平移 `dt` 秒；纯日期（`dawn_probe.date`）平移 `days` 天。"""
    if isinstance(o, dict):
        return {k: shift_state(v, dt, days) for k, v in o.items()}
    if isinstance(o, list):
        return [shift_state(v, dt, days) for v in o]
    if _is_num(o) and EPOCH_LO < o < EPOCH_HI:
        return o + dt
    if isinstance(o, str):
        return _shift_day(o, days) if re.fullmatch(r"\d{4}-\d\d-\d\d", o) else _shift_iso(o, dt)
    return o


def shift_traffic(o, days, now):
    """用量快照：日期键整天平移；只有 `TRAFFIC_TIME_KEYS` 的数按秒平移（token 计数不碰）。"""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            nk = _shift_day(k, days)
            if k in TRAFFIC_TIME_KEYS and _is_num(v):
                out[nk] = v + days * 86400
            else:
                out[nk] = shift_traffic(v, days, now)
        if "generated_at" in out and "platforms" in out:
            out["generated_at"] = int(now)       # 快照「刚生成」：新鲜度闸按它判
        return out
    if isinstance(o, list):
        return [shift_traffic(v, days, now) for v in o]
    return o


def _local_days_between(a, b):
    return (datetime.date.fromtimestamp(b) - datetime.date.fromtimestamp(a)).days


def load_state(now=None):
    now = time.time() if now is None else now
    raw = json.loads(STATE.read_text())
    anchor = raw.pop("_anchor")
    return shift_state(raw, now - anchor, _local_days_between(anchor, now))


def load_traffic(now=None):
    now = time.time() if now is None else now
    raw = json.loads(TRAFFIC.read_text())
    anchor = raw.pop("_anchor")
    return shift_traffic(raw, _local_days_between(anchor, now), now)


def _anonymize(o, idmap, drop=frozenset()):
    """account_id（键 / 值 / 子串）→ 假 id；邮箱 → demo@example.com；`drop` 里的键整键删。"""
    if isinstance(o, dict):
        return {_anonymize(k, idmap): _anonymize(v, idmap, drop) for k, v in o.items() if k not in drop}
    if isinstance(o, list):
        return [_anonymize(v, idmap, drop) for v in o]
    if isinstance(o, str):
        for real, fake in idmap.items():
            o = o.replace(real, fake)
        # 池里已删掉的号（`pinned` / `card_order` 里的残留）与服务端的卡片 id：同一个真值恒映射到同一个假值
        o = _UUID.sub(lambda m: idmap.setdefault(m.group(0), "user-gone%02d00000000000000000000000" % len(idmap)), o)
        o = _CARD.sub(lambda m: idmap.setdefault(m.group(0), "RateLimitResetCredit_demo%03d" % len(idmap)), o)
        return _EMAIL.sub("demo@example.com", o)
    return o


def capture():
    now = time.time()
    st = json.loads((REPO / "state.json").read_text())
    idmap = {aid: "user-demo%02d0000000000000000000000" % i for i, aid in enumerate(st.get("slots", {}), 1)}
    out = _anonymize(st, idmap, DROP_KEYS)
    for i, (fake, sl) in enumerate(out.get("slots", {}).items(), 1):
        sl["email"] = "demo%d@example.com" % i
        sl["file"] = "%s.json" % fake
    # 平移的前提：state 里不能有落在 epoch 量级、却不是时刻的数（否则会被当时刻挪走）
    bad = []

    def _scan(o, k=""):
        if isinstance(o, dict):
            for kk, v in o.items():
                _scan(v, kk)
        elif isinstance(o, list):
            for v in o:
                _scan(v, k)
        elif _is_num(o) and EPOCH_LO < o < EPOCH_HI and abs(o - now) > 400 * 86400:
            bad.append(k)
    _scan(out)
    if bad:
        sys.exit("✗ 这些键的数落在 epoch 量级、却离现在 > 400 天，平移会改坏它们：%s" % sorted(set(bad)))
    out["_anchor"] = now
    tr = json.loads((REPO / ".traffic-latest.json").read_text())
    for src in ((tr.get("scan") or {}).get("sources") or {}).values():
        src.pop("root", None)                   # 本机路径
    if "scan" in tr:
        tr["scan"]["read_failed_sample"] = []
    tr = _anonymize(tr, idmap)
    tr["_anchor"] = now
    DIR.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    TRAFFIC.write_text(json.dumps(tr, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    body = STATE.read_text() + TRAFFIC.read_text()
    if any(a in body for a in idmap) or _UUID.search(body) or _CARD.search(body):
        sys.exit("✗ 真实 id 仍在夹具里")
    print("✓ 夹具已写：%s（%d 个号）· %s" % (STATE.relative_to(REPO), len(out.get("slots", {})), TRAFFIC.relative_to(REPO)))


if __name__ == "__main__":
    if sys.argv[1:] == ["capture"]:
        capture()
    else:
        sys.exit("usage: fixture_tool.py capture")
