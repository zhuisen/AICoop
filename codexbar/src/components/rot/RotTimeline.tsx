import { useLayoutEffect, useRef, useState } from "react";
import type { Theme } from "../../theme";
import { type RotLayout, clockOf, fitDur, mins, quota5hTone, rotAxis, zoomTo } from "../../rotationView";
import { fmtTokL } from "../../tokenView";
import { MONO, tkPal } from "../tk/tkPal";
import type { Acct, Rotation, Seg0 } from "./rotTypes";

/** 稿 §1.4 状态色。★ 用全局语义色（同 R2-9，偏离 P7-3）：断流琥珀 #E0901C、429 / 故障转移红 #E0524D。 */
export const WARN = "#E0901C";
export const BAD = "#E0524D";
const GOOD = "#27B26B";
const LANE_H = 44;

const MODEL_SHADES = ["#2dd4bf", "#7fe8da", "#158f80", "#4d9fff", "#8b7cf6", "#E0A21C"];
const REASON_CN: Record<string, string> = {
  cool_429: "429 冷却 → 故障转移",
  stream_err: "断流 → 轮换",
  quota_rotate: "额度轮换",
  window_start: "窗口起点",
  resume: "同号空闲后继续",
  pro_fallback: "Plus 全部不可用 → Pro 保底接管",
  drift: "身份变了却没有换号记录",
  parallel: "开头时另有 agy 进程在跑（并行，不算换号）",
  auto: "自动切换", wanted: "恢复成你选的", borrow: "借用已停用的", manual: "手动切换",
};

interface Tip {
  x: number; lane: number; flip: boolean; up: boolean; range: string; dur: string; acc: string; tokens: number; requests: number;
  models: { model: string; tokens: number; pct: number; color: string }[]; errs: number; why: string;
}

export interface Lane extends Acct { segs: Seg0[]; current: boolean; cooling: boolean }

/**
 * 在岗时间线（1h / 6h / 24h，AICoop P7 §1.4 方案 A）。
 * ★ 保留（偏离 P7-*）：悬浮明细卡（段 token / 模型拆分 / 断流 / 切入原因）、点账号名聚焦（其余 28%，记录只看它）、
 *   已移除号灰名 + 提示、PRO 的保底说明、读不到 / 空 / 无归属三种空态。
 */
export default function RotTimeline({ t, rot, lanes, lay, hours, color, num, agyTok, isAgy, tps, focus, onFocus, onZoom, empty, acctExtra }: {
  t: Theme; rot: Rotation | null; lanes: Lane[]; lay: RotLayout; hours: number; color: string; num: string;
  agyTok: boolean; isAgy: boolean; tps: Map<string, number | null>; focus: string | null;
  onFocus: (acc: string | null) => void; onZoom: (h: number) => void; empty: string; acctExtra?: React.ReactNode;
}) {
  const p = tkPal(t);
  const track = useRef<HTMLDivElement>(null);
  const [tw, setTw] = useState(400);
  const [hov, setHov] = useState(-1);
  const [hs, setHs] = useState<{ key: string; x: number; label: string } | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  useLayoutEffect(() => {
    const el = track.current;
    if (!el) return;
    setTw(Math.max(1, Math.floor(el.clientWidth / 4) * 4));
    const ro = new ResizeObserver(() => setTw(Math.max(1, Math.floor(el.clientWidth / 4) * 4)));
    ro.observe(el);
    return () => { ro.disconnect(); };
  }, [lanes.length > 0]);
  // 换数据集 ⇒ 悬停 / 浮层作废（ui-design.md「索引状态不得活过数据集」）。
  const sig = `${rot?.generated_at ?? 0}:${hours}`;
  const [lastSig, setLastSig] = useState(sig);
  if (lastSig !== sig) { setLastSig(sig); setHov(-1); setHs(null); setTip(null); }

  const W = rot?.window;
  const start = W?.start ?? 0, end = W?.end ?? 1, span = Math.max(1, end - start);
  const X = (ts: number) => Math.max(0, Math.min(100, ((ts - start) / span) * 100));
  const axis = rotAxis(start, end, hours, lay.L >= 1, tw);
  const cols = lay.cols.map((c) => `${c}px`).join(" ");
  const grid = `${lay.acctW}px minmax(0,1fr) ${cols}`;
  const idx = new Map(lanes.map((l, i) => [l.acc, i]));

  // 块内写不下时长的块数（「太短」提示）。
  let hidN = 0;
  for (const l of lanes) for (const s of l.segs) {
    const w = ((Math.min(s.end, end) - Math.max(s.start, start)) / span) * tw;
    if (!fitDur(s.end - s.start, w)) hidN += 1;
  }
  const zoom = zoomTo(hours);
  const narrow = lay.L === 2;

  // 接力线：换号时刻在两条泳道之间画竖线（断流黄实线 · 429 红虚线 · 其余灰实线）。
  const relays = (rot?.events ?? []).filter((e) => (e.type === "switch" || e.type === "failover" || e.type === "pro_fallback")
    && e.from && e.to && e.from !== e.to && idx.has(e.from) && idx.has(e.to) && e.t >= start && e.t <= end)
    .map((e) => ({ x: X(e.t), a: idx.get(e.from as string) as number, b: idx.get(e.to as string) as number,
                   c: e.reason === "stream_err" ? "rgba(224,144,28,.75)" : e.reason === "cool_429" || e.type === "failover" ? "rgba(224,82,77,.8)" : "rgba(170,179,192,.55)",
                   dash: e.reason === "cool_429" || e.type === "failover" }));

  // 冷却块：429 那一刻起，到该号下一次上岗 / 默认 300 分钟 / 窗口终点（历史冷却的终点没落盘 ⇒ 估计，偏离 P7-4）；
  // 此刻还在冷却的最后一块用真的 `cooling_until`。
  const cools = (acc: Lane) => {
    const ms = (rot?.markers ?? []).filter((m) => m.acc === acc.acc && m.kind === "cool_429").sort((a, b) => a.t - b.t);
    return ms.map((m, i) => {
      const next = acc.segs.find((s) => s.start > m.t)?.start ?? Infinity;
      // ★ 只有 429 之后没再上岗、且 `cooling_until` 晚于这次 429，才是「此刻还在冷却的那一块」—— 否则会把
      //   一次早已结束的冷却画穿后面正常的在岗段（评审 gemini 阶段 5）。
      const live = i === ms.length - 1 && next === Infinity && acc.cooling_until != null && acc.cooling_until > m.t;
      const e = live ? Math.min(acc.cooling_until as number, end) : Math.min(next, m.t + 300 * 60, end);
      return { l: X(m.t), w: Math.max(0.3, X(e) - X(m.t)), title: `${acc.acc} 冷却 ${clockOf(m.t)}–${clockOf(e)}${live ? "" : "（终点是估计）"}` };
    });
  };

  const qc = (v: number | null | undefined) => {
    const k = quota5hTone(v);
    return k === "bad" ? BAD : k === "warn" ? WARN : k === "ok" ? GOOD : p.label;
  };
  /** 标签：当前 / 冷却中（二选一）+ PRO。★ Pro 号同时在岗时两个都要 —— 「保底档在跑」本身就是信号。 */
  const tags = (l: Lane) => {
    const out: { s: string; bg: string; fg: string; title?: string }[] = [];
    if (l.current) out.push({ s: "当前", bg: "rgba(45,212,191,.16)", fg: t.isDark ? "#5eead4" : "#0e7a6e" });
    else if (l.cooling) out.push({ s: "冷却中", bg: "rgba(224,144,28,.14)", fg: t.isDark ? "#f5b544" : "#9a6512",
                                   title: l.cooling_until ? `冷却到 ${clockOf(l.cooling_until)}` : undefined });
    if (l.plan === "pro") out.push({ s: "PRO", bg: t.isDark ? "rgba(255,255,255,.08)" : "rgba(0,0,0,.06)", fg: p.text2,
                                     title: "Pro 是保底档：只有 Plus 全部不可用时代理才会挑它" });
    return out;
  };

  const openTip = (li: number, s: Seg0, errs: number) => {
    const mid = (X(s.start) + X(s.end)) / 2;
    const total = s.by_model.reduce((x, m) => x + m.tokens, 0) || 1;
    setTip({ x: mid, lane: li, flip: mid > 55, up: li >= 3 && li >= lanes.length / 2, range: `${clockOf(s.start)} – ${clockOf(s.end)}`, dur: mins(s.end - s.start),
             acc: s.acc, tokens: s.tokens, requests: s.requests,
             models: s.by_model.slice(0, 4).map((m, i) => ({ ...m, pct: Math.round((m.tokens / total) * 100), color: MODEL_SHADES[i % MODEL_SHADES.length] })),
             errs, why: REASON_CN[s.enter_reason] ?? s.enter_reason });
  };

  return (
    <section data-rot-timeline style={{ borderRadius: 12, background: p.panel, border: `1px solid ${p.border}`,
                                        padding: "12px 16px 14px", display: "flex", flexDirection: "column", gap: 8,
                                        // ★ 一屏规则（README §3.4 / 用户 2026-10-14）：窗口矮时卡片先让、泳道在卡内滚，页面根不滚。
                                        flex: "0 1 auto", minHeight: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, height: 22, minWidth: 0, flexShrink: 0 }}>
        <span style={{ fontSize: 14, fontWeight: 600, flexShrink: 0 }}>在岗时间线</span>
        {hidN > 0 && (
          <span data-rot-narrow style={{ display: "inline-flex", alignItems: "center", gap: 6, height: 22, padding: `0 ${zoom ? 4 : 8}px 0 8px`,
                                         borderRadius: 6, background: t.isDark ? "rgba(255,255,255,.06)" : "rgba(0,0,0,.05)",
                                         fontSize: 12, color: p.text2, flexShrink: 1, minWidth: 0, overflow: "hidden" }}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ flexShrink: 0 }}>
              <path d="M6 1.2 11 10.4H1z" stroke={WARN} strokeWidth="1.3" strokeLinejoin="round" />
              <path d="M6 4.8v2.6M6 8.7v.1" stroke={WARN} strokeWidth="1.3" strokeLinecap="round" />
            </svg>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{narrow ? `${hidN} 段太短` : `${hidN} 段太短写不下时长 · 悬停可看`}</span>
            {zoom && (
              <button type="button" onClick={() => onZoom(zoom)}
                      style={{ height: 18, padding: "0 7px", border: 0, borderRadius: 4, flexShrink: 0, cursor: "pointer", fontFamily: "inherit",
                               background: t.isDark ? "rgba(255,255,255,.10)" : "rgba(0,0,0,.08)", color: p.text, fontSize: 11.5 }}>
                {narrow ? `${zoom}h →` : `切到 ${zoom}h 看清 →`}
              </button>
            )}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span style={{ display: "flex", gap: 12, fontSize: 12, color: p.text2, flexShrink: 0 }}>
          <Lg><i style={{ width: 14, height: 8, borderRadius: 2, background: color }} />在岗</Lg>
          {!isAgy && <Lg><i style={{ width: 14, height: 8, borderRadius: 2, background: `repeating-linear-gradient(45deg, rgba(224,144,28,.55) 0 3px, rgba(224,144,28,.12) 3px 7px)` }} />冷却</Lg>}
          {!isAgy && <Lg><i style={{ width: 6, height: 6, borderRadius: 3, background: WARN }} />断流</Lg>}
          {!isAgy && <Lg><i style={{ width: 10, height: 10, borderRadius: 5, boxShadow: `inset 0 0 0 2px ${BAD}` }} />429</Lg>}
          {!narrow && <Lg><i style={{ width: 2, height: 12, background: "rgba(170,179,192,.7)" }} />换号接力线</Lg>}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: grid, columnGap: 12, alignItems: "end", height: 24, flexShrink: 0,
                    fontSize: 11.5, color: p.label, borderBottom: `1px solid ${p.line}`, paddingBottom: 4 }}>
        <span style={{ display: "inline-flex", alignItems: "center" }}>账号{acctExtra}</span>
        <div style={{ position: "relative", height: 16, fontFamily: MONO, fontSize: 11 }}>
          {axis.minor.map((x, i) => (
            <span key={`m${i}`} style={{ position: "absolute", left: `${x * 100}%`, bottom: -5, width: 1,
                                         height: axis.major.some((a) => Math.abs(a.x - x) < 1e-6) ? 5 : 3, background: p.axis }} />
          ))}
          {axis.major.map((a) => {
            const near = hs && Math.abs(a.x * 100 - hs.x) / 100 * tw < 34;
            const sh = a.x < 0.06 ? "0" : "-50%";
            return <span key={a.label} data-xtick style={{ position: "absolute", left: `${a.x * 100}%`, top: -1, transform: `translateX(${sh})`,
                                                           color: near ? "transparent" : p.label, transition: "color .12s ease-out" }}>{a.label}</span>;
          })}
          <span style={{ position: "absolute", left: "100%", top: -1, transform: "translateX(-100%)",
                         color: hs && hs.x > 88 ? "transparent" : color }}>现在</span>
          {hs && (
            <span style={{ position: "absolute", left: `${hs.x}%`, top: -2, padding: "0 4px", borderRadius: 4, background: color,
                           color: "#062b27", fontWeight: 600, transform: `translateX(${hs.x < 6 ? "0" : hs.x > 94 ? "-100%" : "-50%"})` }}>{hs.label}</span>
          )}
        </div>
        <span style={{ textAlign: "right" }}>Token</span>
        <span style={{ textAlign: "right" }}>{isAgy ? "会话" : "请求"}</span>
        <span style={{ textAlign: "right" }}>t/s</span>
        <span style={{ textAlign: "right" }}>{narrow ? "5h" : "5h 额度"}</span>
      </div>

      <div data-rot-lanes style={{ position: "relative", minHeight: 0, overflowY: "auto", overflowX: "hidden" }}
           onMouseLeave={() => { setHov(-1); setHs(null); }}>
        {lanes.length === 0 && (
          <div data-rot-empty style={{ padding: "26px 0", textAlign: "center", color: p.label, fontSize: 12 }}>{empty}</div>
        )}
        {lanes.map((l, li) => {
          const tg = tags(l);
          const dim = (hov >= 0 && hov !== li) || (focus != null && focus !== l.acc);
          const errs = (rot?.markers ?? []).filter((m) => m.acc === l.acc && m.kind === "stream_err").map((m) => m.t);
          const c429 = (rot?.markers ?? []).filter((m) => m.acc === l.acc && m.kind === "cool_429").map((m) => m.t);
          const ts = tps.get(l.acc);
          return (
            <div key={l.acc} data-rot-lane={l.acc} onMouseEnter={() => setHov(li)}
                 style={{ display: "grid", gridTemplateColumns: grid, columnGap: 12, alignItems: "center", height: LANE_H,
                          borderBottom: `1px solid ${p.hair}`, background: hov === li ? (t.isDark ? "rgba(255,255,255,.04)" : "rgba(0,0,0,.03)") : "transparent",
                          transition: "background .15s ease-out" }}>
              {/* ★ 名字是这一行的身份：不收缩、不省略；放不下先让标签（偏离 P7-5）。 */}
              <div data-lane={l.acc} onClick={() => onFocus(focus === l.acc ? null : l.acc)}
                   title={focus === l.acc ? "再点一次取消聚焦" : "点击只看这个号的轮换记录"}
                   style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, cursor: "pointer" }}>
                <span title={l.retired ? "这个名字已不在账号池里（号被移除，或是改名前的旧名）——用 `codex-rotate alias <旧名> <号>` 把它并回去" : undefined}
                      style={{ fontSize: 14, fontWeight: 600, flexShrink: 0, whiteSpace: "nowrap",
                               color: l.retired ? p.label : focus === l.acc ? color : p.text }}>{l.acc}</span>
                {tg.map((x) => (
                  <span key={x.s} title={x.title}
                        style={{ fontSize: 10.5, padding: "1px 5px", borderRadius: 4, background: x.bg, color: x.fg,
                                 minWidth: 0, flexShrink: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{x.s}</span>
                ))}
              </div>
              <div ref={li === 0 ? track : undefined} style={{ position: "relative", height: 22, opacity: dim ? 0.35 : 1, transition: "opacity .15s ease-out" }}>
                <i style={{ position: "absolute", left: 0, right: 0, top: "50%", height: 1, background: p.hair }} />
                {!isAgy && cools(l).map((c, i) => (
                  <i key={`c${i}`} title={c.title} style={{ position: "absolute", left: `${c.l}%`, width: `${c.w}%`, top: 3, bottom: 3, borderRadius: 4,
                                                           background: "repeating-linear-gradient(45deg, rgba(224,144,28,.55) 0 3px, rgba(224,144,28,.12) 3px 7px)" }} />
                ))}
                {l.segs.map((s, si) => {
                  const left = X(s.start), w = Math.max(0, X(s.end) - left);
                  const inner = fitDur(s.end - s.start, (w / 100) * tw);
                  return (
                    <div key={si} data-seg={`${l.acc}:${si}`}
                         title={`${l.acc} 在岗 ${clockOf(s.start)}–${clockOf(s.end)} · ${mins(s.end - s.start)}${agyTok ? ` · ${fmtTokL(s.tokens, lay.L)}` : ""}`}
                         onMouseEnter={() => {
                           const k = `${li}:${si}`;
                           if (hs?.key !== k) setHs({ key: k, x: left, label: clockOf(s.start) });
                           openTip(li, s, errs.filter((x) => x >= s.start && x <= s.end).length);
                         }}
                         onMouseLeave={() => { setHs(null); setTip(null); }}
                         style={{ position: "absolute", left: `${left}%`, width: `${w}%`, minWidth: 3, top: 0, bottom: 0, borderRadius: 5,
                                  background: color, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden",
                                  fontSize: 10.5, fontWeight: 600, fontFamily: MONO, color: "#062b27", cursor: "default" }}>{inner}</div>
                  );
                })}
                {!isAgy && errs.map((x, i) => (
                  <i key={`e${i}`} title={`断流 ${clockOf(x)} · ${l.acc}`} style={{ position: "absolute", left: `calc(${X(x)}% - 3px)`, top: -5, width: 6, height: 6,
                                                                               borderRadius: 3, background: WARN, boxShadow: `0 0 0 2px ${p.panel}` }} />
                ))}
                {!isAgy && c429.map((x, i) => (
                  <i key={`q${i}`} title={`429 ${clockOf(x)} · ${l.acc}`} style={{ position: "absolute", left: `calc(${X(x)}% - 6px)`, top: "calc(50% - 6px)",
                                                                               width: 12, height: 12, borderRadius: 6, background: p.panel, boxShadow: `inset 0 0 0 2px ${BAD}` }} />
                ))}
              </div>
              <span style={{ fontFamily: MONO, fontSize: 13.5, fontWeight: 600, textAlign: "right", whiteSpace: "nowrap" }}
                    title={l.top_model ? `主模型 ${l.top_model.model} · ${Math.round(l.top_model.share * 100)}%` : undefined}>
                {agyTok ? fmtTokL(l.tokens, lay.L) : "—"}
              </span>
              <span style={{ fontFamily: MONO, fontSize: 12.5, color: p.text2, textAlign: "right" }}>{l.requests}</span>
              <span data-rot-tps style={{ fontFamily: MONO, fontSize: 13, fontWeight: 600, textAlign: "right", color: ts == null ? p.label : num }}
                    title={ts == null ? "这段时间没有实测速度（账本只留近 2 天；估值行不进均速）" : "本期实测 t/s 的中位数（与「请求」页同口径）"}>
                {ts == null ? "—" : Math.round(ts)}
              </span>
              <span style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 6, fontFamily: MONO, fontSize: 12.5,
                             color: qc(l.quota_5h) }}
                    title={l.quota_5h == null ? (l.plan === "pro" ? "Pro 没有 5h 窗口" : "5h 额度读不到（不当满额画）") : undefined}>
                {!narrow && (
                  <i style={{ width: 34, height: 4, borderRadius: 2, background: t.isDark ? "rgba(255,255,255,.08)" : "rgba(0,0,0,.08)", overflow: "hidden", display: "block" }}>
                    <i style={{ display: "block", height: "100%", width: `${l.quota_5h ?? 0}%`, background: qc(l.quota_5h) }} />
                  </i>
                )}
                {l.quota_5h == null ? "—" : `${Math.round(l.quota_5h)}%`}
              </span>
            </div>
          );
        })}
        {lanes.length > 0 && (
          <div style={{ position: "absolute", top: 0, bottom: 0, left: lay.acctW + 12, right: lay.colsSum, pointerEvents: "none" }}>
            {relays.map((r, i) => (
              <i key={i} style={{ position: "absolute", left: `${r.x}%`, top: Math.min(r.a, r.b) * LANE_H + 22,
                                  height: Math.abs(r.a - r.b) * LANE_H, width: 0, borderLeft: `1.5px ${r.dash ? "dashed" : "solid"} ${r.c}` }} />
            ))}
            <i style={{ position: "absolute", right: 0, top: -6, bottom: 0, borderLeft: `1.5px solid ${color}` }} />
            {hs && <i style={{ position: "absolute", left: `${hs.x}%`, top: -6, bottom: 0, borderLeft: `1px dashed ${t.isDark ? "rgba(238,242,247,.45)" : "rgba(0,0,0,.35)"}` }} />}
          </div>
        )}
        {tip && (
          <div data-rot-tip style={{
            position: "absolute", left: `calc(${lay.acctW + 12}px + (100% - ${lay.acctW + 12 + lay.colsSum}px) * ${tip.x / 100})`,
            // 下半区的泳道把浮卡翻到上方：泳道区会在卡内滚，往下画会被裁掉。
            top: tip.up ? tip.lane * LANE_H + 4 : tip.lane * LANE_H + 40,
            transform: `${tip.flip ? "translateX(calc(-100% - 8px))" : "translateX(8px)"}${tip.up ? " translateY(-100%)" : ""}`,
            width: 190, background: p.tipBg, border: `1px solid ${p.tipBorder}`, borderRadius: 8, padding: "7px 9px",
            boxShadow: t.isDark ? "0 12px 30px rgba(0,0,0,.45)" : "0 10px 24px rgba(0,0,0,.14)",
            pointerEvents: "none", zIndex: 5, fontFamily: MONO, fontSize: 11 }}>
            <div style={{ color: p.label, marginBottom: 4 }}>{tip.range} · {tip.dur}</div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontWeight: 700 }}>{tip.acc}</span><span style={{ fontWeight: 700, color: num }}>{agyTok ? fmtTokL(tip.tokens, 0) : ""}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", color: p.text2, marginTop: 2 }}>
              <span>{isAgy ? "会话" : "请求"}</span><span>{tip.requests} {isAgy ? "场" : "次"}</span>
            </div>
            <div style={{ marginTop: 5, paddingTop: 4, borderTop: `1px solid ${p.hair}` }}>
              {/* ★ 「这段没有归属到 token」不是 0 —— 请求可能失败，或那些响应没走代理。 */}
              {tip.models.length === 0 && <div style={{ color: p.label }}>{agyTok ? "该时段无归属到的 token" : "窗口内没有可归属的生成"}</div>}
              {tip.models.map((m, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2 }}>
                  <span style={{ width: 6, height: 6, borderRadius: 2, background: m.color, flexShrink: 0 }} />
                  <span style={{ color: p.text2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.model}</span>
                  <span style={{ marginLeft: "auto", fontWeight: 700 }}>{fmtTokL(m.tokens, 1)}</span>
                  <span style={{ width: 30, textAlign: "right", color: p.label }}>{m.pct}%</span>
                </div>
              ))}
            </div>
            {!isAgy && (
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 5, paddingTop: 4, borderTop: `1px solid ${p.hair}` }}>
                <span style={{ color: p.label }}>断流</span><span style={{ color: WARN }}>{tip.errs} 次</span>
              </div>
            )}
            <div style={{ marginTop: 3, color: num }}>切入 · {tip.why}</div>
          </div>
        )}
      </div>
    </section>
  );
}

function Lg({ children }: { children: React.ReactNode }) {
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>{children}</span>;
}
