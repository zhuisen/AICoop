import { useEffect, useRef, useState, type ReactNode } from "react";
import PlatformLogo, { type LogoPlatform } from "../PlatformLogo";
import ProbeBtn from "../mb/ProbeBtn";
import { IcMore, IcRefresh } from "./OvCard";
import { MONO } from "./ovVars";
import type { OvLayout } from "../../overview";

/**
 * 总览头部（交接包 page5「头部（高 32）」）：
 * `总览` · 平台档 · 弹性空白 · 刷新全池 · 探针（计费）· [定时 | 自动切号] 开关组 · ⋯
 *
 * ★ 平台档：logo + 名称 + 号数，顺序 Codex → Claude → Gemini → Grok（同光晕）；有告警时右上角红点；
 *   Grok 带锁（只读）。860 档只留 logo + 数字（`layout.tabNames`）。
 * ★ 1000 档起「刷新 / 定时 / 自动切号」只留图标 + 开关（`layout.labels`）。
 * ★ 每一档只放**这一档真有**的动作（旧头部的规矩）：探针扣的是那一家的钱，挂错档 = 看着 A 的卡、花 B 的额度。
 */
export type OvTabKey = "codex" | "claude" | "gemini" | "grok";
export interface OvTab {
  key: OvTabKey; name: string; count: number; alert: boolean; alertWhy?: string; color: string;
  /** 这一家怎么轮换（`platforms.ts` 的 `note`）—— 四家的账号语义不同，悬浮要说得出差在哪。 */
  note?: string;
}

const LOGO: Record<OvTabKey, LogoPlatform> = { codex: "codex", claude: "claude", gemini: "agy", grok: "grok" };

export function OvTabs({ tabs, cur, onPick, isDark, layout }: {
  tabs: OvTab[]; cur: OvTabKey; onPick: (k: OvTabKey) => void; isDark: boolean; layout: OvLayout;
}) {
  return (
    <div data-ov-tabs="" style={{ display: "flex", alignItems: "center", gap: 2, padding: 3, borderRadius: 11,
                                  background: "var(--ovTabBg)", border: "1px solid var(--ovTabLine)", flexShrink: 0 }}>
      {tabs.map((tb, i) => {
        const on = tb.key === cur;
        return (
          <span key={tb.key} className="ov-tab" data-provtab={tb.key} data-active={on ? "1" : "0"} role="tab" tabIndex={0}
                title={`${tb.name} · ${tb.count} 个号${tb.note ? ` · ${tb.note}` : ""}${tb.alert ? ` · ⚠️ ${tb.alertWhy ?? "有告警"}` : ""} · ⌘${i + 1}`}
                onClick={() => onPick(tb.key)} onKeyDown={(e) => { if (e.key === "Enter") onPick(tb.key); }}
                style={on ? { background: `${tb.color}26`, boxShadow: `inset 0 0 0 1px ${tb.color}88`, color: "var(--tx)" } : undefined}>
            <PlatformLogo platform={LOGO[tb.key]} isDark={isDark} size={16} />
            {layout.tabNames && <span style={{ fontSize: 13, fontWeight: 600 }}>{tb.name}</span>}
            <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12,
                           color: on ? "var(--tx)" : "var(--tx3)" }}>{tb.count}</span>
            {tb.alert && (
              <i data-ov-tab-alert="" style={{ position: "absolute", top: 3, right: 3, width: 6, height: 6, borderRadius: 3,
                                               background: "#FF4D2E", boxShadow: "0 0 0 2px var(--ovDotRing)" }} />
            )}
          </span>
        );
      })}
    </div>
  );
}

export function HBtn({ children, onClick, title, data, disabled }: {
  children: ReactNode; onClick: () => void; title?: string; data?: string; disabled?: boolean;
}) {
  return (
    <span className="ov-hbtn" role="button" tabIndex={0} title={title} data-ov-head={data} data-head-action=""
          aria-disabled={disabled ? "true" : undefined}
          style={disabled ? { opacity: .6, cursor: "default" } : undefined}
          onClick={() => { if (!disabled) onClick(); }}
          onKeyDown={(e) => { if (e.key === "Enter" && !disabled) onClick(); }}>
      {children}
    </span>
  );
}

/** 刷新全池（窄档只留图标）。 */
export function RefreshBtn({ onClick, busy, labels, title, text = "刷新全池" }: {
  onClick: () => void; busy: boolean; labels: boolean; title?: string; text?: string;
}) {
  return (
    <HBtn onClick={onClick} disabled={busy} title={busy ? `${text.startsWith("刷新") ? "刷新中…" : text} · 另一个窗口发起的也算` : title ?? text} data="refresh">
      <IcRefresh size={14} spin={busy} />{labels && <span>{busy ? "刷新中…" : text}</span>}
    </HBtn>
  );
}

/** 探针（计费）—— 点一下就执行，复用菜单栏那颗 `ProbeBtn`（同一个连点判据、同一套琥珀）。 */
export function ProbeHead({ onFire, loading, hint }: { onFire: () => void; loading: boolean; hint: string }) {
  return (
    <span data-ov-head="probe" data-head-action="" style={{ position: "relative", display: "block", width: 112, height: 32, flexShrink: 0 }}>
      <ProbeBtn onFire={onFire} loading={loading} hint={hint} />
    </span>
  );
}

/** [定时 | 自动切号] 开关组。 */
export function ToggleGroup({ children }: { children: ReactNode }) {
  return (
    <span data-ov-head="toggles" style={{ display: "flex", alignItems: "center", padding: "0 3px", borderRadius: 10,
                                          border: "1px solid var(--ovGrpLine)", flexShrink: 0 }}>
      {children}
    </span>
  );
}
export const GroupDivider = () => <i aria-hidden style={{ width: 1, height: 18, background: "var(--ovGrpLine)" }} />;

export function AutoSwitchItem({ on, onToggle, labels, title }: { on: boolean | null; onToggle: () => void; labels: boolean; title: string }) {
  return (
    <span data-ov-head="auto" data-head-action="" data-on={on == null ? "" : on ? "1" : "0"} role="switch" aria-checked={!!on} tabIndex={0}
          title={title} onClick={onToggle} onKeyDown={(e) => { if (e.key === "Enter") onToggle(); }}
          style={{ display: "flex", alignItems: "center", gap: 7, height: 32, padding: "0 9px", cursor: "pointer",
                   color: on ? "var(--tx)" : "var(--tx2)", fontSize: 12.5, userSelect: "none" }}>
      <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
        <path d="M4 12a8 8 0 0 1 13.7-5.6L20 8.5M20 4v4.5h-4.5M20 12a8 8 0 0 1-13.7 5.6L4 15.5M4 20v-4.5h4.5" fill="none"
              stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {labels && <span>自动切号</span>}
      <span className="ov-sw" data-on={on ? "1" : "0"} style={{ opacity: on == null ? .5 : 1 }}><i /></span>
    </span>
  );
}

export interface HeadMenuItem { key: string; label: string; onClick?: () => void; info?: boolean; title?: string }

/** 头部最右的 ⋯：检查 token、加号说明、数据新鲜度…（旧头部上那些放不进 32 高一行的）。 */
export function HeadMore({ items }: { items: HeadMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
  }, [open]);
  return (
    <span ref={box} style={{ position: "relative", display: "inline-flex", flexShrink: 0 }}>
      <span className="ov-hbtn" role="button" tabIndex={0} data-ov-head="more" title="更多"
            onClick={() => setOpen((o) => !o)} onKeyDown={(e) => { if (e.key === "Enter") setOpen((o) => !o); }}
            style={{ width: 32, padding: 0, justifyContent: "center", color: "var(--tx2)" }}>
        <IcMore size={15} />
      </span>
      {(
        <div className="ov-menu ov-menu-down" data-ov-head-menu="" data-open={open ? "" : undefined} style={{ minWidth: 220 }}>
          {items.map((it) => it.info ? (
            <div key={it.key} className="ov-mi ov-mi-info" data-ov-mi-info={it.key} title={it.title}>{it.label}</div>
          ) : (
            <div key={it.key} className="ov-mi" role="menuitem" tabIndex={0} data-ov-mi={it.key} title={it.title}
                 onClick={() => { setOpen(false); it.onClick?.(); }}
                 onKeyDown={(e) => { if (e.key === "Enter") { setOpen(false); it.onClick?.(); } }}>{it.label}</div>
          ))}
        </div>
      )}
    </span>
  );
}
