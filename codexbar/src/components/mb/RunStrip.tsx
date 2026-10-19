import PlatformLogo from "../PlatformLogo";
import { PLATFORM_NAME, fmtTps, fmtTokens, type RunningRow } from "../../live";
import { MONO, NUM_VAR } from "./vars";

const Chevron = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/**
 * 在跑条（交接包 4f · `P4PopRows.html` 第 46 行，逐值照抄）。
 *
 * - 有 AI 在跑才出现：外层 `grid-template-rows 0fr→1fr`（420 ms 弹簧）。
 * - 默认折叠成一行 logo + t/s；点开展开成完整行（同悬停面板，行依次下落 40 ms 错开）。展开状态由调用方记住。
 * ★ 速度只在同一 AI 内合计（`live.ts`）；没出数写 —；不加「≈」「估」。不出现跨 AI 合计。
 * ★ 折叠内容留在 DOM 里，只靠 CSS 藏（ui.md §5c）。
 */
export default function RunStrip({ rows, todayTokens, open, onToggle, isDark }: {
  rows: RunningRow[];
  todayTokens: number | null;
  open: boolean;
  onToggle: () => void;
  isDark: boolean;
}) {
  const running = rows.length > 0;
  return (
    <div data-mb-strip={running ? "running" : "idle"} data-mb-strip-open={open ? "1" : "0"}
         style={{ display: "grid", gridTemplateRows: running ? "1fr" : "0fr",
                  transition: "grid-template-rows 420ms var(--sp)", flexShrink: 0 }}>
      <div style={{ overflow: "hidden", minHeight: 0 }}>
        <div style={{ margin: "0 12px 2px", borderRadius: 12, background: "var(--card2)", border: "1px solid var(--line)",
                      opacity: running ? 1 : 0, transition: "opacity 240ms" }}>
          <div onClick={onToggle} title={open ? "收起" : "展开每个在跑的 AI"}
               style={{ position: "relative", height: 34, cursor: "pointer" }}>
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", gap: 10,
                          padding: "0 10px 0 12px", opacity: open ? 0 : 1, transition: "opacity 180ms",
                          whiteSpace: "nowrap", overflow: "hidden" }}>
              <span style={{ fontSize: 11.5, color: "var(--tx3)" }}>在跑</span>
              {rows.map((r) => (
                <span key={r.key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <PlatformLogo platform={r.key} isDark={isDark} size={14} alt={PLATFORM_NAME[r.key]} />
                  <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12.5, fontWeight: 600,
                                 color: NUM_VAR[r.key] }}>{fmtTps(r.tps)}</span>
                </span>
              ))}
              <span style={{ fontSize: 10.5, color: "var(--tx3)" }}>t/s</span>
            </div>
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "space-between",
                          padding: "0 30px 0 12px", fontSize: 11, color: "var(--tx3)", opacity: open ? 1 : 0,
                          transition: "opacity 180ms", whiteSpace: "nowrap" }}>
              <span>在跑 · 速度 · Token</span>
              {/* ★ 刻意偏离画板：画板这里写「今日 415M · 均 58.4 t/s」，而那个均速是跨 AI 的速度汇总 ——
                  DECISIONS.md「不做跨 AI 的总合计 … 任何界面都不显示」与 PLAN §0 都禁止。决策文档优先，只留 token。 */}
              <span>今日 {fmtTokens(todayTokens)}</span>
            </div>
            <span style={{ position: "absolute", right: 10, top: 10, color: "var(--tx3)",
                           transform: `rotate(${open ? 180 : 0}deg)`, transition: "transform 360ms var(--sp)" }}>
              <Chevron />
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateRows: open ? "1fr" : "0fr", transition: "grid-template-rows 380ms var(--sp)" }}>
            <div style={{ overflow: "hidden", minHeight: 0 }}>
              <div style={{ paddingBottom: 4 }}>
                {rows.map((r, i) => {
                  const d = open ? `${60 + 40 * i}ms` : "0ms";
                  return (
                    <div key={r.key} data-mb-strip-row={r.key}
                         style={{ display: "grid", gridTemplateColumns: "18px minmax(0, 1fr) 74px 44px", columnGap: 8,
                                  alignItems: "center", height: 30, padding: "0 10px", opacity: open ? 1 : 0,
                                  transform: `translateY(${open ? 0 : -6}px)`,
                                  transition: `opacity 200ms ease-out ${d}, transform 360ms var(--sp) ${d}` }}>
                      <PlatformLogo platform={r.key} isDark={isDark} size={16} alt={PLATFORM_NAME[r.key]} />
                      <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, whiteSpace: "nowrap" }}>
                        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--tx)" }}>{PLATFORM_NAME[r.key]}</span>
                        {r.nSessions >= 2 && (
                          <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 10.5, color: "var(--tx2)",
                                         padding: "0 5px", borderRadius: 7, background: "var(--hov)", border: "1px solid var(--line)" }}>
                            ×{r.nSessions}</span>
                        )}
                      </span>
                      <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 13, fontWeight: 600,
                                     color: NUM_VAR[r.key], textAlign: "center", whiteSpace: "nowrap" }}>
                        {fmtTps(r.tps)}<span style={{ fontSize: 10, fontWeight: 400, color: "var(--tx3)" }}> t/s</span>
                      </span>
                      <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 11.5, color: "var(--tx2)",
                                     textAlign: "right", whiteSpace: "nowrap" }}>{fmtTokens(r.tokens)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
