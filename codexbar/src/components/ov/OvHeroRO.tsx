import type { GrokSnapshot } from "../../grok";
import { grokLastGoodRemPct, grokRemPct } from "../../grok";
import type { ClaudeQuota } from "../../mbLogic";
import type { LivePlatform } from "../../live";
import type { OvLayout } from "../../overview";
import { fmtClock, fmtDur, ovIsLow } from "../../overview";
import { fmtAgo, fmtEta } from "../../helpers";
import { ColTitle, Divider, HeroShell, LiveLineView, NowCol, RelayBar, SwitchCol, SwitchRowNarrow } from "./OvHero";
import { MONO } from "./ovVars";

/**
 * Grok 的顶部三栏 —— **只读**：当前号 · 额度（粗条 + 回满）· 说明（交接包 page5 §3）。
 * 只有周额度；无续航、无切换（xAI 只回 WEEKLY，实测 `window_minutes = 10080`）。
 */
export function GrokHero({ snap, layout, err, pc }: { snap: GrokSnapshot | null; layout: OvLayout; err?: string | null; pc: string }) {
  const a = snap?.accounts?.[0] ?? null;
  const degraded = !!a && !a.available;
  const rem = degraded ? grokLastGoodRemPct(a) : grokRemPct(a);
  const end = (degraded ? a?.last_good?.period_end : a?.quota?.period_end) ?? undefined;
  const low = ovIsLow(rem);
  const bar = degraded ? "var(--warn)" : low ? "var(--bad)" : pc;
  return (
    <HeroShell pc={pc} layout={layout}>
      <NowCol title="当前号 · 只读" pct={rem} color={bar} name="grok"
              email={degraded ? (rem != null ? `${fmtAgo(a?.last_good?.fetched_at)}的读数` : "额度暂时读不到") : "xAI 账单"}
              line={<span style={{ color: "var(--tx3)" }}>{err ? `读不到本机快照：${err}` : snap?.fetched_at ? `读数 ${fmtAgo(snap.fetched_at)}` : "—"}</span>} />
      <Divider />
      <div data-ov-grok-quota="" style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
        <ColTitle><span>额度</span></ColTitle>
        <div style={{ display: "flex", alignItems: "center", gap: 10, height: 22, fontSize: 12, color: "var(--ovPh)" }}>
          <span style={{ width: 18, color: "var(--tx3)" }}>5h</span>没有这个窗口
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, height: 22 }}>
          <span style={{ width: 18, fontSize: 12, color: "var(--tx3)" }}>周</span>
          <span style={{ display: "block", flex: 1, minWidth: 0, height: 6, borderRadius: 6, background: "var(--track)", overflow: "hidden" }}>
            {rem != null && <span style={{ display: "block", width: `${rem}%`, height: "100%", borderRadius: 6, background: bar }} />}
          </span>
          <b style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", width: 44, textAlign: "right", fontSize: 14,
                      color: rem == null ? "var(--ovPh)" : low ? "var(--badTx)" : "var(--tx)" }}>{rem == null ? "—" : `${Math.round(rem)}%`}</b>
          <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", width: 64, fontSize: 11, color: "var(--tx3)" }}>
            {rem == null ? "" : `↻${fmtEta(end)}`}
          </span>
        </div>
      </div>
      {layout.wide && (<>
        <Divider />
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
          <ColTitle><span>说明</span></ColTitle>
          {["只有周额度 · xAI 账单", "只读 · 不切号", "低于 10% 同样告警"].map((s) => (
            <span key={s} style={{ display: "block", height: 20, lineHeight: "20px", fontSize: 12, color: "var(--tx2)",
                                   overflow: "hidden", textOverflow: "ellipsis" }}>{s}</span>
          ))}
        </div>
      </>)}
    </HeroShell>
  );
}

/**
 * Claude 的顶部三栏。结构同 Codex，但**只用真有的数据**（PLAN §4）：
 *   · 本机只有 1 个 Claude 号、仓库没有 Claude 账号池后端 ⇒ 没有接力、没有切换记录；
 *   · 额度来自状态栏转写（`read_statusline_quota`）—— 读不到写 —，绝不编一个满额。
 *   接力条只画轴 + 「5h 回满」时刻（有重置时间时），并写明为什么不画接力。
 */
export function ClaudeHero({ quota, layout, live, liveErr, onLogs, nowMs, pc }: {
  quota: ClaudeQuota | null; layout: OvLayout; live: LivePlatform | null | undefined; liveErr: boolean; pc: string;
  onLogs: () => void; nowMs: number;
}) {
  const f = quota?.fiveH?.rem ?? null, w = quota?.week?.rem ?? null;
  const pct = f == null && w == null ? null : Math.min(f ?? 100, w ?? 100);
  const reset5 = quota?.fiveH?.resetsAt ?? null;
  const toReset = reset5 != null ? (reset5 * 1000 - nowMs) / 60000 : null;
  const src = quota?.source === "statusline" ? "状态栏" : quota?.source === "plan-usage-history" ? "Claude.app 记录" : null;
  const empty = "只有本机一个号 · 不切号";
  return (
    <HeroShell pc={pc} layout={layout}>
      <NowCol title="正在使用" pct={pct} color={ovIsLow(pct) ? "var(--bad)" : pc} name="本机"
              right={src && quota?.capturedAt ? <span style={{ color: "var(--tx3)" }}>{src} · {fmtClock(quota.capturedAt * 1000)}</span> : undefined}
              email="Claude Code" line={<LiveLineView live={live} liveErr={liveErr} />} />
      <Divider />
      <div data-ov-runway="" style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
        <ColTitle gap={10}>
          <span>还能连续用</span>
          <b data-runway-hours="" style={{ fontFamily: MONO, fontSize: 18, lineHeight: 1, color: "var(--tx)" }}>—</b>
          {toReset != null && toReset > 0 && reset5 != null && <span style={{ marginLeft: "auto" }}>5h 回满 {fmtClock(reset5 * 1000)}（{fmtDur(toReset)} 后）</span>}
        </ColTitle>
        <RelayBar plan={null} marker={toReset != null ? { atMin: toReset, text: `5h 回满 ${fmtClock((reset5 ?? 0) * 1000)}` } : null}
                  caption={pct == null
                    ? "Claude 额度读不到 —— 状态栏还没转写过（开一次 Claude Code 即可），不是「用完了」"
                    : "Claude 只有本机 1 个号，没有可估连续使用配速的记录 —— 不画接力，只标 5h 回满时刻"} />
      </div>
      {layout.wide ? (<><Divider /><SwitchCol rows={[]} onLogs={onLogs} empty={empty} /></>)
                   : <SwitchRowNarrow rows={[]} onLogs={onLogs} empty={empty} />}
    </HeroShell>
  );
}
