/**
 * 空闲额度面板的版面与动画编排（AICoop P11 §6；画板 `P11_Final` ④ 是 2× 画的）。
 * ★ 用户 2026-10-21「悬浮显示的内容太小了」⇒ 选 **1.5×**：画板数值一律 × 0.75（原来 ÷2 = 1×）。
 * ★ 零 import：测试用 `node --experimental-strip-types` 直接加载（CLAUDE.md §4）。
 *
 * 画板（2×）→ 这里（1.5×）：
 *   面板宽 580 → 435 · 外圆角 20 → 15 · 内边距 11 → 8（8.25 吸整）· 格间距 8 → 6 · 一行 4 格 ⇒ 格宽 (435 − 16 − 18)/4 = 100.25
 *   格高 134 → 100.5（不显示「窗口明细」那行；P9 S1「不再有窗口明细」）· 格圆角 14 → 10.5
 *   环 64 → 48（r 27 → 20.25，线宽 5 → 3.75，顶 26 → 19.5）· 大数字 20 → 15 px（顶 98 → 73.5）
 *   右上角重置 11.5 → 10.5 px（× 0.75 是 8.6；取刘海版 `P11_NotchHover` 画板原值 10.5 —— 偏离记 PLAN）
 *   在菜单栏的白点 7 → 6（5.25 吸整，左上 10 → 7）· 落进环心的 logo 26 → 20（19.5 吸整）
 *   ★ 白点取整数：浏览器按 **CSS 像素**取整元素的边，非整数宽会随格子坐标被取成两种宽（1× 时 3.5 实测扁圆）。
 *     格子左上角另吸到 0.5 px（Retina 整物理像素）。
 * 动画：格子依次弹入（每格差 45 ms，首格 80 ms）；托盘 logo 420 ms 弹簧飞进环心，相邻错开 25 ms；
 *   托盘以外的几家 120 ms 后原位淡入；文字与环 200 ms 时出现。
 */

export const PANEL_W = 435;
export const PAD = 8;
export const GAP = 6;
export const COLS = 4;
export const CELL_H = 100.5;
export const RING = 48;
export const RING_R = 20.25;
export const RING_SW = 3.75;
export const RING_TOP = 19.5;
export const RING_C = 2 * Math.PI * RING_R;
export const LOGO = 20;
/** 托盘里 logo 的边长（Rust `tray_idle::LOGO`）。飞行用的图按它画，落进环心时缩到 `LOGO`。 */
export const PILL_LOGO = 18;
// ★ 用户 2026-10-21「响应要加快」：飞行 420 → 280、其余几家 120 → 60 ms 后淡入、文字 200 → 110 ms 出现。
export const FLY_MS = 280;
export const FLY_STAGGER = 25;
export const OTHERS_IN_MS = 60;
export const LOW = "#FF8A73";

export const NAME: Record<string, string> = {
  codex: "Codex", claude: "Claude", agy: "Gemini", grok: "Grok", kimi: "Kimi", deepseek: "DeepSeek",
};

/** 画板 `BRC`（格子底色 / 描边用的品牌色）与 `NUMC`（环色，深色底）。浅色底画板没给 ⇒ 环用品牌色本身。 */
const BRC: Record<string, [number, number, number]> = {
  codex: [45, 212, 191], claude: [224, 120, 79], agy: [77, 159, 255],
  grok: [139, 124, 246], kimi: [236, 72, 153], deepseek: [77, 107, 254],
};
const NUMC: Record<string, string> = {
  codex: "#5EEAD4", claude: "#F09A76", agy: "#7AB8FF", grok: "#B9AEFB", kimi: "#F59AC8", deepseek: "#A3AEFF",
};

export function tone(key: string): { tint: (a: number) => string; num: (isDark: boolean) => string } {
  const c = BRC[key] ?? [143, 153, 166];
  return {
    tint: (a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`,
    num: (isDark) => (isDark ? NUMC[key] ?? "#c9d1db" : `rgb(${c[0]},${c[1]},${c[2]})`),
  };
}

export interface GridLayout { cw: number; ch: number; h: number; pos: { x: number; y: number }[] }

/** n 格的版面（面板内坐标，含边框内的内边距）。没有格子 ⇒ 高度 0（面板不出现）。 */
export function gridLayout(n: number): GridLayout {
  const cw = (PANEL_W - 2 * PAD - GAP * (COLS - 1)) / COLS;
  const rows = Math.ceil(n / COLS);
  const snap = (v: number) => Math.round(v * 2) / 2;
  const pos = Array.from({ length: n }, (_, k) => ({ x: snap(PAD + (k % COLS) * (cw + GAP)), y: snap(PAD + Math.floor(k / COLS) * (CELL_H + GAP)) }));
  const h = rows ? PAD + rows * CELL_H + (rows - 1) * GAP + PAD : 0;
  return { cw, ch: CELL_H, h, pos };
}

export function cellDelay(k: number): number { return 80 + k * 45; }

/** Rust `tpshover-open` 给的版面（`mode: "idle"` 那份）。只取这里要的几样。 */
export interface IdleLayout {
  panel: { x: number; y: number };
  segments: { platform: string; logo: { x: number; y: number; size: number } }[];
}

export function parseIdleLayout(raw: unknown): IdleLayout | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (o.mode !== "idle") return null;
  const p = o.panel as Record<string, unknown> | undefined;
  if (!p || typeof p.x !== "number" || typeof p.y !== "number") return null;
  const segs = Array.isArray(o.segments) ? (o.segments as IdleLayout["segments"]).filter((s) =>
    s && typeof s.platform === "string" && s.logo && typeof s.logo.x === "number" && typeof s.logo.y === "number") : [];
  return { panel: { x: p.x, y: p.y }, segments: segs };
}

export interface IdleFlight {
  key: string;
  /** 托盘里那个 logo 在不在（不在 = 原位淡入淡出，不飞）。 */
  fromTray: boolean;
  /** 窗口坐标；`s` 是相对 `PILL_LOGO` 的缩放。 */
  pill: { x: number; y: number; s: number };
  cell: { x: number; y: number };
  delay: number;
  delayBack: number;
}

/**
 * 每一格 logo 的起落点（窗口坐标，图片左上角）。面板描边 1 px 也算进去（格子坐标从描边内侧起）。
 * ★ 托盘里的几家按托盘顺序错开 25 ms 起飞；关闭时倒序飞回（最右的先走）。
 */
export function planIdleFlights(layout: IdleLayout, keys: string[], g: GridLayout, px: number, py: number): IdleFlight[] {
  const tray = layout.segments.map((s) => s.platform);
  const n = keys.filter((k) => tray.includes(k)).length;
  return keys.map((key, i) => {
    const seg = layout.segments.find((s) => s.platform === key);
    const c = g.pos[i];
    // 缩放以图片中心为原点（CSS 默认 transform-origin 50% 50%）⇒ 左上角要按缩放前的尺寸对齐中心
    const cx = px + 1 + c.x + g.cw / 2, cy = py + 1 + c.y + RING_TOP + RING / 2;
    const j = tray.indexOf(key);
    return {
      key, fromTray: !!seg,
      pill: seg ? { x: seg.logo.x, y: seg.logo.y, s: 1 } : { x: cx - PILL_LOGO / 2, y: cy - PILL_LOGO / 2, s: 0.7 },
      cell: { x: cx - PILL_LOGO / 2, y: cy - PILL_LOGO / 2 },
      delay: j >= 0 ? j * FLY_STAGGER : 0,
      delayBack: j >= 0 ? (n - 1 - j) * FLY_STAGGER : 0,
    };
  });
}

/** 落进环心时的缩放。 */
export const CELL_SCALE = LOGO / PILL_LOGO;

/** 面板底部「已隐藏 X · 撤销」一行的高（B1，用户 2026-10-22）。 */
export const NOTE_H = 22;
