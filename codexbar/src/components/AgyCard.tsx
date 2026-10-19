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
import { Ab, DynText, HoldAb, IcRefresh, IcSwap, OvCard, OvMenu, OvTag, type OvWin } from "./ov/OvCard";
import type { LiveLine } from "./AccountCard";

/**
 * Gemini（agy）账号卡 —— 与 Codex 卡**同一个外壳**（交接包 page5 §3：「Codex 和 Gemini 同结构」）。
 *
 * ★ 机制差别只体现在**说法**上（照搬 codex 的原话在这几处都是假话）：
 *   · 「切换」= 把这个号写进钥匙串，**只对下一次启动的 agy 生效**（已开着的会话不受影响）；
 *   · 「冷却」= 额度见底（agy 没有 429 冷却这回事）；
 *   · 页脚左格是**最紧那个窗口的重置日**，不是「到期」—— agy 不提供订阅到期日（2026-09-16 三个探针一致）。
 * ★ 池里没有号时退回那张**只读卡**（`agy-rotate login --current` 之前的形态）：只有「刷新」。
 * ★ 旧卡上的每个操作都还在（CLAUDE.md §6）：切换 · 探针 · 刷新在底栏；置顶 · 轮换 · 改名 · 查看用量 · 移除在 ⋯。
 */
export default function AgyCard({ t, color, snap, busy, err, disabled, state, hov, drag, aid, action, plan, label, email,
  bestPct, privacy, live, lastUse, rotLoaded, coolMin, pinRank = null, rotates,
  onSwitch, switching, onProbe, probing, onRefresh, onTogglePin, onToggleRotate, onRename, onRemove, onOpen }: {
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
  onRename?: (next: string) => void;
  onRemove?: () => void;
  onOpen?: () => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
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

  const tag = state === "inuse" ? { text: "在用", kind: "inuse" as const }
    : state === "next" ? { text: "下一个", kind: "next" as const }
    : state === "cool" ? { text: "冷却中", kind: "cool" as const }
    : state === "unprobed" ? { text: "未探测", kind: "unprobed" as const }
    : state === "low" ? { text: "额度低", kind: "low" as const }
    : state === "off" ? { text: "已停用", kind: "off" as const }
    : state === "readonly" ? { text: "只读", kind: "readonly" as const }
    : null;
  const delta = state === "ok" || state === "next" || state === "low" ? deltaText(rem, bestPct ?? null) : "";

  const head = (
    <>
      {editing !== null ? (
        <input autoFocus value={editing} data-ov-rename=""
               onClick={(e) => e.stopPropagation()}
               onChange={(e) => setEditing(e.target.value)}
               onKeyDown={(e) => {
                 e.stopPropagation();
                 if (e.key === "Enter" && editing.trim()) { onRename?.(editing.trim()); setEditing(null); }
                 if (e.key === "Escape") setEditing(null);
               }}
               onBlur={() => setEditing(null)}
               style={{ fontSize: 14, fontWeight: 700, color: "var(--tx)", minWidth: 0, width: 110, background: "transparent",
                        border: "1px solid var(--accLine)", borderRadius: 5, padding: "0 4px", fontFamily: "inherit", height: 20 }} />
      ) : (
        <b data-card-name="" data-hero-acct={state === "inuse" ? "" : undefined}
           style={{ fontSize: 15, minWidth: 24, overflow: "hidden", textOverflow: "ellipsis" }}>{label ?? "agy"}</b>
      )}
      {pinRank !== null && (
        <span data-pin-badge="" title={`已置顶（第 ${pinRank + 1} 位）—— 下次启动 agy 优先用它`}
              style={{ fontSize: 10.5, fontWeight: 700, color: "var(--acc)", flexShrink: 0 }}>▲{pinRank + 1}</span>
      )}
      {tag && <OvTag tag={tag} title={state === "next" ? "下次启动 agy 会装进这个号（与顶部续航条同一个真源：agy-rotate next）"
                                     : state === "readonly" ? "Antigravity 还没建账号池 —— `agy-rotate login --current` 收编当前号"
                                     : state === "off" ? "已停用自动轮换 —— 启动 agy 时不会挑它（池子空且开着借用时除外）" : undefined} />}
      {/* 在用但停了轮换（被借用 / 被别的 agy 写回）：「在用」压过了「已停用」，这枚补上另一半事实。 */}
      {rotates === false && state === "inuse" && <OvTag tag={{ text: "已停用", kind: "off" }} title="这个号停了自动轮换，此刻钥匙串里是它" />}
      {agyBadgePlan(plan) === "ultra" && <OvTag tag={{ text: "ULTRA", kind: "ultra" }} title="Google AI Ultra" />}
      {degraded && snap && <StaleMark t={t} note={action ? action.note : agyReasonNote(snap)} tone={tone} size={11} />}
      {!!err && <StaleMark t={t} note={`读不到本机的额度快照：${err}`} tone="red" size={11} />}
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
  ) : state === "off" ? (
    <DynText tone="muted">已停用轮换 · {lastLine}</DynText>
  ) : (
    <DynText tone="muted">{lastLine}</DynText>
  );

  const footLeft = (
    <span data-agy-footer="" title={(tight?.group
      ? `${tight.group} 是 4 个桶里最紧的，它在 ${fmtResetDate(tight.b.reset_at)} 重置。⚠️ 这不是订阅到期日 —— agy 不提供订阅期。`
      : "还没读到任何窗口的重置时刻") + `\n${readOnly ? "Google 订阅 · 不在轮换池" : "Google 订阅 · 在轮换池"}`}>
      {shown?.stale ? `${fmtAgo(shown.at ?? undefined)}的读数`
        : tight ? `重置 ${fmtResetDate(tight.b.reset_at)}`
        : shown ? "重置 —" : "额度暂时读不到"}
    </span>
  );
  const footRight = plan === "ultra" || plan === "pro" ? (
    <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--tx3)", flexShrink: 0 }}>
      {plan === "ultra" ? "Google AI Ultra" : "Google AI Pro"}
    </span>
  ) : null;

  const actions = readOnly ? (
    <Ab onClick={onRefresh} disabled={busy} data="refresh" title="重新取一次额度（本机 / 云端读数，零消耗）">
      <IcRefresh spin={busy} />刷新
    </Ab>
  ) : (
    <>
      {state !== "inuse" && onSwitch && (
        <Ab primary onClick={onSwitch} disabled={switching} data="switch"
            title={`${state === "off" ? "借用" : "切到"} ${label} —— ★ 只对**下一次启动的** agy 生效，已开着的会话不受影响`}>
          <IcSwap />{switching ? "切换中…" : state === "off" ? "借用" : "切换"}
        </Ab>
      )}
      {onProbe && state !== "off" && (
        <HoldAb loading={!!probing} onFire={onProbe}
                hint={`起一次 agy 让 ${label} 真跑一句，验它是否真能干活。⚠️ 计费：花的是 agy 自己的额度（实测单次约 15k token、约 30s）`} />
      )}
      <Ab onClick={onRefresh} disabled={busy} data="refresh" title="重新取一次这一池的额度（云端按账号读，零消耗）">
        <IcRefresh spin={busy} />刷新
      </Ab>
      <OvMenu onOpenChange={setMenuOpen} items={[
        { key: "pin", label: pinRank !== null ? `取消置顶（第 ${pinRank + 1} 位）` : "置顶 —— 下次启动优先用它", onClick: onTogglePin, hidden: !onTogglePin },
        { key: "rotate", label: rotates ? "停用自动轮换" : "恢复自动轮换", onClick: () => onToggleRotate?.(!rotates), hidden: !onToggleRotate },
        { key: "rename", label: "重命名", onClick: () => setEditing(label ?? ""), hidden: !onRename },
        { key: "usage", label: "查看用量 →", onClick: onOpen, hidden: !onOpen },
        { key: "remove", label: "从池里移除", bad: true, confirm: "再点一次确认移除", onClick: onRemove, hidden: !onRemove },
      ]} />
    </>
  );

  return (
    <OvCard id={aid ?? label ?? "agy"} t={t} state={state} ringPct={rem} platColor={color} head={head} right={right}
            email={email ? maskId(email, privacy) : (busy ? "正在取额度…" : "—")}
            emailTitle={tight?.group ? `环上的数来自 ${tight.group} —— 4 个桶里最紧的那个。任何一个见底 agy 就用不了，所以取最小值。` : undefined}
            dyn={dyn} w5={toWin("5h", "5h")} ww={toWin("周", "w")}
            footLeft={footLeft} footRight={footRight} actions={actions} hov={hov} menuOpen={menuOpen} drag={drag} />
  );
}
