import { useState } from "react";
import type { Theme } from "../theme";
import type { AgySnapshot, AgyAction } from "../agy";
import {
  AGY_EXPIRED_TITLE, AGY_UNKNOWN_TITLE, agyResetText, agyShown, agyTightest, agyWinRows, agyQuotaVisible,
  agyBadgePlan, agyReasonNote, agyReasonTone,
} from "../agy";
import { fmtAgo, fmtResetDate, maskId } from "../helpers";
import type { OvState } from "../overview";
import { deltaText, fmtClock, fmtDur } from "../overview";
import { fmtTokens, fmtTps } from "../live";
import type { DragWiring } from "./DragHandle";
import StaleMark from "./StaleMark";
import AgyActionLink from "./AgyActionLink";
import { ActGroup, Ab, CardMenu, DynText, IcBolt, IcInfo, IcRefresh, IcTrash, OvCard, OvTag, PinMark, ProbeIb, RotIb, RotMark,
         useProbeFire, type OvWin } from "./ov/OvCard";
import type { LiveLine } from "./AccountCard";

/**
 * Gemini（agy）账号卡 —— 与 Codex 卡**同一个外壳**（交接包 page5 §3：「Codex 和 Gemini 同结构」）。
 *
 * ★ 机制差别只体现在**说法**上（照搬 codex 的原话在这几处都是假话）：
 *   · 「切换」= 把这个号写进钥匙串，**只对下一次启动的 agy 生效**（已开着的会话不受影响）；
 *   · 「冷却」= 额度见底（agy 没有 429 冷却这回事）；
 *   · 页脚左格是**最紧那个窗口的重置日**，不是「到期」—— agy 不提供订阅到期日（2026-09-16 三个探针一致）。
 * ★ 池里没有号时退回那张**只读卡**（`agy-rotate login --current` 之前的形态）：只有「刷新」。
 * ★ 旧卡上的每个操作都还在（CLAUDE.md §6），位置同 Codex 卡（P5）：切换 · ⚡ · ⊘ 在悬停底栏；置顶 = 名称行图钉；
 *   改名 · 查看用量 在 ···「详情」的 Sheet 里；移除 = ···「删除」+ 确认框。刷新 = 头部「刷新全池」（这里的刷新本来就是刷全池）。
 * ⚠️ 与稿的一处偏离：稿里 Gemini 没有置顶（`CAP.gemini.pin = false`），而 `agy-rotate pin` 是真有的后端能力 ——
 *   实测事实优先，图钉照 Codex 画（ui.md「1:1 指文档，与实测冲突时事实优先」）。
 */
export default function AgyCard({ t, color, snap, busy, err, disabled, state, hov, drag, aid, action, plan, label, email,
  bestPct, privacy, live, lastUse, rotLoaded, coolMin, pinRank = null, rotates,
  onSwitch, switching, onProbe, probing, onRefresh, onTogglePin, onToggleRotate, onRemove, onShowDetail }: {
  t: Theme;
  /** 平台识别色（App 用 `colorOf(traffic, "agy")` 算好传下来）。 */
  color: string;
  snap: AgySnapshot | null;
  busy?: boolean;
  err?: string | null;
  disabled?: boolean;
  state: OvState;
  hov?: boolean;
  drag?: DragWiring;
  aid?: string;
  action?: AgyAction | null;
  plan?: string | null;
  label?: string;
  email?: string;
  bestPct?: number | null;
  privacy: boolean;
  live?: LiveLine | null;
  lastUse?: { last: number; today: number } | null;
  rotLoaded?: boolean;
  /** `read_agy_board` 给的「额度见底，约几分钟后回来」。 */
  coolMin?: number;
  pinRank?: number | null;
  rotates?: boolean;
  onSwitch?: () => void;
  switching?: boolean;
  onProbe?: () => void;
  probing?: boolean;
  onRefresh?: () => void;
  onTogglePin?: () => void;
  onToggleRotate?: (on: boolean) => void;
  onRemove?: () => void;
  onShowDetail?: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const fire = useProbeFire(onProbe ?? (() => {}), !!probing);
  if (!agyQuotaVisible(snap, { disabled })) return null;

  const shown = agyShown(snap);
  const degraded = !!snap && !snap.available;
  const tight = agyTightest(shown?.quota);
  const rem = tight ? tight.b.remaining_percent : null;
  const rows = agyWinRows(shown?.quota);
  const tone = snap ? agyReasonTone(snap) : "muted";
  const readOnly = label === undefined;

  const toWin = (lbl: "5h" | "周", kind: "5h" | "w"): OvWin => {
    const row = rows.find((r) => r.label === lbl);
    // 看得见的字也要说「这次没读到」（不许只留一个 —）：下一步是点刷新，不是干等。
    if (!row) return { label: lbl, pct: null, reset: "", kind, absent: true, note: "没读到",
                       title: `${lbl} 窗口这次没读到 —— 点「刷新」重取一次。` };
    // 看得见的那几个字也要分开两种「—」：旧读数过期了 vs 上游这次没给（格子 48px，只放得下 3 个字，全句在 title）。
    if (row.remaining == null) return { label: lbl, pct: null, reset: "", kind, note: row.seen_at ? "已过期" : "没给数",
                                        title: row.seen_at ? AGY_EXPIRED_TITLE : AGY_UNKNOWN_TITLE };
    const rt = agyResetText(row);
    return { label: lbl, pct: row.remaining, kind, reset: rt.text, dim: !!row.seen_at,
             title: row.seen_at
               ? `${row.group ?? "?"} · 剩 ${row.remaining.toFixed(1)}% —— 这是 ${fmtAgo(row.seen_at)}的读数：最近一次云端没返回这一组，沿用上次的数。`
               : `${row.group ?? "?"} · 剩 ${row.remaining.toFixed(1)}%${rt.title ? `\n${rt.title}` : ""}` };
  };

  const off = rotates === false && !readOnly;
  // ★ 停轮换覆盖原状态标签（P5 §2.3）；边框 / 环仍按原状态。
  const tag = off ? { text: "不轮换", kind: "off" as const }
    : state === "inuse" ? { text: "在用", kind: "inuse" as const }
    : state === "next" ? { text: "下一个", kind: "next" as const }
    : state === "cool" ? { text: "冷却中", kind: "cool" as const }
    : state === "unprobed" ? { text: "未探测", kind: "unprobed" as const }
    : state === "low" ? { text: "额度低", kind: "low" as const }
    : state === "readonly" ? { text: "只读", kind: "readonly" as const }
    : null;
  const delta = state === "ok" || state === "next" || state === "low" ? deltaText(rem, bestPct ?? null) : "";

  const head = (
    <>
      <b data-card-name="" data-hero-acct={state === "inuse" ? "" : undefined}
         style={{ fontSize: 15, minWidth: 24, overflow: "hidden", textOverflow: "ellipsis" }}>{label ?? "agy"}</b>
      {tag && <OvTag tag={tag} title={state === "next" && !off ? "下次启动 agy 会装进这个号（与顶部续航条同一个真源：agy-rotate next）"
                                     : state === "readonly" ? "Antigravity 还没建账号池 —— `agy-rotate login --current` 收编当前号"
                                     : off ? "不轮换 —— 仍在池里，启动 agy 时自动换号不挑它；手动可切（池子空且开着借用时除外）" : undefined} />}
      {agyBadgePlan(plan) === "ultra" && <OvTag tag={{ text: "ULTRA", kind: "ultra" }} title="Google AI Ultra" />}
      {degraded && snap && <StaleMark t={t} note={action ? action.note : agyReasonNote(snap)} tone={tone} size={11} />}
      {!!err && <StaleMark t={t} note={`读不到本机的额度快照：${err}`} tone="red" size={11} />}
    </>
  );
  const marks = readOnly ? null : (
    <>
      {off && onToggleRotate && <RotMark onRestore={() => onToggleRotate(true)} />}
      {onTogglePin && <PinMark rank={pinRank} onToggle={onTogglePin} hint="下次启动 agy 优先用它" />}
    </>
  );
  const right = delta === "最优" ? <OvTag tag={{ text: "最优", kind: "best" }} title="全池可用号里余量最多的" />
    : delta ? <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "var(--tx3)" }}>{delta}</span>
    : null;

  const lastLine = lastUse && lastUse.last > 0
    ? `上次用 ${fmtClock(lastUse.last * 1000)} · 今日 ${lastUse.today > 0 ? fmtTokens(lastUse.today) : "0"}`
    : rotLoaded ? "24 小时内没启动过它" : "上次用 —";
  const dyn = state === "inuse" && live && live.sessions > 0 ? (
    <DynText tone="live" title="Gemini 此刻在跑的会话合计（与托盘 / 刘海同源）">
      <i style={{ display: "inline-block", verticalAlign: 1, margin: "0 7px 0 3px", width: 6, height: 6, borderRadius: 3,
                  background: "var(--acc)", boxShadow: "0 0 0 3px rgba(45,212,191,.2)" }} />
      {fmtTps(live.tps)} t/s · {live.sessions} 会话 · 今日 {fmtTokens(live.today)}
    </DynText>
  ) : tight == null && action ? (
    <AgyActionLink t={t} action={action} fontSize={11.5} />
  ) : state === "cool" ? (
    <DynText tone="warn">额度见底 · {coolMin ? `约 ${fmtDur(coolMin)} 后回来` : "等它回满"}</DynText>
  ) : state === "unprobed" ? (
    <DynText tone="bad">{busy ? "正在取额度…" : "未读到额度 · 点刷新再取一次"}</DynText>
  ) : state === "low" ? (
    <DynText tone="bad">额度低 · 最紧一格剩 {Math.round(rem ?? 0)}%</DynText>
  ) : state === "readonly" ? (
    <DynText tone="muted">本机 agy 正在用的号 · 未建池</DynText>
  ) : (
    <DynText tone="muted">{lastLine}</DynText>
  );

  // 底栏左：套餐名（P5 §3.1：Gemini 写「Google AI Ultra / Pro」）；读数是旧的就先说是几时的；不知道套餐退回最紧那格的重置日。
  const planName = plan === "ultra" ? "Google AI Ultra" : plan === "pro" ? "Google AI Pro" : null;
  const footLeft = (
    <span data-agy-footer="" title={(tight?.group
      ? `${tight.group} 是 4 个桶里最紧的，它在 ${fmtResetDate(tight.b.reset_at)} 重置。⚠️ 这不是订阅到期日 —— agy 不提供订阅期。`
      : "还没读到任何窗口的重置时刻") + `\n${readOnly ? "Google 订阅 · 不在轮换池" : "Google 订阅 · 在轮换池"}`}>
      {shown?.stale ? `${fmtAgo(shown.at ?? undefined)}的读数`
        : planName ?? (tight ? `重置 ${fmtResetDate(tight.b.reset_at)}` : shown ? "重置 —" : "额度暂时读不到")}
    </span>
  );

  const actions = readOnly ? (
    <Ab onClick={onRefresh} disabled={busy} data="refresh" title="重新取一次额度（本机 / 云端读数，零消耗）">
      <IcRefresh spin={busy} />刷新
    </Ab>
  ) : (
    <ActGroup>
      {state === "dead" ? null : state === "inuse" ? (
        <Ab current data="inuse" title="当前正在用这个号（钥匙串里是它）">在用</Ab>
      ) : onSwitch && (
        <Ab primary onClick={onSwitch} disabled={switching} data="switch" title="换号 · 下一次启动 agy 生效（已开着的会话不受影响）">
          {switching ? "切换中…" : "切换"}
        </Ab>
      )}
      {onProbe && state !== "dead" && (
        <ProbeIb loading={!!probing} onFire={onProbe}
                 hint={`起一次 agy 让 ${label} 真跑一句，验它是否真能干活。⚠️ 计费：花的是 agy 自己的额度（实测单次约 15k token、约 30s）`} />
      )}
      {state !== "dead" && <RotIb off={off} onToggle={onToggleRotate ? (wasOff) => onToggleRotate(wasOff) : undefined} unsupported={!onToggleRotate} />}
      <CardMenu onOpenChange={setMenuOpen} items={[
        ...(onProbe && state !== "dead" ? [{ key: "probe", label: "探针 · 计费", icon: <IcBolt />, warn: true, narrow: true, onClick: fire }] : []),
        ...(onShowDetail ? [{ key: "detail", label: "详情", icon: <IcInfo />, onClick: onShowDetail }] : []),
        ...(onRemove ? [{ key: "remove", label: "删除", icon: <IcTrash />, bad: true, onClick: onRemove }] : []),
      ]} />
    </ActGroup>
  );

  return (
    <OvCard id={aid ?? label ?? "agy"} t={t} state={state} ringPct={rem} platColor={color} head={head} right={right}
            email={email ? maskId(email, privacy) : (busy ? "正在取额度…" : "—")}
            emailTitle={tight?.group ? `环上的数来自 ${tight.group} —— 4 个桶里最紧的那个。任何一个见底 agy 就用不了，所以取最小值。` : undefined}
            dyn={dyn} w5={toWin("5h", "5h")} ww={toWin("周", "w")}
            marks={marks} off={off} pinned={pinRank !== null}
            footLeft={footLeft} actions={actions} hov={hov} menuOpen={menuOpen} drag={drag} />
  );
}
