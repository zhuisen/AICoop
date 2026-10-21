/** 代理轮换台账（`traffic/rotation.py::collect` / `agy_rotation.py::collect` 的输出）。 */

export interface Seg0 {
  acc: string;
  start: number;
  end: number;
  requests: number;
  tokens: number;
  by_model: { model: string; tokens: number }[];
  enter_reason: string;
  current?: boolean;
}
export interface Acct {
  acc: string;
  /** 套餐。★ 看 `plan` 不看 label —— 老号从 Plus 升 Pro 时 label 一个字都不变。 */
  plan: string;
  color: string;
  tokens: number;
  requests: number;
  top_model: { model: string; share: number } | null;
  /** 最紧窗口的剩余 %（旧列；悬浮卡里还用）。 */
  quota_pct: number | null;
  /** 5h 窗口剩余 %（AICoop P7 右列）。读不到 / 没有 5h 窗口 ⇒ null，画「—」。 */
  quota_5h?: number | null;
  /** 此刻在冷却 ⇒ 终点（epoch 秒）；没在冷却 ⇒ null。 */
  cooling_until?: number | null;
  /** 这个名字已不在账号池里：号被 `remove` 掉，或是改名后没被 `alias` 认领的旧名。
   *  ★ 零活动的退役名字在 `rotation.py` 的数据层就整条丢掉了，能走到这里的**都有活动**。 */
  retired?: boolean;
}
export interface Marker { acc: string; t: number; kind: string }
export interface Ev { t: number; type: string; from: string | null; to: string | null; reason: string; text: string; accs: string[] }
export interface Rotation {
  ok: boolean;
  reason?: string;
  detail?: string;
  generated_at: number;
  window: { start: number; end: number; hours: number };
  accounts: Acct[];
  segments: Seg0[];
  markers: Marker[];
  events: Ev[];
  log: { t: number; text: string }[];
  /**
   * 每号 × 每天的在岗时长（用户 2026-09-21 选的口径：「优先级到底生效没」）。
   * ★★ 格子**三态**，绝不合并：对象=这天用了它 · `null`=这天没选中它（确实是 0）
   *    · `"unknown"`=这天我们没读到（在 `covers_from` 之前）。
   */
  daily: {
    days: string[];
    rows: { acc: string; rank: number | null; rotate_off: boolean;
            cells: ({ secs: number; requests: number; tokens: number } | null | "unknown")[] }[];
    /** 每天走**中转站**的 POST 数 —— 不进账号池，所以泳道里看不到。 */
    relay: number[];
  };
  kpi: {
    tokens: number; requests: number; avg_tokens: number;
    rotations: number; avg_dwell: number; cool_429: number; stream_err: number;
    pro_segs: number; pro_secs: number;
  };
  coverage: {
    responses_seen: number; responses_with_tokens: number; responses_unplaced: number;
    attributed_pct: number | null; undated_lines: number; in_window_lines: number;
    /** ★ 三态，不是一个 bool：见 `windowNote()` 与 `rotation.py::_tail_covering`。 */
    tail_truncated: boolean; window_covered: boolean; tail_bytes: number;
    covers_from: number | null;
    log_begins_at: number | null; log_begins_reason: "ok" | "undated_head" | "unreadable";
  };
}

/**
 * 服务日志的一行。`t` 为 `null` = **这一行没有可用的时间**，不是"时间是 0"。
 * `inferred` = 时间是**推出来的**，不是日志里写着的（见 `parseServiceLogs`）。
 */
export interface SvcLine { src: string; t: number | null; inferred: boolean; text: string }
