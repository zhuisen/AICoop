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
export interface EntryLite { id: string; ok?: boolean; state?: string; stale?: boolean; stale_since?: number; detail?: string; data?: UsageLite }

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

/**
 * 一组账户合起来的「近 7 个活跃日日均实扣」（全方面评审 §4 存疑：原来把各账户自己的日均直接相加 ——
 * 各账户的活跃日不重合时，合起来的日均被高估，「还能撑」被算短）。
 * 先按日期把各账户的实扣、请求数加起来，再按 `monitor.runway` 同一条规则取：有请求的日子、最近 7 个、少于 2 个 ⇒ null。
 * ★ 不拿一部分冒充全组（阶段 C 评审）。下面任一条 ⇒ null：
 *   · 某账户没有数据 / 没有日序列 / 没有 `covered`（旧快照）；
 *   · 选中的某一天不在**每个**账户的 `covered` 里（那天没看过它 ≠ 它那天花了 0）；
 *   · 选中的某一天某账户有请求却没有实扣数。
 */
export function groupPerActiveDay(accts: readonly (Pick<UsageLite, "daily" | "covered"> | null | undefined)[]): number | null {
  if (!accts.length || accts.some((a) => !a || !a.daily || !a.covered?.length)) return null;
  const by = new Map<string, { c: number; r: number; bad: boolean }>();
  for (const a of accts) {
    for (const d of a!.daily) {
      const x = by.get(d.date) ?? { c: 0, r: 0, bad: false };
      if (typeof d.actual_cost === "number") x.c += d.actual_cost;
      else if ((d.requests || 0) > 0) x.bad = true;
      x.r += d.requests || 0;
      by.set(d.date, x);
    }
  }
  const act = [...by.entries()].filter(([, x]) => x.r > 0).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)).slice(-7);
  if (act.length < 2) return null;
  const seen = (cov: readonly (readonly [string, string])[], day: string) => cov.some((c) => Array.isArray(c) && c[0] <= day && day <= c[1]);
  if (act.some(([day, x]) => x.bad || accts.some((a) => !seen(a!.covered!, day)))) return null;
  return act.reduce((n, [, x]) => n + x.c, 0) / act.length;
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
  // ★ 按 token 降序（用户 2026-10-25「都要这样排序」），原来按实付金额。
  return [...acc.values()].sort((a, b) => b.total_tokens - a.total_tokens);
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
  | { kind: "error"; acc: string; why: string | null }
  | { kind: "stale"; since: number | null };

/**
 * 明细横幅（P8-2.4）。优先级：出口账户余额为 0 > 任一账户余额为 0 > 余额读不到 > 从未取到（首次就失败）> 取数失败（旧快照）。
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
  // ★ 第一次就没取到：没有旧数据 ⇒ 也不会有 `stale`，原来横幅与账户行都一句原因都不说（全方面评审 §4）
  const never = rows.find((r) => { const e = byId(r.id); return r.enabled && e?.ok === false && !e.data && e.state !== "disabled"; });
  if (never) return { kind: "error", acc: never.label, why: byId(never.id)?.detail ?? null };
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

export interface Delta { up: boolean; txt: string }
/** 中转站用量块的环比（`RelayUsage` 的 `delta`）：本窗口 `labels`（升序日期）vs 紧邻的上一个等长窗口（`n` 天）。
 *  **样本不够就给 null（界面写「—」），不给一个假的 0%。** */
export function ringRatio(rows: readonly { state?: string; data?: Pick<UsageLite, "daily" | "covered"> | null }[],
                          labels: readonly string[], n: number): { tok: Delta | null; cost: Delta | null } | null {
  if (!labels.length) return null;
  const all = new Set<string>();
  for (const r of rows) for (const d of r.data?.daily ?? []) all.add(d.date);
  // ★★★ **上一窗口必须等长且与当前窗口零交集**（2026-09-10 修）。
  //
  //   原来是 `sorted.slice(Math.max(0, len - 2n), len - n)` + 只判 `size === 0`。
  //   两个洞：`len - n` 为负时 JS `slice` 把负数 end 当**从尾部倒数** ⇒ 取到的
  //   "上一窗口"落在当前窗口**内部**（拿总量和自己的子集比）；以及没有等长校验 ⇒
  //   1 天可以冒充 7 天的上期。实测本机真快照：7d 档显示「环比 ↑148757.6%」，
  //   14d 档「↑87.7%」，而注释一直承诺"样本不够就说 —"。
  //   参考实现 `TrafficPage.tsx` / `PlatformPage.tsx` 都有 `win.length === n` 守卫，
  //   这一页抄了口径没抄守卫。
  //
  //   现在按**自然日**回退一个等长窗口，并要求它与当前窗口不相交。
  const endPrev = new Date(labels[0] + "T00:00:00Z").getTime() - 86400000;
  const prev = new Set<string>();
  for (let k = 0; k < n; k++) {
    prev.add(new Date(endPrev - k * 86400000).toISOString().slice(0, 10));
  }
  // ★ 只有当上一窗口**真的有观测**时才比 —— 否则那是"我们还没看过"，不是"降到 0"。
  const cur = new Set(labels);
  if ([...prev].some((d) => cur.has(d))) return null;      // 与当前窗口重叠 ⇒ 不比
  // ★★ 上一窗口必须**整段落在观测范围内**。
  //    补零之后"某天没有行"有两种含义：**观测过、当天为 0**，与**根本没观测过**。
  //    前者可以入分母，后者不行 —— 拿没观测过的日子当 0 去比，得到的涨幅是凭空的。
  //    只挡"整段早于观测"不够：部分重叠时（本机夹具 14d 档实测 6/14 天有观测）
  //    仍会算出 ↑522.2%。判据是 `prev` 的**最早一天** ≥ 我们最早的观测。
  const sorted = [...all].sort();
  const prevDays = [...prev].sort();
  const prevFirst = prevDays[0];
  if (!sorted.length || prevFirst < sorted[0]) return null;
  // ★ 上一窗口里**每一家**都要有一段 `covered`（取数确实看过的区间）把它整段盖住（全方面评审 §4 存疑）：
  //   只比「最早观测」挡不住中间的空洞 —— app 停了几天、那几天从没取过，补零后会被当成 0 去比。
  //   旧快照没有 `covered` ⇒ 没证据 ⇒ 不比（同 `relayView.monthSum`）。
  // ★ 参与者 = 没停用的账户（`state: "disabled"` 由 `monitor.collect` 写出；阶段 C 评审：原来用「有 data」—— 首次就没取到的启用账户被漏掉，停用账户的旧数据反而参与阻断）。
  //   启用账户没有数据 ⇒ 不知道 ⇒ 不比。覆盖要从上一窗口第一天一直连到当前窗口最后一天（当前窗口的空洞同样会让环比失真）。
  const live = rows.filter((r) => r.state !== "disabled");
  const curLast = labels[labels.length - 1];
  const covers = (c: readonly (readonly [string, string])[] | null | undefined) =>
    (c ?? []).some((x) => Array.isArray(x) && x[0] <= prevFirst && x[1] >= curLast);
  if (!live.length || !live.every((r) => r.data && covers(r.data.covered))) return null;
  // ★ 两期用同一组参与者（阶段 D 评审 codex：上期遍历全部 `rows`、本期取 `view.grandTok`，停用账户的旧数据
  //   只进一边 ⇒ 实测 ↑100.0% 变成 ↓97.9%）。
  let ptok = 0, pcost = 0, ctok = 0, ccost = 0;
  for (const r of live) {
    for (const d of r.data?.daily ?? []) {
      if (prev.has(d.date)) { ptok += d.total_tokens || 0; pcost += d.actual_cost || 0; }
      else if (cur.has(d.date)) { ctok += d.total_tokens || 0; ccost += d.actual_cost || 0; }
    }
  }
  const mk = (now: number, before: number): Delta | null => {
    if (!before) return null;
    const pct = ((now - before) / before) * 100;
    return { up: pct >= 0, txt: `${pct >= 0 ? "↑" : "↓"}${Math.abs(pct).toFixed(1)}%` };
  };
  return { tok: mk(ctok, ptok), cost: mk(ccost, pcost) };
}
