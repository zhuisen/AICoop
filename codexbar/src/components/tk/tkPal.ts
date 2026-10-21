import type { Theme } from "../../theme";
import type { LogoPlatform } from "../PlatformLogo";

/**
 * Token 消耗页（R2）的配色。深色照稿；稿只画了深色 ⇒ 浅色走主题 token
 * （P3 浅色平台数字色 `#0E9F8E / #C2562F / #2B6FD6 / #6B5BD6`）。
 */
export interface TkPal {
  panel: string; panel2: string; border: string; line: string; hair: string;
  text: string; text2: string; label: string; accent: string; accentOn: string;
  amber: string; up: string; down: string; tipBg: string; tipBorder: string; track: string;
  selAll: string; selAllBorder: string; idleBorder: string; hoverRow: string; axis: string;
}

export function tkPal(t: Theme): TkPal {
  if (t.isDark) return {
    panel: "#141a22", panel2: "rgba(255,255,255,.025)", border: "rgba(255,255,255,.07)",
    line: "rgba(255,255,255,.1)", hair: "rgba(255,255,255,.06)",
    text: "#eef2f7", text2: "#aab3c0", label: "#8f99a6", accent: "#2dd4bf", accentOn: "#062b27",
    // ★ 涨跌沿用全局语义色（`ui-design.md`；稿里是 #22c58b / #ff8a73，偏离 R2-9）。
    amber: "#f5b544", up: "#27B26B", down: "#E0524D",
    tipBg: "#11161d", tipBorder: "rgba(255,255,255,.12)", track: "rgba(255,255,255,.07)",
    selAll: "rgba(255,255,255,.08)", selAllBorder: "rgba(255,255,255,.24)",
    idleBorder: "rgba(255,255,255,.08)", hoverRow: "rgba(255,255,255,.05)", axis: "rgba(255,255,255,.22)",
  };
  return {
    panel: t.cardBg, panel2: "rgba(0,0,0,.02)", border: t.cardBorder, line: "rgba(0,0,0,.1)",
    hair: "rgba(0,0,0,.06)", text: t.text, text2: t.text2, label: t.muted, accent: t.accent,
    accentOn: t.accentText, amber: "#9a6512", up: "#1d8f55", down: "#c23f3a",
    tipBg: "#ffffff", tipBorder: "rgba(0,0,0,.12)", track: "rgba(0,0,0,.07)",
    selAll: "rgba(0,0,0,.06)", selAllBorder: "rgba(0,0,0,.24)", idleBorder: "rgba(0,0,0,.1)",
    hoverRow: "rgba(0,0,0,.04)", axis: "rgba(0,0,0,.25)",
  };
}

const NUM_DARK: Record<string, string> = {
  codex: "#5EEAD4", claude: "#F09A76", agy: "#7AB8FF", grok: "#B9AEFB", kimi: "#F59AC8", deepseek: "#A3AEFF",
};
const NUM_LIGHT: Record<string, string> = {
  codex: "#0E9F8E", claude: "#C2562F", agy: "#2B6FD6", grok: "#6B5BD6", kimi: "#b8407e", deepseek: "#4352c8",
};
/** 平台「浅色数字色」（卡片大数、浮层数值）。未登记的平台回落到平台色本身。 */
export function numColor(t: Theme, key: string, fallback: string): string {
  return (t.isDark ? NUM_DARK : NUM_LIGHT)[key] ?? fallback;
}

const LOGO_KEYS = new Set<string>(["codex", "claude", "agy", "grok", "kimi", "deepseek"]);
export function logoKey(k: string): LogoPlatform | null {
  return LOGO_KEYS.has(k) ? (k as LogoPlatform) : null;
}

export const MONO = "'JetBrains Mono','PingFang SC',monospace";
export const EASE = "cubic-bezier(.2,.9,.3,1)";
export const SPR9 = "linear(0, 0.18, 0.45, 0.68, 0.83, 0.92, 0.97, 0.99, 1)";
