import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Theme } from "../../theme";
import { CMD_TABS, copyOf, type CmdTab } from "../../settingsCmds";

const MONO = "'JetBrains Mono', monospace";

/** 复制：先走 Clipboard API，WKWebView 拒绝时退回选中 + `execCommand`。两条都失败 ⇒ false（界面写「复制失败」，不假装成功）。 */
async function copyText(s: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(s);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = s; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta);
      try {
        ta.select();
        return document.execCommand("copy");
      } finally {
        ta.remove();   // ★ execCommand 抛异常时也要拿掉（评审 P6-codex-4：否则每次失败留一个透明输入框）
      }
    } catch {
      return false;
    }
  }
}

/**
 * 「指令与规则」折叠行（P9 S1 账号池组）：四签 + 指令表 + 复制钮（1.8 s 复原）。默认收起。
 * ★ 折叠用 CSS（`display` + 显式高度），内容一直在 DOM 里（ui.md §5c：静态 DOM 上的闸不许静默失效）。
 */
export default function CmdRules({ t }: { t: Theme }): React.ReactElement {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<CmdTab["k"]>("entry");
  // Auto Height 的替代（P99）：展开 / 切签时**正文**整块淡入 + 上移 4px，A/B 两套同样的关键帧交替才能重播（README §3.5）。
  // 签条常驻不重播（评审 P7-codex-2）。高度本身一步到位 —— 同一份稿的性能规矩不许做高度类布局动画（PLAN 44）。
  const [ab, setAb] = useState(false);
  // Animated Tabs（P99「P9 指令与规则：选中块滑过去」）：量选中签的真实位置，同 `SetKit.SegSlide`。收起时量不到（display:none）⇒ 展开那一帧再量。
  const tabsRef = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState<{ x: number; w: number } | null>(null);
  useLayoutEffect(() => {
    if (!open) return;
    const b = tabsRef.current?.querySelector<HTMLElement>(`[data-cmd-tab="${tab}"]`);
    setPill(b ? { x: b.offsetLeft, w: b.offsetWidth } : null);
  }, [open, tab]);
  const [copied, setCopied] = useState<{ k: string; ok: boolean } | null>(null);
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const cur = CMD_TABS.find((x) => x.k === tab) ?? CMD_TABS[0];
  const amber = t.isDark ? "#fbbf24" : "#8a5a0e";
  const copy = (k: string, s: string) => {
    void copyText(s).then((ok) => {
      setCopied({ k, ok });
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(null), 1800);
    });
  };
  return (
    <>
      <div className="set-row" role="button" data-cmd-rules={open ? "open" : "closed"} onClick={() => { if (!open) setAb((v) => !v); setOpen((v) => !v); }}
           style={{ display: "flex", alignItems: "center", gap: 12, minHeight: 44, padding: "7px 0", boxSizing: "border-box", cursor: "pointer" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span className={`set-chev${open ? " open" : ""}`} style={{ width: 10, fontSize: 10, color: t.accent }}>▶</span>
            <div style={{ fontSize: 13, fontWeight: 500, color: t.isDark ? "#5eead4" : "#0e7a6e", whiteSpace: "nowrap" }}>指令与规则</div>
          </div>
          <div style={{ fontSize: 12, color: t.muted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            入口、Codex / Gemini 账号池、其他工具的常用指令
          </div>
        </div>
      </div>
      <div className="set-sub" data-cmd-panel style={{ display: open ? "block" : "none", padding: "0 0 10px 18px" }}>
        <div style={{ padding: "10px 14px 12px", borderRadius: 10, background: t.isDark ? "#0e1319" : "#f6f8fb",
                      border: `1px solid ${t.cardBorder}`, display: "flex", flexDirection: "column", gap: 10 }}>
          <div role="tablist" ref={tabsRef} style={{ position: "relative", display: "inline-flex", alignSelf: "flex-start", padding: 2, gap: 2, borderRadius: 8,
                                       background: t.cardBg, border: `1px solid ${t.cardBorder}` }}>
            {pill && <i className="set-pill" data-cmd-pill style={{ transform: `translateX(${pill.x - 2}px)`, width: pill.w, background: t.accent }} />}
            {CMD_TABS.map((x) => (
              <button key={x.k} type="button" role="tab" aria-selected={tab === x.k} data-cmd-tab={x.k} onClick={() => { if (x.k !== tab) { setTab(x.k); setAb((v) => !v); } }}
                      className="set-seg-btn"
                      style={{ position: "relative", height: 24, padding: "0 10px", borderRadius: 6, border: 0, fontSize: 12, fontFamily: "inherit", cursor: "pointer",
                               background: "transparent", color: tab === x.k ? t.accentText : t.text2 }}>{x.name}</button>
            ))}
          </div>
          <div className={ab ? "set-in-b" : "set-in-a"} data-cmd-body style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 12, color: t.muted }}>{cur.note}</div>
          <div style={{ display: "grid", gridTemplateColumns: "236px minmax(0,1fr) 22px", gap: "6px 14px", fontSize: 12.5, lineHeight: 1.6 }}>
            {cur.rows.map((r) => {
              const c = copyOf(r);
              const k = `${cur.k}:${r.cmd}`;
              const done = copied?.k === k;
              return [
                <span key={k + ":c"} data-cmd={r.cmd} style={{ fontFamily: MONO, fontSize: 12, color: r.warn ? amber : t.isDark ? "#5eead4" : "#0e7a6e",
                                                               whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.cmd}</span>,
                <span key={k + ":d"} style={{ color: r.warn ? amber : t.text2, minWidth: 0 }}>{r.desc}</span>,
                c == null ? <span key={k + ":x"} /> : (
                  <button key={k + ":x"} type="button" data-cmd-copy={c} title={done ? (copied?.ok ? "已复制" : "复制失败") : `复制：${c}`}
                          onClick={(e) => { e.stopPropagation(); copy(k, c); }} className="set-btn"
                          style={{ width: 22, height: 20, borderRadius: 5, padding: 0, cursor: "pointer", display: "grid", placeItems: "center",
                                   border: `1px solid ${done && copied?.ok ? "rgba(45,212,191,.45)" : t.ghostBorder}`,
                                   background: done && copied?.ok ? "rgba(45,212,191,.1)" : "transparent", color: t.muted, fontSize: 11 }}>
                    {done ? (copied?.ok ? "✓" : "✗") : "⧉"}
                  </button>
                ),
              ];
            })}
          </div>
          </div>
        </div>
      </div>
    </>
  );
}
