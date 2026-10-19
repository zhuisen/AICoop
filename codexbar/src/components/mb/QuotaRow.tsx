import type { ReactNode } from "react";
import PlatformLogo, { type LogoPlatform } from "../PlatformLogo";
import { isLow } from "../../mbLogic";
import { MONO } from "./vars";

/** 一个额度窗口格。`pct: null` = 这一格读不到（画 —，不画 0）。 */
export interface WinCell {
  label: string;
  pct: number | null;
  /** ↻ 回满时间的短文本（`2h05m` / `6d21h` / `未启动`）；读不到写 —。 */
  refill: string;
  refillTitle?: string;
  /** 沿用的旧读数：降不透明度（与总览卡同一画法）。 */
  dim?: boolean;
  title?: string;
}

/**
 * 菜单栏账号行（交接包 4f「账号行」，`P4PopRows.html` 的 `.qrow`，逐值照抄）：
 *   logo · 号名 + 小字状态 · 5h 条 + %（下一行 ↻ 回满）· 周条 + %（同）· [悬停长出的「切换」]
 *
 * ★ 四家（Codex / Claude / Gemini / Grok）共用这一个外形，数据各走各的通路（`AccountRow` /
 *   `ClaudeRow` / `AgyRow` / `GrokRow` 只负责把自己的数据翻译成这些 props）。
 * ★ 点行内容 = `onOpen`（跳工作台总览对应 AI 档）；「切换」按钮**必须 stopPropagation**，
 *   否则点切换会同时弹出主窗口（ui.md「菜单栏账号行的尾部切换按钮」）。
 * ★ 悬停只让**最右一列**从 0 长到 46（`menubar.css` `.qrow`），两根条跟着缩，数据不被盖住。
 *   在用 / 只读的号（`readOnly`）只提亮、不出按钮。
 */
export default function QuotaRow({ platform, isDark, name, nameColor, sub, wins, note, readOnly,
                                   onSwitch, switching, switchTitle, onOpen, opacity, title, data }: {
  platform: LogoPlatform;
  isDark: boolean;
  name: string;
  /** 默认 `--tx`；低额度时组件自己改成 `--bad`。 */
  nameColor?: string;
  /** 号名下一行的小字（在用 / 下一个 / 未探测 / 只读 / -15% …）。 */
  sub?: ReactNode;
  /** 两个固定槽位 5h / 周；`null` 槽 = 这家根本没有这个窗口（Grok 的 5h）。 */
  wins?: [WinCell | null, WinCell | null];
  /** 没有额度可画时，占两格的一句话（「未探测 · 刷新一次后显示额度」）。 */
  note?: ReactNode;
  readOnly: boolean;
  onSwitch?: () => void;
  switching?: boolean;
  switchTitle?: string;
  onOpen?: () => void;
  opacity?: number;
  title?: string;
  /** 给闸用的 data-* 属性。 */
  data?: Record<string, string>;
}) {
  const low = !!wins && wins.some((w) => w != null && isLow(w.pct));
  const canSwitch = !readOnly && !!onSwitch;
  return (
    <div className={`qrow${canSwitch ? "" : " qro"}${low ? " qlow" : ""}`} {...data}
         onClick={switching ? undefined : onOpen} title={title}
         style={{ height: 42, padding: "0 10px 0 12px", borderTop: "1px solid var(--line)",
                  background: low ? "var(--badBg)" : "transparent",
                  cursor: onOpen && !switching ? "pointer" : "default", opacity: opacity ?? 1 }}>
      <PlatformLogo platform={platform} isDark={isDark} size={16} />
      <span className="mb-row-info" style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 1,
                     minWidth: 0, lineHeight: 1.2 }}>
        <span className="mb-row-name" style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap",
                       overflow: "hidden", textOverflow: "ellipsis",
                       color: low ? "var(--bad)" : nameColor ?? "var(--tx)" }}>{name}</span>
        <span style={{ fontSize: 9.5, whiteSpace: "nowrap", overflow: "hidden" }}>{sub}</span>
      </span>
      {wins ? wins.map((w, i) => <Cell key={i} w={w} label={i === 0 ? "5h" : "周"} />)
        : <span style={{ gridColumn: "span 2", fontSize: 11.5, color: "var(--tx3)", whiteSpace: "nowrap",
                         overflow: "hidden", textOverflow: "ellipsis" }}>{note}</span>}
      <span style={{ overflow: "hidden", display: "flex", justifyContent: "flex-end" }}>
        {canSwitch && (
          <span className="sw2" role="button" title={switchTitle}
                onClick={(e) => { e.stopPropagation(); if (!switching) onSwitch?.(); }}
                style={{ display: "flex", alignItems: "center", height: 24, padding: "0 9px", borderRadius: 7,
                         background: switching ? "var(--hov2)" : "var(--acc)",
                         color: switching ? "var(--tx3)" : "var(--accTx)", fontSize: 11.5, fontWeight: 600,
                         whiteSpace: "nowrap", cursor: switching ? "default" : "pointer" }}>
            {switching ? "切换中…" : "切换"}
          </span>
        )}
      </span>
    </div>
  );
}

function Cell({ w, label }: { w: WinCell | null; label: string }) {
  if (!w) {
    return (
      <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--tx3)" }}>
        <span style={{ width: 13 }}>{label}</span>—
      </span>
    );
  }
  const low = isLow(w.pct);
  const bar = low ? "var(--bad)" : w.label === "5h" ? "var(--b5)" : "var(--bw)";
  return (
    <span data-win={w.label} title={w.title}
          style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, opacity: w.dim ? .62 : 1 }}>
      <span style={{ width: 13, fontSize: 11, color: "var(--tx3)", flexShrink: 0 }}>{w.label}</span>
      <span style={{ display: "block", flex: 1, minWidth: 14, height: 4, borderRadius: 4,
                     background: "var(--track)", overflow: "hidden" }}>
        <span className="qbar" style={{ display: "block", width: `${w.pct == null ? 0 : Math.max(0, Math.min(100, w.pct))}%`,
                       height: "100%", borderRadius: 4, background: bar }} />
      </span>
      <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", lineHeight: 1.15, flexShrink: 0 }}>
        <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12, fontWeight: 600,
                       whiteSpace: "nowrap", color: w.pct == null ? "var(--tx3)" : low ? "var(--bad)" : "var(--tx)" }}>
          {w.pct == null ? "—" : `${Math.round(w.pct)}%`}
        </span>
        <span title={w.refillTitle} style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 9.5,
                       whiteSpace: "nowrap", color: "var(--tx3)" }}>↻{w.refill}</span>
      </span>
    </span>
  );
}
