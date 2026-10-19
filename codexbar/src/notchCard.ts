// 刘海卡片（交接包 2026-10-19 page4 · 4e「④ 悬浮卡片 + 光桥」）的纯逻辑 —— **零 import**，
// `tests/test_notch_card.py` 用 `node --experimental-strip-types` 直接跑（CI 没有 node_modules）。
//
// 管五件事：① Tab 默认规则 ② 额度行的告警判定、置顶与告警行文字 ③ 卡片版面（行顶、总高）
// ④ logo 从光晕飞进行里的起止点 ⑤ 果冻下垂几何、光晕告警团的位置、高度上报时机、面积图路径。
// 数值全部照抄 `page4-popover-notch/code/P4NotchMotion.html` 的内联样式与 `renderVals()`。
// 坐标一律以**刘海左上角**为原点（逻辑 pt）：网页里刘海始终水平居中，窗口宽随展开 / 收起变，
// 以刘海为原点的坐标不随窗口宽变。

/** 原型的 `SP` 常量，逐字照抄 = 临界阻尼弹簧 `crit(0.36, 0.55)`（交接包 README「动效曲线」；测试里现算比对）。 */
export const SPRING =
  "linear(0.000, 0.041, 0.135, 0.250, 0.366, 0.475, 0.572, 0.655, 0.725, 0.782, 0.829, 0.866, 0.896, 0.919, 0.938, 0.952, 0.963, 0.972, 0.979, 0.984, 0.988, 0.991, 0.993, 0.995, 0.996, 0.997, 0.998, 0.998, 0.999, 0.999, 1.000)";

export type NotchKey = "codex" | "claude" | "agy" | "grok";
/** 固定顺序，与光晕 / 托盘槽位 / 额度行一致。 */
export const ORDER: NotchKey[] = ["codex", "claude", "agy", "grok"];
export const NAME: Record<NotchKey, string> = { codex: "Codex", claude: "Claude", agy: "Gemini", grok: "Grok" };

// ── 尺寸（与 `notch.rs` 的 `CARD_W` / `CARD_GAP` 同值，闸在 test_notch_hud.py） ─────────────
export const CARD_W = 300;
export const CARD_GAP = 10;
/** 交接包：「最高约 560 pt（C 场景 + 今日 Tab），需能放进 900 pt 高的 Air 屏幕」。 */
export const CARD_H_MAX = 560;
/** 告警橙红（交接包 tokens `bad`）。 */
export const ALERT = "#FF4D2E";

export const PAD_TOP = 8;
/** 告警行 26 + 下边距 8。 */
export const ALERT_H = 34;
export const TAB_H = 30;
export const ROW_H = 32;
export const SESS_H = 22;
export const SESS_PAD = 4;
/** 底栏 36 + 上描边 1。 */
export const RUN_FOOT_H = 37;
/** 今日：摘要 32 + 图 70 + 横轴 14 + 表头 20 + 底栏 32 + 上描边 1（行另算，每行 26 + 下描边 1）。 */
export const TODAY_FIXED_H = 32 + 70 + 14 + 20 + 33;
export const TODAY_ROW_H = 27;
export const BLOCK_GAP = 8;
export const Q_HEAD_H = 26;
export const Q_ROW_H = 28;
/** 额度块底栏 32 + 上描边 1。 */
export const Q_FOOT_H = 33;
export const PAD_BOTTOM = 8;
/** 一行最多列几个会话：只有悬停那一行展开，卡片要放得进 `CARD_H_MAX`（见 PLAN §4 偏离记录）。 */
export const MAX_SESS = 6;

// ── ① Tab ──────────────────────────────────────────────────────────────────
export type View = "run" | "today";

/** 有 AI 在跑默认「在跑」；空闲默认「今日」。**每次展开都回到这里**。 */
export function defaultView(nRunning: number): View {
  return nRunning > 0 ? "run" : "today";
}

/** 空闲时「在跑」置灰不可点：选了也落到「今日」（展开着时最后一家停下，同样落到今日）。 */
export function effectiveView(chosen: View, nRunning: number): View {
  return nRunning > 0 ? chosen : "today";
}

// ── ② 额度行 ───────────────────────────────────────────────────────────────
export const LOW_PCT = 10;

/**
 * 「某家 < 10%」。★ 判的是**显示出来的整数**（与 `mbLogic.isLow` / `notchSegs.segColor` 同一条纪律，
 * 测试核两份实现在边界上一致）：剩 9.6% 时行上写「10%」就不能红，剩 9.4% 写「9%」就必须红。
 */
export function isLowPct(pct: number | null | undefined): boolean {
  return typeof pct === "number" && Number.isFinite(pct) && Math.round(pct) < LOW_PCT;
}

/** 一格窗口。`absent` = 这家根本没有这个窗口（Grok 的 5h：留空）；`pct: null` = 读不到（写 —）。 */
export interface QWin { pct: number | null; refill: string; absent?: boolean; stale?: boolean; title?: string }
export interface QLine { key: NotchKey; name: string; w5: QWin; ww: QWin }

export const ABSENT: QWin = { pct: null, refill: "", absent: true };

/** 显示的百分比文字：读不到写 —，没有这个窗口写空。 */
export function pctText(w: QWin): string {
  if (w.absent) return "";
  return w.pct == null ? "—" : `${Math.round(Math.max(0, Math.min(100, w.pct)))}%`;
}

/** 这一行里最紧的那个 < 10% 窗口；没有 ⇒ null。 */
export function lowWindow(l: QLine): { win: "5h" | "周"; pct: number; refill: string } | null {
  const c: { win: "5h" | "周"; pct: number; refill: string }[] = [];
  if (!l.w5.absent && isLowPct(l.w5.pct)) c.push({ win: "5h", pct: l.w5.pct as number, refill: l.w5.refill });
  if (!l.ww.absent && isLowPct(l.ww.pct)) c.push({ win: "周", pct: l.ww.pct as number, refill: l.ww.refill });
  if (!c.length) return null;
  return c.reduce((a, b) => (b.pct < a.pct ? b : a));
}

/** 「某家 < 10%：该行**置顶**」。低的按最紧排前，其余保持固定顺序（稳定，不随数据跳）。 */
export function orderQuota(lines: QLine[]): QLine[] {
  const fixed = [...lines].sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
  const low = fixed.filter((l) => lowWindow(l)).sort((a, b) => (lowWindow(a)!.pct - lowWindow(b)!.pct));
  return [...low, ...fixed.filter((l) => !lowWindow(l))];
}

export interface AlertLine { key: NotchKey; head: string; pct: string; tail: string }

/**
 * 卡片顶部告警行（「Gemini 号C 5h 剩 **8%** · 0h54m 后回满」）。几家同时低只写最紧的那一家。
 * ★ 回满时间只有真的是一段时长（含数字）才说「后回满」；「未启动 / 待确认 / —」拼上去是病句。
 */
export function alertOf(lines: QLine[]): AlertLine | null {
  let best: { l: QLine; w: NonNullable<ReturnType<typeof lowWindow>> } | null = null;
  for (const l of lines) {
    const w = lowWindow(l);
    if (w && (!best || w.pct < best.w.pct)) best = { l, w };
  }
  if (!best) return null;
  const { l, w } = best;
  return { key: l.key, head: `${NAME[l.key]} ${l.name} ${w.win} 剩 `, pct: `${Math.round(w.pct)}%`,
           tail: /\d/.test(w.refill) ? ` · ${w.refill} 后回满` : "" };
}

/** 全部低额度的平台（光晕 / 光桥 / 顶边那一段换橙红）。 */
export function alertKeys(lines: QLine[]): NotchKey[] {
  return ORDER.filter((k) => lines.some((l) => l.key === k && lowWindow(l)));
}

/** 号名列宽：原型 34（示意号名全是「号A」）。真实号名会更长 —— 按最长的估宽，上限 64，超出省略号。 */
export function nameColWidth(names: readonly string[]): number {
  let w = 0;
  for (const n of names) {
    let x = 0;
    for (const ch of n) x += /[　-鿿＀-￯]/.test(ch) ? 12.5 : 7.5;
    if (x > w) w = x;
  }
  return Math.max(34, Math.min(64, Math.ceil(w)));
}

// ── ③ 版面 ─────────────────────────────────────────────────────────────────
export interface RunRowIn { multi: boolean; open: boolean; nSess: number }
export interface CardIn {
  alert: boolean;
  view: View;
  run: RunRowIn[];
  /** 今日 Tab 列几家（0 用量的已去掉）。 */
  todayRows: number;
  quotaRows: number;
}
export interface CardLayout {
  /** 在跑各行的顶（卡片内）。 */
  rowTop: number[];
  /** 额度块顶（卡片内）。 */
  quotaTop: number;
  /** 卡片总高（含上下内边距）。 */
  height: number;
}

export function sessHeight(r: RunRowIn): number {
  return r.multi && r.open ? Math.min(r.nSess, MAX_SESS) * SESS_H + SESS_PAD : 0;
}

/** 照原型 `renderVals()` 的 geometry 那一段：上块按当前 Tab 取高（另一块收成 0fr）。 */
export function layoutCard(c: CardIn): CardLayout {
  let y = PAD_TOP + (c.alert ? ALERT_H : 0) + TAB_H;
  const rowTop: number[] = [];
  if (c.view === "run") {
    for (const r of c.run) { rowTop.push(y); y += ROW_H + sessHeight(r); }
    y += RUN_FOOT_H;
  } else {
    let yy = y;
    for (let i = 0; i < c.run.length; i++) { rowTop.push(yy); yy += ROW_H; }
    y += TODAY_FIXED_H + c.todayRows * TODAY_ROW_H;
  }
  const quotaTop = y + BLOCK_GAP;
  return { rowTop, quotaTop, height: quotaTop + Q_HEAD_H + c.quotaRows * Q_ROW_H + Q_FOOT_H + PAD_BOTTOM };
}

/**
 * 今日 Tab 最多列几家，让卡片不超过 `CARD_H_MAX`（本机快照有 7 家时 C 场景 + 今日 Tab 会到 617）。
 * 放不下的是占比最小的几家 —— 面积图与总数里仍有它们（交接包全局规则：放不下先藏次要的）。
 */
export function todayRowCap(alert: boolean, quotaRows: number): number {
  const fixed = layoutCard({ alert, view: "today", run: [], todayRows: 0, quotaRows }).height;
  return Math.max(1, Math.floor((CARD_H_MAX - fixed) / TODAY_ROW_H));
}

// ── ④ logo 飞行（交接包「logo 来向」：Codex 左翼 · Claude 下沿左半 · Gemini 下沿右半 · Grok 右翼） ──────
export const FLY_LOGO = 12;
export const FLY_FROM_S = 0.4;
export const FLY_TO_S = 1.5;
/** 行里 logo 的 x（卡片内）：块外边距 8 + 行左内边距 6 + 箭头列 14 + 列间距 7（原型 `logoX`）。 */
export const ROW_LOGO_X = 8 + 6 + 14 + 7;
/** 没有一行是多会话时不留箭头列（用户 2026-10-19，同悬停面板）：logo 与下块额度行的 logo 对齐 = 块外边距 8 + 14。 */
export const ROW_LOGO_X_NOCHEV = 8 + 14;
/** 行 32 高、logo 18 ⇒ 上下各 7。 */
export const ROW_LOGO_DY = 7;

/** 出发点（以刘海左上为原点）。原型的 `ox/oy`；Grok 原型没画，取 Codex 的镜像。 */
export function flyFrom(k: NotchKey, nw: number): { x: number; y: number } {
  switch (k) {
    case "codex": return { x: -16, y: 10 };
    case "claude": return { x: nw * 0.33 - 6, y: 34 };
    case "agy": return { x: nw * 0.67 - 6, y: 34 };
    case "grok": return { x: nw + 4, y: 10 };
  }
}

/** 落点：卡片在刘海下沿下方 10、水平居中。 */
export function flyTo(rowTop: number, nw: number, nh: number, chev = true): { x: number; y: number } {
  return { x: nw / 2 - CARD_W / 2 + (chev ? ROW_LOGO_X : ROW_LOGO_X_NOCHEV), y: nh + CARD_GAP + rowTop + ROW_LOGO_DY };
}

/** 这一行的数据从哪一侧滑入（与 logo 同侧）：左翼 / 下沿左半 = 左，下沿右半 / 右翼 = 右。 */
export function side(k: NotchKey): -1 | 1 {
  return k === "codex" || k === "claude" ? -1 : 1;
}

/** 原型 `doOpen` 的 `settled` 计时：860 ms 后把 logo 交给行自己画。 */
export const SETTLE_MS = 860;

// ── ⑤ 果冻下垂 · 光晕告警团 · 高度上报 · 面积图 ─────────────────────────────────
export const DRIP_RANGE = 24;
export const DRIP_W = 44;

/**
 * 果冻下垂（定稿 D）：光标距刘海 24 pt 内，下沿在光标正上方鼓出一滴黑，最多 8 pt。
 * `dx` = 光标相对刘海中线（Rust `notch-cursor` 给）；`distance` = 到刘海矩形的距离。
 * 返回以刘海左上为原点的 left、高度（6 + 8p，顶在 26 ⇒ 最多伸出下沿 8）、是否可见。
 */
export function dripGeom(cur: { dx: number; distance: number } | null, nw: number, open: boolean):
  { left: number; h: number; on: boolean; p: number } {
  const p = cur && !open ? Math.max(0, Math.min(1, 1 - cur.distance / DRIP_RANGE)) : 0;
  const mx = nw / 2 + (cur ? cur.dx : 0);
  const left = Math.max(4, Math.min(nw - 48, mx - DRIP_W / 2));
  return { left, h: 6 + 8 * p, on: p > 0, p };
}

/** 告警快闪团（60 宽）在第 i 段中点：贴边层从刘海左沿外 11 起、宽 nw + 22（原型 `aX`）。 */
export function alertBlobLeft(i: number, n: number, nw: number): number {
  return -11 + ((nw + 22) * (i + 0.5)) / n - 30;
}

/** 卡片高度的过渡时长（原型 `height 420ms SP`）。 */
export const HEIGHT_MS = 420;

/** 报给 Rust 的高度：长高立刻报（窗口要先够高），变矮等高度动画走完再报（先缩会裁掉动画）。 */
export function resizeDelay(prevH: number | null, nextH: number, reduce: boolean): number {
  if (prevH == null || nextH >= prevH || reduce) return 0;
  return HEIGHT_MS;
}

/**
 * 堆叠面积的一层（填到下一层之上）。曲线照原型：相邻两点之间用水平切线的三次贝塞尔（`C mx,y0 mx,y1 x1,y1`），
 * 不会过冲到相邻点之外 —— 面积图不该画出数据里没有的峰。只有一个点时画成居中的一根柱。
 */
export function stackPath(top: number[], base: number[], yMax: number, w: number, h: number): string {
  const n = top.length;
  if (!n) return "";
  const y = (v: number) => (h - (v / yMax) * h).toFixed(1);
  if (n === 1) {
    const cw = w * 0.12, x0 = ((w - cw) / 2).toFixed(1), x1 = ((w + cw) / 2).toFixed(1);
    return `M${x0},${y(base[0])} L${x0},${y(top[0])} L${x1},${y(top[0])} L${x1},${y(base[0])} Z`;
  }
  const x = (i: number) => (i / (n - 1)) * w;
  const seg = (vals: number[], idx: number[]) => idx.slice(1).map((j, k) => {
    const i = idx[k], m = ((x(i) + x(j)) / 2).toFixed(1);
    return ` C${m},${y(vals[i])} ${m},${y(vals[j])} ${x(j).toFixed(1)},${y(vals[j])}`;
  }).join("");
  const fwd = top.map((_, i) => i), back = [...fwd].reverse();
  return `M0.0,${y(top[0])}${seg(top, fwd)} L${w.toFixed(1)},${y(base[n - 1])}${seg(base, back)} Z`;
}
