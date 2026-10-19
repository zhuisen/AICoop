import type { Theme } from "../theme";
import type { GrokSnapshot, GrokAccount } from "../grok";
import { grokRemPct, grokLastGoodRemPct, grokQuotaVisible, grokBadgePlan } from "../grok";
import { fmtAgo, fmtEta, maskId } from "../helpers";
import GrokStaleMark from "./GrokStaleMark";
import { Ab, DynText, IcRefresh, OvCard, OvTag } from "./ov/OvCard";

/**
 * Grok 账号卡 —— **只读**（交接包 page5：「只读号只有『刷新』」）。与 Codex / Gemini 卡同一个外壳、同样 148 高。
 *
 * ★ 5h 槽画「—」占位：xAI 只回 WEEKLY（实测 `window_minutes = 10080`），交接包要求
 *   「只有周额度的平台 5h 显示 — 占位」—— 它取代了 2026-09 那版「整行不画」（PLAN §4）。
 *   等高由外壳保证，不再靠末行对齐去凑。
 * ★ 数字绝不假装是活的：降级时画上次读数并在页脚说是几时的；从没读到就是 —。
 */
export default function GrokCard({ t, color, snap, privacy, busy, err, disabled, hov, onOpen, onRefresh }: {
  t: Theme;
  /** 平台识别色（`colorOf(traffic, "grok")`）。 */
  color: string;
  snap: GrokSnapshot | null;
  privacy: boolean;
  busy?: boolean;
  err?: string | null;
  disabled?: boolean;
  hov?: boolean;
  onOpen?: () => void;
  onRefresh?: () => void;
}) {
  if (!grokQuotaVisible(snap, { disabled })) return null;
  const a: GrokAccount | null = snap?.accounts?.[0] ?? null;
  const degraded = !!a && !a.available;
  const rem = degraded ? grokLastGoodRemPct(a) : grokRemPct(a);
  const plan = grokBadgePlan(a);
  const end = (degraded ? a?.last_good?.period_end : a?.quota?.period_end) ?? undefined;
  return (
    <OvCard id="grok" t={t} state="readonly" ringPct={rem} platColor={degraded ? "var(--warn)" : color}
            onClick={onOpen} hov={hov}
            head={<>
              <b data-card-name="" style={{ fontSize: 15 }}>grok</b>
              <OvTag tag={{ text: "只读", kind: "readonly" }} title="grok 不在轮换池，只显示额度，不参与切号" />
              {plan && <OvTag tag={{ text: plan, kind: "ultra" }} title={`套餐：${plan}`} />}
              {degraded && a && <GrokStaleMark t={t} a={a} size={11} />}
              {!!err && <GrokStaleMark t={t} note={`读不到本机的额度快照：${err}`} tone="red" size={11} />}
            </>}
            email={a?.email ? maskId(a.email, privacy) : (busy ? "正在取额度…" : "未探测")}
            dyn={<DynText tone={rem != null && Math.round(rem) < 10 ? "bad" : "muted"}>
              {rem == null ? "额度暂时读不到 · 点刷新再取一次" : "只有周额度 · 只读不切号"}
            </DynText>}
            w5={{ label: "5h", pct: null, reset: "", kind: "5h", absent: true, title: "xAI 只有周额度，没有 5h 窗口" }}
            ww={{ label: "周", pct: rem, reset: rem == null ? "" : fmtEta(end), kind: "w", dim: degraded }}
            footLeft={<span data-grok-read-at="" title="xAI 账单 · 不在轮换池">{degraded
              ? (rem != null ? `${fmtAgo(a?.last_good?.fetched_at)}的读数` : "额度暂时读不到")
              : (snap?.fetched_at ? `xAI 账单 · ${fmtAgo(snap.fetched_at)}` : "xAI 账单 · 不在轮换池")}</span>}
            actions={<Ab onClick={onRefresh} disabled={busy || !onRefresh} data="refresh"
                         title="重新取一次 grok 周额度（只读 GET，不计费、不碰 refresh_token）">
              <IcRefresh spin={busy} />刷新
            </Ab>} />
  );
}
