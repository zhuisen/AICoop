import type { ReactNode } from "react";

const Chev = () => (
  <svg className="ov-chev" width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/**
 * 已停用（或失效）的号：默认折叠成底部一条虚线框（数量 + 号名 + 说明），点开在**同一个网格**里展开
 * （420 ms 临界阻尼，交接包 page5「账号区」）。
 * ★ 折叠用 CSS（`grid-template-rows: 0fr→1fr` + `visibility`），不是条件渲染 —— 内容一直在 DOM 里，
 *   展开不会重挂卡片（ui.md「收起用 visibility」）。收起态加 `inert`：看不见的按钮也不能被 Tab 到。
 */
export function OvStrip({ kind, count, names, note, open, onToggle, cols, children }: {
  kind: "off" | "dead"; count: number; names: string[]; note: string; open: boolean; onToggle: () => void;
  cols: number; children: ReactNode;
}) {
  return (
    <div data-ov-strip={kind} style={{ display: "flex", flexDirection: "column", gap: open ? 12 : 0, transition: "gap 420ms var(--sp)" }}>
      <div className="ov-strip" data-open={open ? "1" : "0"} role="button" tabIndex={0} onClick={onToggle}
           onKeyDown={(e) => { if (e.key === "Enter") onToggle(); }}>
        <span style={{ flexShrink: 0 }}>{kind === "off" ? "已停用" : "失效"} {count}</span>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--tx2)", overflow: "hidden", textOverflow: "ellipsis",
                       flexShrink: 1, minWidth: 0 }}>{names.join(" · ")}</span>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", minWidth: 0, flexShrink: 2 }}>{note}</span>
        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 4, color: "var(--tx2)", flexShrink: 0 }}>
          {open ? "收起" : "展开"}<Chev />
        </span>
      </div>
      <div className="ov-fold" data-open={open ? "1" : "0"}>
        <div className="ov-fold-in" inert={!open}>
          <div className="ov-fold-grid" data-cards-off={kind}
               style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: 12 }}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
