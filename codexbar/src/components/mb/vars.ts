// 菜单栏弹窗的配色变量 —— 交接包 page4 `code/P4PopRows.html` 的 `VARS`，逐值照抄。
// 组件里一律写 `var(--x)`，与画板的内联样式一一对应，方便逐像素对照。
//
// ★ 一处刻意偏离：**浅色主题的三级中性文字用 `theme.ts` 的值，不用画板的**。
//   画板 `--tx3: #7b8794` 在白底上只有 ~3.6:1，低于本仓 `tests/test_theme_contrast.py`
//   守的 4.5:1（用户 2026-08-23 定的 B 档三级灰）。深色三级灰两边本来就一样。

const SPRING = "linear(0.000, 0.041, 0.135, 0.250, 0.366, 0.475, 0.572, 0.655, 0.725, 0.782, 0.829, 0.866, 0.896, 0.919, 0.938, 0.952, 0.963, 0.972, 0.979, 0.984, 0.988, 0.991, 0.993, 0.995, 0.996, 0.997, 0.998, 0.998, 0.999, 0.999, 1.000)";

const DARK: Record<string, string> = {
  "--bg": "#0e1117", "--pop": "#11161d", "--card": "#171e27", "--card2": "#141a22",
  "--line": "rgba(255,255,255,.07)", "--line2": "rgba(255,255,255,.12)",
  "--tx": "#eef2f7", "--tx2": "#aab3c0", "--tx3": "#798390",
  "--acc": "#2dd4bf", "--accTx": "#062b27", "--track": "rgba(255,255,255,.08)",
  "--b5": "#2dd4bf", "--bw": "#22b573", "--warn": "#f5b544", "--warnBg": "rgba(245,181,68,.10)",
  "--warnLine": "rgba(245,181,68,.35)", "--bad": "#FF4D2E", "--seg": "#0b0f14",
  "--cx": "#5eead4", "--cl": "#F09A76", "--ge": "#7ab8ff", "--gr": "#b9aefb",
  "--shadow": "0 24px 60px rgba(0,0,0,.55)", "--hov": "rgba(255,255,255,.05)",
  "--accSoft": "rgba(45,212,191,.14)", "--accLine": "rgba(45,212,191,.45)", "--hov2": "rgba(255,255,255,.06)",
  "--cardh": "#1b2330", "--badBg": "rgba(255,77,46,.12)", "--badLine": "rgba(255,77,46,.4)",
  "--warnBg2": "rgba(245,181,68,.22)", "--badTx": "#FF8A73", "--goodBg": "rgba(34,181,115,.12)",
  "--sp": SPRING,
};

const LIGHT: Record<string, string> = {
  "--bg": "#eef1f5", "--pop": "#ffffff", "--card": "#f4f6f9", "--card2": "#f7f8fa",
  "--line": "rgba(15,23,42,.08)", "--line2": "rgba(15,23,42,.14)",
  "--tx": "#161b22", "--tx2": "#4d5663", "--tx3": "#606b77",
  "--acc": "#0e9f8e", "--accTx": "#ffffff", "--track": "rgba(15,23,42,.08)",
  "--b5": "#0e9f8e", "--bw": "#16a34a", "--warn": "#b7791f", "--warnBg": "rgba(183,121,31,.08)",
  "--warnLine": "rgba(183,121,31,.3)", "--bad": "#e5391b", "--seg": "#e9edf2",
  "--cx": "#0e9f8e", "--cl": "#c2562f", "--ge": "#2b6fd6", "--gr": "#6b5bd6",
  "--shadow": "0 24px 60px rgba(15,23,42,.18)", "--hov": "rgba(15,23,42,.04)",
  "--accSoft": "rgba(14,159,142,.10)", "--accLine": "rgba(14,159,142,.4)", "--hov2": "rgba(15,23,42,.05)",
  "--cardh": "#eef2f6", "--badBg": "rgba(229,57,27,.07)", "--badLine": "rgba(229,57,27,.3)",
  "--warnBg2": "rgba(183,121,31,.16)", "--badTx": "#e5391b", "--goodBg": "rgba(22,163,74,.10)",
  "--sp": SPRING,
};

export function mbVars(isDark: boolean): Record<string, string> {
  return isDark ? DARK : LIGHT;
}

/** 平台数字色变量名（`--cx/--cl/--ge/--gr`），按请求账本的平台键。 */
export const NUM_VAR: Record<string, string> = {
  codex: "var(--cx)", claude: "var(--cl)", agy: "var(--ge)", grok: "var(--gr)",
};

export const MONO = "'JetBrains Mono', monospace";
