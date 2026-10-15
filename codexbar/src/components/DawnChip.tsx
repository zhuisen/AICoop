import { useEffect, useRef, useState } from "react";
import type { Theme } from "../theme";
import { dawnDesc, type DawnKind } from "../dawn";
import { useDawnStatus } from "../hooks/useDawnStatus";

const MONO = "'JetBrains Mono'";

/**
 * 总览工具栏的「定时 开/关」胶囊 + 点开的浮层（开关 / 时间 / 上次运行）。codex 与 Gemini 两档共用。
 *
 * 用户 2026-10-15：「定时的功能在设置移动到总览，各 AI 版块上」+「胶囊只显示 定时 开/关，
 * 点击才出时间选择」。所以胶囊本身**不直接切开关** —— 这是会花钱的功能，开关放进浮层里多一步。
 * ★ 浮层里那句「上次运行」是「定时到底跑没跑」的唯一可见证据（launchd 定时有静默不跑的前科），
 *   悬浮在胶囊上也看得到同一句（`title`）。
 * ★ 图标用线条钟面而不是 ⏰ emoji：本仓设计语言不用 emoji 当图标（`~/.claude/rules/ui-design.md`）。
 */
export default function DawnChip({ t, kind, active, compact }: {
  t: Theme; kind: DawnKind; active: boolean;
  /** 顶栏一行放不下时（`useOneRowHeader`）收窄内边距，与旁边的按钮同一档。 */
  compact?: boolean;
}) {
  const { rec, busy, toggle, setTime } = useDawnStatus(kind, active);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const box = useRef<HTMLSpanElement>(null);
  const on = !!rec?.enabled;
  // `dawnDesc` 用 `**` 标重点（设置页旧版按 markdown 渲染）；这里是 `title` 与纯文本，剥掉。
  const desc = dawnDesc(rec, kind).replace(/\*\*/g, "");

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
  }, [open]);

  const time = draft ?? rec?.time ?? "06:00";
  const dirty = draft != null && draft !== rec?.time;

  return (
    <span ref={box} data-head-action="" style={{ position: "relative", display: "inline-flex" }}>
      <span data-dawn-chip={kind} onClick={() => setOpen(o => !o)} title={desc}
            style={{ fontSize: 11.5, fontWeight: 700, padding: compact ? "5px 8px" : "5px 11px", borderRadius: 8,
                     cursor: "pointer", whiteSpace: "nowrap", userSelect: "none",
                     display: "inline-flex", alignItems: "center", gap: 6,
                     color: on ? t.accent : t.muted,
                     border: `1px solid ${on ? t.accent + "55" : t.ghostBorder}`,
                     background: on ? "rgba(45,212,191,.07)" : "transparent" }}>
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
             strokeWidth="1.6" strokeLinecap="round" aria-hidden>
          <circle cx="8" cy="8.5" r="5.5" /><path d="M8 5.6v3l2 1.4M3 2.6 1.6 4M13 2.6 14.4 4" />
        </svg>
        定时 {rec == null ? "—" : on ? "开" : "关"}
      </span>
      {open && (
        <div data-dawn-pop={kind}
             style={{ position: "absolute", right: 0, top: "calc(100% + 6px)", width: 280, zIndex: 20,
                      background: t.popBg, border: `1px solid ${t.ghostBorder}`, borderRadius: 10,
                      boxShadow: t.popShadow, padding: 12, display: "flex", flexDirection: "column",
                      gap: 10, fontSize: 11.5, color: t.text2, cursor: "default" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <b style={{ color: t.text, fontSize: 12 }}>
              {kind === "codex" ? "Codex 定时探针" : "Gemini 定时探针"}
              <span style={{ marginLeft: 6, fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 4,
                             color: "#E0901C", border: "1px solid #E0901C66" }}>计费</span>
            </b>
            <span data-dawn-toggle onClick={() => { if (!busy) void toggle(); }}
                  style={{ width: 34, height: 18, borderRadius: 9, position: "relative", flexShrink: 0,
                           cursor: busy ? "default" : "pointer", opacity: busy ? .5 : 1,
                           background: on ? t.accent : t.barTrack, transition: "background .2s" }}>
              <span style={{ position: "absolute", top: 2, left: 2, width: 14, height: 14, borderRadius: 7,
                             background: "#fff", transform: on ? "translateX(16px)" : "none",
                             transition: "transform .2s" }} />
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span>每天</span>
            <input data-dawn-time type="time" value={time} onChange={e => setDraft(e.target.value)}
                   style={{ fontFamily: MONO, fontSize: 12, padding: "3px 6px", borderRadius: 6,
                            background: t.popFieldBg, color: t.text, border: `1px solid ${t.ghostBorder}` }} />
            {dirty
              ? <span data-dawn-save onClick={() => { if (!busy && draft) void setTime(draft).then(() => setDraft(null)); }}
                      style={{ fontWeight: 700, color: t.accent, cursor: "pointer" }}>保存</span>
              : <span style={{ fontFamily: MONO, color: t.muted }}>{rec?.window ?? ""}</span>}
          </div>
          <div style={{ color: t.muted, lineHeight: 1.5 }}>
            实际在所选时刻起 3 分钟内随机触发；电脑睡着错过的，醒来后由 app 补跑。
          </div>
          <div data-dawn-desc style={{ lineHeight: 1.5, borderTop: `1px solid ${t.divider}`, paddingTop: 8 }}>
            {desc}
          </div>
        </div>
      )}
    </span>
  );
}
