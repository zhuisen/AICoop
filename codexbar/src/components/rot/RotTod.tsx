import { useMemo, useState } from "react";
import type { Theme } from "../../theme";
import { type RotLayout, bestText, slotClock, todAlpha, todConclusion, todGrid } from "../../rotationView";
import { MONO, tkPal } from "../tk/tkPal";
import { WARN } from "./RotTimeline";
import type { Lane } from "./RotTimeline";
import type { Rotation } from "./rotTypes";

const ROW_H = 44;
const EASE = "cubic-bezier(.2,.9,.3,1)";

function rgba(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a.toFixed(3)})`;
}

/**
 * 账号 × 时段（7d / 14d / 30d，AICoop P7 §1.5 L1）：一行一个号，横轴是一天的 48 个半小时，把本期每一天叠起来看。
 * 十字准星：行、列各一条淡高亮跟着滑（120 ms，不回弹）；首次进入只淡入（`hbWas`）。
 */
export default function RotTod({ t, rot, lanes, lay, color, num, focus, onFocus, acctExtra, empty, isAgy }: {
  t: Theme; rot: Rotation | null; lanes: Lane[]; lay: RotLayout; color: string; num: string;
  focus: string | null; onFocus: (acc: string | null) => void; acctExtra?: React.ReactNode; empty: string;
  /** Gemini 没有代理 ⇒ 断流不可观测：不给「断流」模式，结论也不说「没有断流」（评审 codex 阶段 5）。 */
  isAgy?: boolean;
}) {
  const p = tkPal(t);
  const [mode0, setMode] = useState<"duty" | "err">("duty");
  const mode = isAgy ? "duty" : mode0;
  const [hov, setHov] = useState(-1);
  const [hb, setHb] = useState(-1);
  const [hbWas, setHbWas] = useState(false);
  const W = rot?.window;
  const nDays = W ? Math.max(1, Math.round((W.end - W.start) / 86400)) : 1;
  const rows = useMemo(() => todGrid(lanes.map((l) => l.acc), rot?.segments ?? [], rot?.markers ?? []),
                       [lanes, rot]);
  const erMax = Math.max(1, ...rows.flatMap((r) => r.errs));
  const narrow = lay.L === 2;
  const md = (ts: number) => {
    const d = new Date(ts * 1000);
    return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const tz = new Intl.DateTimeFormat("en-US", { timeZoneName: "short" }).formatToParts(new Date())
    .find((x) => x.type === "timeZoneName")?.value ?? "";
  const grid = `${lay.acctW}px minmax(0,1fr) ${lay.todCols}`;
  const k = hov, colO = k >= 0 && hb >= 0 ? 1 : 0;
  const tr = hbWas ? `transform .12s ${EASE}, opacity .1s` : "opacity .1s";
  const last = k === rows.length - 1;
  const r = k >= 0 ? rows[k] : null;
  const leave = () => { setHov(-1); setHb(-1); setHbWas(false); };
  const conc = isAgy ? "Gemini 没有代理，看不到断流 —— 这里只看在岗。" : todConclusion(rows);

  return (
    <section data-rot-tod style={{ borderRadius: 12, background: p.panel, border: `1px solid ${p.border}`,
                                   padding: "12px 16px 14px", display: "flex", flexDirection: "column", gap: 6,
                                   flex: "0 1 auto", minHeight: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, height: 24, flexShrink: 0 }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>账号 × 时段</span>
        {lay.showMeta && W && (
          <span style={{ fontSize: 12, fontFamily: MONO, color: p.label }}>{md(W.start)} → {md(W.end)} · {tz}</span>
        )}
        <span style={{ flex: 1 }} />
        <div role="group" aria-label="看什么" style={{ display: "flex", gap: 4 }}>
          {(isAgy ? (["duty"] as const) : (["duty", "err"] as const)).map((m) => {
            const on = mode === m;
            return (
              <button key={m} type="button" data-tod-mode={m} aria-pressed={on} onClick={() => setMode(m)}
                      style={{ height: 22, padding: "0 9px", borderRadius: 11, fontSize: 12, fontFamily: "inherit", cursor: "pointer",
                               border: `1px solid ${on ? rgba(m === "err" ? WARN : color, 0.5) : p.idleBorder}`,
                               background: on ? rgba(m === "err" ? WARN : color, 0.14) : "transparent",
                               color: on ? p.text : p.text2, transition: "background .15s ease-out, border-color .15s ease-out" }}>
                {m === "duty" ? (narrow ? "在岗" : "在岗频率") : "断流"}
              </button>
            );
          })}
        </div>
        <i style={{ width: 24, height: 8, borderRadius: 2, flexShrink: 0,
                    background: mode === "duty" ? `linear-gradient(90deg, ${rgba(color, 0.15)}, ${color})`
                      : `linear-gradient(90deg, ${rgba(WARN, 0.2)}, ${WARN})` }} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: grid, columnGap: 12, alignItems: "end", height: 22, flexShrink: 0,
                    fontSize: 11.5, color: p.label, borderBottom: `1px solid ${p.line}`, paddingBottom: 4 }}>
        <span style={{ display: "inline-flex", alignItems: "center" }}>账号{acctExtra}</span>
        <div style={{ position: "relative", height: 14, fontFamily: MONO, fontSize: 11 }}>
          {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
            <span key={h} style={{ position: "absolute", left: `${(h / 24) * 100}%`,
                                   transform: h === 0 ? "none" : h === 24 ? "translateX(-100%)" : "translateX(-50%)" }}>
              {String(h).padStart(2, "0")}
            </span>
          ))}
        </div>
        <span style={{ textAlign: "right" }}>在岗</span>
        <span style={{ textAlign: "right" }}>常用时段</span>
      </div>

      <div data-rot-lanes style={{ position: "relative", minHeight: 0, overflowY: "auto", overflowX: "hidden" }} onMouseLeave={leave}>
        {rows.length === 0 && (
          <div data-rot-empty style={{ padding: "26px 0", textAlign: "center", color: p.label, fontSize: 12 }}>{empty}</div>
        )}
        <i aria-hidden style={{ position: "absolute", left: 0, right: 0, top: 0, height: ROW_H, borderRadius: 6,
                                background: t.isDark ? "rgba(255,255,255,.045)" : "rgba(0,0,0,.035)",
                                transform: `translate3d(0,${Math.max(0, k) * ROW_H}px,0)`, opacity: k >= 0 ? 1 : 0,
                                transition: tr, willChange: "transform", pointerEvents: "none" }} />
        <div aria-hidden style={{ position: "absolute", inset: 0, display: "grid", gridTemplateColumns: grid, columnGap: 12,
                                  pointerEvents: "none", zIndex: 2 }}>
          <span />
          <div style={{ position: "relative" }}>
            <i style={{ position: "absolute", top: 0, bottom: 0, left: 0, width: "calc(100% / 48)", borderRadius: 2,
                        background: t.isDark ? "rgba(255,255,255,.08)" : "rgba(0,0,0,.06)",
                        transform: `translate3d(${Math.max(0, hb) * 100}%,0,0)`, opacity: colO, transition: tr }} />
            {r && hb >= 0 && (
              <span data-tod-tip style={{
                position: "absolute", top: last ? k * ROW_H - 30 : (k + 1) * ROW_H + 2,
                left: `${Math.min(86, Math.max(14, ((hb + 0.5) / 48) * 100))}%`, transform: "translateX(-50%)",
                padding: "5px 8px", borderRadius: 7, background: t.isDark ? "#eef2f7" : "#141a22",
                color: t.isDark ? "#0e1117" : "#eef2f7", fontSize: 11.5, fontWeight: 500, whiteSpace: "nowrap",
                boxShadow: "0 8px 20px rgba(0,0,0,.4)", opacity: colO,
                transition: `left .12s ${EASE}, top .12s ${EASE}, opacity .1s` }}>
                {r.acc} · {slotClock(hb)}–{slotClock(hb + 1)} · {r.days[hb]}/{nDays} 天在岗{isAgy ? "" : ` · 断流 ${r.errs[hb]}`}
              </span>
            )}
          </div>
        </div>
        {rows.map((row, i) => {
          const l = lanes[i];
          const dim = focus != null && focus !== row.acc;
          return (
            <div key={row.acc} data-rot-lane={row.acc} onMouseEnter={() => setHov(i)}
                 style={{ position: "relative", display: "grid", gridTemplateColumns: grid, columnGap: 12, alignItems: "center",
                          height: ROW_H, borderBottom: `1px solid ${p.hair}`, opacity: dim ? 0.35 : 1, transition: "opacity .15s ease-out" }}>
              <div data-lane={row.acc} onClick={() => onFocus(focus === row.acc ? null : row.acc)}
                   title={focus === row.acc ? "再点一次取消聚焦" : "点击只看这个号的轮换记录"}
                   style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, cursor: "pointer" }}>
                <span style={{ fontSize: 14, fontWeight: 600, flexShrink: 0, whiteSpace: "nowrap",
                               color: l?.retired ? p.label : focus === row.acc ? color : p.text }}>{row.acc}</span>
                {l?.plan === "pro" && (
                  <span title="Pro 是保底档：只有 Plus 全部不可用时代理才会挑它"
                        style={{ fontSize: 10.5, padding: "1px 5px", borderRadius: 4, background: t.isDark ? "rgba(255,255,255,.08)" : "rgba(0,0,0,.06)",
                                 color: p.text2, minWidth: 0, overflow: "hidden" }}>PRO</span>
                )}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(48, minmax(0,1fr))", gap: 1, height: 24 }}>
                {row.days.map((c, b) => {
                  const er = row.errs[b];
                  const a = todAlpha(mode, c, nDays, er, erMax);
                  const bg = mode === "duty" ? (c > 0 ? rgba(color, a) : (t.isDark ? "rgba(255,255,255,.03)" : "rgba(0,0,0,.035)"))
                    : er > 0 ? rgba(WARN, a) : c > 0 ? rgba(color, 0.1) : (t.isDark ? "rgba(255,255,255,.03)" : "rgba(0,0,0,.035)");
                  return <i key={b} data-tod-cell={b}
                            onMouseEnter={() => { if (hb !== b) { setHbWas(hb >= 0); setHb(b); } }}
                            style={{ borderRadius: 2, background: bg, transition: "background .15s ease-out" }} />;
                })}
              </div>
              <span style={{ fontFamily: MONO, fontSize: 13.5, fontWeight: 600, textAlign: "right" }}>
                {(row.secs / 3600).toFixed(1)}h
              </span>
              <span style={{ fontFamily: MONO, fontSize: 12.5, textAlign: "right", color: row.best == null ? p.label : num }}>
                {bestText(row.best, narrow)}
              </span>
            </div>
          );
        })}
      </div>
      <div data-tod-conclusion style={{ flexShrink: 0, fontSize: 12.5, color: p.text2, overflow: "hidden", textOverflow: "ellipsis" }}>{conc}</div>
    </section>
  );
}
