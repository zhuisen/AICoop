import GrokStaleMark from "./GrokStaleMark";
import QuotaRow, { type WinCell } from "./mb/QuotaRow";
import type { Theme } from "../theme";
import type { GrokSnapshot, GrokAccount } from "../grok";
import { grokRemPct, grokLastGoodRemPct, grokQuotaVisible, grokBadgePlan } from "../grok";
import { fmtEta } from "../helpers";

const Lock = () => (
  <svg width="9" height="9" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <rect x="5" y="11" width="14" height="9" rx="2" fill="none" stroke="currentColor" strokeWidth="1.7" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" strokeWidth="1.7" />
  </svg>
);

/**
 * 菜单栏里的 Grok 行（交接包 2026-10-19 · 4f「当前号 · 只读」）。外形在 `mb/QuotaRow`。
 *
 * ★★ **走完全独立的数据通路**：数据**绝不**混进 `accounts` / `alive` / `aliveByLabel`（计数徽章、
 *   探针全池、自动切号都读它们）。闸在 `tests/test_grok_not_in_pool_ui.py`。
 * ★ **只读**：grok 不在池里，这一行永远不出按钮（交接包：只有 Grok 只读）。
 * ★★ **grok 不画 5h 那一格的条**（用户 2026-09-15「取消 5h 窗口」）：xAI 只回 WEEKLY。
 *   固定槽位下那格写「5h —」（画板同款），说的是"这家没有这个窗口"，不是"读不到"。
 * ★ 方向：接口给的是**已用**，这里一律换成**剩余**再画（`grokRemPct`，见 `tests/test_grok_direction.py`）。
 * ★ 失败态：读不到 ⇒ 写 —，绝不画 0%；有上次读数 ⇒ 照画但降不透明度，并挂 `GrokStaleMark` 说明原因。
 */
export default function GrokRow({ t, snap, busy, disabled, onOpen }: {
  t: Theme;
  snap: GrokSnapshot | null;
  busy?: boolean;
  /** 用户在设置页停用了 grok。停用 = 一个像素都不画。 */
  disabled?: boolean;
  /** 点行内容 = 跳工作台总览的 Grok 档。 */
  onOpen?: () => void;
}) {
  // ★ 与总览卡**共用同一个判据** —— 两边各写一份迟早出现「主窗有、菜单栏没有」。
  if (!grokQuotaVisible(snap, { disabled })) return null;
  const isDark = t.isDark;
  if (!snap || snap.accounts.length === 0) {
    return (
      <QuotaRow platform="grok" isDark={isDark} name="grok" sub={<Sub />} readOnly onOpen={onOpen}
                note={busy ? "正在取额度…" : "未探测 · 刷新一次后显示额度"} data={{ "data-mb-grok": "none" }} />
    );
  }

  const a: GrokAccount = snap.accounts[0];
  const rem = grokRemPct(a);
  const lgRem = grokLastGoodRemPct(a);

  if (!a.available) {
    // ★ 降级：有上次读数就画上次的（降不透明度 + 「上次读数」），没有就写 —。
    const stale = lgRem != null;
    const week: WinCell = { label: "周", pct: stale ? lgRem : null, dim: stale,
                            refill: fmtEta(a.last_good?.period_end ?? undefined),
                            title: stale ? "上次读数 —— 这次额度暂时读不到" : "额度暂时读不到" };
    return (
      <QuotaRow platform="grok" isDark={isDark} name="grok" readOnly onOpen={onOpen}
                sub={<Sub plan={grokBadgePlan(a)} mark={<GrokStaleMark t={t} a={a} size={10} />} />}
                wins={[null, week]} data={{ "data-mb-grok": stale ? "stale" : "unread" }} />
    );
  }

  const q = a.quota!;
  const week: WinCell = { label: "周", pct: rem, refill: fmtEta(q.period_end ?? undefined) };
  return (
    <QuotaRow platform="grok" isDark={isDark} name="grok" readOnly onOpen={onOpen}
              sub={<Sub plan={grokBadgePlan(a)} />} wins={[null, week]} data={{ "data-mb-grok": "ok" }} />
  );
}

function Sub({ plan, mark }: { plan?: string; mark?: React.ReactNode }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <span style={{ display: "flex", alignItems: "center", gap: 2, color: "var(--tx3)" }}
            title="grok 不在轮换池，只显示额度，不参与切号"><Lock />只读</span>
      {plan ? <span style={{ color: "var(--gr)", fontWeight: 700 }}>{plan}</span> : null}
      {mark}
    </span>
  );
}
