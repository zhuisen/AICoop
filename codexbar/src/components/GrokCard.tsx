import type { Theme } from "../theme";
import type { GrokSnapshot, GrokAccount } from "../grok";
import { grokRemPct, grokLastGoodRemPct, grokQuotaVisible, grokBadgePlan, grokInferred, GROK_INFERRED_NOTE } from "../grok";
import { fmtAgo, fmtEta, maskId } from "../helpers";
import GrokStaleMark from "./GrokStaleMark";
import { Ab, DynText, IcRefresh, OvCard, OvTag, ULTRA_TAG_STYLE } from "./ov/OvCard";
import { ovIsLow } from "../overview";

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
  // ★ 不再标「只读」（用户 2026-10-23「grok 不要变成只读了，解锁吧，看着不舒服」）：与 Claude 本机卡同一套 ——
  //   单号就是在用的那个。仍不出「切换 / 探针」（没有池可切），这是能力边界，不再用锁和「只读」字样去说它。
  const state = rem == null ? "unprobed" : ovIsLow(rem) ? "low" : "inuse";
  const inferred = rem != null && grokInferred(a);
  return (
    <OvCard id="grok" t={t} state={state} ringPct={rem} platColor={degraded ? "var(--warn)" : color}
            onClick={onOpen} hov={hov}
            head={<>
              <b data-card-name="" style={{ fontSize: 15 }}>grok</b>
              <OvTag tag={{ text: "在用", kind: "inuse" }} title="grok 单号：就是 grok CLI 当前登录的那个号" />
              {degraded && a && <GrokStaleMark t={t} a={a} size={11} />}
              {!!err && <GrokStaleMark t={t} note={`读不到本机的额度快照：${err}`} tone="red" size={11} />}
              {/* ★ 套餐徽章放最后、空间不够就缩成省略号（用户 2026-10-23 截图：860 / 1200 / 1440 下名字行要 180px、只有
                  155–175，最右的失效标记被裁掉一半）。告警标记排在它前面 ⇒ 永远不被裁；全名在悬停提示里。 */}
              {plan && <span data-ov-tag="ultra" data-grok-plan="" title={`套餐：${plan}`}
                             style={{ ...ULTRA_TAG_STYLE, flexShrink: 1, minWidth: 0,
                                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{plan}</span>}
            </>}
            email={a?.email ? maskId(a.email, privacy) : (busy ? "正在取额度…" : "未探测")}
            dyn={<DynText tone={rem != null && Math.round(rem) < 10 ? "bad" : "muted"}>
              <span data-grok-inferred={inferred ? "" : undefined}
                    title={rem == null ? "额度暂时读不到 · 点刷新再取一次" : inferred ? GROK_INFERRED_NOTE : "只有周额度 · 单号"}>
                {rem == null ? "读不到" : inferred ? "<1% · 推断" : "周额度"}
              </span>
            </DynText>}
            w5={{ label: "5h", pct: null, reset: "", kind: "5h", absent: true, title: "xAI 只有周额度，没有 5h 窗口" }}
            ww={{ label: "周", pct: rem, reset: rem == null ? "" : fmtEta(end), kind: "w", dim: degraded, atLeast: inferred,
                  title: inferred ? GROK_INFERRED_NOTE : undefined }}
            footLeft={<span data-grok-read-at="" title="xAI 账单 · 不在轮换池">{degraded
              ? (rem != null ? `${fmtAgo(a?.last_good?.fetched_at)}的读数` : "额度暂时读不到")
              : (snap?.fetched_at ? `xAI 账单 · ${fmtAgo(snap.fetched_at)}` : "xAI 账单 · 不在轮换池")}</span>}
            actions={<Ab onClick={onRefresh} disabled={busy || !onRefresh} data="refresh"
                         title="重新取一次 grok 周额度（一次 GET，不计费、不碰 refresh_token）">
              <IcRefresh spin={busy} />刷新
            </Ab>} />
  );
}
