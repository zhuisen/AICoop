import type { Notice } from "../../mbLogic";

const Warn = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M12 3 2 20h20L12 3Z" fill="currentColor" />
    <path d="M12 10v4.5M12 17v.4" stroke="#000" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);
const Chevron = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/**
 * 通知条（交接包 4f：「重置卡作废 / 到期 / 池见底 / 低额度 合并成一条：只显示最紧急一条 +
 * 「还有 N 条」，点开展开其余（340 ms）」）。色调跟着最紧急那条走：红 = `--bad*`、琥珀 = `--warn*`。
 *
 * ★ 展开区一直在 DOM 里，只靠 `grid-template-rows` 藏（ui.md §5c）。
 * ★ 重置卡那条**可关**（用户 2026-09-18：「太过了，喧宾夺主，并且无法取消」）—— 它会自己过期，
 *   连挂三天关不掉就是噪音；关掉按卡的身份记忆，换了新卡会再提醒一次（`useCardBannerDismiss`）。
 *   其余几条（低额度 / 池见底 / 订阅到期）说的是还没解决的事，不给关。
 */
export default function NoticeBar({ head, rest, open, onToggle, onDismiss }: {
  head: Notice;
  rest: Notice[];
  open: boolean;
  onToggle: () => void;
  onDismiss: (n: Notice) => void;
}) {
  const bad = head.tone === "bad";
  const more = rest.length > 0;
  const X = ({ n }: { n: Notice }) => n.dismissible ? (
    <span role="button" aria-label="关闭这条提醒" data-mb-notice-x=""
          title="关掉这条提醒。换了新卡会重新提醒一次"
          onClick={(e) => { e.stopPropagation(); onDismiss(n); }}
          style={{ flexShrink: 0, cursor: "pointer", color: "var(--tx3)", fontSize: 14, lineHeight: 1, padding: "2px 4px" }}>×</span>
  ) : null;
  return (
    <div data-mb-notice={head.tone} style={{ borderRadius: 10, overflow: "hidden", flexShrink: 0,
                  background: bad ? "var(--badBg)" : "var(--warnBg)", border: `1px solid ${bad ? "var(--badLine)" : "var(--warnLine)"}` }}>
      <div onClick={more ? onToggle : undefined}
           style={{ display: "flex", alignItems: "center", gap: 8, height: 32, padding: "0 10px",
                    color: bad ? "var(--bad)" : "var(--warn)", cursor: more ? "pointer" : "default" }}>
        <Warn />
        <span data-mb-notice-head="" style={{ flex: 1, minWidth: 0, fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap",
                       overflow: "hidden", textOverflow: "ellipsis" }} title={head.text}>{head.text}</span>
        <X n={head} />
        {more && <>
          <span style={{ fontSize: 11.5, color: "var(--tx3)", whiteSpace: "nowrap", opacity: open ? 0 : 1,
                         transition: "opacity 150ms" }}>还有 {rest.length} 条</span>
          <span style={{ color: "var(--tx3)", transform: `rotate(${open ? 180 : 0}deg)`, transition: "transform 300ms var(--sp)" }}>
            <Chevron /></span>
        </>}
      </div>
      <div style={{ display: "grid", gridTemplateRows: open ? "1fr" : "0fr", transition: "grid-template-rows 340ms var(--sp)" }}>
        <div style={{ overflow: "hidden", minHeight: 0 }}>
          {rest.map((n) => (
            <div key={n.id} data-mb-notice-rest=""
                 style={{ display: "flex", alignItems: "center", gap: 8, height: 30, padding: "0 10px 0 32px",
                          borderTop: `1px solid ${bad ? "var(--badLine)" : "var(--warnLine)"}`, fontSize: 12,
                          color: n.tone === "bad" ? "var(--badTx)" : "var(--tx2)" }}>
              <span style={{ flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                    title={n.text}>{n.text}</span>
              <X n={n} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
