import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState, type MouseEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import { useNotchData } from "./hooks/useNotchData";
import { useAgyPool } from "./hooks/useAgyPool";
import { usePlatformPrefs } from "./hooks/usePlatformPrefs";
import { usePrivacy } from "./hooks/usePrivacy";
import { useLive } from "./hooks/useLive";
import { useCacheMode } from "./hooks/useCacheMode";
import { agyShown, agyWinRows } from "./agy";
import { fmtEta, maskId, slotToAccount, inUseAid } from "./helpers";
import { agySegs, codexSegs, type NotchSeg } from "./notchSegs";
import { platformColor } from "./theme";
import { bridgeBackground, glowBackground, glowKeys, NO_ACTIVITY, type NotchActivity } from "./notchGlow";
import { PLATFORM_NAME, fmtTokens, fmtTps, numColor, runningRows, type RunningRow } from "./live";
import * as HL from "./tpsHoverLogic";
import * as C from "./notchCard";
import PlatformLogo, { logoSrc } from "./components/PlatformLogo";
import { compactUSD } from "./components/MenuBarToday";
import { parseClaudeQuota, isStale, type ClaudeQuota, type ClaudeWin } from "./mbLogic";
import { grokLastGoodRemPct, grokQuotaVisible, grokRemPct, type GrokSnapshot } from "./grok";
import { applyCacheMode, applyPlatformPrefs, colorOf, fmtTok, todayView, type TrafficData } from "./traffic";
import { fmtUSD } from "./rates";
import { dayKeys, dayMetrics, filterPlatform, parsePayload, rowsForDay, PLATFORM_ORDER as REQ_ORDER } from "./requests";
import { IDLE_PANEL_EVENT, IDLE_PANEL_WANT, type IdlePanelData } from "./idleTray";
import * as NI from "./notchIdle";
import NotchIdleGrid from "./components/NotchIdleGrid";
import "./notch.css";

/** 卡片开着时倒计时文字的刷新间隔。收起时卡片看不见，不需要它。 */
const OPEN_TICK_MS = 30_000;
/** 「下一个时间点」闹钟的上限：睡眠唤醒后计时器会晚到，最多晚这么久自己纠正。 */
const MAX_WAKE_MS = 60 * 60 * 1000;
/** 展开时补读的节流：Claude 额度转写、今日快照、各家今日均速。展开得再勤也最多这么久读一次。 */
const REFETCH_MS = 60_000;

const SP = C.SPRING;

/**
 * 刘海卡片（交接包 2026-10-19 page4 · 4e「④ 悬浮卡片 + 光桥」；基础沿用 page 99 定稿）。
 * 窗口、层级、悬停与收起判定全在 `notch.rs`（光标跟踪 60 Hz、命中区、收起动画预算 560 ms），这里只画、只报高度。
 * 版面 / 告警 / 飞行 / 果冻下垂的判据在 `notchCard.ts`，光晕颜色在 `notchGlow.ts`（都是零 import 纯函数，有行为闸）。
 *
 * ★ 取数**不轮询**：Codex 状态与本机 agy 快照走 `useNotchData`（只听推送）；`useAgyPool(false)` 只读池文件、
 *   收别的 webview 广播的现读结果（保鲜由菜单栏 webview 负责）；谁在跑 / t/s 走 `useLive`（与托盘、悬停面板同源）；
 *   grok 只读 sidecar + 收 `grok-quota-updated`；Claude 额度、今日快照、各家今日均速只在**展开时**补读，且 60 s 节流。
 * ★ 卡片本身不响应点击（功能 3「点击长成弹窗」已取消）；只有「请求页 →」「用量页 →」「总览 →」三个链接。
 */

type Fly = { key: C.NotchKey; x: number; y: number; s: number; op: number; sh: number; tr: string };

function prefersReduce(): boolean {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (_e: unknown) { return false; }
}

function noop(_e: unknown): void { /* 高度上报 / 导航失败不影响卡片本身 */ }

function isMulti(r: RunningRow): boolean {
  return r.nSessions > 1 && r.sessions.length > 1;
}

const pctTxt = (d: number): string => `${d >= 0 ? "↑" : "↓"}${Math.abs(d).toFixed(1)}%`;
const upCol = "#3ecf8e", downCol = "#ff7a6b";

/** codex / agy 那几段（`notchSegs.ts`，有行为闸）→ 一行的 5h / 周两格。读不到写 —，不编数。 */
function winsFromSegs(segs: NotchSeg[], prefix: string): { w5: C.QWin; ww: C.QWin } {
  const one = segs.length === 1 && segs[0].pct == null && !segs[0].key.startsWith(`${prefix}-5h`) && !segs[0].key.startsWith(`${prefix}-周`);
  if (one) {
    // 失效 / 待刷新 / 读不到 / 当前号未知：两格都写 —，原因放悬浮说明
    const w: C.QWin = { pct: null, refill: segs[0].reset, title: segs[0].title ?? segs[0].reset };
    return { w5: w, ww: w };
  }
  const pick = (lab: string): C.QWin => {
    const s = segs.find((x) => x.key === `${prefix}-${lab}`);
    return s ? { pct: s.pct, refill: s.reset, stale: !!s.stale, title: s.title } : { pct: null, refill: "—" };
  };
  return { w5: pick("5h"), ww: pick("周") };
}

function claudeWin(w: ClaudeWin | null, stale: boolean): C.QWin {
  return w ? { pct: w.rem, refill: w.idle ? "未启动" : w.resetsAt ? fmtEta(w.resetsAt) : "—", stale }
           : { pct: null, refill: "—", title: "这一格读不到 —— 跑一次 Claude Code 后会补上" };
}

export default function NotchHud() {
  const { state, agy: agySnap } = useNotchData();
  // ★ agy 走池（四方评审 2026-10-17）：`useAgyPool(false)` 只读池文件、只收 `agy-pool-updated` /
  //   `agy-live-changed` 两个推送，不起子进程、不轮询。本机 RPC 那份（`agySnap`）只在 `snapshotOf`
  //   能证明归属时才用 —— 自 agy 1.2 起它恒 `csrf_required`，单用它就是画几周前的 `last_good`。
  const agyPool = useAgyPool(false);
  const { prefs } = usePlatformPrefs();
  const { privacy } = usePrivacy();
  const { live } = useLive();
  const { mode: cacheMode } = useCacheMode();
  const [open, setOpen] = useState(false);
  /** 这一轮展开是哪一种（Rust `notch-mode`，展开前一刻推）：空闲额度格子 / 4e 卡片。收起后保留上一轮的，直到下次展开。 */
  const [mode, setMode] = useState<"idle" | "run">("run");
  /** 空闲时光标在刘海「靠近」区里（Rust `notch-near`，左右各 60、向下 32）。 */
  const [near, setNear] = useState(false);
  const [idleData, setIdleData] = useState<IdlePanelData | null>(null);
  /** 只为让「随时间变」的部分重算：窗口过重置点、冷却结束、倒计时文字。 */
  const [tick, setTick] = useState(0);
  const [nw, setNw] = useState(179);
  const [nh, setNh] = useState(32);
  const [reduce, setReduce] = useState<boolean>(prefersReduce);
  const [chosen, setChosen] = useState<C.View>("run");
  const [settled, setSettled] = useState(false);
  const [ex, dispatch] = useReducer(HL.expandReduce, HL.EXPAND0);
  const [fly, setFly] = useState<Fly[]>([]);
  const goRef = useRef<Fly[] | null>(null);
  const timers = useRef<number[]>([]);
  const cardRef = useRef<HTMLDivElement>(null);
  const [cursor, setCursor] = useState<{ dx: number; distance: number } | null>(null);
  const isOff = useCallback((k: string) => !!prefs.by?.[k]?.off, [prefs]);

  useEffect(() => {
    const geom = (g: { width: number; height: number } | null | undefined) => {
      if (!g) return;
      setNw(g.width); setNh(g.height);
      document.documentElement.style.setProperty("--nw", `${g.width}px`);
      document.documentElement.style.setProperty("--nh", `${g.height}px`);
    };
    let dead = false;
    const uns = [
      listen<boolean>("notch-open", (e) => setOpen(!!e.payload)),
      listen<string>("notch-mode", (e) => setMode(e.payload === "idle" ? "idle" : "run")),
      listen<boolean>("notch-near", (e) => setNear(!!e.payload)),
      // 空闲格子：常驻的菜单栏 webview 算好推过来（与托盘悬停面板同一份）
      listen<IdlePanelData>(IDLE_PANEL_EVENT, (e) => setIdleData(e.payload)),
      // 改分辨率 / 换屏后刘海尺寸变了，Rust 摆完窗口再告诉这里
      listen<{ width: number; height: number }>("notch-geom", (e) => geom(e.payload)),
      // 果冻下垂：Rust 只在收起态、光标在刘海附近时以 60 Hz 推（离开范围时补一帧让这滴黑收回去）
      listen<{ dx: number; distance: number }>("notch-cursor", (e) => setCursor({ dx: e.payload.dx, distance: e.payload.distance })),
    ];
    // ★ 监听都注册好之后再问一次当前状态：窗口刚建好时光标已经停在刘海上，
    //   `notch-open` 可能早于 listen 生效 —— 不补这一句，Rust 认为展开了、这里还收着。
    void Promise.all(uns).then(() => {
      void emit(IDLE_PANEL_WANT).catch(noop);
      return invoke<{ width: number; height: number; open?: boolean; mode?: string; near?: boolean } | null>("notch_geometry");
    }).then((g) => {
      if (dead || !g) return;
      geom(g);
      if (g.mode) setMode(g.mode === "idle" ? "idle" : "run");
      setNear(!!g.near);
      setOpen(!!g.open);
    })
      .catch(noop);
    return () => { dead = true; for (const u of uns) void u.then((f) => f()); };
  }, []);

  // ── 数据 ───────────────────────────────────────────────────────────────
  const { inUse, liveN } = useMemo(() => {
    const slots = state.slots ?? {};
    // `slotToAccount` 第三参是 token 表，只影响 token 过期提示，额度窗口与状态用不到 ——
    // 刘海因此不读 `read_auth_tokens`（useStore 每 30s 读一次全部 token）。
    const accts = Object.entries(slots).map(([aid, sl]) => slotToAccount(aid, sl, {}, state.pinned));
    const aid = inUseAid(state);
    return {
      inUse: accts.find((a) => a.aid === aid),
      liveN: accts.filter((a) => a.status === "live" || a.status === "low").length,
    };
  }, [state, tick]);   // tick：数据没变时让 now 前进（窗口过重置点、冷却结束）

  // agy 画哪一份：池里当前号的（与菜单栏同一条）；池还没建起来就退回本机那份
  const agyCur = agyPool.accounts.find((a) => a.sub === agyPool.liveSub);
  const agyShownSnap = useMemo(
    () => (agyCur ? agyPool.snapshotOf(agyCur, agySnap) : agyPool.accounts.length === 0 ? agySnap : null),
    [agyCur, agyPool.snapshotOf, agyPool.accounts.length, agySnap]);

  // grok：只读 sidecar + 收推送（采样器 / 菜单栏取到新数后 Rust 发 `grok-quota-updated`）。刘海从不发起联网的取数。
  const [grokSnap, setGrokSnap] = useState<GrokSnapshot | null>(null);
  useEffect(() => {
    const read = () => {
      invoke<string | null>("read_grok_quota").then((raw) => {
        if (!raw) return;
        let d: GrokSnapshot;
        try { d = JSON.parse(raw) as GrokSnapshot; } catch (_e: unknown) { return; }
        setGrokSnap((prev) => (prev && prev.fetched_at >= d.fetched_at ? prev : d));
      }).catch(noop);
    };
    read();
    const un = listen("grok-quota-updated", read);
    return () => { void un.then((f) => f()); };
  }, []);

  // 今日快照：只读盘（`.traffic-latest.json`，扫描是主窗 / 菜单栏的事）+ 收 `traffic-updated`；展开时 60 s 节流补读一次
  const [traffic, setTraffic] = useState<TrafficData | null>(null);
  const trafficAt = useRef(0);
  const readTraffic = useCallback(() => {
    trafficAt.current = Date.now();
    invoke<string | null>("read_traffic_snapshot").then((raw) => {
      if (!raw) return;
      let d: TrafficData;
      try { d = JSON.parse(raw) as TrafficData; } catch (_e: unknown) { return; }
      setTraffic((prev) => (prev && prev.generated_at >= d.generated_at ? prev : d));
    }).catch(noop);
  }, []);
  useEffect(() => {
    readTraffic();
    const un = listen("traffic-updated", readTraffic);
    return () => { void un.then((f) => f()); };
  }, [readTraffic]);

  // Claude 额度（状态栏转写；没有时 Claude.app 的 plan-usage-history）：展开时读，60 s 节流。读不到保留上一份（§7.0b）。
  const [claudeQ, setClaudeQ] = useState<ClaudeQuota | null>(null);
  const claudeAt = useRef(0);
  // 各家今日均速（`requests.ts::dayMetrics`，与请求页 / 菜单栏今日 Tab 同一个算法）：今日 Tab 展开时读，60 s 节流
  const [tpsBy, setTpsBy] = useState<Record<string, number | null>>({});
  const reqAt = useRef(0);

  const [act, setAct] = useState<NotchActivity>(NO_ACTIVITY);
  // ★ 4e 卡片只在「在跑」那种展开里出现；空闲那种展开画额度格子（P11 刘海屏版）
  const cardOpen = open && mode !== "idle";
  useEffect(() => {
    // 谁正在跑 —— Rust 用 FSEvents 看四家自己的会话文件，**变了才推**（`activity.rs::watch_activity`）。
    // ★ **空闲时不亮** —— 光晕只表示「有 AI 在跑」，额度看卡片。
    invoke<NotchActivity | null>("notch_activity").then((a) => { if (a) setAct(a); }).catch(noop);
    const un = listen<NotchActivity>("notch-activity", (e) => setAct(e.payload));
    return () => { void un.then((f) => f()); };
  }, []);

  // ★ 下一个「数据没变、但该重画」的时间点：在用号各窗口的重置点、agy 各窗口的重置点、
  //   任一号冷却结束。只定这一个闹钟，到点重算；空闲时没有任何周期性工作。
  useEffect(() => {
    const now = Date.now() / 1000;
    const times: number[] = [];
    const q = (state.slots ?? {})[inUseAid(state) ?? ""]?.quota;
    for (const w of [q?.primary, q?.secondary]) if (w?.resets_at) times.push(w.resets_at);
    for (const sl of Object.values(state.slots ?? {})) if (sl.cooling_until) times.push(sl.cooling_until);
    for (const r of agyWinRows(agyShown(agyShownSnap)?.quota)) if (r.reset_at) times.push(r.reset_at);
    const next = Math.min(...times.filter((t) => t > now));
    const ms = Number.isFinite(next) ? Math.min((next - now) * 1000 + 1000, MAX_WAKE_MS) : MAX_WAKE_MS;
    const id = setTimeout(() => setTick((n) => n + 1), ms);
    return () => clearTimeout(id);
  }, [state, agyShownSnap, tick]);

  // 空闲那种展开也要按当下的「减弱动态效果」画（4e 卡片在自己的展开流程里读）
  // ★ 系统设置随时可能改：只在展开时重读的话，开着 app 时打开「减弱动态效果」，下次靠近照样亮光晕
  useEffect(() => {
    let mq: MediaQueryList | null = null;
    try { mq = window.matchMedia("(prefers-reduced-motion: reduce)"); } catch (_e: unknown) { return; }
    const on = () => setReduce(prefersReduce());
    mq.addEventListener?.("change", on);
    return () => { mq?.removeEventListener?.("change", on); };
  }, []);
  useEffect(() => { if (open && mode === "idle") setReduce(prefersReduce()); }, [open, mode]);

  // 卡片开着才走倒计时文字
  useEffect(() => {
    if (!cardOpen) return;
    setTick((n) => n + 1);
    const id = setInterval(() => setTick((n) => n + 1), OPEN_TICK_MS);
    return () => clearInterval(id);
  }, [cardOpen]);

  // ── 派生 ───────────────────────────────────────────────────────────────
  const rows = useMemo(() => runningRows(live), [live]);
  const nRun = rows.length;
  const view = C.effectiveView(chosen, nRun);
  const isRunV = view === "run";

  const lines = useMemo<C.QLine[]>(() => {
    const out: C.QLine[] = [];
    const nowSec = Date.now() / 1000;
    if (inUse && !isOff("codex")) {
      out.push({ key: "codex", name: maskId(inUse.node, privacy), ...winsFromSegs(codexSegs(inUse, false), "codex") });
    }
    if (!isOff("claude")) {
      const st = !!claudeQ && isStale(claudeQ.capturedAt, nowSec);
      out.push({ key: "claude", name: "本机", w5: claudeWin(claudeQ?.fiveH ?? null, st), ww: claudeWin(claudeQ?.week ?? null, st) });
    }
    const agy = agySegs(agyShownSnap, isOff("agy"), agyPool.accounts.length > 0 && !agyCur);
    if (agy.length) {
      const nm = agyCur ? maskId(agyCur.label, privacy) : agyPool.accounts.length === 0 ? "当前号" : "—";
      out.push({ key: "agy", name: nm, ...winsFromSegs(agy, "agy") });
    }
    if (grokQuotaVisible(grokSnap, { disabled: isOff("grok") }) && grokSnap) {
      const a = grokSnap.accounts[0];
      const rem = grokRemPct(a), lg = grokLastGoodRemPct(a);
      // ★ grok 只有周窗口：5h 那格留空（这家没有这个窗口），不是「读不到」
      const ww: C.QWin = a.available && rem != null
        ? { pct: rem, refill: fmtEta(a.quota?.period_end ?? undefined) }
        : lg != null ? { pct: lg, refill: fmtEta(a.last_good?.period_end ?? undefined), stale: true, title: "上次读数 —— 这次额度暂时读不到" }
        : { pct: null, refill: "—", title: "额度暂时读不到" };
      out.push({ key: "grok", name: "grok", w5: C.ABSENT, ww });
    }
    return C.orderQuota(out);
  }, [inUse, isOff, privacy, claudeQ, agyShownSnap, agyPool.accounts.length, agyCur, grokSnap, tick]);
  const alert = C.alertOf(lines);
  const hot = new Set(C.alertKeys(lines));

  // 光晕：在跑且没停用的几家，平台色（用户在设置里改过就用改过的）；低额度那家换橙红
  const litKeys = glowKeys(act, isOff);
  const litCols = litKeys.map((k) => (hot.has(k) ? C.ALERT : prefs.by?.[k]?.color ?? platformColor(k)));
  const glow = glowBackground(litCols);
  const bridge = bridgeBackground(litCols);
  const lit = litKeys.length > 0;

  const today = useMemo(() => todayView(applyPlatformPrefs(applyCacheMode(traffic, cacheMode), prefs)), [traffic, cacheMode, prefs]);
  const shaped = useMemo(() => applyPlatformPrefs(applyCacheMode(traffic, cacheMode), prefs), [traffic, cacheMode, prefs]);
  const perAll = today ? today.per.filter((p) => p.tok > 0) : [];
  const per = perAll.slice(0, C.todayRowCap(!!alert, lines.length));

  const blocks: C.RunRowIn[] = rows.map((r) => ({ multi: isMulti(r), open: isMulti(r) && !!ex.open[r.key], nSess: r.sessions.length }));
  const lay = C.layoutCard({ alert: !!alert, view, run: blocks, todayRows: per.length, quotaRows: lines.length });

  // ── 展开 / 收起 ──────────────────────────────────────────────────────────
  const later = (fn: () => void, ms: number) => { timers.current.push(window.setTimeout(fn, ms)); };
  const clearTimers = () => { timers.current.forEach((t) => window.clearTimeout(t)); timers.current = []; };
  const st = useRef({ rows, nw, nh, reduce, isRunV, settled });
  st.current = { rows, nw, nh, reduce, isRunV, settled };

  const wasOpen = useRef(false);
  useEffect(() => {
    if (cardOpen === wasOpen.current) return;
    wasOpen.current = cardOpen;
    clearTimers();
    const cur = st.current;
    if (cardOpen) {
      const red = prefersReduce();
      setReduce(red);
      dispatch({ t: "reset" });
      setSettled(false);
      // ★ 每次展开都回到默认 Tab（有人在跑 = 在跑；空闲 = 今日）
      const v = C.defaultView(cur.rows.length);
      setChosen(v);
      const now = Date.now();
      if (now - claudeAt.current > REFETCH_MS) {
        claudeAt.current = now;
        invoke<string>("read_statusline_quota")
          .then((raw) => { const q = parseClaudeQuota(raw); if (q) setClaudeQ(q); })
          .catch(noop);   // 读不到保留上一份；一次都没读到 ⇒ 两格写 —
      }
      if (now - trafficAt.current > REFETCH_MS) readTraffic();
      // logo 从各自那段光晕飞进自己那一行（只在「在跑」Tab；减弱动态效果时不飞）
      const pl0 = C.layoutCard({ alert: !!alert, view: "run", run: cur.rows.map(() => ({ multi: false, open: false, nSess: 0 })), todayRows: 0, quotaRows: 0 });
      if (!red && v === "run" && cur.rows.length) {
        goRef.current = cur.rows.map((r, i) => {
          const to = C.flyTo(pl0.rowTop[i], cur.nw, cur.nh, cur.rows.some(isMulti));
          const d = 140 + i * 40;
          return { key: r.key, x: to.x, y: to.y, s: C.FLY_TO_S, op: 1, sh: 0,
                   tr: `transform 600ms ${SP} ${d}ms, opacity 160ms ease-out ${d}ms, filter 700ms ease-out 260ms` };
        });
        setFly(cur.rows.map((r) => {
          const f = C.flyFrom(r.key, cur.nw);
          return { key: r.key, x: f.x, y: f.y, s: C.FLY_FROM_S, op: 0, sh: 9, tr: "none" };
        }));
      } else {
        goRef.current = null;
        setFly([]);
      }
      later(() => { setSettled(true); setFly([]); }, red ? 0 : C.SETTLE_MS);
    } else {
      setSettled(false);
      // 收起：logo 从行里（此刻真实所在）缩回各自那段光晕
      const card = cardRef.current;
      const stage = card?.parentElement;
      if (cur.reduce || !cur.isRunV || !card || !stage) { goRef.current = null; setFly([]); return; }
      const sr = stage.getBoundingClientRect();
      const start: Fly[] = [], go: Fly[] = [];
      for (const r of cur.rows) {
        const el = stage.querySelector(`[data-notch-fly="${r.key}"]`) ?? stage.querySelector(`[data-notch-logo="${r.key}"]`);
        if (!el) continue;
        const b = el.getBoundingClientRect();
        start.push({ key: r.key, x: b.left - sr.left, y: b.top - sr.top, s: b.width / C.FLY_LOGO, op: 1, sh: 0, tr: "none" });
        const f = C.flyFrom(r.key, cur.nw);
        go.push({ key: r.key, x: f.x, y: f.y, s: C.FLY_FROM_S, op: 0, sh: 9,
                  tr: `transform 380ms ${SP} 40ms, opacity 220ms ease-out 160ms, filter 700ms ease-out 0ms` });
      }
      goRef.current = start.length ? go : null;
      setFly(start);
      later(() => setFly([]), 620);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardOpen]);

  // 两拍起飞：第一拍放在起点（无过渡）并强制算一次样式，第二拍给终点 + 过渡
  useLayoutEffect(() => {
    if (!goRef.current || !fly.length) return;
    cardRef.current?.getBoundingClientRect();
    const go = goRef.current;
    goRef.current = null;
    setFly(go);
  }, [fly]);
  useEffect(() => () => clearTimers(), []);

  // 今日 Tab 可见时补读各家今日均速（起一次 `requests.py --json`；60 s 节流）
  useEffect(() => {
    if (!cardOpen || view !== "today") return;
    const now = Date.now();
    if (now - reqAt.current <= REFETCH_MS) return;
    reqAt.current = now;
    let alive = true;
    invoke<string>("read_requests").then((raw) => {
      const p = parsePayload(raw);
      if (!alive || (!p.ok && !p.requests.length)) return;   // 这次没读到 ≠ 今天没有请求：保留上一份
      const rowsT = rowsForDay(p.requests, dayKeys(p, Date.now()).today);
      const out: Record<string, number | null> = {};
      for (const k of REQ_ORDER) out[k] = dayMetrics(filterPlatform(rowsT, k)).avgTps;
      setTpsBy(out);
    }).catch(noop);
    return () => { alive = false; };
  }, [cardOpen, view]);

  // 会话展开 / 折叠：悬停 250 ms 展开、离开这一行 250 ms 折叠（与悬停面板同一份规则，`tpsHoverLogic.ts`）
  const multiKeys = rows.filter(isMulti).map((r) => r.key).join(",");
  useEffect(() => { dispatch({ t: "prune", multi: multiKeys ? multiKeys.split(",") : [] }); }, [multiKeys]);
  useEffect(() => {
    const at = HL.nextDue(ex);
    if (at == null) return;
    const id = window.setTimeout(() => dispatch({ t: "tick", now: Date.now() }), Math.max(0, at - Date.now()));
    return () => window.clearTimeout(id);
  }, [ex]);
  // 行高变了 ⇒ 还在飞的 logo 落点作废：直接交给行自己画
  const openKeys = Object.keys(ex.open).filter((k) => ex.open[k]).join(",");
  useEffect(() => { if (openKeys) setFly((f) => (f.length && cardOpen ? [] : f)); }, [openKeys, cardOpen]);

  // 卡片实际高度报给 Rust（定窗口高与命中区）：长高立刻报，变矮等 420 ms 高度动画走完再报
  const lastH = useRef<number | null>(null);
  const resizeT = useRef<number | null>(null);
  useEffect(() => {
    const h = lay.height;
    if (lastH.current === h) return;
    if (resizeT.current != null) window.clearTimeout(resizeT.current);
    const send = () => { lastH.current = h; resizeT.current = null; invoke("notch_card_resize", { h, mode: "run" }).catch(noop); };
    const d = C.resizeDelay(lastH.current, h, reduce);
    if (d === 0) send(); else resizeT.current = window.setTimeout(send, d);
  }, [lay.height, reduce]);
  // ★ 空闲格子的高度单独报一份（Rust 两种展开各存一份）：换种类那一下 Rust 已经有对的高度，不等网页收到 `notch-mode`。
  //   格子面板没有高度动画 ⇒ 立刻报；还没收到格子（0 格）不报 —— 报上去会被钳成 80，是一块看不见的命中区。
  const idleCells = idleData?.cells ?? [];
  const idleH = NI.notchGrid(idleCells.length).h;
  useEffect(() => { if (idleH > 0) invoke("notch_card_resize", { h: idleH, mode: "idle" }).catch(noop); }, [idleH]);
  // 展开着格子变空（设置改成「只看菜单栏」、数据刷新）⇒ 收起，不留一块空白展开态
  useEffect(() => { if (open && mode === "idle" && idleData && !idleCells.length) invoke("notch_dismiss").catch(noop); },
            [open, mode, idleData, idleCells.length]);

  const pickIdle = (key: string) => {
    emit("open-main-page", NI.cellTarget(key)).catch(noop);
    invoke("notch_dismiss").catch(noop);
  };

  const go = (page: "requests" | "traffic" | "overview") => (e: MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    emit("open-main-page", { page, platform: null }).catch(noop);
  };

  // ── 画 ─────────────────────────────────────────────────────────────────
  const isOpen = cardOpen;
  const idleOpen = open && mode === "idle";
  const idleLow = idleCells.some((c) => c.low);
  const niOp = NI.idleGlowOpacity({ lit, reduce, near, idleOpen, cardOpen: isOpen });
  const niTr = NI.idleGlowTransition(niOp);
  const ms = (v: number) => `${v}ms`;
  const fade = "150ms ease-out";
  const vT = reduce ? "0ms" : `420ms ${SP}`;
  const pTr = reduce ? "opacity 150ms"
    : `opacity ${isOpen ? `200ms ease-out 120ms` : "140ms ease-in"}, transform ${isOpen ? `460ms ${SP} 100ms` : "260ms ease-in"}, height 420ms ${SP}`;
  const bTr = reduce ? "opacity 150ms"
    : isOpen ? "transform 220ms ease-out, opacity 120ms ease-out" : "transform 180ms ease-in 80ms, opacity 160ms ease-in 80ms";
  const bSx = isOpen || reduce ? 1 : 0;
  const hT = isOpen ? (reduce ? fade : `220ms ease-out ${ms(700)}`) : "100ms";
  const qDelay = nRun > 0 ? 640 : 300;
  const qT = isOpen ? (reduce ? fade : `240ms ease-out ${ms(qDelay)}`) : "100ms ease-out";
  const qT2 = isOpen && !reduce ? `440ms ${SP} ${ms(qDelay)}` : "100ms";
  const barT = reduce ? "0ms" : isOpen ? `600ms ${SP} ${ms(qDelay + 120)}` : "100ms";
  const tdIn = isOpen && !isRunV;
  // 任一种展开都收起果冻下垂：展开后 Rust 不再推光标，传 `isOpen`（只认 4e）会让空闲展开时那滴黑冻在最后一帧
  const drip = C.dripGeom(cursor, nw, open);
  const nameW = C.nameColWidth(lines.map((l) => l.name));
  const flying = new Set(fly.map((f) => f.key));
  // 今日面积图（256 × 70，色序与光晕 / 平台色同；占比最大的一层贴底）
  const VW = 256, VH = 70;
  const chart = useMemo(() => {
    if (!today) return null;
    const acc = new Array(today.hours.length).fill(0) as number[];
    const layers = today.series.map((s) => {
      const base = [...acc];
      s.values.forEach((v, i) => { acc[i] += v; });
      return { key: s.key, base, top: [...acc] };
    });
    const yMax = Math.max(1, ...acc) * 1.08;
    return layers.map((l) => ({ key: l.key, d: C.stackPath(l.top, l.base, yMax, VW, VH) }));
  }, [today]);
  const ticks = useMemo(() => {
    if (!today) return [];
    const n = today.hours.length;
    const step = [1, 2, 3, 4, 6, 8, 12].find((s) => Math.ceil(n / s) <= 5) ?? 12;
    // 从末尾往前取（最后一个一定落在节奏上），按真实 x 定位
    const idx: number[] = [];
    for (let i = n - 1; i >= 0; i -= step) idx.unshift(i);
    return idx.map((i) => ({ i, x: n <= 1 ? 50 : (i / (n - 1)) * 100, t: i === n - 1 ? "现在" : `${today.hours[i].slice(11)}:00` }));
  }, [today]);

  const fmtCount = (n: number) => n.toLocaleString("en-US");

  return (
    <div className={["nh-root", lit ? "nh-active" : "nh-quiet", isOpen && "nh-open", reduce && "nh-reduce"].filter(Boolean).join(" ")}
         data-notch-open={isOpen ? "1" : "0"} data-notch-mode={mode} data-notch-near={near ? "1" : "0"} data-notch-view={view} data-notch-h={lay.height}
         style={{ ["--glow" as string]: glow, ["--cw" as string]: `${C.CARD_W}px` }}>
      <div className="nh-stage">
        <div className="ni-glow" aria-hidden="true" data-notch-near-glow={niOp} style={{ opacity: niOp, transition: niTr }}>
          <i className="e" /><i className="s" style={{ boxShadow: NI.idleGlowShadow(idleLow) }} />
          {/* 小红点是光晕的一部分：同一层的不透明度与过渡（一起淡入、一起延后淡出、减弱动态效果时一起不显示） */}
          {idleLow && <i className="ni-lowdot" data-notch-idle-lowdot />}
        </div>
        {/* 平台色光晕跟这一轮展开的种类走：空闲格子开着时 AI 开跑，不在格子头顶换成平台色（收起后再亮） */}
        <div className="nh-glow" aria-hidden="true" style={{ opacity: !lit || idleOpen ? 0 : open ? 0.6 : 0.9 }}>
          <i className="g2" /><i className="g1" />
          {litKeys.map((k, i) => hot.has(k) && (
            <i key={k} className="ga" data-notch-alert-glow={k} style={{ left: C.alertBlobLeft(i, litKeys.length, nw) }} />
          ))}
        </div>
        <div className="nh-bridge" data-notch-bridge={lit ? "lit" : "idle"}
             style={{ background: bridge, transform: `scaleX(${bSx})`, opacity: isOpen ? 0.95 : 0, transition: bTr }} />
        <div className="nh-bridge-soft"
             style={{ background: bridge, transform: `scaleX(${bSx})`, opacity: isOpen && lit ? 0.5 : 0, transition: bTr }} />

        <div ref={cardRef} className="nh-card" data-notch-card
             style={{ height: lay.height, opacity: isOpen ? 1 : 0, pointerEvents: isOpen ? "auto" : "none",
                      transform: !isOpen && !reduce ? "translateY(-8px) scale(.94)" : "none", transition: pTr }}>
          <i className="nh-topline" style={{ background: bridge, opacity: isOpen ? 0.85 : 0 }} />
          <div className="nh-content">
            {alert && (
              <div className="nh-alert" data-notch-alert={alert.key}
                   style={{ opacity: isOpen ? 1 : 0, transition: `opacity ${isOpen ? (reduce ? fade : "220ms ease-out 220ms") : "100ms ease-out"}` }}>
                <i />{alert.head}<b className="nh-mono">{alert.pct}</b>{alert.tail}
              </div>
            )}
            <div className="nh-block">
              <div className="nh-tabbar">
                <div className="nh-seg">
                  <i style={{ width: isRunV ? 64 : 88, transform: `translateX(${isRunV ? 0 : 64}px)`,
                              transition: reduce ? "none" : `transform 360ms ${SP}, width 360ms ${SP}` }} />
                  <button type="button" data-notch-tab="run" disabled={nRun === 0}
                          onClick={() => { if (nRun > 0) setChosen("run"); }}
                          style={{ width: 64, color: isRunV ? "#eef2f7" : "#798390", opacity: nRun > 0 ? 1 : 0.4 }}>
                    在跑<span className="nh-mono">{nRun}</span>
                  </button>
                  <button type="button" data-notch-tab="today" onClick={() => setChosen("today")}
                          style={{ width: 88, color: isRunV ? "#798390" : "#eef2f7" }}>
                    今日<span className="nh-mono">{today ? fmtTok(today.totalTok) : "—"}</span>
                  </button>
                </div>
                <span className="nh-hdr" style={{ opacity: isOpen ? 1 : 0 }}>
                  {isRunV ? "速度 · Token" : `↻ ${traffic ? new Date(traffic.generated_at * 1000).toTimeString().slice(0, 5) : "—"}`}
                </span>
              </div>

              {/* 在跑 Tab：同 page 2 的行（logo · 名 · ×N · t/s · Token），多会话行停 250 ms 展开 */}
              <div className={rows.some(isMulti) ? "nh-fold" : "nh-fold nh-nochev"} data-notch-run style={{ gridTemplateRows: isRunV ? "1fr" : "0fr", transition: `grid-template-rows ${vT}` }}>
                <div className="nh-clip">
                  <div style={{ opacity: isRunV ? 1 : 0, transition: `opacity ${reduce ? fade : `200ms ease-out ${isRunV ? "120ms" : "0ms"}`}` }}>
                    {rows.map((r, i) => {
                      const k = r.key;
                      const multi = isMulti(r);
                      const o = multi && !!ex.open[k];
                      const sx = C.side(k) * 16;
                      const dt = isOpen ? (reduce ? fade : `260ms ease-out ${ms(560 + i * 40)}`) : "100ms ease-out";
                      const dt2 = isOpen ? (reduce ? fade : `420ms ${SP} ${ms(540 + i * 40)}`) : "100ms ease-out";
                      const dX = isOpen || reduce ? 0 : sx;
                      const rT = reduce ? "0ms" : o ? `340ms ${SP}` : `300ms ${SP} 100ms`;
                      const tps = fmtTps(r.tps);
                      return (
                        <div key={k} data-notch-row={k} data-notch-open-row={o ? "1" : "0"}
                             onMouseEnter={() => dispatch({ t: "enter", key: k, multi, now: Date.now() })}
                             onMouseLeave={() => dispatch({ t: "leave", key: k, now: Date.now() })}>
                          <div className="nh-row" style={{ background: ex.hov === k ? "rgba(255,255,255,.06)" : "transparent" }}>
                            <span className="nh-chev" style={{ opacity: multi && isOpen ? 1 : 0, transform: `rotate(${o ? 90 : 0}deg)`, transition: `transform ${rT}` }}>
                              {multi && (
                                <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" style={{ display: "block" }}>
                                  <path d="M3.5 2l3 3-3 3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                              )}
                            </span>
                            <span className="nh-logo" data-notch-logo={k} style={{ visibility: flying.has(k) ? "hidden" : "visible" }}>
                              <PlatformLogo platform={k} isDark size={18} />
                            </span>
                            <span className="nh-name" style={{ opacity: isOpen ? 1 : 0, transform: `translateX(${dX}px)`, transition: `opacity ${dt}, transform ${dt2}` }}>
                              <b>{PLATFORM_NAME[k]}</b>
                              {multi && <span className="nh-chip nh-mono" data-notch-n>×{r.nSessions}</span>}
                            </span>
                            <span className="nh-tps nh-mono" data-notch-tps={tps}
                                  style={{ color: r.tps == null ? "#798390" : hot.has(k) ? "#ff8a73" : numColor(k, "dark"),
                                           opacity: isOpen ? 1 : 0, transform: `translateX(${dX}px)`, transition: `opacity ${dt}, transform ${dt2}` }}>
                              {tps}<span className="nh-unit"> t/s</span>
                            </span>
                            <span className="nh-tok nh-mono" style={{ opacity: isOpen ? 1 : 0, transform: `translateX(${dX}px)`, transition: `opacity ${dt}, transform ${dt2}` }}>
                              {fmtTokens(r.tokens)}
                            </span>
                          </div>
                          {multi && (
                            <div className="nh-fold" data-notch-sessions={k} style={{ gridTemplateRows: o ? "1fr" : "0fr", transition: `grid-template-rows ${rT}` }}>
                              <div className="nh-clip">
                                <div style={{ paddingBottom: C.SESS_PAD }}>
                                  {r.sessions.slice(0, C.MAX_SESS).map((s, j) => (
                                    <div key={s.id} className="nh-sess" data-notch-sess
                                         style={{ opacity: o ? 1 : 0, transition: `opacity ${reduce ? "0ms" : o ? `260ms ease-out ${ms(90 + j * 45)}` : "120ms ease-in"}` }}>
                                      <span /><span className="nh-sess-line" />
                                      <span className="nh-sess-t">{s.title || s.id.slice(0, 8)}</span>
                                      <span className="nh-sess-tps nh-mono">{fmtTps(s.tps)}<span> t/s</span></span>
                                      <span className="nh-sess-tok nh-mono">{fmtTokens(s.tokens)}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                    <div className="nh-foot" data-notch-runfoot style={{ height: 36, opacity: isOpen ? 1 : 0, transition: `opacity ${hT}` }}>
                      {/* ★ 今日总量与 Tab 标签、今日 Tab 同一个数（`todayView`，与菜单栏今日 Tab 同源）—— 同一张卡片里两个「今日」不能不一样；
                          快照还没读到才退回实时账本那份。均速 = 请求账本（与悬停面板同源）。 */}
                      <span>今日 <b>{today ? fmtTok(today.totalTok) : live ? fmtTokens(live.today.tokens) : "—"}</b>{live?.today.avg_tps != null && <> · 均 <b>{HL.fmtAvg(live.today.avg_tps)}</b> t/s</>}</span>
                      <a href="#" className="nh-link" data-notch-link="requests" onClick={go("requests")}>请求页 →</a>
                    </div>
                  </div>
                </div>
              </div>

              {/* 今日 Tab：415M · $ · 环比 · 峰值 + 24 h 堆叠面积 + 各家一行（0 用量不显示；300 宽放不下占比列） */}
              <div className="nh-fold" data-notch-today style={{ gridTemplateRows: isRunV ? "0fr" : "1fr", transition: `grid-template-rows ${vT}` }}>
                <div className="nh-clip">
                  <div style={{ opacity: isRunV ? 0 : 1, transition: `opacity ${reduce ? fade : `200ms ease-out ${isRunV ? "0ms" : "120ms"}`}` }}>
                    <div className="nh-sum">
                      <span className="nh-sum-tok nh-mono">{today ? fmtTok(today.totalTok) : "—"}</span>
                      <span className="nh-sum-cost nh-mono">{today ? compactUSD(today.totalCost) : "—"}</span>
                      {today?.deltaPct != null && (
                        <span className="nh-badge nh-mono" style={{ color: today.deltaPct >= 0 ? upCol : downCol,
                                                                    background: today.deltaPct >= 0 ? "rgba(62,207,142,.12)" : "rgba(255,77,46,.12)" }}>
                          {pctTxt(today.deltaPct)}
                        </span>
                      )}
                      <span className="nh-peak nh-mono">{today?.peak ? `峰 ${fmtTok(today.peak.v)} · ${today.peak.hour.slice(11)}:00` : "今日暂无用量"}</span>
                    </div>
                    <div className="nh-chart">
                      <svg width={VW} height={VH} viewBox={`0 0 ${VW} ${VH}`} aria-hidden="true" data-notch-chart
                           style={{ clipPath: `inset(0 ${tdIn || reduce ? 0 : 100}% 0 0)`,
                                    transition: tdIn && !reduce ? `clip-path 900ms cubic-bezier(.2,.7,.2,1) ${settled ? 160 : 380}ms` : "clip-path 0ms" }}>
                        {chart?.map((l) => <path key={l.key} d={l.d} fill={colorOf(shaped, l.key)} />)}
                      </svg>
                    </div>
                    <div className="nh-axis nh-mono">
                      {ticks.map((t) => (
                        <span key={t.i} style={{ left: `${t.x}%`, transform: t.x <= 0 ? "none" : t.x >= 100 ? "translateX(-100%)" : "translateX(-50%)" }}>{t.t}</span>
                      ))}
                    </div>
                    <div className="nh-trow nh-thead"><span /><span>AI</span><span>Token</span><span>费用</span><span>t/s</span><span>环比</span></div>
                    {per.map((p, i) => {
                      const k = p.key;
                      const known = k === "codex" || k === "claude" || k === "agy" || k === "grok";
                      const tps = tpsBy[k];
                      const d = ms(200 + 40 * i);
                      return (
                        <div key={k} className="nh-trow nh-tline" data-notch-trow={k}
                             style={{ opacity: tdIn ? 1 : 0, transform: `translateY(${tdIn || reduce ? 0 : 6}px)`,
                                      transition: reduce ? `opacity ${fade}` : `opacity 220ms ease-out ${d}, transform 380ms ${SP} ${d}` }}>
                          {known ? <PlatformLogo platform={k as C.NotchKey} isDark size={14} />
                                 : <span className="nh-sq" style={{ background: colorOf(shaped, k) }} />}
                          <span className="nm">{k === "agy" ? "Gemini" : p.name}</span>
                          <span className="tk nh-mono">{fmtTok(p.tok)}</span>
                          <span className="ct nh-mono">{fmtUSD(p.cost)}</span>
                          <span className="ts nh-mono" style={{ color: tps == null ? "#798390" : known ? numColor(k as C.NotchKey, "dark") : "#aab3c0" }}>
                            {tps == null ? "—" : Math.round(tps)}
                          </span>
                          <span className="dl nh-mono" style={{ color: p.deltaPct == null ? "#798390" : p.deltaPct >= 0 ? upCol : downCol }}>
                            {p.deltaPct == null ? "—" : pctTxt(p.deltaPct)}
                          </span>
                        </div>
                      );
                    })}
                    <div className="nh-foot" data-notch-todayfoot style={{ height: 32 }}>
                      <span>今日 <b>{live ? fmtCount(live.today.n) : "—"}</b> 次请求{live?.today.avg_tps != null && <> · 均 <b>{HL.fmtAvg(live.today.avg_tps)}</b> t/s</>}</span>
                      <a href="#" className="nh-link" data-notch-link="traffic" onClick={go("traffic")}>Token 消耗 →</a>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* 下块 · 额度 · 当前号：Codex · Claude · Gemini · Grok（< 10% 的置顶整行橙红；Grok 只有周） */}
            <div className="nh-block" data-notch-quota
                 style={{ marginTop: C.BLOCK_GAP, opacity: isOpen ? 1 : 0, transform: `translateY(${isOpen || reduce ? 0 : 10}px)`,
                          transition: `opacity ${qT}, transform ${qT2}` }}>
              <div className="nh-qhead"><span>额度 · 当前号</span><span>5h · 周</span></div>
              {lines.map((l) => {
                const isHot = hot.has(l.key);
                const c = isHot ? "#ff8a73" : "#eef2f7";
                const cell = (w: C.QWin, lab: string, fill: string) => (
                  <span className="nh-qwin" title={w.title} data-notch-win={`${l.key}:${lab}`}
                        style={{ opacity: w.absent ? 0 : w.stale ? 0.55 : 1 }}>
                    <em>{lab}</em>
                    <span className="nh-bar"><span style={{ width: `${isOpen && w.pct != null ? Math.max(0, Math.min(100, w.pct)) : 0}%`,
                                                             background: isHot ? C.ALERT : fill, transition: `width ${barT}` }} /></span>
                    <span className="nh-qpct nh-mono" style={{ color: w.pct == null ? "#798390" : c }}>{C.pctText(w)}</span>
                  </span>
                );
                return (
                  <div key={l.key} className="nh-qrow" data-notch-qrow={l.key} data-notch-hot={isHot ? "1" : "0"}
                       style={{ gridTemplateColumns: `16px ${nameW}px minmax(0, 1fr) minmax(0, 1fr)`, background: isHot ? "rgba(255,77,46,.12)" : "transparent" }}>
                    <PlatformLogo platform={l.key} isDark size={16} />
                    <span className="nh-qname" style={{ color: c }} title={l.name}>{l.name}</span>
                    {cell(l.w5, "5h", "#2dd4bf")}
                    {cell(l.ww, "周", "#22b573")}
                  </div>
                );
              })}
              <div className="nh-foot" style={{ height: 32 }}>
                <span>账号池 <b>{liveN}</b> 个号可用</span>
                <a href="#" className="nh-link" data-notch-link="overview" onClick={go("overview")}>总览 →</a>
              </div>
            </div>
          </div>
        </div>

        <NotchIdleGrid cells={idleCells} open={idleOpen} reduce={reduce} onPick={pickIdle} />

        <div className="nh-island" />
        <div className="nh-drip" data-notch-drip={drip.on ? drip.h.toFixed(1) : "0"}
             style={{ left: drip.left, height: drip.h, opacity: drip.on ? 1 : 0 }} />
        <div className="nh-flylayer" style={{ opacity: isRunV ? 1 : 0 }}>
          {fly.map((f) => (
            <img key={f.key} className="nh-fly" data-notch-fly={f.key} alt="" draggable={false}
                 src={logoSrc(f.key, true)} width={C.FLY_LOGO} height={C.FLY_LOGO}
                 style={{ transform: `translate(${f.x}px, ${f.y}px) scale(${f.s})`, opacity: f.op,
                          filter: `drop-shadow(0 0 ${f.sh}px ${hot.has(f.key) ? C.ALERT : prefs.by?.[f.key]?.color ?? platformColor(f.key)})`,
                          transition: f.tr }} />
          ))}
        </div>
      </div>
    </div>
  );
}
