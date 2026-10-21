import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState, type MouseEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import { useLive } from "./hooks/useLive";
import { PLATFORM_NAME, PLATFORM_ORDER, fmtTokens, fmtTps, numColor, runningRows, type PlatformKey, type RunningRow } from "./live";
import PlatformLogo, { logoSrc } from "./components/PlatformLogo";
import * as L from "./tpsHoverLogic";
import IdleGrid from "./components/IdleGrid";
import { parseIdleLayout, type IdleLayout } from "./idleGridLayout";
import "./tpsHover.css";

/**
 * 托盘胶囊的悬停面板（交接包 2026-10-19 page2）。窗口、进出判定、命中区都在 Rust `tps_hover.rs`；
 * 这里只画面板、做动画、报高度。
 *
 * ★ logo 的归属：打开时从胶囊**飞进**来（覆盖层 `.hv-fly`，窗口坐标）；落地后**交给行自己画**
 *   （`data-hover-logo-cell`），于是展开 / 折叠时 logo 的位移天然与行高同曲线、同时长、同延迟
 *   —— 交接包「容易遗漏」第 1 条，原型里试出来的坑。关闭时反过来：量出行里 logo 的当前位置，
 *   换回覆盖层飞回胶囊。
 * ★ 飞行期间托盘画「无 logo 的胶囊」（`tray_pill_hide_logos`）。落地后托盘已画回 logo，
 *   所以飞回开始时这里再设一次 true，飞完再 false；Rust 在关闭动画走完、藏窗那一刻也会设回 false（兜底）。
 * ★ logo 任何状态都不变暗：停下那一行只降**数据**的透明度（交接包全局规则；HoverSpec E 画板把整行
 *   连 logo 一起降到 .4，与全局规则冲突，按全局规则 —— 偏离记录 PLAN §4）。
 */

type Mode = "closed" | "open" | "closing" | "clicked";
interface Fly { key: string; x: number; y: number; s: number; tr: string; op: number }

const SP = L.SPRING;

function loadTheme(): "dark" | "light" {
  try {
    const v = localStorage.getItem("codexbar_theme");
    if (v === "light" || v === "dark") return v;
  } catch (_e: unknown) { /* 读不到 localStorage 就按默认深色 */ }
  return "dark";
}

function prefersReduce(): boolean {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (_e: unknown) { return false; }
}

function isMulti(r: RunningRow): boolean {
  return r.nSessions > 1 && r.sessions.length > 1;
}

function noop(_e: unknown): void { /* 托盘 / 高度命令失败不影响面板本身 */ }

export default function TpsHover() {
  const { live } = useLive();
  const [theme, setTheme] = useState<"dark" | "light">(loadTheme);
  const [reduce, setReduce] = useState<boolean>(prefersReduce);
  const [mode, setMode] = useState<Mode>("closed");
  const [layout, setLayout] = useState<L.HoverLayout | null>(null);
  /** 这次打开的是空闲额度格子（P11 §6）还是在跑速度面板。由 Rust 的 `tpshover-open` payload `mode` 定。 */
  const [idleLay, setIdleLay] = useState<IdleLayout | null>(null);
  const [kind, setKind] = useState<"run" | "idle">("run");
  const [closeWhy, setCloseWhy] = useState("");
  const [flew, setFlew] = useState(false);
  const [flying, setFlying] = useState<Fly[]>([]);
  const [ex, dispatch] = useReducer(L.expandReduce, L.EXPAND0);
  const [shown, setShown] = useState<L.Shown<RunningRow>[]>([]);
  const winRef = useRef<HTMLDivElement>(null);
  const goRef = useRef<Fly[] | null>(null);
  const timers = useRef<number[]>([]);

  const rows = useMemo(() => runningRows(live), [live]);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const recon = useCallback(() => {
    setShown((prev) => L.reconcile(prev, rowsRef.current.map((r) => ({ key: r.key, row: r })), Date.now(), PLATFORM_ORDER));
  }, []);
  useEffect(recon, [rows, recon]);
  useEffect(() => {
    const at = L.nextPhaseAt(shown);
    if (at == null) return;
    const id = window.setTimeout(recon, Math.max(0, at - Date.now()) + 5);
    return () => window.clearTimeout(id);
  }, [shown, recon]);

  const blocks: L.BlockIn[] = shown.map((s) => {
    const multi = isMulti(s.row);
    return { multi, open: multi && !!ex.open[s.key], nSess: s.row.sessions.length, collapsed: s.phase === "collapsing" };
  });
  const pl = L.layoutPanel(blocks);

  // 行变成单会话 / 消失 ⇒ 它的展开态作废
  const multiKeys = shown.filter((s) => isMulti(s.row)).map((s) => s.key).join(",");
  useEffect(() => { dispatch({ t: "prune", multi: multiKeys ? multiKeys.split(",") : [] }); }, [multiKeys]);
  useEffect(() => {
    const at = L.nextDue(ex);
    if (at == null) return;
    const id = window.setTimeout(() => dispatch({ t: "tick", now: Date.now() }), Math.max(0, at - Date.now()));
    return () => window.clearTimeout(id);
  }, [ex]);

  // 主题：读 `codexbar_theme`，设置页 / 主窗改了发 `theme-changed`（同菜单栏）；每次打开再重读一次
  useEffect(() => {
    const sync = () => setTheme(loadTheme());
    window.addEventListener("storage", sync);
    const un = listen("theme-changed", sync);
    return () => { window.removeEventListener("storage", sync); un.then((f) => f()).catch(noop); };
  }, []);

  const later = (fn: () => void, ms: number) => { timers.current.push(window.setTimeout(fn, ms)); };
  const clearTimers = () => { timers.current.forEach((t) => window.clearTimeout(t)); timers.current = []; };

  // 用 ref 拿事件回调里的最新值（监听只挂一次）
  const st = useRef({ shown, blocks, layout, reduce, kind });
  st.current = { shown, blocks, layout, reduce, kind };

  const startOpen = useCallback((raw: unknown) => {
    clearTimers();
    setTheme(loadTheme());
    const red = prefersReduce();
    setReduce(red);
    dispatch({ t: "reset" });
    const il = parseIdleLayout(raw);
    setIdleLay(il);
    setKind(il ? "idle" : "run");
    setMode("open");
    if (il) { goRef.current = null; setFlying([]); setFlew(false); return; }
    const lay = L.parseLayout(raw);
    setLayout(lay);
    // 落点按「全部折叠」算（打开时展开态清零）
    const cur = st.current.shown;
    const pl0 = L.layoutPanel(cur.map((s) => ({ multi: isMulti(s.row), open: false, nSess: s.row.sessions.length, collapsed: s.phase === "collapsing" })));
    const plans = red ? [] : L.planFlights(lay, cur.map((s) => s.key), pl0.logoY, cur.some((s) => isMulti(s.row)))
      .filter((f) => cur.find((s) => s.key === f.key)?.phase !== "collapsing");
    setFlew(plans.length > 0);
    if (!plans.length) { goRef.current = null; setFlying([]); return; }
    goRef.current = plans.map((f) => ({ key: f.key, x: f.row.x, y: f.row.y, s: f.row.s, op: 1,
      tr: `transform ${L.FLY_IN_MS}ms ${SP} ${f.delayIn}ms, opacity 150ms` }));
    setFlying(plans.map((f) => ({ key: f.key, x: f.pill.x, y: f.pill.y, s: f.pill.s, op: 1, tr: "none" })));
    invoke("tray_pill_hide_logos", { hidden: true }).catch(noop);
    later(() => setFlying([]), L.settleMs(plans.length));
  }, []);

  const startClose = useCallback((reason: string) => {
    clearTimers();
    goRef.current = null;
    setCloseWhy(reason);
    if (reason === "click") {
      // 点击 = Rust 160 ms 后藏窗、走原有菜单栏弹窗（两个独立窗口，没法真的「长成」352）：这里只快速淡出
      setMode("clicked");
      setFlying((f) => f.map((x) => ({ ...x, op: 0, tr: "opacity 120ms ease-out" })));
      return;
    }
    setMode("closing");
    if (st.current.kind === "idle") { setFlying([]); return; }
    const { layout: lay, reduce: red, shown: cur, blocks: bl } = st.current;
    const win = winRef.current;
    if (!lay || red || !win) { setFlying([]); return; }
    const alive = cur.filter((s) => s.phase !== "collapsing");
    const plans = L.planFlights(lay, alive.map((s) => s.key), L.layoutPanel(bl).logoY);
    const wr = win.getBoundingClientRect();
    const start: Fly[] = [];
    const go: Fly[] = [];
    for (const f of plans) {
      // 起点 = logo 此刻真实所在（行里，或还在飞的覆盖层）—— 不按版面推算，展开动画半路关也不跳
      const el = win.querySelector(`[data-hover-fly="${f.key}"]`) ?? win.querySelector(`[data-hover-logo-cell="${f.key}"]`);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      start.push({ key: f.key, x: r.left - wr.left, y: r.top - wr.top, s: r.width / L.PILL_LOGO, op: 1, tr: "none" });
      go.push({ key: f.key, x: f.pill.x, y: f.pill.y, s: 1, op: 1, tr: `transform ${L.FLY_BACK_MS}ms ${SP} ${f.delayBack}ms, opacity 150ms` });
    }
    if (!start.length) { setFlying([]); return; }
    goRef.current = go;
    setFlying(start);
    invoke("tray_pill_hide_logos", { hidden: true }).catch(noop);
    later(() => { invoke("tray_pill_hide_logos", { hidden: false }).catch(noop); setFlying([]); }, L.restoreLogosAt(start.length));
  }, []);

  // 两拍起飞：第一拍放在起点（无过渡）并强制算一次样式，第二拍给终点 + 过渡
  useLayoutEffect(() => {
    if (!goRef.current || !flying.length) return;
    winRef.current?.getBoundingClientRect();
    const go = goRef.current;
    goRef.current = null;
    setFlying(go);
  }, [flying]);

  useEffect(() => {
    const a = listen("tpshover-open", (e) => startOpen(e.payload));
    const b = listen<string>("tpshover-close", (e) => startClose(String(e.payload)));
    return () => { [a, b].forEach((u) => { u.then((f) => f()).catch(noop); }); clearTimers(); };
  }, [startOpen, startClose]);

  // 高度上报：长高立刻报（窗口要先够高），变矮等收起动画走完再报（先缩会把动画裁掉）
  const lastH = useRef<number | null>(null);
  const resizeT = useRef<number | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  useEffect(() => {
    // 空闲额度格子自己报高度（`IdleGrid`）
    if (kind === "idle") { lastH.current = null; return; }
    const h = pl.height;
    if (lastH.current === h) return;
    if (resizeT.current != null) window.clearTimeout(resizeT.current);
    const send = () => {
      lastH.current = h;
      resizeT.current = null;
      invoke("tpshover_resize", { h })
        // Rust 按新高度重摆了窗口 ⇒ 此刻的版面才与窗口一致；只在开着时取（关着时窗口没动）
        .then(() => modeRef.current === "open" ? invoke("tpshover_layout") : undefined)
        .then((v) => { const lay = v === undefined ? null : L.parseLayout(v); if (lay) setLayout(lay); })
        .catch(noop);
    };
    const d = L.resizeDelay(lastH.current, h, reduce);
    if (d === 0) send(); else resizeT.current = window.setTimeout(send, d);
  }, [pl.height, reduce, kind]);

  const isDark = theme === "dark";
  const isOpen = mode === "open" && kind === "run";
  // 没有一行能展开 ⇒ 箭头列整列让出来（`.hv-nochev`），logo 落点跟着变（`LOGO_X_NOCHEV`）
  const chev = shown.some((s) => isMulti(s.row));
  const shellTr = reduce ? "opacity 150ms"
    : mode === "open" ? `opacity 160ms ease-out, transform 240ms ${SP}`
    : mode === "closing" ? "opacity 160ms ease-in 120ms, transform 160ms ease-in 120ms"
    : mode === "clicked" ? "opacity 120ms ease-out" : "none";
  const stagger = isOpen && flew && !reduce;
  const headT = `opacity ${isOpen ? 220 : 100}ms ease-out ${stagger ? 480 : 0}ms`;
  const footT = `opacity ${isOpen ? 220 : 100}ms ease-out ${stagger ? 520 : 0}ms`;
  const rowTr = reduce ? "0ms" : `340ms ${SP}`;
  const px = layout ? layout.panel.x : 40;
  const py = layout ? layout.panel.y : 30;

  const openLink = (e: MouseEvent) => {
    e.preventDefault();
    emit("open-main-page", { page: "requests", platform: null }).catch(noop);
  };

  return (
    <div ref={winRef} className={chev ? "hv-win" : "hv-win hv-nochev"} data-theme={theme} data-hover-mode={mode}>
      <div className="hv-shell" data-hover-panel data-hover-h={pl.height}
           style={{ left: px, top: py, opacity: isOpen ? 1 : 0, transform: `scale(${isOpen || reduce ? 1 : 0.98})`,
                    pointerEvents: isOpen ? "auto" : "none", transition: shellTr }}>
        <div className="hv-grid hv-head" data-hover-head style={{ opacity: isOpen ? 1 : 0, transition: headT }}>
          <span /><span /><span>AI</span><span className="hv-c">速度</span><span className="hv-r">Token</span>
        </div>
        {shown.map((s, i) => {
          const k = s.key as PlatformKey;
          const r = s.row;
          const multi = isMulti(r);
          const open = multi && !!ex.open[k];
          const held = s.phase !== "live";
          const delay = stagger ? L.dataDelay(i) : 0;
          const dt = isOpen ? `240ms ease-out ${delay}ms` : "100ms ease-out";
          const dOp = (isOpen ? 1 : 0) * (held ? 0.4 : 1);
          const hT = reduce ? "0ms" : open ? `340ms ${SP}` : `300ms ${SP} 100ms`;
          const target = layout ? L.rowLogoPoint(layout, pl.logoY[i], chev) : null;
          const hidden = flying.some((f) => f.key === k);
          const tps = fmtTps(r.tps);
          return (
            <div key={k} className="hv-fold" data-hover-block={k} data-hover-phase={s.phase}
                 style={{ gridTemplateRows: s.phase === "collapsing" ? "0fr" : "1fr",
                          transition: reduce ? "none" : `grid-template-rows 300ms ${SP} 100ms` }}>
              <div className="hv-clip">
                {i > 0 && <div className="hv-div" />}
                <div data-hover-row={k} data-hover-open={open ? "1" : "0"}
                     onMouseEnter={() => dispatch({ t: "enter", key: k, multi, now: Date.now() })}
                     onMouseLeave={() => dispatch({ t: "leave", key: k, now: Date.now() })}>
                  <div className="hv-grid hv-row" aria-expanded={multi ? open : undefined}
                       style={{ height: open ? L.ROW_H_OPEN : L.ROW_H, cursor: multi ? "pointer" : "default",
                                background: ex.hov === k ? "var(--hv-hov)" : "transparent",
                                transition: `height ${hT}, background 120ms` }}>
                    <span className="hv-chev" style={{ opacity: multi ? dOp : 0, transform: `rotate(${open ? 90 : 0}deg)`,
                                                       transition: `transform ${rowTr}, opacity ${dt}` }}>
                      {multi && (
                        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                          <path d="M3.5 2l3 3-3 3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </span>
                    <span className="hv-logo" data-hover-logo-cell={k}
                          data-logo-target={target ? `${target.x},${target.y}` : undefined}
                          style={{ visibility: hidden ? "hidden" : "visible" }}>
                      <PlatformLogo platform={k} isDark={isDark} size={L.LOGO} />
                    </span>
                    <span className="hv-name" style={{ opacity: dOp, transform: `translateX(${isOpen ? 0 : -4}px)`,
                                                       transition: `opacity ${dt}, transform ${dt}` }}>
                      <span className="hv-name-t">{PLATFORM_NAME[k]}</span>
                      {multi && <span className="hv-chip" data-hover-n>×{r.nSessions}</span>}
                    </span>
                    <span className="hv-num hv-tps" data-hover-tps={tps}
                          style={{ color: r.tps == null ? "var(--hv-tx3)" : numColor(k, theme), opacity: dOp, transition: `opacity ${dt}` }}>
                      {tps}<span className="hv-unit"> t/s</span>
                    </span>
                    <span className="hv-num hv-tok" data-hover-tok style={{ opacity: dOp, transition: `opacity ${dt}` }}>
                      {fmtTokens(r.tokens)}
                    </span>
                  </div>
                  {multi && (
                    <div className="hv-fold" data-hover-sessions={k}
                         style={{ gridTemplateRows: open ? "1fr" : "0fr", transition: `grid-template-rows ${hT}` }}>
                      <div className="hv-clip">
                        <div style={{ paddingBottom: L.SESS_PAD }}>
                          {r.sessions.map((ss, j) => {
                            const sdt = reduce ? "0ms" : open ? `260ms ease-out ${90 + j * 45}ms` : "120ms ease-in";
                            return (
                              <div key={ss.id} className="hv-grid hv-sess" data-hover-sess
                                   style={{ opacity: (open ? 1 : 0) * (held ? 0.4 : 1), transform: `translateY(${open ? 0 : -6}px)`,
                                            transition: `opacity ${sdt}, transform ${sdt}` }}>
                                <span />
                                <span className="hv-sess-line" />
                                <span className="hv-sess-t">{ss.title || ss.id.slice(0, 8)}</span>
                                <span className="hv-num hv-sess-tps">{fmtTps(ss.tps)}<span className="hv-sess-unit"> t/s</span></span>
                                <span className="hv-num hv-sess-tok">{fmtTokens(ss.tokens)}</span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        <div className="hv-foot" data-hover-foot style={{ opacity: isOpen ? 1 : 0, transition: footT }}>
          <span>今日 <b>{live ? fmtTokens(live.today.tokens) : "—"}</b> · 均 <b>{L.fmtAvg(live?.today.avg_tps)}</b> t/s</span>
          <a href="#" className="hv-link" data-hover-link onClick={openLink}>请求页 →</a>
        </div>
      </div>
      <IdleGrid mode={kind === "idle" ? mode : "closed"} active={kind === "idle"} flyBack={closeWhy !== "idle"} layout={idleLay} isDark={isDark} reduce={reduce} />
      {flying.map((f) => (
        <img key={f.key} className="hv-fly" data-hover-fly={f.key} alt="" draggable={false}
             src={logoSrc(f.key as PlatformKey, isDark)} width={L.PILL_LOGO} height={L.PILL_LOGO}
             style={{ transform: `translate(${f.x}px, ${f.y}px) scale(${f.s})`, opacity: f.op, transition: f.tr }} />
      ))}
    </div>
  );
}
