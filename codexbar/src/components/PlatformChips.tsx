import PlatformLogo, { type LogoPlatform } from "./PlatformLogo";
import { numColor, type PlatformKey } from "../live";
import { MONO } from "./mb/vars";

/** 菜单栏的平台档。★ 比主窗的 `PoolKey` 多一个 `claude`（交接包 4f：Codex · Claude · Gemini · Grok）。 */
export type MbPlat = "codex" | "claude" | "gemini" | "grok";

export interface ChipItem {
  key: MbPlat;
  label: string;
  /** 这一档**渲染出来**几个号。写"池里有几个"就是在说界面上看不到的事。 */
  count: number;
  /** 这一档有没有失效账号 —— 数字后跟一颗红点。 */
  hasDead?: boolean;
}

/** 档位 → logo / 数字色用的平台键（请求账本那套：Gemini 的键是 `agy`）。 */
export const LOGO_OF: Record<MbPlat, LogoPlatform & PlatformKey> = { codex: "codex", claude: "claude", gemini: "agy", grok: "grok" };

/**
 * 菜单栏的**平台芯片行**（交接包 2026-10-19 · 4f「平台芯片 28」，`P4PopRows.html` 第 53 行逐值照抄）。
 *
 * ★ 2026-10-19 起用**官方彩色 logo**（`PlatformLogo`，资产内置、不远程加载），取代 v4 稿的蒙版单色图：
 *   交接包规定「logo 任何状态都不变暗」，选中 / 未选中只换芯片的底色、描边与数字色（平台数字色）。
 * ★ 顺序固定 Codex → Claude → Gemini → Grok。Grok 原来带锁（只读），用户 2026-10-23「解锁吧，看着不舒服」⇒ 去掉。
 */
export default function PlatformChips({ items, cur, on, right, isDark }: {
  items: ChipItem[];
  cur: MbPlat;
  on: (k: MbPlat) => void;
  /** 右侧小字 `↻ HH:MM`（当前这一档上次刷新的时刻）。 */
  right?: React.ReactNode;
  isDark: boolean;
}): React.ReactElement {
  return (
    <div className="mb-chips2" style={{ display: "flex", alignItems: "center", gap: 6, height: 44, padding: "0 12px",
                                        flexShrink: 0 }}>
      {items.map((p) => {
        const sel = p.key === cur;
        const pc = numColor(LOGO_OF[p.key], isDark ? "dark" : "light");
        return (
          <button key={p.key} type="button" className="mb-chip2" data-mb-chip={p.key} data-on={sel ? "1" : "0"}
                  onClick={() => on(p.key)} title={`${p.label} · ${p.count} 号`}
                  style={{ display: "flex", alignItems: "center", gap: 5, height: 28, padding: "0 8px 0 6px",
                           borderRadius: 14, cursor: "pointer", fontFamily: "inherit", flexShrink: 0,
                           background: sel ? `${pc}22` : "transparent",
                           border: `1px solid ${sel ? `${pc}99` : "var(--line)"}` }}>
            <PlatformLogo platform={LOGO_OF[p.key]} isDark={isDark} size={16} alt={p.label} />
            <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12, fontWeight: 600,
                           color: sel ? pc : "var(--tx2)", transition: "color 200ms" }}>{p.count}</span>
            {/* 死号提示：只在真有死号时出现 —— 常亮的灯会被学会忽略。 */}
            {p.hasDead && <span className="mb-chip-dead" />}
          </button>
        );
      })}
      {right && <span style={{ marginLeft: "auto", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 11,
                               color: "var(--tx3)", whiteSpace: "nowrap" }}>{right}</span>}
    </div>
  );
}
