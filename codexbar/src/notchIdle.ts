/**
 * 刘海屏版空闲额度格子（AICoop 交接包 2026-10-21 · `11_idle/P11_NotchHover`；画板 1.5× 画、刘海 270×48，这里一律 ÷1.5）。
 * ★ 零 import：测试用 `node --experimental-strip-types` 直接加载（CLAUDE.md §4）。
 *
 * 画板（1.5×）→ 这里（1×）：
 *   面板宽 450 → 300（= 4e 卡片宽 `CARD_W`，Rust 命中区直接复用）· 顶 63 → 42（刘海 32 + 10 pt 光桥）
 *   内边距 9 → 6 · 圆角 18 → 12 · 格间距 6 → 4 · 一行 4 格 ⇒ 格宽 (300 − 12 − 12)/4 = 69
 *   格高 112 → 74.67（吸到 74.5：Retina 整物理像素）· 格圆角 12 → 8
 *   环 48 → 32（r 20 → 13.33，线宽 4 → 2.67，顶 22 → 14.67）· logo 20 → 13（顶 36 → 24，按环心对齐）
 *   大数字 15 px → 10 px（顶 80 → 53.33）· 右上角重置 10.5 → 7 px（右 8 → 5.33，顶 6 → 4）
 *   光桥 2 × 15 → 1.5 × 10（透明 → rgba(233,237,243,.5)）· 刘海版**没有**托盘面板那颗「在菜单栏」白点
 *   面板阴影 `0 24 60` → `0 16 40`（正好装进窗口留的透明边 40 / 58）· 入场位移 −10 → −6.67
 * 光晕（中性冷白，「这里能点」）：刘海形 box-shadow `0 4 26 6 / .30` + 1 px 描边 `.18`，
 *   外加一团椭圆（370 × 70，顶 30，blur 6 → 246.67 × 46.67，顶 20，blur 4）；
 *   有一家剩余 < 10% ⇒ 右肩叠珊瑚红一团（`70 4 18 1 / .55` → `46.67 2.67 12 .67`）+ 小红点（10 → 7，刘海右沿外 11 → 7、顶 18 → 12）。
 */

// ★ 用户 2026-10-21「刘海屏版本也要改」（选「和托盘一样 1.5×」）：格子面板改成与托盘悬停面板**同一套**尺寸
//   （`idleGridLayout.ts`：P11 2× 画板 × 0.75），取代上面那组 ÷1.5 的面板 / 格子 / 环 / 字（光晕、光桥仍按刘海画板 ÷1.5）。
//   面板宽 435 与 Rust `tps_hover::IDLE_PANEL_W` 同值（`notch.rs::card_w` 直接用它）。
export const PANEL_W = 435;
export const PANEL_GAP = 10;
export const PAD = 8;
export const GAP = 6;
export const COLS = 4;
export const RADIUS = 15;
export const CELL_H = 100.5;
export const CELL_R = 10.5;
export const RING = 48;
export const RING_R = 20.25;
export const RING_SW = 3.75;
export const RING_TOP = 19.5;
export const RING_C = 2 * Math.PI * RING_R;
export const LOGO = 20;
export const MAIN_TOP = 73.5;
export const MAIN_PX = 15;
export const RESET_PX = 10.5;
export const LOW = "#FF8A73";
/** 底部「已隐藏 X … · 撤销」一行的高（同悬停面板 `idleGridLayout.ts::NOTE_H`）。 */
export const NOTE_H = 22;
/** 展开时光晕降到 55%（画板「光晕降到 55%」）。 */
export const OPEN_GLOW = 0.55;
/** 靠近 200 ms 淡入；离开 300 ms 后才开始淡出。 */
export const GLOW_IN_MS = 200;
export const GLOW_OUT_DELAY_MS = 300;

export interface NotchGrid { cw: number; ch: number; h: number; pos: { x: number; y: number }[] }

/** n 格的版面（面板内坐标）。没有格子 ⇒ 高度 0。 */
export function notchGrid(n: number, notes = 0): NotchGrid & { noteTop: number } {
  const cw = (PANEL_W - 2 * PAD - GAP * (COLS - 1)) / COLS;
  const rows = Math.ceil(n / COLS);
  const pos = Array.from({ length: n }, (_, k) => ({ x: PAD + (k % COLS) * (cw + GAP), y: PAD + Math.floor(k / COLS) * (CELL_H + GAP) }));
  const gh = rows ? PAD + rows * CELL_H + (rows - 1) * GAP + PAD : 0;
  // ★ 「已隐藏」行（全方面评审 §9：刘海原来不画，藏了的那家在刘海上没有撤销入口）。全藏了也照画
  const noteTop = rows ? gh - PAD + 2 : PAD - 2;
  const h = notes ? noteTop + notes * NOTE_H + PAD - 2 : gh;
  return { cw, ch: CELL_H, h, pos, noteTop };
}

const WHITE_SH = "0 2.67px 17.33px 4px rgba(233,237,243,.30), 0 0 0 1px rgba(233,237,243,.18)";
const LOW_SH = ", 46.67px 2.67px 12px .67px rgba(255,138,115,.55)";

/** 刘海形那层的 box-shadow：中性白；有一家低额度 ⇒ 右肩再叠一团珊瑚红。 */
export function idleGlowShadow(low: boolean): string {
  return WHITE_SH + (low ? LOW_SH : "");
}

/**
 * 中性光晕（含小红点）此刻的不透明度。
 * ★ 跟这一轮展开的种类走：空闲格子开着 ⇒ 55%（中途 AI 开跑也不变，收起后再换）；4e 卡片开着 ⇒ 不亮。
 * ★ 收起时：只在没有 AI 在跑、Rust 说「靠近」时亮（Rust 只在碰下去会开空闲格子时才报靠近）。
 * ★ 减弱动态效果时不显示（画板原文）。
 */
export function idleGlowOpacity(o: { lit: boolean; reduce: boolean; near: boolean; idleOpen: boolean; cardOpen: boolean }): number {
  if (o.reduce || o.cardOpen) return 0;
  if (o.idleOpen) return OPEN_GLOW;
  return !o.lit && o.near ? 1 : 0;
}

/** 光晕的过渡：亮起 200 ms 淡入；熄灭先等 300 ms 再淡出（离开靠近区 / 收起时面板先走、光晕后收）。 */
export function idleGlowTransition(op: number): string {
  return `opacity ${GLOW_IN_MS}ms ease-out ${op > 0 ? 0 : GLOW_OUT_DELAY_MS}ms`;
}

/** 点格子去哪：有总览档的四家 ⇒ 总览；Kimi / DeepSeek ⇒ 用量详情（同托盘面板）。 */
export function cellTarget(key: string): { page: "overview" | "traffic"; platform: string } {
  const overview = key === "codex" || key === "claude" || key === "agy" || key === "grok";
  return { page: overview ? "overview" : "traffic", platform: key };
}
