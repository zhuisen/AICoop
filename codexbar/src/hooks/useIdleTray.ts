import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import { fmtEta, type Account } from "../helpers";
import type { PlatformPrefs, TrafficData } from "../traffic";
import { agyResetText, agyShown, agyWinRows, type AgySnapshot } from "../agy";
import { grokLastGoodRemPct, grokRemPct, type GrokSnapshot } from "../grok";
import { parseClaudeQuota, type ClaudeQuota } from "../mbLogic";
import { useAgyPool } from "./useAgyPool";
import { getSettings, IDLE_TRAY_EVENT } from "../pages/SettingsPage";
import { dayKey, IDLE_PANEL_EVENT, IDLE_PANEL_WANT, panelCells, pickIdleSlots, shouldRerank, TRAY_KEYS, trayPayload, usageOf,
         weeklyWarns, IDLE_SNOOZE_EVENT, SNOOZE_KEY, liveSnoozes, snoozeUntil, claudeRem,
         mergeFrozen, type IdlePanelData, type IdleWarn, type PanelIn, type Snoozed } from "../idleTray";

/** Claude 额度转写只在 Claude Code 刷新状态栏时才变：与总览 `useClaudeQuota` 同一个间隔（60 s）。
 *  ★ 原来 5 分钟：刚停手就悬停，面板比总览旧最多 5 分钟（2026-10-21 复查 B1）。另在托盘弹出 / 光标靠近托盘时读。 */
const CLAUDE_EVERY_MS = 60_000;
/** 光标靠近托盘（`idle-near`）时补读一次本机额度，最多每 30 s 一次。 */
const NEAR_READ_GAP_MS = 30_000;
/** 没有数据变化时也要按时重算：跨午夜重排、24 h 动态位过期。 */
const TICK_MS = 60_000;

/** 今天冻结的常驻 + 上一次打招呼（epoch 秒）。记进 localStorage：重启 / 部署后不重排、不再打一次招呼。 */
const FROZEN_KEY = "codexbar_idle_frozen";
/** 本 webview 内部事件：`idle-near` 变真 ⇒ 补读额度（两个 effect 之间传话，不出 webview）。 */
const NEAR_READ = "codexbar-idle-near-read";
const HELLO_KEY = "codexbar_idle_hello";
type Frozen = { day: string; keep: string[]; sig: string };

function loadFrozen(): Frozen | null {
  try {
    const o = JSON.parse(localStorage.getItem(FROZEN_KEY) ?? "null") as Partial<Frozen> | null;
    return o && typeof o.day === "string" && typeof o.sig === "string" && Array.isArray(o.keep)
      ? { day: o.day, sig: o.sig, keep: o.keep.filter((k): k is string => typeof k === "string") } : null;
  } catch (_e: unknown) { return null; }
}
function saveFrozen(f: Frozen): void {
  try { localStorage.setItem(FROZEN_KEY, JSON.stringify(f)); } catch (_e: unknown) { /* 存不下就只活在本进程 */ }
}
function loadSnooze(): Record<string, number> {
  try { return liveSnoozes(JSON.parse(localStorage.getItem(SNOOZE_KEY) ?? "null") as Record<string, unknown> | null, Date.now()); }
  catch (_e: unknown) { return {}; }
}
function loadHello(): number | null {
  const v = Number(localStorage.getItem(HELLO_KEY));
  return Number.isFinite(v) && v > 0 ? v : null;
}

/**
 * 空闲托盘（AICoop P11）的取数 + 选位，跑在**常驻的菜单栏 webview** 里；结果经 `set_idle_tray` 交给 Rust 画。
 *
 * ★ 选位逻辑全在 `idleTray.ts`（零 import，有行为闸）；这里只把各家的数拼成 `IdlePlatform[]`。
 * ★ 额度只读不取（同刘海）：Codex 用 `useStore` 已有的在用号；agy 读池里当前号；grok / agy 本机读 sidecar + 收推送；
 *   Claude 读状态栏转写。从不发起联网。读不到 ⇒ `remaining` 为空 ⇒ 整只灰色剪影，绝不当满或空。
 * ★ 排名每天冻结一次（P11 §2「顺序与稳定」）：跨了本地午夜、空闲、鼠标不在托盘上时才换上新常驻。
 *   固定 / 位数 / 排序依据 / 统计窗口是用户的动作，改了立刻生效。
 */

export function useIdleTray(inUse: Account | undefined, traffic: TrafficData | null, prefs: PlatformPrefs,
                            running: boolean): void {
  const [cfg, setCfg] = useState(getSettings);
  const [claude, setClaude] = useState<ClaudeQuota | null>(null);
  const [grok, setGrok] = useState<GrokSnapshot | null>(null);
  const [agySnap, setAgySnap] = useState<AgySnapshot | null>(null);
  const [tick, setTick] = useState(0);
  const near = useRef(false);
  const frozen = useRef<Frozen | null>(loadFrozen());
  const agyPool = useAgyPool(false);
  // 「隐藏到重置」（B1）：key → 藏到的时刻（epoch ms）；各家大数字那个窗口的重置时刻由 `platforms` 顺手记下
  const [snz, setSnz] = useState<Record<string, number>>(loadSnooze);
  const mainReset = useRef<Record<string, number | null>>({});

  useEffect(() => {
    const subs = [
      listen(IDLE_TRAY_EVENT, () => setCfg(getSettings())),
      // 悬停面板点了格子的 ×（或底部「撤销」）。藏到这一家大数字那个窗口重置；读不到重置时刻 ⇒ 5h（grok 是周窗口 ⇒ 24h）
      listen<{ key?: unknown; undo?: unknown }>(IDLE_SNOOZE_EVENT, (e) => {
        const key = typeof e.payload?.key === "string" ? e.payload.key : null;
        if (!key) return;
        setSnz((prev) => {
          const now = Date.now();
          const next = liveSnoozes(prev, now);
          if (e.payload?.undo) delete next[key];
          else next[key] = snoozeUntil(mainReset.current[key], now, key === "grok" ? 24 : 5);
          try { localStorage.setItem(SNOOZE_KEY, JSON.stringify(next)); } catch (_e: unknown) { /* 存不下就只活在本进程 */ }
          return next;
        });
      }),
      listen<boolean>("idle-near", (e) => {
        near.current = !!e.payload;
        if (near.current) window.dispatchEvent(new Event(NEAR_READ));
      }),
      listen<number>("idle-hello", (e) => {
        try { localStorage.setItem(HELLO_KEY, String(e.payload)); } catch (_e: unknown) { /* 存不下：重启后可能再打一次 */ }
      }),
    ];
    const id = window.setInterval(() => setTick((n) => n + 1), TICK_MS);
    return () => { window.clearInterval(id); subs.forEach((p) => { void p.then((f) => f()); }); };
  }, []);

  // 额度：只读本机盘 + 收推送；读不到保留上一份（CLAUDE.md §7.0b）
  useEffect(() => {
    const readClaude = () => {
      invoke<string>("read_statusline_quota").then((raw) => { const q = parseClaudeQuota(raw); if (q) setClaude(q); }).catch(() => {});
    };
    const readGrok = () => {
      invoke<string | null>("read_grok_quota").then((raw) => {
        if (!raw) return;
        let d: GrokSnapshot;
        try { d = JSON.parse(raw) as GrokSnapshot; } catch (_e: unknown) { return; }
        setGrok((p) => (p && p.fetched_at >= d.fetched_at ? p : d));
      }).catch(() => {});
    };
    const readAgy = () => {
      invoke<string | null>("read_agy_quota").then((raw) => {
        if (!raw) return;
        let d: AgySnapshot;
        try { d = JSON.parse(raw) as AgySnapshot; } catch (_e: unknown) { return; }
        setAgySnap((p) => (p && p.fetched_at >= d.fetched_at ? p : d));
      }).catch(() => {});
    };
    readClaude(); readGrok(); readAgy();
    const id = window.setInterval(readClaude, CLAUDE_EVERY_MS);
    // 悬停面板是另一个 webview，这里收不到它打开；光标靠近托盘（Rust 推 `idle-near`）就是「马上要看」的信号
    let lastNear = 0;
    const onNear = () => {
      const t = Date.now();
      if (t - lastNear < NEAR_READ_GAP_MS) return;
      lastNear = t; readClaude(); readGrok(); readAgy();
    };
    window.addEventListener(NEAR_READ, onNear);
    const subs = [
      listen("menubar-shown", readClaude),
      listen("grok-quota-updated", readGrok),
      listen("agy-quota-updated", readAgy),
    ];
    return () => { window.clearInterval(id); window.removeEventListener(NEAR_READ, onNear); subs.forEach((p) => { void p.then((f) => f()); }); };
  }, []);

  const agyCur = agyPool.accounts.find((a) => a.sub === agyPool.liveSub);
  const agyView = useMemo(() => {
    const snap = agyCur ? agyPool.snapshotOf(agyCur, agySnap) : agyPool.accounts.length === 0 ? agySnap : null;
    return agyShown(snap);
  }, [agyCur, agyPool.snapshotOf, agyPool.accounts.length, agySnap]);
  const agyQuota = agyView?.quota ?? null;
  const agyStale = !!agyView?.stale;

  const platforms = useMemo<PanelIn[]>(() => {
    const now = Date.now();
    const live = inUse && inUse.status !== "dead" ? inUse : null;
    // 大数字固定是 5h：没有 5h 窗口 ⇒ 写 —，不拿周窗口顶替（倒计时也会跟着换了含义）
    const w5 = live ? live.windows.find((w) => w.mins === 300) : undefined;
    const c5 = claudeRem(claude?.fiveH, now);
    const a5 = agyWinRows(agyQuota).find((r) => r.label === "5h");
    const g = grok?.accounts[0];
    const gNow = g ? grokRemPct(g) : null;
    const gRem = g ? gNow ?? grokLastGoodRemPct(g) : null;
    const gPeriodEnd = g ? (gNow === null ? g.last_good?.period_end : g.quota?.period_end) : null;
    // ★ logo 水位 = 5h 剩余（用户 2026-10-22「logo 水位都改成 5h」，取代 P11 §2「各窗口取最紧」）：与悬停格子的大数字
    //   同一个数。原来 Claude 5h 99% / 周 67% 时 logo 画 67%，用户读成「刷到 100% 了 svg 还是旧的」。
    //   没有 5h 窗口的写 null（整只灰），不拿周窗口顶替；grok 只有周窗口 ⇒ 用周（同 `main`）。红点、插队跟着这个数走。
    const rem: Record<string, (number | null)[]> = {
      codex: live ? [w5?.pct ?? null] : [],
      claude: [c5],
      agy: agyWinRows(agyQuota).length ? [a5?.remaining ?? null] : [],
      grok: g ? [gRem] : [],
    };
    // 面板大数字 = 5h 剩余；grok 只有周窗口 ⇒ 用周。右上角：5h 倒计时（grok 是周）；按量计费（Kimi / DeepSeek）不写
    const main: Record<string, [number | null, string]> = {
      codex: [w5?.pct ?? null, w5 ? w5.reset : ""],
      claude: [c5, c5 === null || !claude?.fiveH ? "" : claude.fiveH.idle ? "未启动" : fmtEta(claude.fiveH.resetsAt ?? undefined)],
      // ★ 倒计时走 `agyResetText`（与总览 AgyCard 同一个真源）：窗口没启动时它说「未启动」，
      //   直接 fmtEta 会画出一个跟着「现在」滑、永远走不到 0 的 ↻4h59m（复查 B3）。
      agy: [a5?.remaining ?? null, a5?.reset_at ? agyResetText(a5).text : ""],
      // 降级时 `quota` 是 null ⇒ 倒计时取上一次读数的周期末（同 GrokCard / OvHeroRO，复查 B4）
      grok: [gRem, gPeriodEnd ? fmtEta(gPeriodEnd) : ""],
    };
    // 候选 = 托盘认得的六家去掉设置里停用的（停用的已被 `applyPlatformPrefs` 移出快照）。快照里还没有的一家照样是候选：
    // 用量记 0（不进排名），额度照读 —— 否则「固定」与「全部 + 未接入的平台」对它静默失效。
    // 这一次没读到、拿的是上一次的读数（agy `last_good` / grok 上一次成功）⇒ 面板上降一级灰
    // agy 的 5h 行是沿用的旧读数（`seen_at`：这次没返回这个桶）⇒ 同样降一级灰（同刘海 / AgyCard，复查 B7）
    const stale: Record<string, boolean> = { agy: agyStale || a5?.seen_at != null, grok: gNow === null && gRem !== null };
    // ★ Codex 也按真实重置时刻藏（全方面评审 §8，三方一致：原来恒 null ⇒ 一律 5 h）；窗口没锚定 ⇒ null ⇒ 5 h
    mainReset.current = { codex: w5?.resetsAtSec ?? null, claude: claude?.fiveH && !claude.fiveH.idle ? claude.fiveH.resetsAt : null,
                          agy: a5?.reset_at ?? null, grok: gPeriodEnd ?? null };
    return TRAY_KEYS.filter((k) => !!traffic?.platforms[k] || !prefs.by[k]?.off).map((k) => {
      const [m, r] = main[k] ?? [null, ""];
      return { key: k, remaining: rem[k] ?? [], ...usageOf(traffic?.platforms[k], cfg.idleDays, now),
               main: m, reset: cfg.idleHoverReset && r && r !== "—" ? `↻ ${r}` : "", stale: !!stale[k] };
    });
  }, [inUse, claude, agyQuota, agyStale, grok, traffic, prefs, cfg.idleDays, cfg.idleHoverReset, tick]);

  // 藏着的（B1）不进托盘、不进面板、不插队；到点自己回来（`tick` 每分钟重算）
  const live = useMemo(() => liveSnoozes(snz, Date.now()), [snz, tick]);
  const shown = useMemo(() => platforms.filter((p) => !(p.key in live)), [platforms, live]);
  const snoozed = useMemo<Snoozed[]>(() => Object.entries(live).sort((a, b) => a[1] - b[1])
    .map(([key, until]) => ({ key, reset: fmtEta(until / 1000) })), [live]);

  // 周额度（格子左上角的「周 N%」小红牌；logo 水位已是 5h）。读不到写 null ⇒ 不报
  const warns = useMemo<IdleWarn[]>(() => {
    const now = Date.now();
    const live = inUse && inUse.status !== "dead" ? inUse : null;
    const cw = live?.windows.find((w) => w.mins === 10080);
    const aw = agyWinRows(agyQuota).find((r) => r.label === "周");
    const on = new Set(shown.map((p) => p.key));
    return weeklyWarns([
      { key: "codex", week: cw?.pct ?? null, reset: cw?.reset ?? "" },
      { key: "claude", week: claudeRem(claude?.week, now), reset: claude?.week?.resetsAt ? fmtEta(claude.week.resetsAt) : "" },
      { key: "agy", week: aw?.remaining ?? null, reset: aw?.reset_at ? agyResetText(aw).text : "" },
      // ★ grok 只有周窗口：格子的大数字就是周 ⇒ 不再在底部重复一条（用户 2026-10-22 截图：0% 的格子 + 一条「周额度剩 0%」）
    ].filter((w) => on.has(w.key)));
  }, [inUse, claude, agyQuota, shown, tick]);

  const panel = useRef<IdlePanelData | null>(null);
  useEffect(() => {
    const un = listen(IDLE_PANEL_WANT, () => { if (panel.current) void emit(IDLE_PANEL_EVENT, panel.current).catch(() => {}); });
    return () => { void un.then((f) => f()); };
  }, []);

  const lastTray = useRef("");
  useEffect(() => {
    // 快照还没到 ⇒ 什么都不定（Rust 先照旧画文字标题）。在这里定下的「今天的常驻」会是空的，而空数组是真值，
    // 快照到了也不会再冻结 ⇒ 一整天都按实时排名换位（三方评审 2026-10-21）。
    if (!traffic) return;
    const now = Date.now();
    const sig = JSON.stringify([cfg.idleSlots, cfg.idleRankBy, cfg.idleDays, cfg.idlePinned]);
    const f = frozen.current;
    const userChanged = !f || f.sig !== sig;
    const keep = userChanged || shouldRerank(f.day, now, !running, near.current) ? undefined : f.keep;
    const slots = pickIdleSlots(shown, { slots: cfg.idleSlots, rankBy: cfg.idleRankBy, pinned: cfg.idlePinned, now, keep });
    const resident = slots.filter((s) => s.kind === "resident").map((s) => s.key);
    // 冻结的常驻只增不换：今天新用了一家、补进了空着的常驻位 ⇒ 记进去（日期不变），之后它也不在白天被挤走
    if (!keep) { frozen.current = { day: dayKey(now), keep: resident, sig }; saveFrozen(frozen.current); }
    // ★ 藏着的那家**留在冻结表里原来的位置**（全方面评审 §8：原来整份换成此刻的常驻，藏到期回来时顺序变了）。
    //   顶上来的那家排在后面；藏着的回来后 `pickIdleSlots` 按冻结表顺序取前两位，它就回到原位。
    else if (resident.some((k) => !keep.includes(k))) {
      frozen.current = { day: f!.day, keep: mergeFrozen(keep, resident, snoozed.map((z) => z.key)), sig };
      saveFrozen(frozen.current);
    }
    // 选「文字标题」时托盘里没有 logo ⇒ 面板没有「菜单栏里的那几家」，按排名排；「只看菜单栏」在这时没有对象 ⇒ 按「用过的」
    const bar = cfg.idleIcons ? slots : [];
    const scope = !cfg.idleIcons && cfg.idleHoverScope === "bar" ? "used" : cfg.idleHoverScope;
    const next: IdlePanelData = {
      cells: panelCells(shown, bar, { scope, max: cfg.idleHoverMax,
                                          showUnconnected: cfg.idleHoverUnconnected, rankBy: cfg.idleRankBy }),
      max: cfg.idleHoverMax,
      warns,
      snoozed,
    };
    // 同一份就不再发：Rust 每收一次都会重画一张 NSImage。`cells` = 面板有几行内容（格子 + 「已隐藏」行；
    // 0 时 Rust 不弹空面板）。★ 「已隐藏」行也算：全藏了以后它是唯一的撤销入口（全方面评审 §8）
    const tray = JSON.stringify({ enabled: cfg.idleIcons, slots: trayPayload(slots), cells: next.cells.length + (next.snoozed?.length ?? 0) });
    if (tray !== lastTray.current) {
      lastTray.current = tray;
      invoke("set_idle_tray", JSON.parse(tray) as Record<string, unknown>).catch(() => { lastTray.current = ""; });
    }
    if (JSON.stringify(next) !== JSON.stringify(panel.current)) {
      panel.current = next;
      void emit(IDLE_PANEL_EVENT, next).catch(() => {});
    }
  }, [shown, cfg, running, traffic, warns, snoozed]);

  // 「上次 AI 活动」= 用量快照里最近一次使用（小时桶末尾，只会偏晚 ⇒ 只会少打招呼）。重启后 Rust 靠它接上
  const lastActive = useMemo(() => {
    const ts = platforms.map((p) => p.lastUsedAt ?? 0);
    const m = ts.length ? Math.max(...ts) : 0;
    return m > 0 ? Math.floor(m / 600_000) * 600 : null;   // 取整到 10 分钟：当前小时内它随 now 走，别每分钟发一次
  }, [platforms]);
  useEffect(() => {
    invoke("set_idle_prefs", { glow: cfg.idleGlow, hello: cfg.idleHello, lastHello: loadHello(), lastActive }).catch(() => {});
  }, [cfg.idleGlow, cfg.idleHello, lastActive]);
}
