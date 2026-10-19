import { mbVars } from "../mb/vars";

/**
 * 总览（交接包 page5 `code/P5DemoA.html`）的配色变量。在菜单栏那套 `mbVars`（page4，同一个交接包、
 * 同一组 tx/acc/warn/bad 值）上**只补总览独有的几个面**，逐值照抄原型的内联样式。
 * 组件里一律 `var(--x)`，与原型一一对应，方便逐像素对照。
 *
 * ★ 浅色：交接包只画了深色。浅色值沿用 `mbVars` 的 LIGHT（已过 `test_theme_contrast` 的三级灰），
 *   这里补的几个面按「深色是白 7–16%、浅色是黑 6–16%」对称取（PLAN §4 偏离记录）。
 */
const DARK_EXTRA: Record<string, string> = {
  "--ovCard": "#141a22", "--ovCardH": "#18202a", "--ovLineH": "rgba(255,255,255,.16)",
  "--ovOff": "#10151c", "--ovSegTx": "#071015", "--ovBackTx": "#e6eef8", "--ovPh": "#5d6773",
  "--ovTabBg": "#0a0e13", "--ovTabLine": "rgba(255,255,255,.07)", "--ovDotRing": "#0d1117",
  "--ovAb": "#c4ccd6", "--ovAbLine": "rgba(255,255,255,.12)", "--ovFoot": "rgba(255,255,255,.06)",
  "--ovBtnLine": "rgba(255,255,255,.1)", "--ovGrpLine": "rgba(255,255,255,.08)",
  "--ovTrackBar": "rgba(255,255,255,.04)", "--ovTick": "rgba(255,255,255,.08)",
  "--ovSwOff": "rgba(255,255,255,.14)", "--ovNum": "#5eead4", "--ovNextTx": "#062b27",
  "--ovTagOff": "rgba(255,255,255,.06)", "--ovStripLine": "rgba(255,255,255,.12)",
  "--ovMenu": "#1b2330", "--ovMenuShadow": "0 12px 32px rgba(0,0,0,.5)",
  "--ovBdIn": "rgba(45,212,191,.5)", "--ovBdCool": "rgba(245,181,68,.35)", "--ovBdBad": "rgba(255,77,46,.35)",
  "--ovTagIn": "rgba(45,212,191,.12)", "--ovTagWarn": "rgba(245,181,68,.12)", "--ovTagBest": "rgba(45,212,191,.08)",
  "--ovB5": "#2dd4bf", "--ovBw": "#22b573", "--ovWarnTx": "#f5b544",
};
const LIGHT_EXTRA: Record<string, string> = {
  "--ovCard": "#ffffff", "--ovCardH": "#f6f8fb", "--ovLineH": "rgba(15,23,42,.18)",
  "--ovOff": "#f4f6f9", "--ovSegTx": "#071015", "--ovBackTx": "#161b22", "--ovPh": "#606b77",
  "--ovTabBg": "#e6eaf0", "--ovTabLine": "rgba(15,23,42,.08)", "--ovDotRing": "#eef1f5",
  "--ovAb": "#4d5663", "--ovAbLine": "rgba(15,23,42,.14)", "--ovFoot": "rgba(15,23,42,.07)",
  "--ovBtnLine": "rgba(15,23,42,.12)", "--ovGrpLine": "rgba(15,23,42,.10)",
  "--ovTrackBar": "rgba(15,23,42,.05)", "--ovTick": "rgba(15,23,42,.10)",
  "--ovSwOff": "rgba(15,23,42,.18)", "--ovNum": "#0a7a6e", "--ovNextTx": "#ffffff",
  "--ovTagOff": "rgba(15,23,42,.06)", "--ovStripLine": "rgba(15,23,42,.16)",
  "--ovMenu": "#ffffff", "--ovMenuShadow": "0 12px 32px rgba(15,23,42,.18)",
  "--ovBdIn": "rgba(14,159,142,.5)", "--ovBdCool": "rgba(183,121,31,.35)", "--ovBdBad": "rgba(229,57,27,.32)",
  "--ovTagIn": "rgba(14,159,142,.10)", "--ovTagWarn": "rgba(183,121,31,.10)", "--ovTagBest": "rgba(14,159,142,.07)",
  "--ovB5": "#0e9f8e", "--ovBw": "#16a34a",
  // ★ 琥珀 / 青**当文字**用时的浅色值：`--warn` #b7791f、`--acc` #0e9f8e 在白卡上只有 3.4 / 3.3
  //   （`tests/test_card_action_bar.py` 实测「探针」3.42 不过 4.5）。图形（环 / 条）仍用原色。
  "--ovWarnTx": "#8a5a0e",
};

export function ovVars(isDark: boolean): Record<string, string> {
  return { ...mbVars(isDark), ...(isDark ? DARK_EXTRA : LIGHT_EXTRA) };
}

export const MONO = "'JetBrains Mono', monospace";
