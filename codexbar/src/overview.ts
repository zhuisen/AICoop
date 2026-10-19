/**
 * 工作台 · 总览（交接包 2026-10-19 page5 · 5b 卡片版）的纯逻辑。
 *
 * ★ **零 import**（本仓「pure TS under node」）：`tests/test_overview_5b.py` 用
 *   `node --experimental-strip-types` 直接调这些函数做行为闸，CI 没有 node_modules。
 *   所以这里只放**结构化的最小形状**（`RelayInput` 等），不 import `Board` / `Account` ——
 *   调用方（`components/ov/*`）负责把真数据映射进来。
 */

// ── 版式（交接包 README §4「窗口变窄」） ──────────────────────────────────────

export type OvCols = 2 | 3 | 4;
export interface OvLayout {
  cols: OvCols;
  /** 顶部三栏的 `grid-template-columns`（原型 `heroCols`）。 */
  heroCols: string;
  /** ≥1200 档：三栏齐全（「今天的切换」是第三栏）；否则它收成三栏下方一行。 */
  wide: boolean;
  /** 头部按钮带文字（原型 `lblD`）；否则只留图标 + 开关。 */
  labels: boolean;
  /** 平台档带名称（原型 `tabNameD`）；860 档只留 logo + 数字。 */
  tabNames: boolean;
}

/**
 * 按**内容区宽度**（不是窗口宽度）分档。
 * ★ 原型的「1200 / 1000 / 860」是窗口宽、侧栏是 52 的折叠态：内容区 = 窗口 − 52 − 左右内边距 40
 *   ⇒ 1108 / 908 / 768。按内容区判，侧栏展开（176）时自动退一档 —— 同一个窗口宽，
 *   侧栏开着的卡片区本来就窄 124，照窗口宽分档会把 4 列硬塞进 984 里。
 */
export const OV_BP_WIDE = 1100;
export const OV_BP_MID = 900;

/** 宽度 → 它所在那一档的下沿。★ 存这个而不是原始宽度：拖窗口时 RO 每像素都报，
 *  存原始宽度会让整个总览每像素重渲染一次；档内宽度变化对版式没有任何影响。 */
export function ovBand(contentW: number): number {
  return contentW >= OV_BP_WIDE ? OV_BP_WIDE : contentW >= OV_BP_MID ? OV_BP_MID : 0;
}

export function ovLayout(contentW: number): OvLayout {
  if (contentW >= OV_BP_WIDE) {
    return { cols: 4, heroCols: "290px 1px minmax(0, 1fr) 1px 232px", wide: true, labels: true, tabNames: true };
  }
  if (contentW >= OV_BP_MID) {
    return { cols: 3, heroCols: "280px 1px minmax(0, 1fr)", wide: false, labels: false, tabNames: true };
  }
  return { cols: 2, heroCols: "250px 1px minmax(0, 1fr)", wide: false, labels: false, tabNames: false };
}

// ── 文本 ───────────────────────────────────────────────────────────────────

/** 分钟 → `3h20m` / `25m` / `<1m` / `1d2h`（原型「还能连续用」的数值格式）。 */
export function fmtDur(min: number): string {
  if (!Number.isFinite(min) || min < 0) return "—";
  if (min < 1) return "<1m";
  const m = Math.round(min);
  if (m < 60) return `${m}m`;
  if (m < 1440) return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m`;
  const d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
  return `${d}d${h}h`;
}

/** 时刻（epoch 毫秒）→ 本地 `HH:MM`。 */
export function fmtClock(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * `codex-rotate next --json` 的重置串（`2h05m` / `6d6h`）→ 分钟。空串 / 认不出 ⇒ `null`（不是 0：
 * 「不知道什么时候回满」与「马上回满」相反）。
 */
export function parseReset(s: string | null | undefined): number | null {
  if (!s) return null;
  const m1 = /^(\d+)h(\d+)m$/.exec(s.trim());
  if (m1) return Number(m1[1]) * 60 + Number(m1[2]);
  const m2 = /^(\d+)d(\d+)h$/.exec(s.trim());
  if (m2) return Number(m2[1]) * 1440 + Number(m2[2]) * 60;
  return null;
}

// ── 续航接力条（交接包 README「续航接力条（核心）」） ───────────────────────

/**
 * 接力里的一个号。所有时间都是「从现在起多少分钟」。
 *
 * ★ 口径与 `codex-rotate::_burst` 同一份（「在其上扩展，不另造」）：
 *   · `nowMin` = 此刻还能连续用的分钟 = min(5h 剩余能连续用的分钟, 周剩余能连续用的分钟)
 *     —— 正是 `_burst.now_min` 里每个号的那一项；
 *   · `fullMin` = 5h 回满后一整窗能连续用多少（`eta5h.per_window_min`）；
 *   · `weekMin` = 周剩余能连续用多少（`_burst::wk_min`；换算比值缺 ⇒ `null` = 不设上限）。
 * agy 没有连续使用的配速，调用方给的是「周剩余 ÷ 全池每小时消耗」的钟点分钟（旧续航条 agy 分支同一口径），
 * `fullMin = null`（不会回满再接）。
 */
export interface RelayInput {
  id: string;
  label: string;
  /** 此刻能被挑（在代理/选号器的队列里）。 */
  usable: boolean;
  /** 此刻还能连续用几分钟；`null` = 配速未知（Pro 没有 5h 窗口 / 没有用完历史）。 */
  nowMin: number | null;
  /** 不可用的号多久后回来（冷却结束 / 见底的 5h 回满）；`null` = 不会自己回来。 */
  backAtMin: number | null;
  /** 5h 窗口已经开始计时 ⇒ 它几分钟后回满；`null` = 没开始（满格浮动）或没有 5h 窗口。 */
  refillAtMin: number | null;
  /** 一整窗能连续用几分钟（回满之后的预算）；`null` = 不会「回满再接」。 */
  fullMin: number | null;
  /** 周剩余能连续用几分钟（上限）；`null` = 换算不出来，不设上限。 */
  weekMin: number | null;
}

export type RelaySegKind = "now" | "back" | "gap" | "open";
export interface RelaySeg {
  kind: RelaySegKind;
  start: number;
  /** `open` 段与「之后再没人回来」的断档：`end = Infinity`。 */
  end: number;
  id?: string;
  label?: string;
  /** 该号在接力里的序号（配色用，同一个号永远同一个颜色）。 */
  color?: number;
  /** 断档之后谁接上、为什么。 */
  resumeLabel?: string;
  resumeWhy?: "refill" | "cool";
}
export interface RelayPlan {
  segs: RelaySeg[];
  /** 断档前能连续用多少分钟；`null` = 一个能估的号都没有（画「—」，不画 0）。 */
  continuousMin: number | null;
  /** 有配速未知的号在接力里 ⇒ 实际只会更长，数值前写「≥」。 */
  atLeast: boolean;
  /** 第一段断档（没有 ⇒ `null`）。 */
  firstGap: RelaySeg | null;
}

/** 模拟最远看多久（分钟）。轴只画 4h，数值要能说出「断档前 6 小时」也得往后算。 */
export const RELAY_SIM_MIN = 24 * 60;
/** 5h 窗口时长（分钟）：满格（未开始计时）的号从被用的那一刻起 300 分钟后回满。 */
export const FIVE_H_MIN = 300;

/**
 * 接力模拟。贪心：任一时刻用「已经可用、队列序最靠前」的号，直到它的预算用完；
 * 没号可用 ⇒ 断档，直到最早回来的那个号。
 *
 * 不变量（行为闸 `tests/test_overview_5b.py::RelayPlanBehaviour`）：
 *  · 没人回来得及接力时，断档前的总长 == Σ 可用号 `nowMin`（= `_burst.now_min` 的口径）；
 *  · 冷却结束 / 5h 回满的号**算回接力**，只有真的没号可用才画断档；
 *  · 回来的号用 `back`（淡色）段；一个号的周上限用完就不再回来；
 *  · 配速未知的号排在已知之后、画成 `open` 段并让数值带「≥」，绝不当成 0。
 */
export function relayPlan(input: readonly RelayInput[], simMin = RELAY_SIM_MIN): RelayPlan {
  interface St { a: RelayInput; order: number; from: number; budget: number | null; week: number; used: boolean; started: boolean; refillAt: number | null }
  const st: St[] = input.map((a, order) => {
    const week = a.weekMin == null ? Infinity : Math.max(0, a.weekMin);
    if (a.usable) {
      return { a, order, from: 0, budget: a.nowMin == null ? null : Math.min(Math.max(0, a.nowMin), week),
               week, used: false, started: a.refillAtMin != null, refillAt: a.refillAtMin };
    }
    if (a.backAtMin == null) return { a, order, from: Infinity, budget: 0, week, used: false, started: false, refillAt: null };
    // 回来时的预算：回来前 5h 已经回满 ⇒ 一整窗；否则沿用此刻剩下的（冷却里多半是 0 ⇒ 再等到回满）。
    const refilledByThen = a.refillAtMin != null && a.refillAtMin <= a.backAtMin;
    let from = a.backAtMin, budget: number | null = refilledByThen ? a.fullMin : a.nowMin;
    let refillAt = refilledByThen ? null : a.refillAtMin;
    if ((budget ?? 0) <= 0 && budget !== null && refillAt != null) {
      from = refillAt; budget = a.fullMin; refillAt = null;
    }
    return { a, order, from, budget: budget == null ? (a.nowMin == null ? null : 0) : Math.min(budget, week),
             week, used: false, started: refillAt != null, refillAt };
  });

  const segs: RelaySeg[] = [];
  let t = 0, atLeast = false, guard = 0;
  let lastWhy: "refill" | "cool" | undefined;
  while (t < simMin && guard++ < 400) {
    // 已在计时的 5h 窗口到点就回满 —— 哪怕这段时间没轮到它（没用完的余量不会留到下一窗）。
    for (const s of st) {
      if (s.started && s.refillAt != null && s.refillAt <= t + 1e-9 && s.a.fullMin != null && s.week > 1e-9) {
        // `from` 不动：冷却中的号窗口回满了也要等冷却结束才回来，只是回来时是满的。
        s.budget = Math.min(s.a.fullMin, s.week); s.started = false; s.refillAt = null;
      }
    }
    const ready = st.filter((s) => s.from <= t + 1e-9 && (s.budget === null || s.budget > 1e-9))
      .sort((x, y) => x.order - y.order);
    // ★ 配速已知的先用：未知的那个一旦接上就画到头（`open`），排在前面会把已知的全挡在轴外。
    const known = ready.filter((s) => s.budget !== null);
    const pick = known[0] ?? ready[0];
    if (!pick) {
      const next = st.filter((s) => s.from > t && Number.isFinite(s.from) && (s.budget === null || s.budget > 1e-9))
        .sort((x, y) => x.from - y.from || x.order - y.order)[0];
      if (!next) { segs.push({ kind: "gap", start: t, end: Infinity }); break; }
      lastWhy = next.a.backAtMin != null && Math.abs(next.from - next.a.backAtMin) < 1e-9 && !next.a.usable ? "cool" : "refill";
      segs.push({ kind: "gap", start: t, end: next.from, resumeLabel: next.a.label, resumeWhy: lastWhy });
      t = next.from;
      continue;
    }
    const kind: RelaySegKind = pick.budget === null ? "open" : pick.used || pick.from > 0 ? "back" : "now";
    if (pick.budget === null) {
      atLeast = true;
      segs.push({ kind, start: t, end: Infinity, id: pick.a.id, label: pick.a.label, color: pick.order });
      break;
    }
    const dur = pick.budget;
    segs.push({ kind, start: t, end: t + dur, id: pick.a.id, label: pick.a.label, color: pick.order });
    const startedAt = t;
    t += dur;
    pick.week -= dur;
    pick.used = true;
    // 用完之后：5h 已在计时 ⇒ 到 refillAt 回满；没在计时（满格浮动）⇒ 从这次开始用算起 300 分钟。
    const refillAt = pick.started && pick.refillAt != null ? pick.refillAt : startedAt + FIVE_H_MIN;
    if (pick.a.fullMin != null && pick.week > 1e-9 && refillAt > t - 1e-9) {
      pick.from = refillAt; pick.budget = Math.min(pick.a.fullMin, pick.week);
      pick.started = false; pick.refillAt = null;
    } else {
      pick.from = Infinity; pick.budget = 0;
    }
  }
  // 合并相邻的同号段（同一个号连着两段 = 一段）。
  const merged: RelaySeg[] = [];
  for (const s of segs) {
    const p = merged[merged.length - 1];
    if (p && p.kind === s.kind && p.id && p.id === s.id && Math.abs(p.end - s.start) < 1e-9) p.end = s.end;
    else merged.push({ ...s });
  }
  const firstGap = merged.find((s) => s.kind === "gap") ?? null;
  const anyKnown = st.some((s) => s.budget !== null && (s.a.usable || Number.isFinite(s.from)));
  const continuousMin = firstGap ? firstGap.start : (merged.length ? Math.min(t, simMin) : null);
  // 一路接到模拟尽头都没断 ⇒ 真实值只会更长。
  if (!firstGap && t >= simMin) atLeast = true;
  // 打头就是配速未知的号 ⇒ 「≥ 0」是句空话，画「—」。
  const known = anyKnown && !(atLeast && continuousMin === 0);
  return { segs: merged, continuousMin: known ? continuousMin : null, atLeast, firstGap };
}

/** 段 → 轴上的百分比位置（0–100），轴长 `axisMin`（默认 4h）。超出轴的部分裁掉；完全在轴外 ⇒ `null`。 */
export function segBox(s: { start: number; end: number }, axisMin = 240): { left: number; width: number } | null {
  if (s.start >= axisMin) return null;
  const end = Math.min(s.end, axisMin);
  return { left: (s.start / axisMin) * 100, width: ((end - s.start) / axisMin) * 100 };
}

/** 接力配色（原型 P5DemoA 的色段顺序，按接力里第几个号取）。只区分账号，不表示平台。 */
export const RELAY_COLORS = ["#2dd4bf", "#4d9fff", "#8b7cf6", "#f5b544", "#E0784F"];

/** 断档那行字：`断档 15 分钟 · 号F 5h 回满后接上`。之后没人回来 ⇒ `之后 24 小时内没有号回来`。 */
export function gapNote(g: RelaySeg | null): string {
  if (!g) return "";
  if (!Number.isFinite(g.end)) return `断档 · 之后 ${RELAY_SIM_MIN / 60} 小时内没有号回来`;
  const d = g.end - g.start;
  const len = d < 60 ? `${Math.max(1, Math.round(d))} 分钟` : fmtDur(d);
  const why = g.resumeWhy === "cool" ? "冷却结束后接上" : "5h 回满后接上";
  return `断档 ${len} · ${g.resumeLabel ?? "?"} ${why}`;
}

// ── 卡片状态与排序（README「账号区」） ──────────────────────────────────────

/** 卡片状态。决定标签、环与描边颜色、动态行、排序档。 */
export type OvState = "inuse" | "next" | "ok" | "cool" | "low" | "unprobed" | "dead" | "off" | "readonly";

/** 「额度低」阈值：与菜单栏 / 刘海同一个数（`mbLogic.ts::LOW_PCT`），对**取整后**的值判。 */
export const OV_LOW_PCT = 10;
export function ovIsLow(pct: number | null | undefined): boolean {
  return pct != null && Number.isFinite(pct) && Math.round(pct) < OV_LOW_PCT;
}

export interface OvStateInput {
  inUse: boolean; next: boolean; dead: boolean; off: boolean; readOnly?: boolean;
  coolSec: number;
  /** 最紧窗口剩余；没有任何可读窗口 ⇒ `null`（未探测）。 */
  tightest: number | null;
}
export function ovState(x: OvStateInput): OvState {
  if (x.dead) return "dead";
  // ★ 在用先于停用：停用号也能被借用 / 被别的 agy 写回成当值号。那一刻它就是「正在使用」，
  //   收进停用条里等于把当值号藏起来（harness `agylive=sub2` 实测：当值号整个不见了）。
  if (x.inUse) return "inuse";
  if (x.off) return "off";
  if (x.readOnly) return "readonly";
  if (x.coolSec > 0) return "cool";
  if (x.tightest == null) return "unprobed";
  if (ovIsLow(x.tightest)) return "low";
  if (x.next) return "next";
  return "ok";
}

/** 排序档：在用 → 可用（按可用度）→ 冷却中 / 额度低 → 需处理。停用与失效不在主网格里。 */
export function ovRank(s: OvState): number {
  switch (s) {
    case "inuse": return 0;
    case "next": case "ok": case "readonly": return 1;
    case "cool": case "low": return 2;
    case "unprobed": return 3;
    case "dead": return 4;
    case "off": return 5;
  }
}

/**
 * 默认顺序：档位 → 同档按可用度（最紧窗口剩余）降序 → 名字。
 * ★ `custom`（用户拖过）非空时优先 —— 拖拽排序（用户 2026-09-19 要的）保留；
 *   没被排过的号按默认规则**追加在末尾**，绝不丢（同 `cardOrder.ts::applyOrder`）。
 */
export function ovSort<T>(items: readonly T[], key: (x: T) => { id: string; state: OvState; tightest: number | null; name: string },
                          custom?: readonly string[] | null): T[] {
  const def = [...items].sort((a, b) => {
    const x = key(a), y = key(b);
    return ovRank(x.state) - ovRank(y.state)
      || (y.tightest ?? -1) - (x.tightest ?? -1)
      || x.name.localeCompare(y.name, undefined, { numeric: true });
  });
  if (!custom || custom.length === 0) return def;
  const pos = new Map(custom.map((id, i) => [id, i]));
  const inC = def.filter((x) => pos.has(key(x).id)).sort((a, b) => (pos.get(key(a).id) ?? 0) - (pos.get(key(b).id) ?? 0));
  return [...inC, ...def.filter((x) => !pos.has(key(x).id))];
}

/** 标题行计数：`5 可用 · 1 冷却中 · 1 需处理 · 3 已停用`（0 的项不写）。 */
export interface OvCounts { ok: number; cool: number; bad: number; off: number; low: number }
export function ovCounts(states: readonly OvState[]): OvCounts {
  const c: OvCounts = { ok: 0, cool: 0, bad: 0, off: 0, low: 0 };
  for (const s of states) {
    if (s === "inuse" || s === "next" || s === "ok" || s === "readonly") c.ok++;
    else if (s === "cool") c.cool++;
    else if (s === "low") c.low++;
    else if (s === "unprobed" || s === "dead") c.bad++;
    else if (s === "off") c.off++;
  }
  return c;
}

/** 与最优号的差（`-15%`）；自己就是最优 ⇒ `"最优"`；算不了 ⇒ `""`。 */
export function deltaText(pct: number | null, best: number | null): string {
  if (pct == null || best == null || best < 0) return "";
  const d = Math.round(pct) - Math.round(best);
  return d >= 0 ? "最优" : `${d}%`;
}

// ── 今天的切换（README「今天的切换 · N 次」） ───────────────────────────────

export interface RotEvent { t: number; type: string; from: string | null; to: string | null; reason: string }
export interface SwitchRow { t: number; from: string; to: string; why: string; dot: string }

/** 原因 → 文案 + 色点（codex `traffic/rotation.py` 与 agy `traffic/agy_rotation.py` 两套原因都在这）。 */
export const REASON_TEXT: Record<string, [string, string]> = {
  quota_rotate: ["额度轮换", "#2dd4bf"],
  exhausted: ["5h 用完", "#2dd4bf"],
  cool_429: ["429 冷却", "#f5b544"],
  stream_err: ["断流换号", "#f5b544"],
  pro_fallback: ["Pro 保底接管", "#8b7cf6"],
  window_start: ["窗口起点", "#aab3c0"],
  auto: ["额度低自动换", "#2dd4bf"],
  wanted: ["按你的选择", "#aab3c0"],
  borrow: ["临时借用", "#f5b544"],
  manual: ["手动切换", "#aab3c0"],
  drift: ["被别的 agy 写回", "#f5b544"],
};

/** 今天（本地自然日，`dayStartMs` 起）的切换，新的在前。只认真的换号（from ≠ to、`to` 有值）。 */
export function todaySwitches(events: readonly RotEvent[], dayStartMs: number): SwitchRow[] {
  const out: SwitchRow[] = [];
  for (const e of events) {
    if (e.type !== "switch" && e.type !== "failover") continue;
    if (!e.to || e.to === e.from) continue;
    if (e.t * 1000 < dayStartMs) continue;
    const r = REASON_TEXT[e.reason] ?? [e.reason || "切换", "#aab3c0"];
    out.push({ t: e.t, from: e.from ?? "—", to: e.to, why: r[0], dot: r[1] });
  }
  return out.sort((a, b) => b.t - a.t);
}

/** 本地今天 0 点（毫秒）。 */
export function dayStart(nowMs: number): number {
  const d = new Date(nowMs);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/** 每号：最后一次在岗的结束时刻（秒）+ 今天的 token。来自轮换段（`segments`）。 */
export function lastUseByAcct(segs: readonly { acc: string; end: number; tokens: number }[], dayStartMs: number):
  Map<string, { last: number; today: number }> {
  const m = new Map<string, { last: number; today: number }>();
  for (const s of segs) {
    const v = m.get(s.acc) ?? { last: 0, today: 0 };
    v.last = Math.max(v.last, s.end);
    if (s.end * 1000 >= dayStartMs) v.today += s.tokens || 0;
    m.set(s.acc, v);
  }
  return m;
}

// ── 板子（`codex-rotate next --json` / `agy-rotate next --json`）→ 接力输入 ─────────────

export interface BoardWinLike { label: string; rem: number | null; reset: string }
export interface BoardEntLike {
  aid: string; label: string | null; off: boolean; dead: boolean; cool_min: number;
  wins: BoardWinLike[]; weekly: number | null; tightest: number | null;
  eta5h?: { left_min: number; per_window_min: number } | null;
}
export interface BoardLike {
  queue: BoardEntLike[]; rest: BoardEntLike[];
  burn_pp_per_hour: number | null;
  burst?: { wk_per_5h: number | null; per_window_min: number | null } | null;
}

/**
 * Codex：每号的接力输入，口径逐项对齐 `codex-rotate::_burst`（见 `RelayInput`）。
 * ★ 停用 / 失效的号不进接力（与 `_burst` 的 `pool` 同一个过滤）—— 池子见底时代理会借用停用号，
 *   但那是兜底不是计划，算进续航就等于替用户推翻他的停用设置。
 */
export function codexRelayInputs(b: BoardLike): RelayInput[] {
  const ratio = b.burst?.wk_per_5h ?? null;
  const one = (e: BoardEntLike, usable: boolean): RelayInput => {
    const w5 = e.wins.find((w) => w.label === "5h") ?? null;
    const eta = e.eta5h ?? null;
    const full = eta ? eta.per_window_min : null;
    const weekMin = ratio && e.weekly != null && full ? e.weekly / (ratio * 100 / full) : null;
    const nowMin = eta ? (weekMin == null ? eta.left_min : Math.min(eta.left_min, weekMin)) : null;
    const r5 = w5 ? parseReset(w5.reset) : null;
    const refillAtMin = w5 && w5.rem != null && w5.rem < 100 ? r5 : null;
    let backAtMin: number | null = null;
    if (!usable) backAtMin = e.cool_min > 0 ? e.cool_min : refillAtMin;
    return { id: e.aid, label: e.label ?? e.aid, usable, nowMin, backAtMin, refillAtMin, fullMin: full, weekMin };
  };
  return [...b.queue.map((e) => one(e, true)),
          ...b.rest.filter((e) => !e.off && !e.dead).map((e) => one(e, false))];
}

/**
 * Gemini：agy 没有「连续使用」的配速，只有全池周消耗速度（`burn_pp_per_hour`，钟点、含空闲）——
 * 与旧续航条 agy 分支同一个口径（「全池续航」）。每号能撑 = 周剩余 ÷ 速度。速度算不出 ⇒ `null`（画「—」）。
 */
export function agyRelayInputs(b: BoardLike): RelayInput[] | null {
  const burn = b.burn_pp_per_hour;
  if (!burn || burn <= 0) return null;
  const mins = (e: BoardEntLike) => ((e.weekly ?? e.tightest ?? 0) / burn) * 60;
  return [...b.queue.map((e): RelayInput => ({ id: e.aid, label: e.label ?? e.aid, usable: true, nowMin: mins(e),
                                               backAtMin: null, refillAtMin: null, fullMin: null, weekMin: null })),
          ...b.rest.filter((e) => !e.off && !e.dead && e.cool_min > 0).map((e): RelayInput => ({
            id: e.aid, label: e.label ?? e.aid, usable: false, nowMin: mins(e),
            backAtMin: e.cool_min, refillAtMin: null, fullMin: null, weekMin: null }))];
}
