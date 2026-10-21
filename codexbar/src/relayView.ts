/**
 * 中转站页（AICoop P8，阶段 5）的纯判断。★ 零 import —— 测试用 `node --experimental-strip-types` 直接加载。
 * 规格摘录：`scratch/aicoop_20261021/P7P8_extract.md` P8-*。偏离：PLAN 第 42 条。
 *
 * ★ 只认结构（`RelayRowLite` / `EntryLite`），不 import `relay.ts` 的类型 —— 那是有意的：
 *   这里的每个函数都在 node 下逐个喂边界输入测，类型从外面来就不能保证零依赖。
 */

export interface RelayRowLite { id: string; label: string; base_url: string; enabled: boolean; group?: string | null }
export interface DayLite { date: string; actual_cost: number; cost: number; requests: number; total_tokens: number;
  models?: { model: string; requests: number; total_tokens: number; actual_cost: number; cost: number }[] | null }
export interface UsageLite {
  balance: number | null; unit: string | null;
  today: { cost: number | null; actual_cost: number | null; requests: number | null; total_tokens: number | null };
  runway: { days: number | null; per_active_day: number | null; reason: string | null };
  daily: DayLite[];
  /** 取数确实看过的日期区间（`monitor.merge_covered`，并集只增不减）。旧快照没有 ⇒ 当作没证据。 */
  covered?: [string, string][] | null;
}
export interface EntryLite { id: string; ok?: boolean; state?: string; stale?: boolean; stale_since?: number; data?: UsageLite }

export function hostOf(url: string): string {
  const m = /^[a-z]+:\/\/([^/:?#]+)/i.exec(url.trim());
  return m ? m[1].toLowerCase() : url;
}

export interface Group { key: string; name: string; host: string; ids: string[] }

/**
 * 平台分组（P8-6）：行上有 `group` 就按它，否则按 `base_url` 的 host。顺序 = 每组第一行在登记表里的顺序。
 * 组名：有 `group` 用它；否则组里只有一行用那一行的 label，多行用 host。
 */
export function groupRelays(rows: readonly RelayRowLite[]): Group[] {
  const out: Group[] = [];
  for (const r of rows) {
    const g = (r.group ?? "").trim();
    const key = g ? `g:${g}` : `h:${hostOf(r.base_url)}`;
    let x = out.find((o) => o.key === key);
    if (!x) { x = { key, name: g, host: hostOf(r.base_url), ids: [] }; out.push(x); }
    x.ids.push(r.id);
  }
  for (const x of out) {
    if (!x.name) x.name = x.ids.length === 1 ? (rows.find((r) => r.id === x.ids[0])?.label ?? x.host) : x.host;
  }
  return out;
}

/**
 * 同组合计。★ 任一读不到 ⇒ null（`mixed` 只看读到了的那几个的币种 —— 读不到的账户没有币种，
 * 不能因此报「多币种」）；读到的币种不一致（含「有的有币种、有的没有」）⇒ null + `mixed`。没有一个账户 ⇒ null。
 */
export function sumOf(vals: readonly (number | null | undefined)[], units: readonly (string | null | undefined)[]):
  { v: number | null; unit: string | null; mixed: boolean } {
  const known = vals.map((v, i) => ({ v, u: units[i] || "" })).filter((x) => x.v != null && Number.isFinite(x.v));
  const set = new Set(known.map((x) => x.u));
  if (set.size > 1) return { v: null, unit: null, mixed: true };
  const unit = [...set][0] || (units.find((u) => u) ?? null);
  if (!vals.length || known.length < vals.length) return { v: null, unit, mixed: false };
  return { v: known.reduce((a, x) => a + (x.v as number), 0), unit, mixed: false };
}

/** 还能撑几天：`runway.days` 向下取整（P8-8 缺陷 1：同一账户三处只用这一个来源）。余额为 0 ⇒ 0。读不到 ⇒ null。 */
export function runDays(balance: number | null | undefined, days: number | null | undefined): number | null {
  if (balance === 0) return 0;
  if (days == null || !Number.isFinite(days)) return null;
  return Math.max(0, Math.floor(days));
}

/** 「省 N×」= 牌价 ÷ 实扣；任一读不到或实扣为 0 ⇒ null（不写「省」）。 */
export function saveRatio(cost: number | null | undefined, actual: number | null | undefined): number | null {
  if (cost == null || actual == null || !(actual > 0) || !(cost > 0)) return null;
  return cost / actual;
}

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * 本月实扣 / 牌价（`daily` 求和）。
 * ★ 整月 = `covered`（取数确实看过的日期区间）里有一段从 1 号或更早连到今天。只看 `daily` 最早一天不够：
 *   一条旧月份记录 + 中间断档也会被当成整月（评审 codex 阶段 5）。证据不够 ⇒ `complete: false`，界面写「≥ $x」。
 * 本月一天都没有：看过整月 ⇒ 0（确实没花）；否则 v = null（读不到），**不是 0**。
 */
export function monthSum(daily: readonly DayLite[] | undefined, now: Date, field: "actual_cost" | "cost",
                         covered?: readonly (readonly [string, string])[] | null): { v: number | null; complete: boolean } {
  const first = ymd(new Date(now.getFullYear(), now.getMonth(), 1));
  const today = ymd(now);
  const complete = (covered ?? []).some((c) => Array.isArray(c) && c[0] <= first && c[1] >= today);
  const mine = (daily ?? []).filter((d) => d.date >= first && d.date <= today);
  if (!mine.length) return { v: complete ? 0 : null, complete };
  return { v: mine.reduce((s, d) => s + (d[field] ?? 0), 0), complete };
}

/** 今天那一天（本机日期）。没有 ⇒ null。 */
export function todayOf(daily: readonly DayLite[] | undefined, now: Date): DayLite | null {
  const k = ymd(now);
  return daily?.find((d) => d.date === k) ?? null;
}

/** 按模型合并（合计视角：同名模型相加）。任一账户今天的明细没取到（`models` 为 null）⇒ null。 */
export function mergeModels(days: readonly (DayLite | null)[]): DayLite["models"] {
  const acc = new Map<string, { model: string; requests: number; total_tokens: number; actual_cost: number; cost: number }>();
  for (const d of days) {
    if (!d) continue;
    if (d.models == null) return null;
    for (const m of d.models) {
      const x = acc.get(m.model) ?? { model: m.model, requests: 0, total_tokens: 0, actual_cost: 0, cost: 0 };
      x.requests += m.requests; x.total_tokens += m.total_tokens; x.actual_cost += m.actual_cost; x.cost += m.cost;
      acc.set(m.model, x);
    }
  }
  return [...acc.values()].sort((a, b) => b.actual_cost - a.actual_cost);
}

/**
 * 「今日按模型」（当前视角下这几个账户合在一起）。三态：明细 / 没取到（`unknown`）/ 多币种不可相加（`mixed`）。
 * ★ 有账户整个没数据、或今天那一天不在 `daily` 而今日请求数**不是确定的 0** ⇒ `unknown`（评审阶段 5：
 *   读不到的请求数原来按 0 算，得出「今天还没有请求」）。币种不同 ⇒ 金额不能相加 ⇒ `mixed`。
 */
export function todayModels(ds: readonly (UsageLite | null | undefined)[], now: Date):
  { rows: NonNullable<DayLite["models"]> | null; why: "unknown" | "mixed" | null } {
  if (!ds.length || ds.some((d) => !d)) return { rows: null, why: "unknown" };
  if (new Set(ds.map((d) => d!.unit || "")).size > 1) return { rows: null, why: "mixed" };
  const tdays = ds.map((d) => todayOf(d!.daily, now));
  if (tdays.some((x, i) => x == null && ds[i]!.today?.requests !== 0)) return { rows: null, why: "unknown" };
  const rows = mergeModels(tdays);
  return rows == null ? { rows: null, why: "unknown" } : { rows, why: null };
}

export type Banner =
  | { kind: "nobal"; acc: string }
  | { kind: "zero"; acc: string; isExit: boolean; alt: { id: string; label: string; balance: number; unit: string | null } | null }
  | { kind: "stale"; since: number | null };

/**
 * 明细横幅（P8-2.4）。优先级：出口账户余额为 0 > 任一账户余额为 0 > 余额读不到 > 取数失败（旧快照）。
 * 「见底」按钮先建议**同组余额最多的另一个启用账户**（余额 > 0），没有 ⇒ `alt: null`（界面兜底「切回账号池」）。
 */
export function bannerOf(rows: readonly RelayRowLite[], entries: readonly EntryLite[], exitId: string | null): Banner | null {
  const byId = (id: string) => entries.find((e) => e.id === id);
  const zeroes = rows.filter((r) => byId(r.id)?.data?.balance === 0);
  const z = zeroes.find((r) => r.id === exitId) ?? zeroes[0];
  if (z) {
    const isExit = z.id === exitId;
    // ★ 只比同币种的（USD 10 与 CNY 50 不能比大小，评审 codex 阶段 5）。
    const zu = byId(z.id)?.data?.unit ?? null;
    const alts = rows.filter((r) => r.id !== z.id && r.enabled)
      .map((r) => ({ r, d: byId(r.id)?.data }))
      .filter((x) => x.d && x.d.balance != null && x.d.balance > 0 && (x.d.unit ?? null) === zu)
      .sort((a, b) => (b.d!.balance as number) - (a.d!.balance as number));
    const a = alts[0];
    return { kind: "zero", acc: z.label, isExit,
             alt: a ? { id: a.r.id, label: a.r.label, balance: a.d!.balance as number, unit: a.d!.unit } : null };
  }
  const nb = rows.find((r) => { const e = byId(r.id); return e?.data && e.data.balance == null; });
  if (nb) return { kind: "nobal", acc: nb.label };
  const st = rows.map((r) => byId(r.id)).find((e) => e?.stale);
  if (st) return { kind: "stale", since: st.stale_since ?? null };
  return null;
}

/** 「N 分钟前 / N 小时前」。 */
export function agoText(ts: number | null | undefined, nowSec: number): string {
  if (ts == null) return "—";
  const m = Math.max(0, Math.floor((nowSec - ts) / 60));
  return m < 1 ? "刚刚" : m < 60 ? `${m} 分钟前` : m < 1440 ? `${Math.floor(m / 60)} 小时前` : `${Math.floor(m / 1440)} 天前`;
}

/** 千分位整数。 */
export function int(n: number | null | undefined): string {
  return n == null ? "—" : Math.round(n).toLocaleString("en-US");
}

/** token 简写（`23.5M` / `412k`）。 */
export function tok(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}k`;
  return String(Math.round(n));
}

/** 「3h20m」（分钟 → 时分）。null ⇒ 「—」。 */
export function hm(min: number | null | undefined): string {
  if (min == null || !Number.isFinite(min)) return "—";
  const m = Math.max(0, Math.round(min));
  return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m` : `${m}m`;
}

/** 入口悬停卡的悬停 / 收起计时（P8-2.3）：首次 180 ms 才出，已开着时直接滑过去；离开 80 ms 后收。纯状态迁移。 */
export function hoverDelay(open: boolean, leaving: boolean): number {
  if (leaving) return 80;
  return open ? 0 : 180;
}

/** 悬停卡的纵向位置：贴入口上沿 −8，最下面的入口卡不出底（236 − 104）。 */
export function hoverY(entryTop: number, mapH: number): number {
  return Math.min(entryTop - 8, mapH - 104);
}
