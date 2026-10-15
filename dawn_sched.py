"""定时探针「到没到点」的唯一一份判据 —— `codex-rotate dawn-probe` 与 `agy-rotate dawn-probe` 共用。

## 为什么是「每分钟醒一次、自己判断」而不是 launchd 的固定日历时刻（2026-10-15）

用户要求时间可选，且「选 6:00 就在 6:00～6:03 之间随机」。固定日历时刻写在 plist 里，
改时间就得重写 plist —— 而本仓的铁律是 plist 只由 `install-launchd.sh` 生成，界面不碰它。
所以调度改成：launchd / 计划任务每 60s 拉起一次命令（同 `autosync`），**命令自己**读开关、
时间与当天记录决定跑不跑。实测一次空转约 60ms。

## 随机偏移必须「按天固定」

launchd 每分钟一次、app 内补跑每 10 分钟一次，两条路都会问「到点没有」。偏移若每次现掷，
两边看到的是两个不同的时刻 —— 一个说没到、一个说到了，随机就退化成「谁先问谁算」。
所以偏移由 `(日期, 哪一家)` 决定：同一天里任何进程算出来都是同一秒，换一天换一个。
"""
import datetime
import os
import random
import re
import time

DEFAULT_TIME = "06:00"
#: 「6:00～6:03」—— 偏移取 [0, 180) 秒。`CODEX_ROTATE_DAWN_JITTER` 只给测试用（0 = 不随机）。
JITTER_SECS = 180
#: 距目标不到这么多秒就**睡到那一秒再跑**；更远就退出等下一次唤醒（launchd 每 60s 一次）。
WAIT_SECS = 60


def parse_time(s):
    """`"HH:MM"` → `"HH:MM"`（补零）；不合法返回 None —— 调用方拒绝写入，不默默改成 06:00。"""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(s or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    return "%02d:%02d" % (h, mi)


def jitter(day, kind):
    """当天的随机偏移（秒）。按 `(日期, kind)` 定死 —— 见模块头。"""
    env = os.environ.get("CODEX_ROTATE_DAWN_JITTER")
    span = int(env) if env not in (None, "") else JITTER_SECS
    if span <= 0:
        return 0
    return random.Random("%s|%s" % (day.isoformat(), kind)).randrange(span)


def due_at(rec, kind, day=None):
    """今天该在哪一秒跑（本地时间的 epoch 秒）。"""
    day = day or datetime.date.today()
    hhmm = parse_time((rec or {}).get("time")) or DEFAULT_TIME
    h, mi = map(int, hhmm.split(":"))
    base = time.mktime(datetime.datetime(day.year, day.month, day.day, h, mi).timetuple())
    return base + jitter(day, kind)


def window_text(rec):
    """「06:00–06:03」—— 界面上那句说明的唯一出处（`--status` 带出去）。"""
    hhmm = parse_time((rec or {}).get("time")) or DEFAULT_TIME
    h, mi = map(int, hhmm.split(":"))
    end = (h * 60 + mi + JITTER_SECS // 60) % (24 * 60)
    return "%s–%02d:%02d" % (hhmm, end // 60, end % 60)
