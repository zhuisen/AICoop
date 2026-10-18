// 刘海光晕画什么（纯函数，零 import —— 测试用 `node --experimental-strip-types` 直接跑，CI 没有 node_modules）。

/** 谁正在跑。与 `notch.rs::Activity` 同形（Rust 变了才推 `notch-activity`）。 */
export interface NotchActivity { codex: boolean; claude: boolean; agy: boolean; grok: boolean }

export const NO_ACTIVITY: NotchActivity = { codex: false, claude: false, agy: false, grok: false };

/** 光晕里从左到右的顺序。固定顺序：同一组平台在跑时，颜色位置不随推送先后跳动。 */
export const GLOW_ORDER = ["codex", "claude", "agy", "grok"] as const;

/**
 * 正在跑、且没在设置里关掉的平台各自的颜色（按 `GLOW_ORDER`）。
 * ★ 维护者 2026-10-18：**空闲时不亮** —— 没有平台在跑就返回空，光晕整个隐藏。
 *   PR #1 原设计是空闲时显示额度色、慢呼吸；这里不再用光晕表示额度，额度看悬停面板。
 */
export function glowColors(act: NotchActivity, isOff: (k: string) => boolean,
                           colorOf: (k: string) => string): string[] {
  return GLOW_ORDER.filter((k) => act[k] && !isOff(k)).map((k) => colorOf(k));
}

/** 颜色 → 光晕的背景。一家 = 纯色；多家 = 横向渐变，第 i 家的色标在 (i+.5)/n（每家占一段）。没有 = 空串。 */
export function glowBackground(colors: string[]): string {
  if (colors.length === 0) return "";
  if (colors.length === 1) return colors[0];
  const n = colors.length;
  return `linear-gradient(90deg, ${colors.map((c, i) => `${c} ${(((i + 0.5) / n) * 100).toFixed(1)}%`).join(", ")})`;
}
