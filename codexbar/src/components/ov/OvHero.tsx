import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Board } from "../../hooks/useRotationBoard";
import type { LivePlatform } from "../../live";
import { fmtTokens, fmtTps } from "../../live";
import { maskId } from "../../helpers";
import { burstTitle, eta5hTitle, fmtEtaMin } from "../../eta5h";
import { fitSignature, segFits } from "../../runwayFit";
import type { OvLayout, RelayPlan, SwitchRow } from "../../overview";
import { RELAY_COLORS, agyRelayInputs, codexRelayInputs, fmtClock, fmtDur, gapNote, relayPlan, segBox } from "../../overview";
import { OvRing } from "./OvCard";
import { MONO } from "./ovVars";

/**
 * 顶部三栏（交接包 page5「顶部三栏（约 96 高，内边距 10 / 16，栏间 1 px 分隔线）」）。
 *
 * ★★ 它取代了 `RunwayHero`（2026-09-21 的「续航条 D」，已整体删除）。那块的三个承诺都还在：
 *   ① 「正在使用」= `last_aid`（代理最近一次真的用了谁），并写出时间；
 *   ② 续航按**连续使用时间**（`codex-rotate::_burst`），口径写在条下（披露不是装饰）；
 *   ③ 池子见底 ⇒ 不画续航数字，实心红底「池子见底」+ 最快多久回来 + 各类不可用的号数与能做什么。
 *   新增的是交接包要的接力条：断档用红色斜纹、之后回来的号用淡色段（`overview.ts::relayPlan`）。
 */

/**
 * 四个平台的识别色。★ 由 App 用 `colorOf(traffic, key)` 算好传进来（`ui.md`：取平台色一律走 `colorOf`，
 * 它已把用户在设置里改的颜色折进去；直接写死色值 = 绕过用户偏好）。
 */
export type PlatColors = Record<"codex" | "claude" | "gemini" | "grok", string>;

export function HeroShell({ pc, layout, children }: { pc: string; layout: OvLayout; children: ReactNode }) {
  return (
    <div data-ov-hero="" data-ov-hero-cols={layout.wide ? 3 : 2}
         style={{ display: "grid", gridTemplateColumns: layout.heroCols, columnGap: 16, padding: "10px 16px 8px",
                  borderRadius: 12, background: `linear-gradient(135deg, ${pc}12, ${pc}04)`, border: `1px solid ${pc}48`,
                  flexShrink: 0, minWidth: 0 }}>
      {children}
    </div>
  );
}

export const Divider = () => <i aria-hidden style={{ background: "var(--line)" }} />;

export function ColTitle({ children, right, gap = 8, between }: { children: ReactNode; right?: ReactNode; gap?: number; between?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", height: 18, fontSize: 11, letterSpacing: ".04em", color: "var(--tx3)",
                  gap, justifyContent: between ? "space-between" : undefined, minWidth: 0 }}>
      {children}{right}
    </div>
  );
}

/** 「正在使用」栏：环 54 · 号名 20 · 邮箱 · 实时速度行。 */
export function NowCol({ title, right, pct, color, name, extra, email, line }: {
  title: string; right?: ReactNode; pct: number | null; color: string; name: ReactNode; extra?: ReactNode;
  email: ReactNode; line: ReactNode;
}) {
  return (
    <div data-ov-now="" style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
      <ColTitle between right={right}><span>{title}</span></ColTitle>
      <div style={{ display: "flex", gap: 12, alignItems: "center", minWidth: 0 }}>
        <OvRing size={54} r={24.5} sw={5} pct={pct} color={color} numSize={16} dot={pct == null} />
        <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
            <b data-ov-now-name="" style={{ fontSize: 20, lineHeight: 1, flexShrink: 0 }}>{name}</b>
            {extra}
            <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 11, color: "var(--tx2)",
                           overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>{email}</span>
          </div>
          <div data-ov-live-line="" style={{ display: "block", fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 11.5,
                                             overflow: "hidden", textOverflow: "ellipsis" }}>{line}</div>
        </div>
      </div>
    </div>
  );
}

/** 实时速度行 `● 244 t/s · ×2 · 3.8M`（与托盘 / 刘海同源：`read_live`）。读不到写 —。
 *  ★ 短格式（用户 2026-10-23「话太多了」），整句进悬停提示；与卡片第二行同一套写法。 */
export function LiveLineView({ live, liveErr }: { live: LivePlatform | null | undefined; liveErr: boolean }) {
  if (!live) {
    return <span style={{ color: "var(--tx3)" }}>{liveErr ? "实时速度读不到 —" : "—"}</span>;
  }
  if (!live.running || live.n_sessions === 0) {
    return <span style={{ color: "var(--tx3)" }} title={`此刻没有在跑的会话 · 今日 ${fmtTokens(live.tokens_today)} token`}>空闲 · {fmtTokens(live.tokens_today)}</span>;
  }
  return (
    <span title={`此刻在跑：${fmtTps(live.tps)} t/s · ${live.n_sessions} 个会话 · 今日 ${fmtTokens(live.tokens_today)} token`}>
      <i style={{ display: "inline-block", verticalAlign: 1, margin: "0 7px 0 3px", width: 6, height: 6, borderRadius: 3,
                  background: "var(--acc)", boxShadow: "0 0 0 3px rgba(45,212,191,.2)" }} />
      <b style={{ color: "var(--ovNum)" }}>{fmtTps(live.tps)}</b>
      <span style={{ color: "var(--tx3)" }}> t/s · ×{live.n_sessions} · {fmtTokens(live.tokens_today)}</span>
    </span>
  );
}

const TICKS = [0, 25, 50, 75, 100];
const TICK_TX = ["现在", "+1h", "+2h", "+3h", "+4h"];

/**
 * 续航接力条（横轴 现在 → +4h，每小时一条刻度线）。
 * ★ 色段只区分**账号**（原型的五色，按接力序取）；断档 = 红色斜纹，**不留灰色空白**（README §5）。
 * ★ 段里写不写号名按**像素**判（`runwayFit.segFits`，ResizeObserver 现量）—— 写不下宁可不写，
 *   被截断的 `Ase…` 会被当成另一个号（旧续航条记过）。
 */
export function RelayBar({ plan, caption, marker }: {
  plan: RelayPlan | null; caption: ReactNode;
  /** 没有接力可画时（Claude）在轴上标一个时刻，如 5h 回满。 */
  marker?: { atMin: number; text: string } | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const segs = plan?.segs ?? [];
  const boxes = segs.map((s) => ({ s, box: segBox(s) })).filter((x) => x.box && x.box.width > 0);
  /* ★ 拖窗口时 RO 每帧都报新宽度（2026-10-15 三方评审）：真正影响画面的只有「哪几段写得下名字」，
   *   所以宽度记在 ref 里、签名翻了才 setState；渲染读 ref，换数据时用的也是最新宽度。 */
  const items = useRef<[number, string][]>([]);
  items.current = boxes.filter((x) => x.s.kind !== "gap").map((x) => [(x.box as { width: number }).width, x.s.label ?? ""]);
  const wRef = useRef(0);
  const [, setSig] = useState("");
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let last: string | null = null;
    const measure = () => {
      wRef.current = el.clientWidth;
      const sig = fitSignature(items.current, 100, wRef.current, 11);
      if (sig !== last) { last = sig; setSig(sig); }
    };
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, []);
  const w = wRef.current;
  const gap = plan?.firstGap ?? null;
  return (
    <div ref={ref} data-runway-bar="" style={{ position: "relative", width: "100%", height: 53 }}>
      {TICKS.map((p, i) => (
        <span key={p} style={{ position: "absolute", left: `${p}%`, top: 0,
                               transform: i === 0 ? "translateX(0)" : i === 4 ? "translateX(-100%)" : "translateX(-50%)",
                               fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 10, lineHeight: "11px", color: "var(--tx3)" }}>
          {TICK_TX[i]}
        </span>
      ))}
      <span style={{ position: "absolute", left: 0, top: 13, width: "100%", height: 22, borderRadius: 5, background: "var(--ovTrackBar)" }} />
      {[25, 50, 75].map((p) => (
        <i key={p} style={{ position: "absolute", left: `${p}%`, top: 11, width: 1, height: 26, background: "var(--ovTick)" }} />
      ))}
      {boxes.map(({ s, box }, i) => {
        const b = box as { left: number; width: number };
        const last = b.left + b.width >= 99.999;
        const width = last ? `${b.width}%` : `calc(${b.width}% - 2px)`;
        if (s.kind === "gap") {
          return (
            <span key={`g${i}`} data-relay-gap="" title={gapNote(s)}
                  style={{ position: "absolute", left: `${b.left}%`, top: 13, width, height: 22, borderRadius: 5,
                           background: "repeating-linear-gradient(135deg, rgba(255,77,46,.75) 0 4px, rgba(255,77,46,.18) 4px 8px)",
                           boxShadow: "inset 0 0 0 1px rgba(255,77,46,.6)" }} />
          );
        }
        const c = RELAY_COLORS[(s.color ?? 0) % RELAY_COLORS.length];
        const back = s.kind === "back";
        const dur = Number.isFinite(s.end) ? fmtDur(s.end - s.start) : "配速未知";
        const fits = segFits(b.width, 100, w, s.label ?? "", 11);
        return (
          <span key={`s${i}`} data-relay-seg={s.kind} data-relay-acct={s.label}
                title={`${s.label} · ${back ? "回满后接上 · " : ""}${s.kind === "open" ? "配速未知（没有 5h 用完的历史 / Pro 没有 5h 窗口）—— 至少接到这里" : `能连续用 ${dur}`}`}
                style={{ position: "absolute", left: `${b.left}%`, top: 13, width, height: 22, borderRadius: 5,
                         background: back ? `${c}47` : c, boxShadow: back ? `inset 0 0 0 1px ${c}88` : undefined,
                         display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700,
                         color: back ? "var(--ovBackTx)" : "var(--ovSegTx)", overflow: "hidden" }}>
            {fits ? s.label : ""}
          </span>
        );
      })}
      {marker && marker.atMin >= 0 && marker.atMin <= 240 && (
        <span data-relay-marker="" title={marker.text}
              style={{ position: "absolute", left: `${(marker.atMin / 240) * 100}%`, top: 11, width: 2, height: 26,
                       background: "var(--acc)", borderRadius: 1 }} />
      )}
      <div style={{ position: "absolute", left: 0, right: 0, top: 38, display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
        <span data-runway-note="" style={{ flex: "1 1 0", minWidth: 0, fontSize: 10, color: "var(--tx3)", fontFamily: MONO,
                                           overflow: "hidden", textOverflow: "ellipsis" }}>{caption}</span>
        {gap && (
          <span data-relay-gap-note="" style={{ flex: "0 0 auto", maxWidth: "100%", display: "flex", alignItems: "center", gap: 4,
                                                fontSize: 10.5, fontWeight: 600, color: "var(--badTx)", overflow: "hidden" }}>
            <i style={{ display: "block", width: 8, height: 8, borderRadius: 2, flexShrink: 0,
                        background: "repeating-linear-gradient(135deg, #FF4D2E 0 2px, rgba(255,77,46,.25) 2px 4px)" }} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{gapNote(gap)}</span>
          </span>
        )}
      </div>
    </div>
  );
}

/** 「今天的切换 · N 次」第三栏（≥1200）。 */
export function SwitchCol({ rows, onLogs, empty }: { rows: SwitchRow[] | null; onLogs: () => void; empty?: string }) {
  return (
    <div data-ov-switches="col" style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
      <ColTitle between right={<span data-ov-logs="" onClick={onLogs} style={{ color: "var(--ovNum)", cursor: "pointer" }}>日志 →</span>}>
        <span>今天的切换 · {rows ? rows.length : "—"} 次</span>
      </ColTitle>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {rows && rows.length > 0 ? rows.slice(0, 3).map((r) => (
          <div key={`${r.t}${r.to}`} data-ov-switch-row=""
               style={{ display: "grid", gridTemplateColumns: "38px 8px minmax(0, 1fr)", columnGap: 8, alignItems: "center",
                        height: 19, fontSize: 11.5 }}>
            <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", color: "var(--tx3)" }}>{fmtClock(r.t * 1000)}</span>
            <i style={{ display: "block", width: 6, height: 6, borderRadius: 3, background: r.dot }} />
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
              <b style={{ fontWeight: 600 }}>{r.from} → {r.to}</b><span style={{ color: "var(--tx2)" }}> · {r.why}</span>
            </span>
          </div>
        )) : (
          <span style={{ height: 19, fontSize: 11.5, color: "var(--tx3)", overflow: "hidden", textOverflow: "ellipsis" }}>
            {empty ?? (rows ? "今天还没有换过号" : "切换记录还没读到 —")}
          </span>
        )}
      </div>
    </div>
  );
}

/** 1000 / 860 档：「今天的切换」收成三栏下方一行。 */
export function SwitchRowNarrow({ rows, onLogs, empty }: { rows: SwitchRow[] | null; onLogs: () => void; empty?: string }) {
  return (
    <div data-ov-switches="row"
         style={{ gridColumn: "1 / -1", display: "flex", alignItems: "center", gap: 10, height: 26, marginTop: 6, paddingTop: 6,
                  borderTop: "1px solid var(--line)", fontSize: 11.5, overflow: "hidden", minWidth: 0 }}>
      <span style={{ fontSize: 11, letterSpacing: ".04em", color: "var(--tx3)", flexShrink: 0 }}>今天的切换 · {rows ? rows.length : "—"} 次</span>
      {rows && rows.length > 0 ? rows.slice(0, 3).map((r) => (
        <span key={`${r.t}${r.to}`} data-ov-switch-row="" style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, overflow: "hidden" }}>
          <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", color: "var(--tx3)" }}>{fmtClock(r.t * 1000)}</span>
          <i style={{ display: "block", width: 6, height: 6, borderRadius: 3, background: r.dot, flexShrink: 0 }} />
          <b style={{ fontWeight: 600 }}>{r.from}→{r.to}</b>
          <span style={{ color: "var(--tx2)", overflow: "hidden", textOverflow: "ellipsis" }}>{r.why}</span>
        </span>
      )) : <span style={{ color: "var(--tx3)", overflow: "hidden", textOverflow: "ellipsis" }}>{empty ?? (rows ? "今天还没有换过号" : "—")}</span>}
      <span data-ov-logs="" onClick={onLogs} style={{ marginLeft: "auto", color: "var(--ovNum)", cursor: "pointer", flexShrink: 0 }}>日志 →</span>
    </div>
  );
}

/** Codex / Gemini 的三栏（同一结构，只换说法）。 */
export function PoolHero({ source, board, layout, privacy, live, liveErr, switches, onLogs, nowMs, pc }: {
  source: "codex" | "agy"; board: Board; layout: OvLayout; privacy: boolean; pc: string;
  live: LivePlatform | null | undefined; liveErr: boolean;
  switches: SwitchRow[] | null; onLogs: () => void; nowMs: number;
}) {
  const agy = source === "agy";
  const cur = board.cur ?? board.next;
  const stranded = board.queue.length === 0;
  const inputs = agy ? agyRelayInputs(board) : codexRelayInputs(board);
  const plan = inputs ? relayPlan(inputs) : null;
  const borrowed = !!cur && stranded && (cur.off || cur.dead || cur.cool_min > 0);
  const backInMin = board.rest.reduce<number | null>(
    (a, e) => (e.cool_min > 0 && !e.off && !e.dead ? (a == null ? e.cool_min : Math.min(a, e.cool_min)) : a), null);
  const nCool = board.rest.filter((e) => e.cool_min > 0 && !e.off && !e.dead).length;
  const nOff = board.rest.filter((e) => e.off).length;
  const nDead = board.rest.filter((e) => e.dead).length;

  // 「自动切到 · HH:MM」：今天最后一次切到当前号的那条；没有就写代理最近一次用它的时刻。
  const lastTo = cur && switches ? switches.find((r) => r.to === cur.label) : undefined;
  const nowRight = lastTo
    ? <span style={{ color: "var(--ovNum)", overflow: "hidden", textOverflow: "ellipsis" }}>{lastTo.why === "手动切换" || lastTo.why === "按你的选择" ? "手动切到" : "自动切到"} · {fmtClock(lastTo.t * 1000)}</span>
    : board.cur_ago_min != null
      ? <span style={{ color: "var(--tx3)", overflow: "hidden", textOverflow: "ellipsis" }}>{agy ? "装进于" : "最近一次"} · {fmtClock(nowMs - board.cur_ago_min * 60000)}</span>
      : null;
  const pct = cur?.tightest ?? null;
  const ringC = !cur ? "var(--tx3)" : cur.dead || (pct != null && Math.round(pct) < 10) ? "var(--bad)" : cur.cool_min > 0 ? "var(--warn)" : agy ? pc : "var(--acc)";

  const v = plan?.continuousMin ?? null;
  const value = stranded ? null : v == null ? "—" : `${plan?.atLeast ? "≥ " : ""}${fmtDur(v)}`;
  const burst = board.burst ?? null;
  /** 5h 一整窗连续用多久见底（用户 2026-10-15：只在全池续航这一处展示）。优先全池口径，
   *  没有才退到正在用的号；agy 恒为 null。 */
  const eta = agy ? null : [board.cur, ...board.queue, ...board.rest].find((e) => e?.eta5h?.scope === "pool")?.eta5h ?? board.cur?.eta5h ?? null;
  const etaSpan = eta ? <span data-eta5h="" title={eta5hTitle(eta)}> · 5h 一窗≈{fmtEtaMin(eta.per_window_min)}</span> : null;
  /** 本周还能连续用多久（旧续航条的「本周 ≈」，2026-10-15）。换算样本不够时写「—」不写 0。 */
  const weekSpan = burst
    ? <span data-burst-week="" title={burstTitle(burst, board.weekly_left_pp)}> · 本周≈{burst.week_min != null ? fmtDur(burst.week_min) : "—"}</span>
    : null;
  const caption = stranded
    ? `${nCool} 个${agy ? "额度见底" : "冷却中"} · ${nOff} 个你已停用 · ${nDead} 个凭证失效`
      + (nOff > 0 ? " —— 想立刻继续用，把某个停用的号在它卡片上「借用」或恢复轮换" : "")
    : agy
      ? (inputs ? "钟点时间（含空闲）· 按全池周消耗速度" + (board.burn_pp_per_hour != null ? ` ${board.burn_pp_per_hour}pp/h` : "")
                : "续航算不出来 —— Gemini 还没有可估消耗速度的记录，不是「撑不了多久」")
      : burst
        ? <>连续使用时间 · 按 {burst.events} 次 5h 用完的配速 · 间隔 &gt;5 分钟算闲置{weekSpan}{etaSpan}
          {burst.wk_per_5h != null ? ` · 5h 1pp≈周 ${burst.wk_per_5h}pp` : " · 周换算样本还不够"}</>
        : <>连续使用时间算不出来 —— 还没有 3 次 5h 用完的历史，不是「撑不了多久」{etaSpan}</>;

  const runway = (
    <div data-ov-runway="" style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
      <ColTitle gap={10}>
        <span>还能连续用</span>
        {stranded ? (
          <>
            <span data-runway-stranded="" style={{ fontSize: 10, color: "#fff", fontFamily: MONO, fontWeight: 700, letterSpacing: ".06em",
                                                    background: "var(--bad)", borderRadius: 5, padding: "1px 6px" }}>池子见底</span>
            <span style={{ fontSize: 11, color: "var(--tx2)" }}>{board.rest.length} 个号全不可用</span>
            {backInMin != null && <span style={{ marginLeft: "auto" }}>最快 {fmtDur(backInMin)} 后回来</span>}
          </>
        ) : (
          <>
            <b data-runway-hours="" title={burst && !agy ? burstTitle(burst, board.weekly_left_pp) : undefined}
               style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 18, lineHeight: 1, color: "var(--tx)",
                        letterSpacing: 0 }}>{value}</b>
            {v != null && <span data-runway-until="" style={{ marginLeft: "auto" }}>到 {fmtClock(nowMs + v * 60000)}</span>}
          </>
        )}
      </ColTitle>
      <RelayBar plan={plan} caption={caption} />
    </div>
  );

  const name = cur ? cur.label ?? cur.aid : "—";
  return (
    <HeroShell pc={pc} layout={layout}>
      <NowCol title="正在使用" right={nowRight} pct={pct} color={ringC} name={name}
              extra={<>
                {cur?.pin != null && <span data-runway-pin="" style={{ fontSize: 10.5, fontWeight: 700, color: "var(--acc)", flexShrink: 0 }}>▲{cur.pin}</span>}
                {borrowed && cur && (
                  <span data-runway-borrowed="" title={cur.off ? "你已停用它的自动轮换，但此刻没有别的号可用，临时借用了它"
                                                       : cur.dead ? "这个号的凭证已失效" : `这个号${agy ? "额度见底" : "在冷却中"}（约 ${cur.cool_min} 分钟）`}
                        style={{ fontSize: 10, fontWeight: 700, color: "var(--badTx)", border: "1px solid var(--bad)", borderRadius: 5,
                                 padding: "0 4px", flexShrink: 0 }}>临时借用</span>
                )}
              </>}
              email={cur ? maskId(cur.email ?? "", privacy) : ""}
              line={<LiveLineView live={live} liveErr={liveErr} />} />
      <Divider />
      {runway}
      {layout.wide ? (<><Divider /><SwitchCol rows={switches} onLogs={onLogs} /></>)
                   : <SwitchRowNarrow rows={switches} onLogs={onLogs} />}
    </HeroShell>
  );
}
