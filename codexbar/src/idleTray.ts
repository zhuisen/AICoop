/**
 * 空闲托盘「选谁上菜单栏」（AICoop 交接包 2026-10-21 · `11_idle/P11_Spec` §2，`P11_Final` ①）。
 *
 * ★ 零 import：测试用 `node --experimental-strip-types` 直接加载（CI 没有 node_modules，见 CLAUDE.md §4）。
 *
 * 规则（逐条照稿）：
 *   · 位数：默认 3 家 = 常驻 2 + 动态 1；可改 2 家（只有常驻）。
 *   · 常驻 2 家：手动固定的优先（最多 2 家）；没固定的位置按统计窗口内请求数（或 Token 数）降序补。
 *   · 第 3 家：常驻以外、排名最高的那家（统计窗口内用过才算；没有就空着，不凑数）。
 *     ★ 用户 2026-10-22 取代稿里的「24 小时内最近用过」：「grok 近 14 天没有 Gemini 高，所以排序不对」——
 *       三家都按统计窗口内的排名（默认 14 天 Token 数）。
 *   · 插队：统计窗口内用过、剩余 < 10% 的平台抢占动态位并带红点；不动常驻；多家取排名最高的。
 *   · 顺序：常驻按排名降序，动态位永远在最右。
 *   · 稳定：排名每天 00:00 重算一次，且只在空闲、鼠标不在托盘上时生效（`shouldRerank`）。
 *   · 一家的数：多个窗口取剩余最少的那个；未接入额度或任一窗口读不到 ⇒ 整只灰色剪影（`remaining = null`）。
 *   · 告警：剩余 < 10% 时右上角红点（判「显示的整数」，与 `LOW_PCT` 同口径）。
 */

export type RankBy = "requests" | "tokens";
export type SlotKind = "resident" | "dynamic" | "insert";

export interface IdlePlatform {
  key: string;
  /** 各额度窗口的剩余百分比（0–100）。空数组 = 未接入额度；某个窗口读不到写 null ⇒ 这一家未知。 */
  remaining: (number | null)[];
  /** 统计窗口内的请求数 / Token 数。 */
  requests: number;
  tokens: number;
  /** 最近一次请求的时刻（epoch ms）；没用过 = null。 */
  lastUsedAt: number | null;
}

export interface IdleSlot {
  key: string;
  kind: SlotKind;
  /** 剩余（0–100，取最紧的窗口）；null = 未接入额度 ⇒ 整只灰色剪影。 */
  remaining: number | null;
  red: boolean;
  pinned: boolean;
}

export interface IdleOptions {
  slots: 2 | 3;
  rankBy: RankBy;
  /** 手动固定（最多 2 家，多出的忽略）。 */
  pinned: string[];
  now: number;
  /** 今天冻结的常驻顺序（`shouldRerank` 说不换时传上一次的常驻）。仍有效的照旧，顺序不变。 */
  keep?: string[];
}

export const LOW_PCT = 10;

/**
 * 多个窗口取剩余最少的那个。没有窗口，或**任一**窗口读不到 ⇒ null（不是 100，也不是 0）：
 * 读不到的那个可能正是最紧的（同 `agy.ts::agyTightest`）。所以调用方只放「存在的窗口」，存在但读不到的写 null。
 */
export function tightest(remaining: (number | null)[]): number | null {
  if (!remaining.length || remaining.some((x) => typeof x !== "number" || !Number.isFinite(x))) return null;
  return Math.max(0, Math.min(100, Math.min(...(remaining as number[]))));
}

/** 红点：按显示的整数判（剩 9.6% 显示 10 就不红），与菜单栏 / 刘海 / 总览同口径。 */
export function isLow(rem: number | null): boolean {
  return rem !== null && Math.round(rem) < LOW_PCT;
}

/** 统计窗口内「用过」= 有请求或有 token。 */
const used = (p: IdlePlatform): boolean => p.requests > 0 || p.tokens > 0;

/** 排名：按所选依据降序；并列时另一项降序；再并列按 key 字母序（稳定、可复现）。 */
export function rank<T extends IdlePlatform>(ps: T[], by: RankBy): T[] {
  const a = (p: IdlePlatform) => (by === "requests" ? p.requests : p.tokens);
  const b = (p: IdlePlatform) => (by === "requests" ? p.tokens : p.requests);
  return ps.filter(used).sort((x, y) => a(y) - a(x) || b(y) - b(x) || (x.key < y.key ? -1 : x.key > y.key ? 1 : 0));
}

export function pickIdleSlots(ps: IdlePlatform[], o: IdleOptions): IdleSlot[] {
  const ranked = rank(ps, o.rankBy);
  const byKey = new Map(ps.map((p) => [p.key, p]));
  const order = new Map(ranked.map((p, i) => [p.key, i]));
  const pos = (k: string) => order.get(k) ?? Number.MAX_SAFE_INTEGER;

  const pinned = o.pinned.filter((k, i, a) => byKey.has(k) && a.indexOf(k) === i).slice(0, 2);
  const resident = [...pinned];
  const kept = (o.keep ?? []).filter((k) => byKey.has(k) && order.has(k));
  for (const k of [...kept, ...ranked.map((p) => p.key)]) {
    if (resident.length >= 2) break;
    if (!resident.includes(k)) resident.push(k);
  }
  // 常驻按排名降序（固定的没用过 ⇒ 排在最后，仍保留）；今天已冻结的按冻结时的顺序（不在白天换位）。
  const kpos = (k: string) => { const i = kept.indexOf(k); return i < 0 ? Number.MAX_SAFE_INTEGER : i; };
  resident.sort((x, y) => (kept.length ? kpos(x) - kpos(y) : 0) || pos(x) - pos(y));

  const mk = (k: string, kind: SlotKind): IdleSlot => {
    const rem = tightest(byKey.get(k)?.remaining ?? []);
    return { key: k, kind, remaining: rem, red: isLow(rem), pinned: pinned.includes(k) };
  };
  const out = resident.map((k) => mk(k, "resident"));
  if (o.slots === 2) return out;

  const rest = ranked.filter((p) => !resident.includes(p.key));
  const insert = rest.find((p) => isLow(tightest(p.remaining)));
  if (insert) return [...out, mk(insert.key, "insert")];
  return rest.length ? [...out, mk(rest[0].key, "dynamic")] : out;
}

/** 托盘认得的六家（顺序 = Rust `tray_idle::KEYS`）。别的平台没有托盘 logo，不参与。 */
export const TRAY_KEYS = ["codex", "claude", "agy", "grok", "kimi", "deepseek"] as const;

interface UsageBucket { total: number; rounds: number }
interface UsagePlatform { days: Record<string, UsageBucket>; hours: Record<string, UsageBucket> }

/**
 * 用量快照（`traffic/scan.py`）→ 统计窗口内的请求数 / Token 数 + 最近一次使用。
 * 请求数 = 轮次 `rounds`；最近一次 = 最后一个有 token 的小时桶的**末尾**（不晚于 now）。
 * ★ 小时桶只存近 30 天（`HOURLY_DAYS`）：更早用过的只算进请求数，`lastUsedAt` 为 null ——
 *   动态位只看 24 h 内，不受影响。
 */
export function usageOf(p: UsagePlatform | undefined, days: number, now: number): Pick<IdlePlatform, "requests" | "tokens" | "lastUsedAt"> {
  if (!p) return { requests: 0, tokens: 0, lastUsedAt: null };
  const from = dayKey(now - (days - 1) * 24 * 3600 * 1000);
  const to = dayKey(now);
  let requests = 0, tokens = 0;
  for (const [d, b] of Object.entries(p.days ?? {})) {
    if (d < from || d > to) continue;
    requests += b.rounds || 0;
    tokens += b.total || 0;
  }
  let last: string | null = null;
  for (const [h, b] of Object.entries(p.hours ?? {})) if ((b.total || 0) > 0 && (last === null || h > last)) last = h;
  let lastUsedAt: number | null = null;
  if (last) {
    const [d, hh] = last.split("T");
    const [y, m, dd] = d.split("-").map(Number);
    const end = new Date(y, m - 1, dd, Number(hh) + 1).getTime();
    lastUsedAt = Number.isFinite(end) ? Math.min(end, now) : null;
  }
  return { requests, tokens, lastUsedAt };
}

/** 发给 Rust `set_idle_tray` 的那份（只带画图要的三样）。 */
export function trayPayload(slots: IdleSlot[]): { key: string; remaining: number | null; red: boolean }[] {
  return slots.map((s) => ({ key: s.key, remaining: s.remaining, red: s.red }));
}

// ---------------------------------------------------------------- 悬停面板（P11 §6 · 格子 · 精简）

/** 面板一格要的数：大数字 = 5h 剩余（只有周窗口的 grok 用周）；`reset` = 右上角小字（按量计费不写 = ""）。 */
export interface PanelIn extends IdlePlatform {
  main: number | null;
  reset: string;
  stale?: boolean;
}

export type PanelScope = "used" | "all" | "bar";

export interface PanelOptions {
  scope: PanelScope;
  max: 4 | 8;
  /** 「悬停细节 · 未接入的平台」：默认不显示。 */
  showUnconnected: boolean;
  rankBy: RankBy;
}

export interface PanelCell {
  key: string;
  /** 0–100；null = 读不到（大数字写 —，环只留底轨）。 */
  main: number | null;
  reset: string;
  inBar: boolean;
  low: boolean;
  /** 这一次没读到、显示的是上一次读到的数（数字降一级灰，不冒充现值）。 */
  stale: boolean;
}

/** 菜单栏 → 悬停面板 webview：面板格子（`IdlePanelData`）。面板挂载时发 `IDLE_PANEL_WANT` 要一份。
 *  放在这个零 import 的模块里：悬停面板只要这两个名字，不该为此把设置页整套模块拉进它的包。 */
export const IDLE_PANEL_EVENT = "idle-panel";
export const IDLE_PANEL_WANT = "idle-panel-want";
export interface IdlePanelData { cells: PanelCell[]; max: 4 | 8 }

/**
 * 面板显示哪几家、什么顺序（P11 §6「显示几家」，P9 S1「悬停显示哪些」）：
 *   · 菜单栏里的那几家排最前（顺序同托盘），其余按排名接在后面；
 *   · 用过的（默认）= 统计窗口内用过；只看菜单栏 = 只有托盘那几家；全部 = 托盘认得的全部；
 *   · 未接入额度的默认不显示（托盘里的那几家照样显示 —— 它们已经在菜单栏上了）；
 *   · 最多 4 家（一行）/ 8 家（两行）。
 */
export function panelCells(ps: PanelIn[], slots: IdleSlot[], o: PanelOptions): PanelCell[] {
  const bar = slots.map((s) => s.key);
  const byKey = new Map(ps.map((p) => [p.key, p]));
  const restRanked = rank(ps, o.rankBy).filter((p) => !bar.includes(p.key));
  const unused = ps.filter((p) => !bar.includes(p.key) && !used(p)).sort((x, y) => (x.key < y.key ? -1 : 1));
  const rest = o.scope === "bar" ? [] : o.scope === "used" ? restRanked : [...restRanked, ...unused];
  const connected = (p: PanelIn) => p.main !== null || tightest(p.remaining) !== null;
  const order = [
    ...bar.map((k) => byKey.get(k)).filter((p): p is PanelIn => !!p),
    ...rest.filter((p) => o.showUnconnected || connected(p)),
  ];
  return order.slice(0, o.max).map((p) => {
    const main = p.main === null ? null : Math.max(0, Math.min(100, p.main));
    return { key: p.key, main, reset: p.reset, inBar: bar.includes(p.key), low: isLow(main), stale: main !== null && !!p.stale };
  });
}

/** 本地日期键 `YYYY-MM-DD`（排名按本机时区每天 00:00 重算）。 */
export function dayKey(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** 该不该换上新排名：跨了一天，且空闲、鼠标不在托盘上（P11 §2「顺序与稳定」）。首次（没有旧排名）总是要。 */
export function shouldRerank(prevDay: string | null, now: number, idle: boolean, mouseOnTray: boolean): boolean {
  if (prevDay === null) return true;
  return prevDay !== dayKey(now) && idle && !mouseOnTray;
}
