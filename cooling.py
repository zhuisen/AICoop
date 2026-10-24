"""冷却判据的**唯一一份**：代理选号、`codex-rotate`（ensure-live / next / list / 写额度时解冻）、
`traffic/rotation.py`（泳道里的「冷却到」）都从这里取。零 import，按路径加载也便宜。

★ 2026-10-24 从 `proxy/proxy.py` 搬出（samchen #4 ④⑤）：原来 `codex-rotate` 与 `rotation.py` 只比
  `cooling_until > now`，不认这里的「冷却后读到新额度就解冻」与「窗口已重置」两条提前放行 ⇒ 代理已经在用的号，
  界面与 ensure-live 仍当它在冷却；而 `codex-rotate::_patch_slot` 为了用这份判据，持着 state 锁现 exec 整个 proxy.py。
"""


def cooling(sl, now):
    """这个号是否**仍在冷却**。

    ★ `resets_at` 已过 ⇒ 窗口其实早就重置了，冷却标记是陈旧的，按"可用"处理。
      不这么判的话，一次 429 会把号锁到冷却计时结束，而额度那时早已回满。
    """
    cu = sl.get("cooling_until", 0)
    if cu <= now:
        return False
    if recovered(sl, now):
        return False
    q = sl.get("quota") or {}
    # ★ 还有窗口见底且没到重置 ⇒ 冷却仍成立（全方面评审 §10：周额度用光时 5h 先过重置点，旧判据当它回满了）
    if _spent_resets(q, now):
        return True
    ra = (q.get("primary") or {}).get("resets_at")
    return not (ra and ra <= now)


def recovered(sl, now):
    """冷却之后读到了**新**额度，且 5h 还有余量、没有窗口见底 ⇒ 号已经回来了，冷却作废。

    ★★ 用户 2026-10-23：「官方重置的时候也没有取消冻结。识别到 5H 额度不是 0 的，就应该取消冻结」。
      原来只认「快照里 primary 的重置点已过」：一旦 quotad 在重置后读到新快照，`resets_at` 换成下一个窗口
      （在未来），这条判据反而失效，号一直冻到 `cooling_until` —— 而 429 时读数缺失或过期，`_cool` 按
      5 h 兜底，比真实重置晚得多。
    ★ 必须是 `_cool` **之后**拍的快照（`captured_at > cooled_at`）：冷却前拍的 99% 不能证明 429 之后还有余量，
      否则立刻又挑中它、再撞 429。没有 `cooled_at`（旧数据 / 手动 `cool`）⇒ 不判，保持原样。
    ★ 代理 `cooling()` 与 `codex-rotate::_patch_slot`（写入额度时直接删 `cooling_until`，让 UI / CLI 的
      各处原始判断也跟上）共用这一份。"""
    ca = sl.get("cooled_at")
    q = sl.get("quota") or {}
    if not ca or (q.get("captured_at") or 0) <= ca:
        return False
    p = q.get("primary")
    if not isinstance(p, dict) or p.get("used_percent") is None or p["used_percent"] >= 100:
        return False
    return not _spent_resets(q, now)


def _spent_resets(q, now):
    """见底（used ≥ 100）且还没到重置的窗口各自的 `resets_at`。`_cool` 与 `cooling` 共用这一份。"""
    return [w.get("resets_at") for w in (q.get("primary"), q.get("secondary"))
            if isinstance(w, dict) and (w.get("used_percent") or 0) >= 100
            and (w.get("resets_at") or 0) > now]
