// 菜单栏弹窗（交接包 2026-10-19 page4 · 4f）的纯逻辑。★ 零 import —— 测试用
// `node --experimental-strip-types` 直接跑（CI 没有 node_modules，见 CLAUDE.md §4）。
//
// 这里只放「判据」：低额度、排序、通知合并、按住探针的状态机、Claude 额度解析。
// 怎么画在组件里；判据只有这一份，组件与测试共用。

// ── 低额度 ───────────────────────────────────────────────────────────────

/** 交接包 4f：「任一窗口 < 10%：整行淡橙红底、号名和该条变橙红」。严格小于。 */
export const LOW_PCT = 10;

/**
 * ★ 判的是**显示出来的整数**（与刘海 `notchSegs.ts::segColor` 同一条纪律）：剩 9.6% 时行上写
 * 「10%」，那它就不能是红的；剩 9.4% 写「9%」就必须红。判原值会让数字和颜色互相矛盾。
 */
export function isLow(pct: number | null | undefined): boolean {
  return typeof pct === "number" && Number.isFinite(pct) && Math.round(pct) < LOW_PCT;
}

/** 一行里最紧的那个窗口（读不到的窗口不参与；全读不到 ⇒ null，不是 0）。 */
export function tightestOf(pcts: readonly (number | null | undefined)[]): number | null {
  let m: number | null = null;
  for (const p of pcts) {
    if (typeof p !== "number" || !Number.isFinite(p)) continue;
    if (m == null || p < m) m = p;
  }
  return m;
}

// ── 排序 ─────────────────────────────────────────────────────────────────

export interface SortKey {
  /** 最紧窗口的剩余 %；null = 读不到（未探测）。 */
  tight: number | null;
  inUse: boolean;
  next: boolean;
}

/**
 * 「按可用排序」（交接包 4f 账号块表头）。顺序：
 *   ① 有窗口 < 10% 的号 —— 最紧的排最前（Gemini 低额度画板的「最紧的排最前」）；
 *   ② 在用；③ 下一个；④ 其余按最紧窗口降序；⑤ 读不到的排最后。
 * 同档内保持原顺序（稳定），切号时行不会无故跳。
 */
export function sortByAvailability<T extends SortKey>(rows: readonly T[]): T[] {
  const rank = (r: T): number => {
    if (isLow(r.tight)) return 0;
    if (r.inUse) return 1;
    if (r.next) return 2;
    if (r.tight == null) return 4;
    return 3;
  };
  return rows
    .map((r, i) => ({ r, i, k: rank(r) }))
    .sort((a, b) => {
      if (a.k !== b.k) return a.k - b.k;
      if (a.k === 0 || a.k === 3) {
        const d = a.k === 0 ? (a.r.tight as number) - (b.r.tight as number)
                            : (b.r.tight as number) - (a.r.tight as number);
        if (d !== 0) return d;
      }
      return a.i - b.i;
    })
    .map((x) => x.r);
}

/** 账号块表头左半。有低额度的号时排序规则变了，表头必须跟着说。 */
export function blockTitle(rows: readonly SortKey[]): string {
  return rows.some((r) => isLow(r.tight)) ? "账号 · 最紧的排最前" : "账号 · 按可用排序";
}

// ── 通知条 ───────────────────────────────────────────────────────────────

export type NoticeTone = "bad" | "warn";

export interface Notice {
  /** 稳定身份（React key + 「关掉这一条」的记忆键）。 */
  id: string;
  tone: NoticeTone;
  /** 同色调内越小越紧急。 */
  urgency: number;
  text: string;
  /** 可关（只有重置卡那一条：它会自己过期，连挂三天关不掉是噪音）。 */
  dismissible?: boolean;
}

/**
 * 多条告警合并成一条（交接包 4f「通知条」）：只显示最紧急一条 +「还有 N 条」。
 * 紧急度：红（池见底 / 低额度）> 琥珀（重置卡作废 / 订阅到期）；同色按 `urgency` 升序，再按 id。
 */
export function mergeNotices(list: readonly Notice[]): { head: Notice | null; rest: Notice[] } {
  const toneRank = (t: NoticeTone): number => (t === "bad" ? 0 : 1);
  const sorted = [...list].sort((a, b) =>
    toneRank(a.tone) - toneRank(b.tone) || a.urgency - b.urgency || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return { head: sorted[0] ?? null, rest: sorted.slice(1) };
}

/** 「号C 5h 只剩 8% · 0h54m 后回满」。回满时间读不到就不说「后回满」。 */
export function lowNotice(id: string, name: string, win: string, pct: number, refill: string | null): Notice {
  // ★ 只有真的是一段时长（含数字）才说「后回满」；「未启动 / 待确认 / —」拼上去是一句病句。
  const tail = refill && /\d/.test(refill) ? ` · ${refill} 后回满` : "";
  return { id: `low:${id}:${win}`, tone: "bad", urgency: pct, text: `${name} ${win} 只剩 ${Math.round(pct)}%${tail}` };
}

/** 整池都没号可用（每个读得到的号都 < 10%，且至少读到一个）。 */
export function poolDry(rows: readonly SortKey[]): boolean {
  const known = rows.filter((r) => r.tight != null);
  return known.length > 0 && known.every((r) => isLow(r.tight));
}

export function poolDryNotice(platform: string): Notice {
  return { id: `dry:${platform}`, tone: "bad", urgency: -1, text: `${platform} 池见底 · 所有号都不到 ${LOW_PCT}%` };
}

/** 订阅到期提醒的窗口（天）。交接包示例「号D 订阅 7 天后到期」。 */
export const SUB_WARN_DAYS = 7;

/** `YYYY-MM-DD` 到期日 → 还剩几天（向下取整）。读不到 ⇒ null。 */
export function daysUntil(isoDate: string, nowMs: number): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) return null;
  const [y, m, d] = isoDate.split("-").map(Number);
  const end = new Date(y, m - 1, d).getTime();
  if (!Number.isFinite(end)) return null;
  return Math.floor((end - nowMs) / 86_400_000);
}

export function subNotice(id: string, name: string, days: number, date: string): Notice {
  const when = days <= 0 ? "今天" : `${days} 天后`;
  return { id: `sub:${id}`, tone: "warn", urgency: days + 0.5, text: `${name} 订阅 ${when}到期（${date}）` };
}

// ── 按住探针（计费，按住 0.6 s 才执行） ─────────────────────────────────────

export const HOLD_MS = 600;
/** 中途松手：进度 150 ms 退回、不执行。 */
export const RETREAT_MS = 150;

export type HoldState =
  | { phase: "idle" }
  | { phase: "holding"; since: number }
  | { phase: "retreat"; since: number }
  | { phase: "fired"; at: number };

export type HoldEvent =
  | { type: "down"; now: number; disabled?: boolean }
  | { type: "up"; now: number }
  | { type: "leave"; now: number }
  | { type: "tick"; now: number }
  | { type: "reset" };

export const HOLD_IDLE: HoldState = { phase: "idle" };

/**
 * 状态机。不变量（有行为闸）：
 *  · 按住不满 `HOLD_MS` 就松手 / 移出 ⇒ 永远不会进 `fired`；
 *  · 一次按住最多 `fired` 一次（`fired` 之后再 tick 不会再 fired，必须 `reset` 回 idle）；
 *  · `disabled`（正在探测）时按下无效。
 */
export function holdReduce(s: HoldState, e: HoldEvent): HoldState {
  switch (e.type) {
    case "reset":
      return HOLD_IDLE;
    case "down":
      if (e.disabled) return s;
      if (s.phase === "idle" || s.phase === "retreat") return { phase: "holding", since: e.now };
      return s;
    case "up":
    case "leave":
      if (s.phase !== "holding") return s;
      if (e.now - s.since >= HOLD_MS) return { phase: "fired", at: e.now };
      return { phase: "retreat", since: e.now };
    case "tick":
      if (s.phase === "holding" && e.now - s.since >= HOLD_MS) return { phase: "fired", at: e.now };
      if (s.phase === "retreat" && e.now - s.since >= RETREAT_MS) return HOLD_IDLE;
      return s;
  }
}

/** 琥珀填充的目标宽度（%）与过渡 —— 照抄 P4PopRows `holdW/holdT`。 */
export function holdFill(s: HoldState): { width: number; transition: string } {
  return s.phase === "holding"
    ? { width: 100, transition: `width ${HOLD_MS}ms linear` }
    : { width: 0, transition: `width ${RETREAT_MS}ms ease-out` };
}

// ── Claude 额度（`read_statusline_quota`，契约 PLAN §2.2） ──────────────────

export interface ClaudeWin {
  /** 剩余 % = 100 − used_pct。 */
  rem: number;
  /** 回满时刻（epoch 秒）；null = 来源不给（plan-usage-history 没有重置时间）。 */
  resetsAt: number | null;
  /** 窗口未启动：旧窗口已过重置点，**且**之后的状态栏读数没有再报这个窗口 ⇒ 100%，↻ 写「未启动」。 */
  idle?: boolean;
}

export interface ClaudeQuota {
  source: "statusline" | "plan-usage-history" | "none";
  capturedAt: number | null;
  fiveH: ClaudeWin | null;
  week: ClaudeWin | null;
}

const toSec = (v: unknown): number | null => {
  if (typeof v !== "number" || !Number.isFinite(v) || v <= 0) return null;
  return v > 1e12 ? Math.floor(v / 1000) : v;
};

function claudeWin(w: unknown, capturedAt: number | null): ClaudeWin | null {
  if (!w || typeof w !== "object") return null;
  const o = w as Record<string, unknown>;
  const used = o.used_pct;
  if (typeof used !== "number" || !Number.isFinite(used)) return null;
  // ★ 窗口已过重置时刻：那个「已用」属于旧窗口，不能当现值（statusline_quota 标了 `expired`）。
  //   重置点之后又有一份状态栏读数（`capturedAt` 晚于重置点）却没再报这个窗口 ⇒ Claude Code 自己说
  //   「没有在走的窗口」，即未启动、剩 100%（实测 2026-10-19：重置后 Claude Code 不带 five_hour，
  //   下一次请求后才带回 `used 0`）。重置后没有任何新读数 ⇒ 证不了，仍是「读不到」（同 codex
  //   `test_expired_reset_without_a_fresh_reading_is_not_zero` 那条）。
  if (o.expired === true) {
    const rs = toSec(o.resets_at);
    return rs != null && capturedAt != null && capturedAt > rs ? { rem: 100, resetsAt: null, idle: true } : null;
  }
  return { rem: Math.max(0, Math.min(100, 100 - used)), resetsAt: toSec(o.resets_at) };
}

/** 读不到 / 形状不对 ⇒ null（「读不到」，界面写 —，绝不当 0）。 */
export function parseClaudeQuota(raw: unknown): ClaudeQuota | null {
  let o: unknown = raw;
  if (typeof raw === "string") {
    try { o = JSON.parse(raw); } catch (_e: unknown) { return null; }
  }
  if (!o || typeof o !== "object") return null;
  const c = (o as Record<string, unknown>).claude;
  if (!c || typeof c !== "object") return null;
  const r = c as Record<string, unknown>;
  const src = r.source === "statusline" || r.source === "plan-usage-history" ? r.source : "none";
  const cap = toSec(r.captured_at);
  return {
    source: src,
    capturedAt: cap,
    fiveH: claudeWin(r.five_hour, cap),
    week: claudeWin(r.seven_day, cap),
  };
}

/** 读数陈旧阈值（秒）。与 `helpers.ts::QUOTA_STALE_SEC` 同值（30 分钟）。 */
export const STALE_SEC = 30 * 60;

export function isStale(capturedAt: number | null, nowSec: number): boolean {
  return capturedAt != null && nowSec - capturedAt > STALE_SEC;
}

// ── 版式 ─────────────────────────────────────────────────────────────────

/**
 * 号名列宽。交接包写死 46（示意数据全是「号A」两个字）；真实号名可能是 `tomyhuohuo`，
 * 46 会把它截成「tom…」。按同一块里最长的名字估宽（CJK 13.5 / 其余 8，13.5px 字），
 * 下限 46（= 设计值）、上限 84（再宽两根条就短到读不出），超出省略号。整块共用一个宽度，列才对得齐。
 */
export function nameColWidth(names: readonly string[]): number {
  let w = 0;
  for (const n of names) {
    let x = 0;
    for (const ch of n) x += /[　-鿿＀-￯]/.test(ch) ? 13.5 : 8;
    if (x > w) w = x;
  }
  return Math.max(46, Math.min(84, Math.ceil(w)));
}

/**
 * 临界阻尼弹簧的 CSS `linear()` 近似（交接包 README「动效曲线」，代码原样）。
 * response 0.36 s、0.55 s 内落定；n = 30 个采样点。
 */
export function critSpring(resp = 0.36, T = 0.55, n = 30): string {
  const w = (2 * Math.PI) / resp;
  const pts: string[] = [];
  for (let i = 0; i <= n; i++) {
    pts.push((i === n ? 1 : 1 - (1 + (w * T * i) / n) * Math.exp((-w * T * i) / n)).toFixed(3));
  }
  return `linear(${pts.join(", ")})`;
}
