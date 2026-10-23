import type { Theme } from "../../theme";
import type { ClaudeQuota } from "../../mbLogic";
import type { LivePlatform } from "../../live";
import { fmtTokens, fmtTps } from "../../live";
import { fmtClock, fmtDur, ovIsLow } from "../../overview";
import { Ab, DynText, IcRefresh, OvCard } from "./OvCard";

/**
 * Claude 账号卡。结构同 Codex（交接包 page5 §3），但**只用真有的数据**（PLAN §4）：
 *   · 本机只有 1 个 Claude 号，仓库**没有** Claude 账号池后端（切号要写 Claude Code 凭证，已定不碰）
 *     ⇒ 不出「切换」「探针」，只有「刷新」；
 *   · 额度来自状态栏转写（`read_statusline_quota`）；读不到写 —，绝不编一个满额；
 *   · 邮箱不读（那要碰凭证）—— 写「Claude Code · 本机」。
 */
export default function ClaudeCard({ t, color, quota, err, live, hov, busy, onRefresh, nowMs }: {
  t: Theme; color: string; quota: ClaudeQuota | null; err: string | null; live: LivePlatform | null | undefined;
  hov?: boolean; busy?: boolean; onRefresh: () => void; nowMs: number;
}) {
  const f = quota?.fiveH ?? null, w = quota?.week ?? null;
  const pct = f == null && w == null ? null : Math.min(f?.rem ?? 100, w?.rem ?? 100);
  const reset = (x: { resetsAt: number | null } | null) =>
    x?.resetsAt != null && x.resetsAt * 1000 > nowMs ? fmtDur((x.resetsAt * 1000 - nowMs) / 60000) : "";
  const running = !!live && live.running && live.n_sessions > 0;
  const state = pct == null ? "unprobed" : ovIsLow(pct) ? "low" : "inuse";
  const src = quota?.source === "statusline" ? "状态栏转写" : quota?.source === "plan-usage-history" ? "Claude.app 记录（无重置时间）" : null;
  return (
    <OvCard id="claude-local" t={t} state={state} ringPct={pct} platColor={color} hov={hov}
            head={<>
              <b data-card-name="" style={{ fontSize: 15 }}>本机</b>
              <span data-ov-tag="inuse" style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11, fontWeight: 600,
                                                 color: "var(--acc)", padding: "1px 7px", borderRadius: 6, background: "var(--ovTagIn)" }}>在用</span>
            </>}
            email="Claude Code · 本机"
            emailTitle="不读 Claude 凭证，所以这里没有邮箱"
            dyn={running ? (
              <DynText tone="live" title={`此刻在跑：${fmtTps(live?.tps)} t/s · ${live?.n_sessions} 个会话 · 今日 ${fmtTokens(live?.tokens_today)} token`}>{fmtTps(live?.tps)} t/s · ×{live?.n_sessions} · {fmtTokens(live?.tokens_today)}</DynText>
            ) : pct == null ? (
              <DynText tone="bad" title={`额度读不到 · 开一次 Claude Code 让状态栏转写${err ? `（${err}）` : ""}`}>读不到</DynText>
            ) : (
              <DynText tone="muted" title={`此刻没有在跑的会话${live ? ` · 今日 ${fmtTokens(live.tokens_today)} token` : ""}`}>空闲{live ? ` · ${fmtTokens(live.tokens_today)}` : ""}</DynText>
            )}
            w5={{ label: "5h", pct: f?.rem ?? null, reset: reset(f), note: f?.idle ? "未启动" : undefined, kind: "5h" }}
            ww={{ label: "周", pct: w?.rem ?? null, reset: reset(w), note: w?.idle ? "未启动" : undefined, kind: "w" }}
            footLeft={<span>{src && quota?.capturedAt ? `${src} · ${fmtClock(quota.capturedAt * 1000)}` : "额度来源：状态栏转写"}</span>}
            actions={<Ab onClick={onRefresh} disabled={busy} data="refresh" title="重读一次状态栏转写的额度（读本机文件，零消耗）">
              <IcRefresh />刷新
            </Ab>} />
  );
}
