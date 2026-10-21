import codexOnDark from "../assets/logos/codex-on-dark.svg";
import codexBrand from "../assets/logos/codex-brand.svg";
import codexOnColor from "../assets/logos/codex-on-color.svg";
import claudeColor from "../assets/logos/claudecode-color-eyes.svg";
import claudeOnColor from "../assets/logos/claudecode-on-color.svg";
import geminiColor from "../assets/logos/gemini-color.svg";
import geminiOnColor from "../assets/logos/gemini-on-color.svg";
import grokOnDark from "../assets/logos/grok-on-dark.svg";
import grokOnLight from "../assets/logos/grok-on-light.svg";
import grokOnColor from "../assets/logos/grok-on-color.svg";
import kimiOnDark from "../assets/logos/kimi-on-dark.svg";
import kimiOnLight from "../assets/logos/kimi-on-light.svg";
import deepseekColor from "../assets/logos/deepseek-color.svg";

/**
 * 官方 logo（交接包 2026-10-19 `assets/logos/` 四家 + 2026-10-21 Kimi / DeepSeek，LobeHub icons-static-svg，MIT）。
 *
 * 变体选择照交接包 README「Logo」节，**不要自己换**：
 * - Codex：深色底 `codex-on-dark`；浅色底 `codex-brand`（品牌蓝紫渐变、透明底）。
 *   ⚠️ 不用 `codex-color`（自带白底）—— 所以那份根本没拷进来。
 * - Claude Code：两种主题都用 `claudecode-color-eyes`（眼睛补黑，浅色底不透白）。
 * - Gemini（agy）：`gemini-color`。显示名叫 Gemini。
 * - Grok：深色底 `grok-on-dark`，浅色底 `grok-on-light`。
 * - 托盘胶囊单色：`*-on-color`（`variant="mono"`）。
 *
 * ★ **logo 任何状态都不变暗**（交接包：35% 变暗会把彩色 logo 压成灰色）。所以这个组件
 *   不接收 opacity，外层容器降透明度时调用方要把 logo 放到降透明度的元素之外。
 * ★ 资产内置（vite 打包），不远程加载 —— 离线也得有 logo。
 */
export type LogoPlatform = "codex" | "claude" | "agy" | "grok" | "kimi" | "deepseek";

const LOGOS: Record<LogoPlatform, { dark: string; light: string; mono: string }> = {
  codex: { dark: codexOnDark, light: codexBrand, mono: codexOnColor },
  claude: { dark: claudeColor, light: claudeColor, mono: claudeOnColor },
  agy: { dark: geminiColor, light: geminiColor, mono: geminiOnColor },
  grok: { dark: grokOnDark, light: grokOnLight, mono: grokOnColor },
  // Kimi / DeepSeek（AICoop 交接包 2026-10-21 只给了这一种）：空闲托盘与它的悬停面板用。
  // Kimi 只给了白字版 ⇒ 浅色底用同一份把字改成 #161b22、**蓝点保留 #027AFF**（`kimi-on-light.svg`）。
  // ✗ 不用 `invert(1)`：那会把蓝点反成橙色，等于给品牌换色（P11 §3「不换颜色」，评审 2026-10-21）。
  kimi: { dark: kimiOnDark, light: kimiOnLight, mono: kimiOnDark },
  deepseek: { dark: deepseekColor, light: deepseekColor, mono: deepseekColor },
};

export function logoSrc(platform: LogoPlatform, isDark: boolean, variant: "auto" | "mono" = "auto"): string {
  const l = LOGOS[platform];
  if (variant === "mono") return l.mono;
  return isDark ? l.dark : l.light;
}

export default function PlatformLogo({ platform, isDark, size = 14, variant = "auto", alt = "" }: {
  platform: LogoPlatform;
  isDark: boolean;
  size?: number;
  variant?: "auto" | "mono";
  alt?: string;
}) {
  return (
    <img src={logoSrc(platform, isDark, variant)} width={size} height={size} alt={alt}
         data-logo={platform} draggable={false}
         style={{ display: "block", flexShrink: 0 }} />
  );
}
