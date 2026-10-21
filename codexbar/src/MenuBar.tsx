import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { listen } from "@tauri-apps/api/event";
import { LogicalSize } from "@tauri-apps/api/dpi";
import { THEMES } from "./theme";
import Toast from "./components/Toast";
import AccountRow from "./components/AccountRow";
import GrokRow from "./components/GrokRow";
import AgyRow from "./components/AgyRow";
import ClaudeRow from "./components/mb/ClaudeRow";
import RunStrip from "./components/mb/RunStrip";
import NoticeBar from "./components/mb/NoticeBar";
import ProbeBtn from "./components/mb/ProbeBtn";
import { useTodayTps } from "./components/mb/useTodayTps";
import { mbVars, MONO } from "./components/mb/vars";
import { agyAction, agyShown, agyTightest, agyWinRows, agyResetText } from "./agy";
import PlatformChips, { LOGO_OF, type ChipItem, type MbPlat } from "./components/PlatformChips";
import { useRotationBoard } from "./hooks/useRotationBoard";
import { useAgyPool } from "./hooks/useAgyPool";
import MenuBarToday from "./components/MenuBarToday";
import { useStore } from "./hooks/useStore";
import { useDawnProbe } from "./hooks/useDawnProbe";
import { useTraffic } from "./hooks/useTraffic";
import { useGrokQuota } from "./hooks/useGrokQuota";
import { useAgyQuota } from "./hooks/useAgyQuota";
import { useClaudeQuota } from "./hooks/useClaudeQuota";
import { useLive } from "./hooks/useLive";
import { useIdleTray } from "./hooks/useIdleTray";
import { runningRows, type PlatformKey } from "./live";
import { fmtAgo, fmtEta, cardLeftText } from "./helpers";
import { grokRemPct } from "./grok";
import { usePrivacy } from "./hooks/usePrivacy";
import { useCardBannerDismiss } from "./hooks/useCardBannerDismiss";
import { useIntegration } from "./hooks/useIntegration";
import { presentIntegration } from "./components/IntegrationBanner";
import { todayView, fmtTok, colorOf } from "./traffic";
import {
  SUB_WARN_DAYS, blockTitle, daysUntil, isLow, lowNotice, mergeNotices, nameColWidth, poolDry, poolDryNotice,
  sortByAvailability, subNotice, tightestOf, type Notice, type SortKey,
} from "./mbLogic";
import "./App.css";
import "./menubar.css";

const PANEL_W = 352;          // ★ 三处必须一致，由 tests/test_menubar_width_sync.py 守着
/**
 * 弹窗高度。★★ **规则是「跟今日 Tab 一致」**（用户 2026-09-06），而这条规则的实现
 * 换过一次，换的原因值得记：
 *
 * **v1（2026-09-06 上午）：写死 `PANEL_H_MAX = 580`。**
 * 580 是当时量到的今日 Tab 自然高度。它错在**把一个随数据变化的量写死成了常量** ——
 * 今日页的高度 ≈ 固定头部 + 图例行数 × 35px，而图例只列**今天有流量**的平台。
 * 那天本机有 7 家，今日页恰好 580；用户当晚只剩 4 家，今日页自然高变成 **477**，
 * 而窗口仍被钉在 580 ⇒ **底部 103px 死白**（用户截图，实测 `.mb-root` h=477 vs 窗口 580，
 * 差值与截图里量出的空白逐像素吻合）。
 * ⚠️ 当时的注释甚至预判了「账号很少时会留白」，却**没想到今日页自己也会变矮** ——
 * 因为我是拿"当前这一刻的数据"去标定一个常量的，而那一刻恰好是最高的那种状态。
 *
 * **v2（现在）：高度是量出来的，不是写死的。**
 * 今日 Tab 可见时量它的自然高度 → `setSize` → 记进 localStorage；
 * 账号 Tab 用记住的那个数（它渲染时今日页不存在，量不到），并靠 `--mb-max-h` 钳到同一个值，
 * 超出部分由 `.mb-list` 自己滚。**两个 Tab 仍然等高，切换仍然不跳**，但那个「高」现在
 * 跟着今日页的真实内容走。
 *
 * ★ 为什么以今日页为基准而不是取两页较大值：用户的原话就是「跟 AI 用量的高度一致」；
 *   取较大值会让账号多时又回到 731，正是最初要修的那个问题。
 * ★ 已知取舍：账号池很小时账号页仍会留白。那是「不跳」的代价，而切页跳高是每次都发生的。
 * ★★ **只在今日页有数据时才采信测量**（`today != null`）。数据没到齐时今日页只有
 *   「头部+Tab+摘要」≈190px，量了就会把窗口钉在下限上 —— 那正是 2026-08-22 那个
 *   「重启后弹窗只剩半截」的老 bug 的复活路径。
 * ★ 闸在 `tests/test_menubar_panel_height.py`：两个 Tab 的 setSize 必须相等，且
 *   `ShortTodayLeavesNoDeadSpace` 用 `?plat=few`（4 家平台）专门守这次的死白。
 *   ⚠️ 上一版注释写的是 `tests/test_menubar_tab_heights_match.py`——**那个文件根本不存在**。
 *   一个指向幽灵闸的注释比没有注释更糟：它让人以为这条规则有人守着。
 */
const PANEL_H_MAX = 640;
/** 下限。低于此值 Tab 条 + 摘要 + 底栏就开始互相挤,而那种状态只会出现在数据还没到齐时。 */
const PANEL_H_MIN = 320;
/** 上次量到的「今日」Tab 高度。★ 必须持久化 —— 冷启动停在账号页时那一页量不到。 */
const H_KEY = "codexbar_mb_h";
/** 首次运行、还没量过时用的值。就是 2026-09-06 之前写死的那个常量。 */
const PANEL_H_FALLBACK = 580;

function loadPanelH(): number {
  try {
    const v = Number(localStorage.getItem(H_KEY));
    if (Number.isFinite(v) && v >= PANEL_H_MIN && v <= PANEL_H_MAX) return v;
  } catch { /* ignore */ }
  return PANEL_H_FALLBACK;
}

function loadTheme(): "dark" | "light" {
  try {
    const v = localStorage.getItem("codexbar_theme");
    if (v === "light" || v === "dark") return v;
  } catch { /* ignore */ }
  return "dark";
}

type Tab = "acc" | "today";
const TAB_KEY = "codexbar_mb_tab";
/** 菜单栏停留在哪个平台档。★ 与主窗那份**分开存** —— 两个 webview 是各自的使用场景，
 *  主窗在管 codex 时菜单栏想看 gemini 额度是完全正常的需求。 */
const PLAT_KEY = "codexbar_mb_plat";
function loadPlat(): MbPlat {
  try {
    const v = localStorage.getItem(PLAT_KEY);
    if (v === "gemini" || v === "grok" || v === "codex" || v === "claude") return v;
  } catch { /* 隐私模式下读不了 */ }
  return "codex";
}

/** 交接稿 §3:**记忆上次停留页**,重开弹窗直达。 */
function loadTab(): Tab {
  try { return localStorage.getItem(TAB_KEY) === "today" ? "today" : "acc"; } catch { return "acc"; }
}

/** 在跑条展开与否（交接包 4f：「展开状态记住」）。 */
const STRIP_KEY = "codexbar_mb_strip";
function loadStrip(): boolean {
  try { return localStorage.getItem(STRIP_KEY) === "1"; } catch { return false; }
}

/** 芯片顺序固定 Codex → Claude → Gemini → Grok（交接包「平台顺序与颜色」）。 */
const MB_PLATS: readonly { key: MbPlat; label: string }[] = [
  { key: "codex", label: "Codex" }, { key: "claude", label: "Claude" },
  { key: "gemini", label: "Gemini" }, { key: "grok", label: "Grok" },
];
const MB_PLAT_LABEL: Record<MbPlat, string> = { codex: "Codex", claude: "Claude", gemini: "Gemini", grok: "Grok" };

const IconBolt = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" fill="currentColor" />
  </svg>
);
const IconRefresh = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M20 12a8 8 0 1 1-2.4-5.7M20 4v4.5h-4.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IconEye = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block" }}>
    <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" fill="none" stroke="currentColor" strokeWidth="1.7" />
    <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="1.7" />
  </svg>
);
const IconEyeOff = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true" style={{ display: "block" }}>
    <path d="M9.9 5.8A9.6 9.6 0 0 1 12 5.5c6.7 0 10.4 6.5 10.4 6.5a18 18 0 0 1-3.4 4.2M6.2 7.8A18 18 0 0 0 1.6 12S5.3 18.5 12 18.5c1.6 0 3-.4 4.3-.9M3 3l18 18" />
  </svg>
);
/**
 * ★ 设置用**真齿轮**（ui.md：「侧栏设置用真齿轮，不是 circle + 8 条直射线」）。交接包画板这里画的是
 * 圆 + 8 条射线，在 17px 下与太阳图标分不出 —— 本仓已判过一次，照项目规则偏离画板。
 */
const IconGear = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ display: "block" }}>
    <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
  </svg>
);
const IconWarn = () => <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 1 21h22L12 2zm1 14h-2v2h2v-2zm0-7h-2v5h2V9z"/></svg>;
const IconArrow = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const IconMore = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block" }}>
    <circle cx="5" cy="12" r="1.7" fill="currentColor" /><circle cx="12" cy="12" r="1.7" fill="currentColor" /><circle cx="19" cy="12" r="1.7" fill="currentColor" />
  </svg>
);

export default function MenuBar() {
  const { accounts, currentNode, inUseNode, lastRefreshAt, cardAlert, loadingAction, toast, refresh, run, showToast } = useStore();
  const { visible: bannerVisible, dismiss: bannerDismiss } = useCardBannerDismiss();
  const { integration } = useIntegration();
  const [theme, setTheme] = useState<"dark" | "light">(loadTheme);
  const [tab, setTabState] = useState<Tab>(loadTab);
  const [plat, setPlatState] = useState<MbPlat>(loadPlat);
  const [prevPlat, setPrevPlat] = useState<MbPlat>(plat);
  const [stripOpen, setStripOpen] = useState<boolean>(loadStrip);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const setPlat = useCallback((v: MbPlat) => {
    setPlatState((cur) => { setPrevPlat(cur); return v; });
    setNoticeOpen(false);
    try { localStorage.setItem(PLAT_KEY, v); } catch { /* 隐私模式下写不了 */ }
  }, []);
  const toggleStrip = useCallback(() => {
    setStripOpen((v) => {
      try { localStorage.setItem(STRIP_KEY, v ? "0" : "1"); } catch { /* 隐私模式下写不了 */ }
      return !v;
    });
  }, []);
  const rootRef = useRef<HTMLDivElement>(null);
  const { privacy, toggle: togglePrivacy } = usePrivacy();
  const t = THEMES[theme];
  const isDark = theme === "dark";

  // ★ 日夜切换已移到设置页（交接包 4f：「日夜切换移到设置」）。弹窗只**读** `codexbar_theme`：
  //   另一个 webview 改了它会触发 `storage`；兜底再在每次弹出时重读一次（同源 localStorage 在两个
  //   webview 之间是否推 `storage` 事件没验过，所以不只靠它）。设置页也可以直接发 `theme-changed`。
  useEffect(() => {
    const sync = () => setTheme(loadTheme());
    window.addEventListener("storage", sync);
    const uns = [listen("menubar-shown", sync), listen("theme-changed", sync)];
    return () => { window.removeEventListener("storage", sync); uns.forEach((u) => { void u.then((f) => f()); }); };
  }, []);

  // ★ 清晨探针的**补跑**路径。挂在菜单栏而不是主窗:这个 webview 在 app 启动时创建、
  //   从不卸载,是更稳的宿主。hook 内部还会再核一次窗口标签(见 `useDawnProbe`)。
  useDawnProbe();

  // 交接稿 §5「弹窗只读缓存,不重复解析」。数据与主窗口共用同一份快照和同一条新鲜度规则。
  const { data: traffic, raw: trafficRaw, cacheMode, prefs, busy: trafficBusy, refresh: refreshTraffic, refreshIfStale } =
    useTraffic();
  const today = useMemo(() => todayView(traffic), [traffic]);
  const platColors = useMemo(
    () => Object.fromEntries(Object.keys(traffic?.platforms ?? {}).map((k) => [k, colorOf(traffic, k)])),
    [traffic]);
  const tpsBy = useTodayTps(tab === "today");

  // 在跑条：`read_live` + `tps-live` 推送（与托盘胶囊 / 悬停面板 / 刘海同源同值）。
  const { live } = useLive();
  const running = useMemo(() => runningRows(live), [live]);

  // 空闲托盘（P11）：菜单栏 webview 常驻，由它选 2–3 家交给 Rust 画。Token 数按未重塑的快照算（排名不随缓存口径变）。
  const inUseAcct = useMemo(() => accounts.find((a) => a.aid === inUseNode), [accounts, inUseNode]);
  useIdleTray(inUseAcct, trafficRaw, prefs, running.length > 0);

  // ★ 托盘弹出时按新鲜度重扫。30s 的阈值比定时器的 2 分钟更紧:用户主动点开就是想看现在的数。
  useEffect(() => {
    const un = listen("menubar-shown", () => { refreshIfStale(30_000); });
    return () => { void un.then((f) => f()); };
  }, [refreshIfStale]);

  const setTab = useCallback((v: Tab) => {
    setTabState(v);
    setMenuOpen(false);
    try { localStorage.setItem(TAB_KEY, v); } catch { /* ignore */ }
  }, []);

  /** Reveal the main window and dismiss the popover. */
  const openMain = useCallback(async (navigateTo?: string, payload?: unknown) => {
    try {
      const [{ WebviewWindow }, { emit }] = await Promise.all([
        import("@tauri-apps/api/webviewWindow"),
        import("@tauri-apps/api/event"),
      ]);
      // ★ 走 `set_main_visible` 而不是 `main.show()` —— 那样会绕过程序坞激活策略的同步,
      //   图标就会和窗口状态脱节(关了窗图标还占着位置且点不动)。
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("set_main_visible", { show: true });
      // ★★ **跳转排在居中之前,而且居中单独 catch。**
      //   原来是 `center()` → `emit()` 共用一个 try —— 居中一旦抛异常,跳转**连带被吞掉**,
      //   表现为"点了菜单栏,窗口开了但停在上次那一页",与忘记传事件的症状**一模一样**。
      //   跳转是本质、居中是装饰:本质的先做,且不受装饰的成败影响。
      if (navigateTo) await emit(navigateTo, payload);
      const main = await WebviewWindow.getByLabel("main");
      if (main) {
        try { await main.center(); } catch { /* 居中失败不该影响已发出的跳转 */ }
      }
      getCurrentWindow().hide();
    } catch (e) { console.error(e); }
  }, []);

  /** 点账号行内容 → 工作台 · 总览，定位到该 AI 档（交接包 4f，本轮新增）。键 = 请求账本那套。 */
  const openOverview = useCallback((pf: PlatformKey) => {
    void openMain("open-main-page", { page: "overview", platform: pf });
  }, [openMain]);

  // The panel is content-sized in the design (`height: fit-content`), but a Tauri window has a fixed
  // frame — so measure and follow. Without this the popover keeps a 580px frame and paints dead space
  // below a short pool, or clips a long one.
  // ★★ 2026-08-22:弹窗重启后只显示上半截(实测 412×220 = 恰好 `PANEL_H_MIN`,而内容要 596)。
  //
  // 触发条件是**快照来得晚**:`useTraffic` 异步取快照,数据到达前今日 Tab 只有「头部+Tab+摘要」
  // ≈190px,量出来被钳到 220。平时缓存热、快照 1ms 就到,测量赶在数据之后所以从没暴露;
  // 这次 `PARSER_V` 7→8 让缓存作废,重启后首扫 ~23s,窗口就钉在 220 了。
  //
  // ⚠️ **真因有三种都能解释,我没能区分开**:① RO 压根没触发;② RO 触发了但**隐藏窗口上
  //   `setSize` 失败**(启动时窗口是 `visible(false)` 建的),而失败被 `.catch` 吞掉;③ 只量了一次。
  //   harness 复现出「只有一次 setSize(220)」,但 headless 的渲染管线本身就可能漏发 RO,
  //   所以那不能算判据。**下面两处改动在三种假说下都成立**,不赌其中任何一个。
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    let h = loadPanelH();
    // ★ 把当前高度喂给 CSS,让 `.mb-root` 的 max-height 与 `setSize` 的钳位**同源**。
    //   写死在 CSS 里就成了第二个真源,改一处忘一处 = 裁切或留白。
    el.style.setProperty("--mb-max-h", `${h}px`);
    let last = 0;
    const apply = () => {
      // ★★ **固定高度,不再按各页内容算**(2026-09-06 评审抓出)。
      //    只把上限降到 580 是不够的:`setSize` 仍按**当前那一页**的 scrollHeight 算,
      //    所以两页只是「恰好都顶到上限」才相等。评审用现成的 `plat=demo` 停掉 Kimi,
      //    今日页立刻变成 **545px** 而账号页仍是 580 —— 切 Tab 照样跳,
      //    而我的测试只证明了「默认夹具下恰好相等」。
      //
      //    用户的要求是「跟 AI 用量的高度一致」,而**唯一能保证一致的做法是不让它随内容变**:
      //    另一页没渲染,它的高度量不到,任何「取两页较大值」的方案都得先渲染两页。
      //    两页现在都能内部滚动(`.mb-list` / `.mb-today`),所以固定高度不会藏内容。
      //
      //    ★ 副作用(已知、可接受):账号很少时面板会留白。本机 5 号 + grok + agy 的内容
      //      本来就超过 580,留白只在小池出现;而**切页跳高**是每次都发生的。
      //    ★ 顺带根治了 220 那个老 bug:高度不再依赖「测量时刻内容有没有到齐」。
      //    ★ `PANEL_H_MIN`(=220)**已删**:它存在的意义是「内容还没到齐时别缩成一条缝」,
      //      而固定高度之后不存在这个状态了。留着会是 `noUnusedLocals` 下的死代码 ——
      //      顺带一提,`tsc --noEmit` **不报**这个错,只有 `npm run build`(走 `tsc -b`)才报;
      //      本仓为这条差异栽过,别拿 `--noEmit` 当发版闸。
      // ★★ **今日页是唯一的高度基准,而且必须它有数据时才算数。**
      //    `.mb-root` 在内容装得下时会自己收缩到自然高(实测 4 家平台 = 477),
      //    装不下时被 `--mb-max-h` 钳住、由 `.mb-today` 自己滚 —— 所以
      //    `自然高 = root 当前高 + 今日页溢出的那一截`,两种情形一个式子。
      const inner = el.querySelector<HTMLElement>(".mb-today");
      if (tab === "today" && today && inner) {
        const overflow = Math.max(0, inner.scrollHeight - inner.clientHeight);
        const want = Math.round(el.getBoundingClientRect().height) + overflow;
        const clamped = Math.max(PANEL_H_MIN, Math.min(PANEL_H_MAX, want));
        if (Math.abs(clamped - h) >= 4) {        // 死区:躲开亚像素抖动造成的来回缩放
          h = clamped;
          el.style.setProperty("--mb-max-h", `${h}px`);
          try { localStorage.setItem(H_KEY, String(h)); } catch { /* ignore */ }
        }
      }
      if (Math.abs(h - last) < 2) return;
      // ★ **成功之后才记账**。原来是先 `last = h` 再 `setSize(...).catch(() => {})` ——
      //   一旦这次 setSize 没生效(隐藏窗口/时序),`last` 已经写成新值,而内容之后不再变化
      //   ⇒ RO 不再触发 ⇒ `apply()` 永远不会重跑,高度就**永久**钉在错的值上。
      //   这是「把'我打算做'记成'我已经做到'」——同一类错误在本项目里犯过不止一次。
      getCurrentWindow().setSize(new LogicalSize(PANEL_W, h))
        .then(() => { last = h; })
        .catch(() => { /* 没生效就不记账,下次还会重试 */ });
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    // ★ **弹出时必量一次**。这是唯一能保证窗口可见、且尺寸真正被用户看到的时刻 ——
    //   不依赖 RO 有没有触发、也不依赖隐藏态的 setSize 是否成功。
    //   `menubar-shown` 是 Rust 在 `win.show()` 之后发的(见 lib.rs 的 `toggle_menubar`)。
    const un = listen("menubar-shown", () => { apply(); });
    return () => { ro.disconnect(); void un.then((f) => f()); };
    // ★ 依赖里必须有 `tab` 与 `today`:前者决定这一轮该不该采信测量,
    //   后者是「今日页数据到齐了没」的判据 —— 少了它,快照晚到时这个 effect
    //   不会重跑,窗口就停在冷启动那个高度上(2026-08-22 那个老 bug 的同族路径)。
  }, [tab, today]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.metaKey) return;
      if (e.key === "w") { e.preventDefault(); getCurrentWindow().hide(); }
      if (e.key === "r" && !e.shiftKey) { e.preventDefault(); refresh(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [refresh]);

  // ★ grok **不进** `accounts`/`alive`:那两个数组同时驱动计数徽章、探针全池的号数、
  //   自动切号。混进去会去"切"/"探"一个切不了的东西,且不报错。闸在 tests/test_grok_not_in_pool_ui.py。
  const { snap: grokSnap, busy: grokBusy, refresh: refreshGrok } = useGrokQuota();
  // ★ agy 同样不进 `accounts`/`alive`,理由与 grok 完全一致。
  const { snap: agySnap, busy: agyBusy } = useAgyQuota();
  // ★ agy 账号池。只在 gemini 档打开时才读盘 —— 菜单栏常开，无谓的 IPC 不该常驻。
  // ★★ 「下一个」与总览**同一个真源**（真挑号器的 board），只在账号 Tab + 对应档时启用。
  const { board: mbBoard } = useRotationBoard(tab === "acc" && plat === "codex");
  const agyPool = useAgyPool(tab === "acc" && plat === "gemini", { background: true });
  const { board: mbAgyBoard } = useRotationBoard(tab === "acc" && plat === "gemini",
                                                { source: "agy", dep: agyPool.accounts });
  // ★ Claude 只有「本机」一个号，额度走状态栏转写（PLAN §2.2）。
  const { quota: claudeQuota, refresh: refreshClaude } = useClaudeQuota(tab === "acc" && plat === "claude");

  /** 「按可用排序」（`mbLogic.sortByAvailability`）：低额度置顶 → 在用 → 下一个 → 其余按最紧窗口 → 读不到。 */
  const alive = useMemo(() => sortByAvailability(accounts.filter(a => a.status !== "dead").map((a) => ({
    a, tight: a.tightest >= 0 ? a.tightest : null, inUse: a.aid === inUseNode,
    next: mbBoard?.next?.aid === a.aid && a.aid !== inUseNode,
  }))).map((x) => x.a), [accounts, inUseNode, mbBoard]);
  const dead = accounts.filter(a => a.status === "dead");
  const nowSec = Date.now() / 1000;

  /** Gemini 各号（排序 + 通知条共用一份读数）。 */
  const agyRows = useMemo(() => {
    const out = agyPool.accounts.map((a) => {
      const snap = agyPool.snapshotOf(a, agySnap);
      const q = agyShown(snap)?.quota;
      const tt = agyTightest(q);
      return { a, snap, wins: agyWinRows(q), tight: tt?.b.remaining_percent ?? null,
               inUse: a.sub === agyPool.liveSub, next: mbAgyBoard?.next?.aid === a.sub && a.sub !== agyPool.liveSub };
    });
    return sortByAvailability(out);
  }, [agyPool, agySnap, mbAgyBoard]);

  /** 芯片行的数据。★ 计数一律是**这一档渲染出来几行**。 */
  const chips: ChipItem[] = MB_PLATS.map(p => ({
    ...p,
    count: p.key === "codex" ? alive.length
      : p.key === "gemini" ? Math.max(1, agyPool.accounts.length)
      : 1,
    // 死号红点只有 codex 这一档有数据来源；恒 false 不是偷懒：永远不亮的灯也比来路不明的灯好。
    hasDead: p.key === "codex" && dead.length > 0,
    readOnly: p.key === "grok",
  }));

  const bestPct = alive.reduce((m, a) => Math.max(m, a.tightest), -1);

  /** 这一档的排序键（表头文案 + 池见底判据）。 */
  const sortKeys: SortKey[] = plat === "codex"
    ? alive.map((a) => ({ tight: a.tightest >= 0 ? a.tightest : null, inUse: a.aid === inUseNode, next: false }))
    : plat === "gemini" ? agyRows
    : plat === "claude" ? [{ tight: claudeQuota ? tightestOf([claudeQuota.fiveH?.rem, claudeQuota.week?.rem]) : null, inUse: true, next: false }]
    : [{ tight: grokRemPct(grokSnap?.accounts[0]), inUse: true, next: false }];

  /**
   * 通知条（交接包 4f）：重置卡作废 / 订阅到期 / 池见底 / 低额度 合并成一条，只说当前这一档的事。
   * ★ 重置卡是 **codex** 专属的；挂在别家档上说的是另一家的事。
   */
  const notices: Notice[] = [];
  if (plat === "codex" && cardAlert && bannerVisible(cardAlert)) {
    notices.push({ id: "card", tone: "warn", urgency: cardAlert.cardDays ?? 0, dismissible: true,
                   text: `${cardAlert.node} ${cardAlert.cardsExpiring || 1} 张重置卡 ${cardLeftText(cardAlert.cardDays ?? 0)}后作废` });
  }
  if (plat === "codex") {
    for (const a of alive) {
      for (const w of a.windows) if (isLow(w.pct)) notices.push(lowNotice(a.aid, a.node, w.label, w.pct, w.reset));
      const left = a.expStale ? null : daysUntil(a.exp, Date.now());
      if (left != null && left >= 0 && left <= SUB_WARN_DAYS) notices.push(subNotice(a.aid, a.node, left, a.exp));
    }
  } else if (plat === "gemini") {
    for (const r of agyRows) {
      for (const w of r.wins) {
        if (w.remaining != null && isLow(w.remaining)) {
          notices.push(lowNotice(r.a.sub, r.a.label, w.label, w.remaining, agyResetText(w).text));
        }
      }
    }
  } else if (plat === "claude" && claudeQuota) {
    for (const [w, lb] of [[claudeQuota.fiveH, "5h"], [claudeQuota.week, "周"]] as const) {
      if (w && isLow(w.rem)) notices.push(lowNotice("claude", "Claude", lb, w.rem, w.resetsAt ? fmtEta(w.resetsAt) : null));
    }
  } else if (plat === "grok") {
    const rem = grokRemPct(grokSnap?.accounts[0]);
    if (isLow(rem)) notices.push(lowNotice("grok", "Grok", "周", rem as number, fmtEta(grokSnap?.accounts[0]?.quota?.period_end ?? undefined)));
  }
  if ((plat === "codex" || plat === "gemini") && sortKeys.length > 1 && poolDry(sortKeys)) {
    notices.push(poolDryNotice(MB_PLAT_LABEL[plat]));
  }
  const merged = mergeNotices(notices);
  const dismissNotice = (n: Notice) => { if (n.id === "card" && cardAlert) bannerDismiss(cardAlert); };

  /** 当前这一档上次刷新的时刻（芯片行右侧 `↻ HH:MM`）。 */
  const refreshedAt: number | null = plat === "codex" ? lastRefreshAt ?? null
    : plat === "gemini" ? agyPool.accounts.reduce<number | null>((m, a) => (a.quota_at && (m == null || a.quota_at > m) ? a.quota_at : m), null)
    : plat === "grok" ? grokSnap?.fetched_at ?? null
    : claudeQuota?.capturedAt ?? null;

  /**
   * 「探针」（计费）只对 codex 档、且只在账号 Tab 出现（扣的是 **codex** 的额度：挂在别家档上 =
   * 用户看着别家的行按下去、花的是另一家的钱）。其余档 / 今日 Tab 那一格是「工作台 →」。
   */
  const codexActions = tab === "acc" && plat === "codex";
  /**
   * ★★★ **「刷新全池」必须刷当前这一档，不能永远刷 codex。** 四家的刷新成本都是零消耗：
   *   codex 走官方 usage GET、gemini 走云端 `fetchAvailableModels`、grok 走它的 billing 端点、
   *   Claude 只重读本机的状态栏转写 —— 所以「免费」那个徽章四档都成立。
   */
  const refreshPool = () => {
    if (plat === "gemini") { agyPool.refresh(); showToast("已刷新 Gemini · 免费"); return; }
    if (plat === "grok") { refreshGrok(); showToast("已刷新 Grok · 免费"); return; }
    if (plat === "claude") { refreshClaude(); showToast("已重读 Claude 额度 · 本机"); return; }
    run("refresh-all", ["refresh-all", "--notify"], "已刷新全池");
  };

  /** 底栏「⋯」里的次要动作（交接包 4f：「⋯（检查 token 等）」）。 */
  const actions = [
    ...(plat === "codex" ? [{ id: "health", label: "检查 token", loadingLabel: "检查中…",
        hint: "逐号问服务端 token 是否被作废(零消耗,不刷新 token);发现失效会记录。约 10s",
        action: () => run("health", ["health"], "已检查 token") }] : []),
    // ★ Gemini 有**自己的**检查 token（刷一次 token + 打一次 `fetchAvailableModels`，零消耗）。
    ...(plat === "gemini" ? [{ id: "agy-health", label: "检查 token", loadingLabel: "检查中…",
        hint: "逐号刷一次 token 再打一次云端额度接口，两步都过才算这个号还能用。零消耗",
        action: () => { agyPool.health(); showToast("正在检查 Gemini 各号…"); } }] : []),
    ...(plat === "grok" ? [{ id: "open-grok", label: "打开 Grok 用量详情", loadingLabel: "",
        hint: "grok 是单号只读：没有池可切、也没有可探的号,只有用量与周额度可看",
        action: () => void openMain("navigate-platform", "grok") }] : []),
    { id: "open-traffic", label: "打开 Token 消耗", loadingLabel: "",
      hint: "在主窗口看分平台/分模型明细、切时间段、看费率卡",
      action: () => void openMain("navigate-traffic") },
  ];

  const headerRun = running.length;
  const accCount = String(chips.reduce((n, c) => n + c.count, 0));
  const dir = MB_PLATS.findIndex((p) => p.key === plat) < MB_PLATS.findIndex((p) => p.key === prevPlat) ? -1 : 1;
  const nameW = nameColWidth(plat === "codex" ? alive.map((a) => a.node)
    : plat === "gemini" ? agyRows.map((r) => r.a.label) : plat === "claude" ? ["本机"] : ["grok"]);
  const blockHead = plat === "grok" ? "当前号 · 只读" : plat === "claude" ? "本机 · 状态栏转写" : blockTitle(sortKeys);
  const refreshing = loadingAction === "refresh-all";

  return (
    <div ref={rootRef} className={`mb-root ${isDark ? "th-dark" : "th-light"}`}
         style={{ ...mbVars(isDark), background: "var(--pop)", color: "var(--tx)", border: "1px solid var(--line2)" }}>

      {/* 头部 46：⚡ CodexBar · N 在跑 / 空闲 · 隐私 · 设置（日夜切换已移到设置页） */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: 46,
                    padding: "0 10px 0 14px", flexShrink: 0 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8, whiteSpace: "nowrap" }}>
          <span style={{ color: "var(--acc)" }}><IconBolt /></span>
          <span style={{ fontSize: 15, fontWeight: 600 }}>AICoop</span>
          <span data-mb-status={headerRun ? "running" : "idle"}
                style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12,
                         color: headerRun ? "var(--acc)" : "var(--tx3)", transition: "color 300ms" }}>
            <i style={{ display: "block", width: 6, height: 6, borderRadius: 3,
                        background: headerRun ? "var(--acc)" : "var(--tx3)", transition: "background 300ms" }} />
            {headerRun ? `${headerRun} 在跑` : "空闲"}
          </span>
        </span>
        <span style={{ display: "flex", gap: 2, color: "var(--tx2)" }}>
          <span className="mb-hbtn" onClick={togglePrivacy}
                title={privacy ? "打码中 — 邮箱已遮蔽,可安全截图。点击恢复" : "打码:遮蔽邮箱,方便截图分享"}
                style={{ color: privacy ? "var(--acc)" : undefined }}>
            {privacy ? <IconEyeOff /> : <IconEye />}
          </span>
          <span className="mb-hbtn" onClick={() => void openMain("navigate-settings")} title="设置（日夜切换在这里）">
            <IconGear />
          </span>
        </span>
      </div>

      <RunStrip rows={running} todayTokens={live?.today.tokens ?? null}
                open={stripOpen} onToggle={toggleStrip} isDark={isDark} />

      {/* Tab 32：账号 N / 今日 415M；选中底块横滑 380 ms 临界阻尼 */}
      <div style={{ position: "relative", display: "flex", height: 32, margin: "8px 12px 0", padding: 3,
                    boxSizing: "border-box", borderRadius: 10, background: "var(--seg)", border: "1px solid var(--line)",
                    flexShrink: 0 }}>
        <i className="mb-tab-pill" style={{ position: "absolute", top: 3, bottom: 3, left: 3, width: "calc(50% - 3px)",
                    borderRadius: 8, background: "var(--acc)", transform: `translateX(${tab === "acc" ? "0%" : "100%"})`,
                    transition: "transform 380ms var(--sp)" }} />
        {([
          // ★★ 这个数是**全部平台的总数**（用户 2026-09-14：「账号 6 应该要改为账号 9」）。
          ["acc", "账号", accCount],
          ["today", "今日", today ? fmtTok(today.totalTok) : "—"],
        ] as [Tab, string, string][]).map(([id, label, val]) => (
          <button key={id} type="button" data-mb-tab={id} onClick={() => setTab(id)}
                  style={{ position: "relative", flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
                           gap: 6, border: 0, background: "transparent", cursor: "pointer", fontFamily: "inherit",
                           fontSize: 13, fontWeight: 600, whiteSpace: "nowrap",
                           color: tab === id ? "var(--accTx)" : "var(--tx2)", transition: "color 250ms" }}>
            {label}<span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 11.5, opacity: .85 }}>{val}</span>
          </button>
        ))}
      </div>

      {tab === "today" ? (
        <div className="mb-pane" style={{ marginTop: 4 }}>
          <MenuBarToday view={today} colors={platColors} cacheMode={cacheMode} isDark={isDark} tpsBy={tpsBy}
                        refreshedAt={traffic?.generated_at ?? null}
                        busy={trafficBusy} onRefresh={refreshTraffic}
                        onOpenPlatform={(k) => void openMain("navigate-platform", k)}
                        onOpenOverview={() => void openMain("navigate-traffic")} />
        </div>
      ) : (
      <div className="mb-pane mb-slide" style={{ marginTop: 4, ["--dx" as string]: "-28px" }}>
      {/* 平台芯片 28：Codex · Claude · Gemini · Grok🔒（官方 logo + 号数）；右侧 ↻ 这一档上次刷新的时刻 */}
      <PlatformChips isDark={isDark} cur={plat} on={setPlat} items={chips}
                     right={refreshedAt
                       // ★ 只画时刻；平台名与「N 分钟前」进 title（352px 的一行放不下）。
                       ? <span title={`${MB_PLAT_LABEL[plat]} · 上次刷新 ${fmtAgo(refreshedAt)}`}>
                           ↻ {new Date(refreshedAt * 1000).toTimeString().slice(0, 5)}
                         </span>
                       : <span title={`${MB_PLAT_LABEL[plat]} · 还没刷新过`}>↻ —</span>} />

      {/* 接入闸 —— **不可关**，且不并进通知条。
          ★ 与通知条的区别正是「该不该能关 / 能不能截短」：「这台机器没接上轮换」**不会自己好**，
            而它的下一步动作是一整句话，压进 32px 的单行会被省略号切掉 —— 本仓披露铁律要求告警必须说下一步。
          ★ 只挂 codex 档：gemini/grok 的接入机制完全不同，这道闸判不了它们。 */}
      {plat === "codex" && (() => {
        const p = presentIntegration(integration);
        if (!p) return null;
        const canConnect = integration?.state === "not_installed"
                        || integration?.state === "broken";
        return (
          <div className="mb-banner mb-banner-slim mb-banner-wrap"
               style={{ background: `${p.color}1a`, border: `1px solid ${p.color}73`, margin: "0 12px 8px",
                        cursor: canConnect ? "pointer" : "default" }}
               onClick={canConnect ? () => void openMain("navigate-settings") : undefined}
               title={canConnect
                 ? `${integration?.lines.join("\n")}\n\n点一下打开设置页的「账号池接入」`
                 : integration?.lines.join("\n")}>
            <span className="mb-banner-icon" style={{ color: p.color }}><IconWarn /></span>
            <div className="mb-banner-body">
              <div className="mb-banner-title" style={{ color: p.color }}>{p.badge}</div>
              <div className="mb-banner-sub" style={{ color: t.text2 }}>{p.text}</div>
            </div>
          </div>
        );
      })()}

      {/* 点行内容 = 跳工作台总览对应 AI 档；悬停最右列长出的「切换」= 直接换号,不开主窗口 */}
      <div className="mb-list">
        <div key={plat} className="mb-slide" style={{ ["--dx" as string]: `${dir * 24}px`, display: "flex",
                                                      flexDirection: "column", gap: 8 }}>
        {merged.head && <NoticeBar head={merged.head} rest={merged.rest} open={noticeOpen}
                                   onToggle={() => setNoticeOpen((v) => !v)} onDismiss={dismissNotice} />}
        <div data-mb-block={plat} style={{ ["--nameW" as string]: `${nameW}px`, borderRadius: 12, background: "var(--card)",
                      border: "1px solid var(--line)", overflow: "hidden", flexShrink: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", height: 26, padding: "0 12px",
                        fontSize: 10.5, color: "var(--tx3)", whiteSpace: "nowrap" }}>
            <span>{blockHead}</span><span>5h · 周 · ↻ 回满</span>
          </div>
        {/* ★★ 一档一份列表。四家的账号语义根本不同（逐请求换号 / 只读本机 / 启动前换凭证 / 单号只读）。 */}
        {plat === "codex" && alive.map(a => (
          /* ★★ 「在用」跟着**代理**走（`last_aid`），不跟 `active`（上次 CLI 切换）。
             「下一个」与「在用」是同一个号时只标「在用」。 */
          <AccountRow key={a.aid} a={a} isCurrent={a.aid === inUseNode}
            isBest={mbBoard?.next?.aid === a.aid && a.aid !== inUseNode}
            bestPct={bestPct} isDark={isDark} onSelect={() => openOverview("codex")}
            // 当前号 / 在用的号不给按钮（交接包：在用的号只提亮不出按钮；切到自己是空操作）。
            onSwitch={a.aid === currentNode || a.aid === inUseNode ? undefined
              : () => run(`switch-${a.aid}`, ["switch", a.node], `已切到 ${a.node}`)}
            switching={loadingAction === `switch-${a.aid}`} />
        ))}

        {/* Gemini：一号一行、可切换（用户 2026-09-13：「可以切号的，按照目前 codex 的方式」）。 */}
        {plat === "gemini" && (agyPool.accounts.length > 0
          ? agyRows.map(({ a }) => (
              <AgyRow key={a.sub} t={t}
                      snap={agyPool.snapshotOf(a, agySnap)} label={a.label}
                      action={agyAction(a.quota_err_reason, a.quota_err_url)}
                      plan={a.plan}
                      isCurrent={a.sub === agyPool.liveSub}
                      isBest={mbAgyBoard?.next?.aid === a.sub && a.sub !== agyPool.liveSub}
                      onSwitch={a.sub === agyPool.liveSub ? undefined
                        : () => { agyPool.switchTo(a.label);
                                  showToast(`已切到 ${a.label} · 下次启动 agy 生效`); }}
                      switching={agyPool.switching === a.label}
                      disabled={!!prefs.by?.agy?.off} busy={agyBusy}
                      onOpen={() => openOverview("agy")} />
            ))
          // 池还没建起来 —— 退回只读的那一行（`agy-rotate login --current` 之前就是这个状态）
          : <AgyRow t={t} disabled={!!prefs.by?.agy?.off}
                    snap={agySnap} busy={agyBusy}
                    onOpen={() => openOverview("agy")} />)}

        {/* Grok：只读，无「切换」。 */}
        {plat === "grok" && (
          <GrokRow t={t} snap={grokSnap} disabled={!!prefs.by?.grok?.off} busy={grokBusy}
                   onOpen={() => openOverview("grok")} />
        )}

        {/* Claude：一个号「本机」，不出「切换」（PLAN §4 偏离：没有 Claude 账号池后端）。 */}
        {plat === "claude" && (
          <ClaudeRow quota={claudeQuota} isDark={isDark} nowSec={nowSec} onOpen={() => openOverview("claude")} />
        )}
        </div>

        {plat === "codex" && dead.length > 0 && (
          <details className="mb-dead-fold">
            <summary className="mb-dead-summary" style={{ color: "var(--tx3)" }}>
              <span className="mb-dead-dot" style={{ background: "var(--bad)" }} />
              {dead.length} 个失效账号
              <span className="mb-dead-chevron">▸</span>
            </summary>
            <div style={{ ["--nameW" as string]: `${nameW}px`, borderRadius: 12, background: "var(--card)",
                          border: "1px solid var(--line)", overflow: "hidden" }}>
              {dead.map(a => (
                <AccountRow key={a.aid} a={a} isCurrent={a.aid === inUseNode} isBest={false} bestPct={bestPct} isDark={isDark} onSelect={() => openOverview("codex")} />
              ))}
            </div>
          </details>
        )}
        </div>
      </div>
      </div>
      )}

      {/* 底栏：刷新全池（免费）· 探针（计费，点一下就执行）/ 工作台 → · ⋯ */}
      <div className="mb-actions" style={{ position: "relative", display: "flex", gap: 8, padding: "10px 12px",
                                           borderTop: "1px solid var(--line)", flexShrink: 0 }}>
        <span className="mb-foot-btn" data-mb-refresh="" onClick={refreshing ? undefined : refreshPool}
              title={plat === "codex" ? "读取 Codex 官方额度接口(GET),不消耗额度"
                : plat === "gemini" ? "按账号读云端额度(fetchAvailableModels),零消耗"
                : plat === "claude" ? "重读本机的 Claude 状态栏转写,不联网"
                : "读 grok 的账单接口,零消耗"}
              style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 7,
                       height: 34, borderRadius: 9, background: "var(--acc)", color: "var(--accTx)", fontSize: 13,
                       fontWeight: 600, opacity: refreshing ? .75 : 1 }}>
          {refreshing ? <><span className="mb-spinner" />刷新中…</> : <>
            <IconRefresh />刷新全池
            <span style={{ fontSize: 10.5, padding: "0 5px", borderRadius: 4, background: "rgba(0,0,0,.14)" }}>免费</span>
          </>}
        </span>
        <span style={{ position: "relative", width: 132, height: 34, flexShrink: 0 }}>
          {/* ★★★ 探针扣的是 **codex** 的额度。只在 codex 档的账号 Tab 出现。 */}
          {codexActions && <ProbeBtn
            hint={`对 ${alive.length} 个号各发一次真实补全(问 hi 要求答 ok),证明"真的还能干活"——token 有效但订阅到期/模型权限被撤/被限流,只有这个测得出来。⚠️ 消耗周额度(实测单次 <1%)`}
            loading={loadingAction === "probe-all"}
            onFire={() => run("probe-all", ["probe", "--all"], "探针 全池")} />}
          {!codexActions && (
            <span className="mb-foot-btn" data-mb-workbench=""
                  onClick={() => tab === "today" ? void openMain("navigate-traffic") : openOverview(LOGO_OF[plat])}
                  title={tab === "today" ? "打开工作台 · Token 消耗" : `打开工作台 · 总览的 ${MB_PLAT_LABEL[plat]} 档`}
                  style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
                           gap: 6, borderRadius: 9, border: "1px solid var(--line2)", color: "var(--tx)", fontSize: 13,
                           fontWeight: 500 }}>
              工作台<IconArrow />
            </span>
          )}
        </span>
        <span className="mb-foot-btn" data-mb-more="" onClick={() => setMenuOpen((v) => !v)} title="更多操作"
              style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 34, height: 34,
                       borderRadius: 9, border: "1px solid var(--line2)", color: "var(--tx2)", flexShrink: 0,
                       background: menuOpen ? "var(--hov2)" : "transparent" }}>
          <IconMore />
        </span>
        {/* ⋯ 菜单：一直在 DOM 里，只靠可见性开合（ui.md §5c）。 */}
        <div data-mb-menu={menuOpen ? "open" : "closed"}
             style={{ position: "absolute", right: 12, bottom: 52, minWidth: 168, padding: 4, borderRadius: 10,
                      background: "var(--pop)", border: "1px solid var(--line2)", boxShadow: "var(--shadow)", zIndex: 40,
                      opacity: menuOpen ? 1 : 0, transform: `translateY(${menuOpen ? 0 : 6}px)`,
                      pointerEvents: menuOpen ? "auto" : "none", transition: "opacity 160ms, transform 220ms var(--sp)" }}>
          {actions.map((btn) => {
            const isLoading = !!btn.loadingLabel && loadingAction === btn.id;
            return (
              <div key={btn.id} className="mb-menu-item" title={btn.hint}
                   onClick={isLoading ? undefined : () => { setMenuOpen(false); btn.action(); }}
                   style={{ color: "var(--tx)", opacity: isLoading ? .6 : 1 }}>
                {isLoading ? <><span className="mb-spinner" />{btn.loadingLabel}</> : btn.label}
              </div>
            );
          })}
        </div>
      </div>

      {toast && <Toast msg={toast} t={t} />}
    </div>
  );
}

