// 托盘胶囊悬停面板（交接包 2026-10-19 page2）的纯逻辑 —— **零 import**，
// `tests/test_tps_hover.py` 用 `node --experimental-strip-types` 直接跑。
//
// 管四件事：① 行版面（logo 落点的 y、面板总高）② logo 飞行起止点与时序
// ③ 会话展开 / 折叠的 250 ms 计时规则 ④ 「停下」那一行 40% → 3 s → 收起。
// 数值全部照抄 `page2-hover/code/HoverSpec.html`（静态尺寸）与 `HoverMotion.html`（`renderVals()` 的时序）。

/** HoverMotion.html 的 `SP` 常量，逐字照抄 = 临界阻尼弹簧 `crit(0.34, 0.5)`（测试里现算比对）。 */
export const SPRING =
  "linear(0.000, 0.039, 0.127, 0.236, 0.349, 0.455, 0.551, 0.635, 0.705, 0.764, 0.812, 0.852, 0.883, 0.909, 0.929, 0.945, 0.957, 0.967, 0.974, 0.980, 0.985, 0.988, 0.991, 0.993, 0.995, 0.996, 0.997, 0.998, 0.998, 0.999, 1.000)";

/** 交接包 README「动效曲线」给的生成式。只给测试核对 SPRING 用。 */
export function critSpring(resp: number, T: number, n: number = 30): string {
  const w = (2 * Math.PI) / resp;
  const pts: string[] = [];
  for (let i = 0; i <= n; i++) {
    const v = i === n ? 1 : 1 - (1 + (w * T * i) / n) * Math.exp((-w * T * i) / n);
    pts.push(v.toFixed(3));
  }
  return "linear(" + pts.join(", ") + ")";
}

// ── ① 版面（HoverSpec.html 的内联样式） ────────────────────────────────
export const PANEL_W = 300;
export const BORDER = 1;
export const PAD_TOP = 4;
export const HEAD_H = 26;
export const ROW_H = 38;
export const ROW_H_OPEN = 32;
export const SESS_H = 22;
export const SESS_PAD = 4;
export const DIVIDER_H = 1;
/** 底栏 36 + 上描边 1。 */
export const FOOT_H = 37;
export const LOGO = 18;
export const PILL_LOGO = 12;
/** logo 在面板里的 x：描边 1 + 左内边距 14 + 箭头列 14 + 列间距 8（原型 `rowLogoX`）。 */
export const LOGO_X = BORDER + 14 + 14 + 8;
/** 没有一行是多会话时不留箭头列（用户 2026-10-19「左边这里有点空旷」）：logo 与底栏「今日」左对齐 = 描边 1 + 内边距 14。 */
export const LOGO_X_NOCHEV = BORDER + 14;

export interface BlockIn {
  /** 多会话（有 ×N、可展开）。 */
  multi: boolean;
  /** 当前展开着。 */
  open: boolean;
  /** 展开后列出的会话行数。 */
  nSess: number;
  /** 停下满 3 s、正在收起 —— 不再占高度。 */
  collapsed: boolean;
}

export interface PanelLayout {
  /** 各 AI 行顶部（面板内，含描边）。 */
  rowTop: number[];
  /** 各行 logo 顶部（面板内）。 */
  logoY: number[];
  /** 面板外框总高（含上下描边）。 */
  height: number;
}

export function rowHeight(b: BlockIn): number {
  return b.multi && b.open ? ROW_H_OPEN : ROW_H;
}

/** 一块（分隔线 + AI 行 + 会话区）的高度。分隔线只在**不是第一块**时有。 */
export function blockHeight(b: BlockIn, first: boolean): number {
  if (b.collapsed) return 0;
  const sess = b.multi && b.open ? b.nSess * SESS_H + SESS_PAD : 0;
  return (first ? 0 : DIVIDER_H) + rowHeight(b) + sess;
}

export function layoutPanel(blocks: BlockIn[]): PanelLayout {
  let y = BORDER + PAD_TOP + HEAD_H;
  const rowTop: number[] = [];
  const logoY: number[] = [];
  blocks.forEach((b, i) => {
    const top = y + (i === 0 ? 0 : DIVIDER_H);
    rowTop.push(top);
    logoY.push(top + (rowHeight(b) - LOGO) / 2);
    y += blockHeight(b, i === 0);
  });
  return { rowTop, logoY, height: y + FOOT_H + BORDER };
}

// ── ② logo 飞行 ─────────────────────────────────────────────────────
// ★ 用户 2026-10-21「响应要加快」：飞入 520 → 320、飞回 440 → 300，数据跟着提前（见 `dataDelay`）。
export const FLY_IN_MS = 320;
export const FLY_IN_STAGGER = 35;
export const FLY_BACK_MS = 300;
/** Rust `CLOSE_ANIM`：leave / idle 后这么久真隐藏窗口。 */
export const RUST_HIDE_MS = 520;
/** 托盘胶囊在 `layout()` 里给的段（窗口内坐标）。 */
export interface Seg { platform: string; x: number; w: number; logo: { x: number; y: number; size: number } }
export interface HoverLayout {
  window: { w: number; h: number };
  menubar_h: number;
  panel: { x: number; y: number; w: number; h: number };
  pill: { x: number; y: number; w: number; h: number };
  segments: Seg[];
}

/** Rust 的 `tpshover-open` payload → 版面；形状不对返回 null（那时不飞，直接淡入）。 */
export function parseLayout(raw: unknown): HoverLayout | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const p = o.panel as Record<string, unknown> | undefined;
  if (!p || typeof p.x !== "number" || typeof p.y !== "number") return null;
  const segs = Array.isArray(o.segments) ? (o.segments as Seg[]).filter((s) =>
    s && typeof s.platform === "string" && s.logo && typeof s.logo.x === "number" && typeof s.logo.y === "number") : [];
  return {
    window: (o.window as HoverLayout["window"]) ?? { w: 0, h: 0 },
    menubar_h: typeof o.menubar_h === "number" ? o.menubar_h : 0,
    panel: { x: p.x, y: p.y, w: typeof p.w === "number" ? p.w : PANEL_W, h: typeof p.h === "number" ? p.h : 0 },
    pill: (o.pill as HoverLayout["pill"]) ?? { x: 0, y: 0, w: 0, h: 0 },
    segments: segs,
  };
}

export interface Pt { x: number; y: number; s: number }
export interface FlightPlan { key: string; pill: Pt; row: Pt; delayIn: number; delayBack: number }

/** 第 i 行的 logo 在窗口里的落点（缩放 12→18 = 1.5，变换原点左上）。 */
export function rowLogoPoint(layout: HoverLayout, logoY: number, chev = true): Pt {
  return { x: layout.panel.x + (chev ? LOGO_X : LOGO_X_NOCHEV), y: layout.panel.y + logoY, s: LOGO / PILL_LOGO };
}

/**
 * 每个在面板里的 AI：从胶囊里自己那段的 logo 飞到自己那一行。胶囊里没有这一家（或版面读不到）⇒ 不飞
 * （那一行的 logo 直接在行里淡入）。错开按**飞行者**的序号算，不按行号 —— 中间一家没段时其余照样 35 ms 一个。
 */
export function planFlights(layout: HoverLayout | null, keys: string[], logoY: number[], chev = true): FlightPlan[] {
  if (!layout) return [];
  const out: FlightPlan[] = [];
  keys.forEach((k, i) => {
    const seg = layout.segments.find((s) => s.platform === k);
    if (!seg) return;
    out.push({ key: k, pill: { x: seg.logo.x, y: seg.logo.y, s: 1 }, row: rowLogoPoint(layout, logoY[i], chev), delayIn: 0, delayBack: 0 });
  });
  const n = out.length;
  out.forEach((f, j) => { f.delayIn = j * FLY_IN_STAGGER; f.delayBack = 60 + (n - 1 - j) * 25; });
  return out;
}

/** 打开后多久把 logo 交还给行自己画（最后一个落地 + 少许余量；原型固定 700）。 */
export function settleMs(nFlights: number): number {
  return nFlights > 0 ? Math.max(420, FLY_IN_MS + (nFlights - 1) * FLY_IN_STAGGER + 40) : 0;
}

/** 飞回胶囊：最后一个落地的时刻，但不晚于 Rust 隐藏窗口之前 20 ms（之后托盘必须已经画回 logo）。 */
export function restoreLogosAt(nFlights: number): number {
  if (nFlights <= 0) return 0;
  return Math.min(60 + (nFlights - 1) * 25 + FLY_BACK_MS, RUST_HIDE_MS - 20);
}

/** 第 i 行数据（名字 / t/s / Token）开始淡入的延迟：logo 落地前约 80 ms（原型 360 + i·35）。 */
export function dataDelay(i: number): number {
  return 160 + i * 35;
}

// ── ③ 展开 / 折叠：悬停 250 ms 展开，离开这一行（含会话区）250 ms 折叠 ────────────
export const HOVER_DWELL = 250;

export interface ExpandState {
  open: Record<string, boolean>;
  hov: string | null;
  due: { key: string; kind: "open" | "close"; at: number }[];
}

export type ExpandEv =
  | { t: "enter"; key: string; multi: boolean; now: number }
  | { t: "leave"; key: string; now: number }
  | { t: "tick"; now: number }
  | { t: "prune"; multi: string[] }
  | { t: "reset" };

export const EXPAND0: ExpandState = { open: {}, hov: null, due: [] };

export function expandReduce(s: ExpandState, e: ExpandEv): ExpandState {
  switch (e.t) {
    case "reset":
      return EXPAND0;
    case "enter": {
      const due = s.due.filter((d) => d.key !== e.key);
      if (e.multi && !s.open[e.key]) due.push({ key: e.key, kind: "open", at: e.now + HOVER_DWELL });
      return { open: s.open, hov: e.key, due };
    }
    case "leave": {
      const due = s.due.filter((d) => d.key !== e.key);
      if (s.open[e.key]) due.push({ key: e.key, kind: "close", at: e.now + HOVER_DWELL });
      return { open: s.open, hov: s.hov === e.key ? null : s.hov, due };
    }
    case "tick": {
      const ready = s.due.filter((d) => d.at <= e.now);
      if (!ready.length) return s;
      const open = { ...s.open };
      for (const d of ready) open[d.key] = d.kind === "open";
      return { open, hov: s.hov, due: s.due.filter((d) => d.at > e.now) };
    }
    case "prune": {
      const keep = new Set(e.multi);
      const stale = Object.keys(s.open).filter((k) => s.open[k] && !keep.has(k));
      if (!stale.length) return s;
      const open = { ...s.open };
      for (const k of stale) open[k] = false;
      return { open, hov: s.hov, due: s.due.filter((d) => keep.has(d.key)) };
    }
  }
}

export function nextDue(s: ExpandState): number | null {
  return s.due.length ? Math.min(...s.due.map((d) => d.at)) : null;
}

// ── ④ 停下：40% → 3 s → 高度收起（与托盘 `HOLD_SECS` 同） ─────────────────────
export const HOLD_MS = 3000;
/** 收起动画（折叠曲线 300 ms + 延后 100 ms）走完才真移除。 */
export const COLLAPSE_MS = 400;

export type Phase = "live" | "held" | "collapsing";
export interface Shown<R> { key: string; row: R; stoppedAt: number | null; phase: Phase }

/**
 * 上一份显示行 + 这一份在跑的行 → 新的显示行（固定平台顺序）。
 * 在跑 ⇒ live；刚从在跑消失 ⇒ 保留最后的数，记下停下时刻；满 3 s 收起；再满 400 ms 移除。
 * 停下后又跑起来 ⇒ 直接回 live。
 */
export function reconcile<R>(prev: Shown<R>[], rows: { key: string; row: R }[], now: number, order: string[]): Shown<R>[] {
  const out: Shown<R>[] = [];
  for (const k of order) {
    const cur = rows.find((r) => r.key === k);
    if (cur) { out.push({ key: k, row: cur.row, stoppedAt: null, phase: "live" }); continue; }
    const old = prev.find((p) => p.key === k);
    if (!old) continue;
    const at = old.stoppedAt ?? now;
    const age = now - at;
    if (age >= HOLD_MS + COLLAPSE_MS) continue;
    out.push({ key: k, row: old.row, stoppedAt: at, phase: age >= HOLD_MS ? "collapsing" : "held" });
  }
  return out;
}

/** 下一个需要重算显示行的时刻（held → collapsing → 移除）；没有 ⇒ null。 */
export function nextPhaseAt<R>(shown: Shown<R>[]): number | null {
  const ts: number[] = [];
  for (const s of shown) {
    if (s.stoppedAt == null) continue;
    ts.push(s.phase === "held" ? s.stoppedAt + HOLD_MS : s.stoppedAt + HOLD_MS + COLLAPSE_MS);
  }
  return ts.length ? Math.min(...ts) : null;
}

// ── 高度上报（`tpshover_resize`）：长高立刻报，变矮等动画走完再报 ──────────────
/** Rust 用这个高度定窗口高与命中区：先缩窗口会把正在收起的那段动画裁掉。 */
export function resizeDelay(prevH: number | null, nextH: number, reduce: boolean): number {
  if (prevH == null || nextH >= prevH || reduce) return 0;
  return COLLAPSE_MS;
}

// ── 底栏 ─────────────────────────────────────────────────────────────
/** 均速一位小数（交接包 `均 58.4 t/s`）；读不到写 —。 */
export function fmtAvg(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? v.toFixed(1) : "—";
}
