import { useEffect, useRef, useState } from "react";
import { useWidth } from "../../pages/TrafficPage";
import type { Theme } from "../../theme";
import { tkPal, MONO } from "../tk/tkPal";
import { money, type RelayEntry, type RelayRow } from "../../relay";
import { type Group, hoverDelay, hoverY, runDays } from "../../relayView";

/** 入口（P8-1.2 + 偏离 P8-3）。★ `\codex` 也走代理（PATH wrapper 统一注入 `--profile rotateproxy`），
 *  稿把它画成单号直连，与实测冲突；VS Code 自带二进制、不走 PATH ⇒ 加一行「不经过代理」。 */
export interface EntryInfo {
  cmd: string; tag: string; direct: boolean;
  rows: { k: string; v: string; c?: "acc" | "warn" | "muted" }[];
}

const EASE = "cubic-bezier(.2,.9,.3,1)";
const YS = [40, 78, 116, 154, 192];

export default function RouteMap({ t, entries, exitId, poolSub, groups, relays, usage, proxyText, proxyTone,
                                   flowText, onPool, onRelay, routeNote }: {
  t: Theme; entries: EntryInfo[];
  /** 当前出口：`null` = 账号池；否则中转站 id。 */
  exitId: string | null;
  poolSub: string; groups: Group[]; relays: RelayRow[]; usage: RelayEntry[];
  proxyText: string; proxyTone: "ok" | "bad" | "unknown"; flowText: string;
  onPool: () => void; onRelay: (id: string) => void; routeNote?: React.ReactNode;
}) {
  const p = tkPal(t);
  const dark = t.isDark;
  const nodeBg = dark ? "#0e1319" : "#f6f8fb";
  const line = dark ? "rgba(255,255,255,.12)" : "rgba(0,0,0,.12)";
  const acc = dark ? "#5eead4" : "#0e7a6e";
  const amb = dark ? "#fbbf24" : "#9a6512";
  const muted = dark ? "#6b7480" : "#6b7480";
  // ★ 量自己（内容宽，不含边框）：拿页面宽减常数会差几个像素，svg 就比卡宽、横向溢出（探针实测 1090/1084）。
  const [box, bw] = useWidth<HTMLElement>();
  const rW = Math.max(600, bw || 600);
  const exL = rW - 16 - 252;
  const pxL = Math.round((230 + exL) / 2 - 95), pxR = pxL + 190;
  // 出口节点：账号池在上，每个中转站平台一个节点往下排（P8-8 缺陷 8：多平台时高度按节点算）。
  const nodes: { g: Group; top: number; h: number }[] = [];
  let y = 98;
  for (const g of groups) { const h = 30 + g.ids.length * 38 + 6; nodes.push({ g, top: y, h }); y += h + 12; }
  const H = Math.max(236, y + 4);
  const exitNode = exitId ? nodes.find((n) => n.g.ids.includes(exitId)) : null;
  const ey = exitNode ? exitNode.top + exitNode.h / 2 : 47;
  const near = exL - pxR < 130;
  const fx = near ? pxL + 40 : Math.round((pxR + exL) / 2 - 42);
  const fy = near ? 130 : exitId ? Math.min(H - 20, ey - 17) : 28;

  // 入口悬停卡：首次 180 ms 才出，已开着时直接滑过去；离开 80 ms 后收（P8-2.3）。
  const [hc, setHc] = useState(-1);
  const [was, setWas] = useState(-1);
  const tm = useRef(0);
  useEffect(() => () => { window.clearTimeout(tm.current); }, []);
  const hv = (i: number) => {
    window.clearTimeout(tm.current);
    if (hc >= 0) { setWas(hc); setHc(i); return; }
    tm.current = window.setTimeout(() => { setWas(-1); setHc(i); }, hoverDelay(false, false));
  };
  const out = () => {
    window.clearTimeout(tm.current);
    tm.current = window.setTimeout(() => { setHc(-1); setWas(-1); }, hoverDelay(true, true));
  };
  const card = hc >= 0 ? entries[hc] : null;
  const hcY = hc >= 0 ? hoverY(YS[hc], H) : 0;
  // ★ 稿的 easing `cubic-bezier(.3,1.15,.5,1)` 会过冲（轻微回弹），与「不回弹」冲突 ⇒ 换临界阻尼（偏离 P8-4）。
  const hcT = was >= 0 ? `transform .3s ${EASE}, opacity .15s` : `opacity .16s ease-out, transform .22s ${EASE}`;

  const entryRow = (e: EntryInfo, i: number) => (
    <div key={e.cmd} data-route-entry={e.cmd} onMouseEnter={() => hv(i)} onMouseLeave={out}
         title={e.rows.map((r) => `${r.k} ${r.v}`).join(" · ")}
         style={{ position: "absolute", left: 16, top: YS[i], width: 214, height: 30, boxSizing: "border-box",
                  display: "flex", alignItems: "center", gap: 8, padding: "0 10px", borderRadius: 8, background: nodeBg,
                  border: `1px ${e.direct ? "dashed" : "solid"} ${e.direct ? (dark ? "rgba(251,191,36,.35)" : "rgba(154,101,18,.4)") : line}`,
                  cursor: "default" }}>
      <span style={{ fontFamily: MONO, fontSize: 12.5, color: e.direct ? amb : p.text, overflow: "hidden", textOverflow: "ellipsis" }}>{e.cmd}</span>
      <span style={{ flex: 1 }} />
      <span style={{ fontSize: 11.5, color: e.direct ? amb : p.label, flexShrink: 0 }}>{e.tag}</span>
    </div>
  );

  const radio = (on: boolean) => (
    <i style={{ width: 10, height: 10, borderRadius: 5, flexShrink: 0,
                boxShadow: `inset 0 0 0 ${on ? 3.5 : 1.5}px ${on ? p.accent : dark ? "rgba(255,255,255,.35)" : "rgba(0,0,0,.35)"}` }} />
  );

  return (
    <section ref={box} data-route-map style={{ position: "relative", height: H, borderRadius: 12, background: p.panel,
                                     border: `1px solid ${p.border}`, flexShrink: 0, overflow: "hidden" }}>
      <span style={{ position: "absolute", left: 16, top: 12, fontSize: 13.5, fontWeight: 600 }}>请求怎么走</span>
      {routeNote && <div style={{ position: "absolute", left: 120, top: 10, right: 16 + 252 + 16, overflow: "hidden" }}>{routeNote}</div>}
      <svg aria-hidden width={rW} height={H} viewBox={`0 0 ${rW} ${H}`} style={{ position: "absolute", left: 0, top: 0 }}>
        {entries.map((e, i) => {
          const yy = YS[i] + 15;
          return e.direct
            ? <path key={e.cmd} d={`M230 ${yy} L262 ${yy}`} fill="none" stroke={dark ? "rgba(251,191,36,.45)" : "rgba(154,101,18,.5)"} strokeWidth="1.5" strokeDasharray="4 4" />
            : <path key={e.cmd} d={`M230 ${yy} C${(230 + pxL) / 2} ${yy} ${(230 + pxL) / 2} 94 ${pxL} 94`} fill="none"
                    stroke={dark ? "rgba(255,255,255,.28)" : "rgba(0,0,0,.25)"} strokeWidth="1.5" />;
        })}
        {[{ id: null as string | null, ty: 47 }, ...nodes.map((n) => ({ id: n.g.ids[0], ty: n.top + n.h / 2, g: n.g }))].map((x, i) => {
          const on = x.id === null ? exitId === null : !!(exitNode && "g" in x && x.g === exitNode.g);
          const mx = (pxR + exL) / 2;
          return <path key={i} data-flow={on ? "on" : "off"} d={`M${pxR} 94 C${mx} 94 ${mx} ${x.ty} ${exL} ${x.ty}`} fill="none"
                       className={on ? "rl-flow" : undefined}
                       stroke={on ? p.accent : dark ? "rgba(255,255,255,.22)" : "rgba(0,0,0,.2)"} strokeWidth={on ? 2.5 : 1.5}
                       strokeDasharray={on ? "8 4" : "4 5"} style={{ transition: "stroke .25s" }} />;
        })}
      </svg>
      {entries.map(entryRow)}
      <span style={{ position: "absolute", left: 268, top: 170, fontSize: 11.5, color: muted }}>
        {rW >= 1080 ? "直连：用 auth.json 里的号，不经过出口选择" : "直连 · 不经过出口"}
      </span>
      {/* 入口悬停卡。★ 内容在 DOM 里由可见性控制（不是条件渲染），收起时只换透明度。 */}
      <div data-route-hover={card ? card.cmd : ""} style={{
        position: "absolute", left: 238, top: 0, width: 224, zIndex: 30, padding: "10px 12px", boxSizing: "border-box",
        borderRadius: 10, background: dark ? "#1c2128" : "#ffffff", border: `1px solid ${p.tipBorder}`,
        boxShadow: dark ? "0 14px 34px rgba(0,0,0,.5)" : "0 12px 28px rgba(0,0,0,.14)",
        display: "flex", flexDirection: "column", gap: 6, transformOrigin: "0 50%",
        transform: `translate3d(0,${hcY}px,0) scale(${hc >= 0 ? 1 : 0.96})`, opacity: hc >= 0 ? 1 : 0,
        transition: hcT, pointerEvents: "none" }}>
        {card && <b style={{ fontFamily: MONO, fontSize: 12.5 }}>{card.cmd}</b>}
        {card?.rows.map((r) => (
          <span key={r.k} style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 12 }}>
            <span style={{ color: p.label, flexShrink: 0 }}>{r.k}</span>
            <span style={{ color: r.c === "acc" ? acc : r.c === "warn" ? amb : r.c === "muted" ? p.label : p.text,
                           overflow: "hidden", textOverflow: "ellipsis" }}>{r.v}</span>
          </span>
        ))}
      </div>
      <div data-route-proxy style={{ position: "absolute", left: pxL, top: 66, width: 190, height: 56, boxSizing: "border-box", borderRadius: 10,
                                     background: nodeBg, border: `1px solid ${dark ? "rgba(255,255,255,.18)" : "rgba(0,0,0,.16)"}`,
                                     display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 2 }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>本地代理</span>
        <span style={{ fontFamily: MONO, fontSize: 11, color: proxyTone === "bad" ? p.down : proxyTone === "unknown" ? amb : p.label }}>{proxyText}</span>
      </div>
      <span data-route-flow style={{ position: "absolute", left: fx, top: fy, fontFamily: MONO, fontSize: 11, color: acc,
                                     background: p.panel, padding: "0 4px" }}>{flowText}</span>

      {/* 账号池节点 */}
      <div data-outlet="pool" data-outlet-active={exitId === null ? "1" : undefined} role="button"
           onClick={exitId === null ? undefined : onPool}
           style={{ position: "absolute", left: exL, top: 16, width: 252, height: 62, boxSizing: "border-box", padding: "9px 12px",
                    borderRadius: 10, cursor: exitId === null ? "default" : "pointer", display: "flex", flexDirection: "column", gap: 4,
                    background: exitId === null ? "rgba(45,212,191,.08)" : nodeBg,
                    border: `1px solid ${exitId === null ? "rgba(45,212,191,.55)" : line}`,
                    transition: "background-color .2s, border-color .2s" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>账号池</span>
          <span style={{ fontSize: 11, padding: "1px 6px", borderRadius: 5, background: "rgba(45,212,191,.12)", color: acc }}>订阅</span>
          <span style={{ flex: 1 }} />
          <span data-act="outlet-pool" style={{ fontSize: 11.5, color: exitId === null ? acc : p.label }}>{exitId === null ? "● 出口" : "切换到这里"}</span>
        </span>
        <span style={{ fontFamily: MONO, fontSize: 11.5, color: p.text2, overflow: "hidden", textOverflow: "ellipsis" }}>{poolSub}</span>
      </div>

      {/* 中转站平台节点（每组一个，账户行可点） */}
      {nodes.map(({ g, top, h }) => {
        const on = !!exitId && g.ids.includes(exitId);
        const ents = g.ids.map((id) => usage.find((u) => u.id === id));
        const sum = ents.every((e) => e?.data?.balance != null) && new Set(ents.map((e) => e?.data?.unit ?? "")).size === 1
          ? money(ents.reduce((s, e) => s + (e?.data?.balance ?? 0), 0), ents[0]?.data?.unit) : "—";
        return (
          <div key={g.key} data-outlet="relay" data-outlet-active={on ? "1" : undefined} data-relay-node={g.name}
               style={{ position: "absolute", left: exL, top, width: 252, height: h, boxSizing: "border-box", padding: "9px 10px 8px 12px",
                        borderRadius: 10, display: "flex", flexDirection: "column", gap: 2,
                        background: on ? "rgba(45,212,191,.05)" : nodeBg, border: `1px solid ${on ? "rgba(45,212,191,.4)" : line}`,
                        transition: "background-color .2s, border-color .2s" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 8, height: 20 }}>
              <span style={{ fontSize: 14, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>{g.name}</span>
              <span style={{ fontSize: 11, padding: "1px 6px", borderRadius: 5, background: "rgba(251,191,36,.12)", color: amb, flexShrink: 0 }}>按量</span>
              <span style={{ flex: 1 }} />
              {g.ids.length > 1 && <span style={{ fontFamily: MONO, fontSize: 11, color: p.label, flexShrink: 0 }}>合计 {sum}</span>}
            </span>
            {g.ids.map((id) => {
              const r = relays.find((x) => x.id === id);
              const e = usage.find((u) => u.id === id);
              const d = e?.data;
              const me = exitId === id;
              const days = runDays(d?.balance, d?.runway?.days);
              const off = r ? !r.enabled : true;
              return (
                <div key={id} data-relay-acc={id} data-act={me ? undefined : `outlet-relay:${id}`} role="button"
                     onClick={me || off ? undefined : () => onRelay(id)}
                     title={off ? `${r?.label ?? id} 已停用 —— 先在下面的账户表里启用` : undefined}
                     style={{ display: "flex", alignItems: "center", gap: 7, height: 36, padding: "0 8px", borderRadius: 7, boxSizing: "border-box",
                              cursor: me || off ? "default" : "pointer", opacity: off ? 0.45 : 1,
                              background: me ? "rgba(45,212,191,.1)" : "transparent",
                              border: `1px solid ${me ? "rgba(45,212,191,.45)" : dark ? "rgba(255,255,255,.06)" : "rgba(0,0,0,.06)"}` }}>
                  {radio(me)}
                  <span style={{ fontSize: 12.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>{r?.label ?? id}</span>
                  <span style={{ fontFamily: MONO, fontSize: 12, flexShrink: 0,
                                 color: d?.balance === 0 ? p.down : d?.balance == null ? muted : p.text }}>
                    {money(d?.balance ?? null, d?.unit)}
                    {/* ★ 同一个事实在同一屏的两处说同一句话（§5c）：明细账户表有旧读数 `*`，这里也要有。 */}
                    {e?.stale && (
                      <span data-relay-balance-stale title={`这次没取到，显示的是上一次的读数${e.detail ? ` —— ${e.detail}` : ""}`}
                            style={{ color: amb, marginLeft: 2, cursor: "help" }}>*</span>
                    )}
                  </span>
                  {days != null && <span style={{ fontFamily: MONO, fontSize: 11, color: muted, flexShrink: 0 }}>{days} 天</span>}
                  <span style={{ flex: 1 }} />
                  <span style={{ fontSize: 11, color: me ? acc : p.label, flexShrink: 0 }}>{off ? "已停用" : me ? "● 出口" : "切到这里"}</span>
                </div>
              );
            })}
          </div>
        );
      })}
    </section>
  );
}
