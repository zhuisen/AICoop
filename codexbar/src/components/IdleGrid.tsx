import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { emit, listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import PlatformLogo, { logoSrc, type LogoPlatform } from "./PlatformLogo";
import { IDLE_PANEL_EVENT, IDLE_PANEL_WANT, type IdlePanelData } from "../idleTray";
import * as G from "../idleGridLayout";

/**
 * 空闲额度面板（AICoop P11 §6 · 格子 · 精简；画板 `P11_Final` ④，2× 画，这里按 1× 取值）。
 * 窗口、进出判定、命中区都在 Rust `tps_hover.rs`（与在跑速度面板共用一个窗口，`mode: "idle"`）；这里只画、做动画、报高度。
 *
 * ★ 数据由常驻的菜单栏 webview 算好推过来（`useIdleTray` → `IDLE_PANEL_EVENT`），这里不取数；挂载时要一份。
 * ★ 每家一格：额度环 + 大数字（5h 剩余，grok 只有周）+ 右上角重置倒计时；菜单栏里的那几家左上角白色小圆点、
 *   底色 16% + 描边。点格子 ⇒ 关面板、打开工作台里该 AI 的总览（Kimi / DeepSeek 没有总览档 ⇒ 用量详情）。
 * ★ 打开：外壳 140 ms 淡入的同时托盘 logo 起飞（420 ms 弹簧，相邻错开 25 ms）落进环心；其余平台 120 ms 后原位淡入；
 *   文字和环 200 ms 时出现。关闭倒放。只动 transform / opacity。减弱动态效果：整块淡入淡出。
 */

type Mode = "closed" | "open" | "closing" | "clicked";
interface Fly { key: string; x: number; y: number; s: number; op: number; tr: string }

const SPRING = "cubic-bezier(.2,.9,.25,1)";
const POP = "cubic-bezier(.34,1.3,.64,1)";
const noop = (_e: unknown): void => { /* 面板失败不影响托盘本身 */ };

export default function IdleGrid({ mode, active, flyBack, layout, isDark, reduce }: {
  mode: Mode;
  /** 窗口这一轮是不是空闲面板。不是 ⇒ 不报高度（窗口高度归在跑面板管）。 */
  active: boolean;
  /** 关闭时 logo 飞回托盘吗。因为 AI 开跑而关（托盘正变成 t/s 胶囊、空闲位置已经不在了）⇒ 只淡出。 */
  flyBack: boolean;
  layout: G.IdleLayout | null;
  isDark: boolean;
  reduce: boolean;
}) {
  const [data, setData] = useState<IdlePanelData | null>(null);
  // 悬停按平台记，不按下标：格子变少时旧下标会越界
  const [hovKey, setHovKey] = useState<string | null>(null);
  const [fly, setFly] = useState<Fly[]>([]);
  const go = useRef<Fly[] | null>(null);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    const un = listen<IdlePanelData>(IDLE_PANEL_EVENT, (e) => setData(e.payload));
    void emit(IDLE_PANEL_WANT).catch(noop);
    // 飞行中被卸载 ⇒ 托盘自己的 logo 必须画回来
    return () => { void un.then((f) => f()); invoke("tray_pill_hide_logos", { hidden: false }).catch(noop); };
  }, []);

  const cells = data?.cells ?? [];
  const g = G.gridLayout(cells.length);
  const hov = hovKey === null ? -1 : cells.findIndex((c) => c.key === hovKey);

  // 高度上报：Rust 按它摆窗口（与在跑面板同一条命令）。只有这一轮是空闲面板时才报 —— 两个面板共用一个窗口高度
  useEffect(() => {
    if (active && (mode === "open" || mode === "closed")) invoke("tpshover_resize", { h: g.h }).catch(noop);
  }, [g.h, mode, active]);

  const isOpen = mode === "open" && cells.length > 0;
  const px = layout?.panel.x ?? 40, py = layout?.panel.y ?? 30;

  // logo 飞行：打开 = 托盘 → 环心；关闭 = 环心 → 托盘。托盘以外的几家只在环心淡入 / 淡出。
  useEffect(() => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
    if (!layout || reduce || !cells.length || (mode !== "open" && mode !== "closing") || (mode === "closing" && !flyBack)) {
      setFly([]);
      return;
    }
    const plans = G.planIdleFlights(layout, cells.map((c) => c.key), g, px, py);
    const atPill = (f: G.IdleFlight, tr: string, op: number): Fly => ({ key: f.key, x: f.pill.x, y: f.pill.y, s: f.pill.s, op, tr });
    const atCell = (f: G.IdleFlight, tr: string, op = 1): Fly => ({ key: f.key, x: f.cell.x, y: f.cell.y, s: G.CELL_SCALE, op, tr });
    if (mode === "open") {
      setFly(plans.map((f) => (f.fromTray ? atPill(f, "none", 1) : atCell(f, "none", 0))));
      go.current = plans.map((f) => atCell(f, f.fromTray
        ? `transform ${G.FLY_MS}ms ${SPRING} ${f.delay}ms`
        : `opacity 200ms ease-out ${G.OTHERS_IN_MS}ms`));
      // 飞行期间托盘画「无 logo 的胶囊」；落地后托盘画回 logo、格子里的 logo 接手（同在跑面板）
      if (plans.some((f) => f.fromTray)) invoke("tray_pill_hide_logos", { hidden: true }).catch(noop);
      timers.current.push(window.setTimeout(() => { invoke("tray_pill_hide_logos", { hidden: false }).catch(noop); setFly([]); },
                                            G.FLY_MS + G.FLY_STAGGER * plans.length + 40));
    } else {
      // 飞回期间托盘同样不画 logo，否则落地前托盘里已经有一份（重影）
      if (plans.some((f) => f.fromTray)) invoke("tray_pill_hide_logos", { hidden: true }).catch(noop);
      setFly(plans.map((f) => atCell(f, "none")));
      go.current = plans.map((f) => (f.fromTray
        ? atPill(f, `transform ${G.FLY_MS}ms ${SPRING} ${f.delayBack}ms`, 1)
        : atCell(f, "opacity 120ms ease-in", 0)));
      timers.current.push(window.setTimeout(() => { invoke("tray_pill_hide_logos", { hidden: false }).catch(noop); setFly([]); },
                                            G.FLY_MS + G.FLY_STAGGER * plans.length + 40));
    }
    // 格子晚于 `tpshover-open` 到（刚启动 / 面板刚挂载）⇒ 「有没有格子」变了也要起飞一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, layout, cells.length > 0]);

  // 两拍起飞：第一拍放在起点（无过渡）并强制算一次样式，第二拍给终点 + 过渡
  useLayoutEffect(() => {
    if (!go.current || !fly.length) return;
    document.body.getBoundingClientRect();
    const next = go.current;
    go.current = null;
    setFly(next);
  }, [fly]);

  const shellTr = reduce ? "opacity 150ms"
    : isOpen ? `opacity 140ms ease-out, transform 220ms ${SPRING}`
    : mode === "closing" ? "opacity 160ms ease-in 260ms, transform 160ms ease-in 260ms"
    : mode === "clicked" ? "opacity 120ms ease-out" : "none";
  const txt = (d: number) => `opacity 140ms ease-out ${isOpen && !reduce ? d : 0}ms`;
  const flying = new Set(fly.map((f) => f.key));

  const hasOverview = (key: string) => key === "codex" || key === "claude" || key === "agy" || key === "grok";
  const openCell = (key: string) => {
    const overview = hasOverview(key);
    void emit("open-main-page", { page: overview ? "overview" : "traffic", platform: key }).catch(noop);
    invoke("tpshover_dismiss").catch(noop);
  };

  return (
    <>
      <div className="ig-shell" data-idle-panel data-idle-h={g.h}
           style={{ left: px, top: py, width: G.PANEL_W, height: g.h, opacity: isOpen ? 1 : 0,
                    transform: `scale(${isOpen || reduce ? 1 : 0.97})`, pointerEvents: isOpen ? "auto" : "none",
                    transition: shellTr }}
           onMouseLeave={() => setHovKey(null)}>
        <div className="ig-hl" aria-hidden="true"
             style={{ width: g.cw, height: g.ch, opacity: hov >= 0 && isOpen ? 1 : 0,
                      transform: `translate3d(${hov >= 0 ? g.pos[hov].x : 0}px, ${hov >= 0 ? g.pos[hov].y : 0}px, 0)`,
                      transition: reduce ? "opacity 120ms" : `transform 400ms ${POP}, opacity 180ms ease-out` }} />
        {cells.map((c, k) => {
          const p = g.pos[k];
          const tone = G.tone(c.key);
          const ringC = c.main === null ? "var(--ig-ring-none)" : c.low ? G.LOW : tone.num(isDark);
          const dash = G.RING_C * (1 - (isOpen && c.main !== null ? c.main / 100 : 0));
          const cdl = isOpen && !reduce ? G.cellDelay(k) : 0;
          return (
            <div key={c.key} className="ig-cell" data-idle-cell={c.key} data-in-bar={c.inBar ? 1 : 0}
                 title={`打开 ${G.NAME[c.key] ?? c.key} ${hasOverview(c.key) ? "总览" : "用量详情"}`}
                 onClick={() => openCell(c.key)} onMouseEnter={() => setHovKey(c.key)}
                 style={{ left: p.x, top: p.y, width: g.cw, height: g.ch,
                          background: tone.tint(c.inBar ? 0.16 : 0.09),
                          boxShadow: `inset 0 0 0 1px ${tone.tint(c.inBar ? 0.42 : 0.14)}`,
                          opacity: isOpen ? 1 : 0,
                          transform: isOpen || reduce ? "none" : "translate3d(0, 5px, 0) scale(.96)",
                          transition: reduce ? "opacity 150ms" : `opacity 250ms ease-out ${cdl}ms, transform 500ms ${POP} ${cdl}ms` }}>
              {c.inBar && <i className="ig-dot" title="在菜单栏" style={{ opacity: isOpen ? 1 : 0, transition: txt(200) }} />}
              {c.reset && <span className="ig-reset" data-idle-reset style={{ opacity: isOpen ? 1 : 0, transition: txt(200) }}>{c.reset}</span>}
              <svg className="ig-ring" width={G.RING} height={G.RING} viewBox={`0 0 ${G.RING} ${G.RING}`}
                   style={{ left: (g.cw - G.RING) / 2, top: G.RING_TOP }} aria-hidden="true">
                <circle cx={G.RING / 2} cy={G.RING / 2} r={G.RING_R} fill="none" stroke="var(--ig-track)" strokeWidth={G.RING_SW} />
                <circle cx={G.RING / 2} cy={G.RING / 2} r={G.RING_R} fill="none" stroke={ringC} strokeWidth={G.RING_SW}
                        strokeLinecap="round" strokeDasharray={G.RING_C.toFixed(2)} strokeDashoffset={dash.toFixed(2)}
                        transform={`rotate(-90 ${G.RING / 2} ${G.RING / 2})`}
                        style={{ transition: reduce ? "none" : `stroke-dashoffset 450ms ${SPRING} ${isOpen ? 200 : 0}ms` }} />
              </svg>
              <span className="ig-logo" data-idle-logo={c.key}
                    style={{ left: (g.cw - G.LOGO) / 2, top: G.RING_TOP + (G.RING - G.LOGO) / 2,
                             visibility: flying.has(c.key) ? "hidden" : "visible",
                             opacity: isOpen ? 1 : 0, transition: reduce ? "opacity 150ms" : "none" }}>
                <PlatformLogo platform={c.key as LogoPlatform} isDark={isDark} size={G.LOGO} />
              </span>
              <span className="ig-main" data-idle-main={c.main === null ? "—" : Math.round(c.main)} data-idle-stale={c.stale ? 1 : 0}
                    title={c.stale ? "这次没读到，显示的是上一次读到的数" : undefined}
                    style={{ color: c.main === null ? "var(--ig-tx3)" : c.low ? G.LOW : c.stale ? "var(--ig-tx2)" : "var(--ig-tx)",
                             opacity: isOpen ? 1 : 0, transition: txt(200) }}>
                {c.main === null ? "—" : `${Math.round(c.main)}%`}
              </span>
            </div>
          );
        })}
      </div>
      {fly.map((f) => (
        <img key={f.key} className="hv-fly" data-idle-fly={f.key} alt="" draggable={false}
             src={logoSrc(f.key as LogoPlatform, isDark)} width={G.PILL_LOGO} height={G.PILL_LOGO}
             style={{ transform: `translate(${f.x}px, ${f.y}px) scale(${f.s})`, opacity: f.op, transition: f.tr }} />
      ))}
    </>
  );
}
