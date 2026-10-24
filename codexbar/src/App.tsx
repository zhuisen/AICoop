import { useState, useMemo, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { isWindowsUI } from "./helpers";
import { THEMES } from "./theme";
import ToastStack from "./components/ToastStack";
import type { AccountDetail } from "./components/AccountTech";
import LogsPage from "./pages/LogsPage";
import RelayPage from "./pages/RelayPage";
import TrafficPage from "./pages/TrafficPage";
import PlatformPage from "./pages/PlatformPage";
import RequestsPage, { type ReqNav } from "./pages/RequestsPage";
import type { RangeState } from "./traffic";
import { colorOf, daysNeeded, DEFAULT_RANGE, todayOf, singleDayOf, hoursOfDay } from "./traffic";
import SettingsPage, { getSettings, loadTheme, patchSettings, saveTheme, TRAY_STYLES, type ThemeName } from "./pages/SettingsPage";
import { useStore } from "./hooks/useStore";
import { useExpiryWatch } from "./hooks/useExpiryWatch";
import { useDeadWatch } from "./hooks/useDeadWatch";
import { useAutoSwitch } from "./hooks/useAutoSwitch";
import { useKeyboard } from "./hooks/useKeyboard";
import { fullVersion } from "./helpers";
import { usePrivacy } from "./hooks/usePrivacy";
import { useTraffic } from "./hooks/useTraffic";
import { useGrokQuota } from "./hooks/useGrokQuota";
import { useAgyQuota } from "./hooks/useAgyQuota";
import { useIntegration } from "./hooks/useIntegration";
import { useCardOrder } from "./hooks/useCardOrder";
import { useCardDrag } from "./hooks/useCardDrag";
import { useRotationBoard } from "./hooks/useRotationBoard";
import { landingProvider, loadPoolKey, poolKeyAt, savePoolKey, type PoolKey } from "./platforms";
import { notify } from "./hooks/useNotify";
import { SURFACE_NOTICE_BODY, SURFACE_NOTICE_TITLE } from "./notchSegs";
import { useAgyPool } from "./hooks/useAgyPool";
import Overview from "./components/ov/Overview";
import { useLive } from "./hooks/useLive";
import { useClaudeQuota } from "./hooks/useClaudeQuota";
import { NavRail, type NavPage } from "./components/NavRail";
import WindowGrip from "./components/WindowGrip";
import { isBlankHeader } from "./windowDrag";
import "./App.css";

// 平台详情页不进导航栏,只能从流量总览钻取(图例行 / 卡片「明细→」/ 点图层),用户定稿 2026-08-09。
type Page = NavPage;

const IconEye = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><path d="M1.6 12S5.3 5.5 12 5.5 22.4 12 22.4 12 18.7 18.5 12 18.5 1.6 12 1.6 12z"/><circle cx="12" cy="12" r="3"/></svg>;
const IconEyeOff = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><path d="M9.9 5.8A9.6 9.6 0 0 1 12 5.5c6.7 0 10.4 6.5 10.4 6.5a18 18 0 0 1-3.4 4.2M6.2 7.8A18 18 0 0 0 1.6 12S5.3 18.5 12 18.5c1.6 0 3-.4 4.3-.9M3 3l18 18"/></svg>;


export default function App() {
  const { state, accounts, currentNode, inUseNode, tokens, lastRefreshAt, freshness, loadingAction, toasts, dismissToast, holdToasts, refresh, run, showToast, pendingDel, deferDelete } = useStore();
  // ★ 主题真源 = localStorage `codexbar_theme`（设置页写 + 广播 `theme-changed`；菜单栏弹窗 / 悬停面板读同一个键）。
  const [theme, setTheme] = useState<ThemeName>(loadTheme);
  const changeTheme = (v: ThemeName) => { setTheme(v); saveTheme(v); };
  useEffect(() => {
    const un = listen("theme-changed", () => setTheme(loadTheme()));
    return () => { void un.then((f) => f()); };
  }, []);
  // 版本号运行期从 tauri 取,别再写死(发版时漏改前端字符串是老毛病)
  const [ver, setVer] = useState("");
  // ★ 版本一律走 `fullVersion()`（`X.Y.Z+B`），两个显示位同一个真源。
  useEffect(() => { void fullVersion().then(setVer).catch(() => {}); }, []);
  const [page, setPage] = useState<Page>("overview");
  /** 「请求页 →」带来的平台筛选（`open-main-page`）。`n` 每次加一，同一平台连点两次也会生效。 */
  const [reqNav, setReqNav] = useState<ReqNav>({ platform: null, n: 0 });
  /** 收到过几次 `main-open-page`（根节点 `data-nav-count`）—— 「一次点击只跳一回」的闸靠它数。 */
  const [navN, setNavN] = useState(0);
  // 接入闸：真源是 `codex-rotate integration`，与 `health` 共用同一个判定函数。
  const { integration } = useIntegration();
  // 卡片自定义顺序（拖拽排序）。★ 走 localStorage + Tauri 广播，主窗与菜单栏不分叉。
  const { order: cardOrder, setOrderFor } = useCardOrder();
  // 拖拽手感层全在这个 hook 里，见其 docstring。★ 这里**没有** rAF 节流、也没有 FLIP：
  // 拖拽期间 DOM 顺序不动，让位交给 CSS `transition: transform`，每次 pointermove 直接写样式。
  const { preview, makeDrag } = useCardDrag();
  // ★ 只在总览页取：它读的是本机文件，但没必要在别的页上跟着 state 变化重算。
  // ⚠️ 原来这里还有一个 `armedAid`：按下手柄→setState→打开卡片根节点的 `draggable`。
  //    **在 WKWebView 上根本起不来**（WebKit 在 mousedown 那一刻就判定能不能拖，
  //    React 的 setState 追不上）。现在手柄自己恒为 draggable，这个状态随之删除。
  /** 时间范围（交接稿 §7 的 `RangeState`）。★ **默认 30d**（v1.5 是 14d）。
   *  总览与平台详情**共用这一份** —— 钻进详情再返回不该把档位重置。 */
  const [trafficSt, setTrafficSt] = useState<RangeState>(DEFAULT_RANGE);
  /** 总览当前看哪一家。★ 记进 localStorage：切到别的页再回来不该跳回第一档 ——
   *  这一档是"我在管哪一家账号"，不是一次性的筛选。 */
  /** 总览当前看哪一家。★ 记进 localStorage：切到别的页再回来不该跳回第一档 ——
   *  这一档是"我在管哪一家账号"，不是一次性的筛选。
   *  ★ 平台清单与菜单栏芯片行**同一份** `POOL_PLATFORMS`（v4 稿 §9.1）。 */
  const [provider, setProvider] = useState<PoolKey>(loadPoolKey);

  // ★ 启用条件必须与**渲染条件**一致（`provider === "codex"`）。此前只看 page ⇒
  //   停在总览的 Gemini/Grok 档时，这条 codex 专属查询照样每次事件都 spawn 一个 python，
  //   而画面上一个像素都不会用到它（codex 评审 2026-09-21 指出）。
  const { board, err: boardErr } = useRotationBoard(page === "overview" && provider === "codex");
  useEffect(() => { savePoolKey(provider); }, [provider]);

  const [drill, setDrill] = useState<string | null>(null);   // 平台详情:null = 停在总览
  const [autoSwitch, setAutoSwitch] = useState(() => getSettings().autoSwitchEnabled);
  const { privacy, toggle: togglePrivacy } = usePrivacy();

  const t = THEMES[theme];
  const win = useMemo(() => getCurrentWindow(), []);
  // 平台判定只影响窗口控制的位置与形状,不影响任何数据逻辑。
  const winUI = useMemo(() => isWindowsUI(), []);

  // ★ Dock 显示开关在 localStorage,Rust 侧读不到 —— 每次启动由主窗口 webview 应用一次,
  //   否则重启后 Dock 图标会消失(设置还开着,行为却回到纯菜单栏)。
  useEffect(() => {
    const st = getSettings();
    invoke("set_dock_visible", { on: st.dockVisible }).catch(() => {});
    // 刘海额度条同理（默认关；关着时这句什么都不建）。
    // ★ 升级提示（samchen #5 ③，用户选「保持刘海屏 + 提示一次」）：v2.1.2 起「刘海屏」= 托盘藏起来，
    //   原来开着「刘海屏版本」的人升级后图标会直接消失。刘海真的显示出来（`active`）且没说过 ⇒ 发一次系统通知；
    //   没有通知权限发不出去 ⇒ 打开主窗口停在设置页，当面说（不然图标没了、也没人告诉他去哪找）。
    if (st.notchHud) invoke<{ active?: boolean }>("set_notch_hud", { on: true }).then((r) => {
      if (!r?.active || st.surfaceNoticed) return;
      patchSettings({ surfaceNoticed: true });
      void notify(SURFACE_NOTICE_TITLE, SURFACE_NOTICE_BODY).then((sent) => {
        if (!sent) { setPage("settings"); void invoke("set_main_visible", { show: true }); }
      });
    }).catch(() => {});
    // 「在跑时显示 t/s」同理：Rust 的 `tray_pill::ENABLED` 默认关、进程内 atomic，默认开要靠这一句。
    invoke("set_tps_tray", { enabled: st.tpsTray }).catch(() => {});
    // 「数字滚动」同理：Rust 默认开，关掉的人重启后要再告诉它一次
    invoke("set_number_roll", { on: st.numberRoll !== false }).catch(() => {});
    // 菜单栏标题样式同理:Rust 侧的 TRAY_STYLE 是进程内 atomic,重启就回默认,
    // 得由主窗口 webview 每次启动重新告诉它一次。
    invoke("set_tray_style", { style: TRAY_STYLES.indexOf(st.trayStyle) }).catch(() => {});
  }, []);

  // menubar → 主窗口的三个跳转入口。齿轮=设置;今日 Tab 底栏=流量总览;点平台图例行=该平台详情。
  useEffect(() => {
    const uns = [
      listen("navigate-settings", () => { setPage("settings"); void invoke("set_main_visible", { show: true }); }),
      listen("navigate-traffic", () => { setDrill(null); setPage("traffic"); void invoke("set_main_visible", { show: true }); }),
      listen<string>("navigate-platform", (e) => {
        setDrill(e.payload); setPage("traffic"); void invoke("set_main_visible", { show: true });
      }),
      // ★ 交接包 2026-10-19 的统一跳转（PLAN §2.3）：悬停面板 / 刘海卡片 / 菜单栏弹窗都发 `open-main-page`，
      //   Rust 把它转成 **`main-open-page` 只发给主窗口**（lib.rs）。★★ 这里**只听** `main-open-page`：
      //   发送方用全局 `emit` 时主窗口自己也会收到一份 `open-main-page`，两个都听 = 一次点击跳两回
      //   （请求页的 `reqNav.n` 会加 2）。闸 `tests/test_overview_5b.py::NavigationArrivesOnce`。
      //   payload `{page, platform}`；platform 用请求账本的键（codex/claude/agy/grok）。
      //   ★ 菜单栏账号行点击（原 `navigate-overview`）也走这条，停在那一行所属的平台档 —— 旧事件已无人发，监听一并删掉。
      // ★ `fresh`（Rust 带）= 主窗口这次是从隐藏 ≥ 1 分钟后打开的；`page` 为空 = 只是显示窗口（Dock / 菜单栏「打开工作台」等），
      //   不切页，只按 `landingProvider` 把总览档放回默认（用户 2026-10-24「默认还是跳到 gemini」）。
      listen<{ page?: string | null; platform?: string | null; fresh?: boolean }>("main-open-page", (e) => {
        const pg = e.payload?.page, pf = e.payload?.platform ?? null, fresh = !!e.payload?.fresh;
        const pk0 = pf === "agy" ? "gemini" : pf;
        const named: PoolKey | null = pk0 === "codex" || pk0 === "claude" || pk0 === "gemini" || pk0 === "grok" ? pk0 : null;
        // 总览档：点名的平台只对总览生效；新的一次打开不论去哪一页都把档放回默认（下次进总览不再停在旧档）
        const ovNamed = pg === "overview" ? named : null;
        if (fresh || ovNamed) setProvider((cur) => landingProvider(cur, ovNamed, fresh));
        if (pg == null) return;
        setNavN((n) => n + 1);
        const reqPf = pf === "codex" || pf === "claude" || pf === "agy" || pf === "grok" ? pf : null;
        if (pg === "requests") {
          setPage("requests"); setReqNav((v) => ({ platform: reqPf, n: v.n + 1 }));
        } else if (pg === "traffic") {
          // 用量详情认任何平台键（空闲额度格子里的 Kimi / DeepSeek 没有总览档，点了来这里）
          setDrill(pf); setPage("traffic");
        } else if (pg === "overview") {
          setDrill(null); setPage("overview");
        } else return;
        void invoke("set_main_visible", { show: true });
      }),
    ];
    return () => { uns.forEach((u) => { void u.then((f) => f()); }); };
  }, [win]);

  useExpiryWatch(accounts, tokens);
  // Dead-account alerts live in the MAIN window only — the menubar popover renders the same store, so
  // running the watcher in both would double-notify.
  useDeadWatch(accounts, currentNode);
  useAutoSwitch(accounts, currentNode, run);
  // ★★ 总览上 ⌘1/⌘2/⌘3/⌘4 = 切到 Codex / Claude / Gemini / Grok 档（用户 2026-10-16：「command+数字是切换
  //   codex、gemini、grok，而不是切换对应的账号」）。序号与 Tab 显示顺序同源（`POOL_PLATFORMS`）。
  //   ⚠️ 这条**取代**了 2026-09-14 / 09-19 的「⌘N 切第 N 张卡」—— 切号仍走卡片上的「切换」。
  //   别的页面没有档位 Tab，⌘N 什么也不做（原来在任何页都会切 codex 号，看不见、却在换计费账号）。
  useKeyboard(win, refresh, setPage as (p: string) => void, (idx) => {
    if (page !== "overview") return;
    const k = poolKeyAt(idx);
    if (k) setProvider(k);
  });

  // ★ 一次取满最大窗口(90d),换档位纯前端切片。scan.py 内部恒扫 max(days,90),所以五个档位的
  //   底层数据本就一样;每换一档重调一次 IPC 等于白付一次全量扫描。
  //   进页面才取,不在启动时取 —— 账号池才是启动要的东西。
  //   取数走 `useTraffic`:先画上次的快照(一次文件读),再后台重扫,所以进页面不再有那 1~4 秒白屏。
  // ★ 窗口由档位 + 环比开关决定（环比要往回多取一个等长周期），并**量化到档**（见 `daysNeeded`）。
  //   ★ 这里刻意用**挂钟**而不是 `todayOf(traffic)`：后者要等数据到位，而窗口决定的正是
  //     "去读哪一份数据"，循环依赖。差一天不会改变结果 —— 档位是 90/365/1095 三档，
  //     只有恰好卡在档界上时才可能差一档，而那时下一次保鲜检查就会纠正过来。
  //     **显示**一律用 `todayOf(data)`（桶按本地日切，挂钟在午夜前后会差一天）。
  // agy 账号池。★ 只在总览的 Google 档才读 —— 与 grok 额度同一条纪律：
  //   不是每个页面都需要它，而"顺手读一下"会变成"每次开 app 都读"。
  const agyPool = useAgyPool(page === "overview" && provider === "gemini");
  // ★ 与 codex 档同一块续航条、同一个板子形状；数据走只读 IPC `read_agy_board`。
  //   `dep` = 池数据：置顶 / 切号 / 停用之后据此重读（agy 那边没有 `state-changed`）。
  const { board: agyBoard, err: agyBoardErr } = useRotationBoard(
    page === "overview" && provider === "gemini", { source: "agy", dep: agyPool.accounts });

  // 代理轮换页的泳道顺序 = 池顺序（AICoop P7「顺序固定」），胶囊上的账号数也用它。
  const rotPools = useMemo(() => ({ codex: accounts.map((a) => a.node), agy: agyPool.accounts.map((a) => a.label) }),
                           [accounts, agyPool.accounts]);
  const trafficDays = daysNeeded(trafficSt, todayOf(null));
  const { data: traffic, raw: trafficRaw, cacheMode, prefs: platPrefs, busy: trafficBusy,
          err: trafficErr, refresh: refreshTraffic, requestHoursFor } = useTraffic({
            enabled: page === "traffic",
            // ★ 窗口由当前档位决定,且**量化到档**(90/365/1095) —— 见 `daysNeeded`。
            //   默认档原样返回 90,所以常用路径的行为一个字都没变。
            days: trafficDays });
  /**
   * ★★ 选中**单独一天**而快照里没有那天的逐小时桶 ⇒ 现补一次（用户 2026-09-15 选的方案）。
   *
   * `scan.py` 只对最近 30 天留小时桶（全部 1095 天都留会把快照从 1.1 MB 撑到约 37 MB，
   * 而它每次扫描都重写）。更早的某一天点进来时，这里发一次 `--hours-day`。
   * ★ 判据是「**一个平台都没有**那天的小时桶」——只要有一个有，就说明那天在窗口内，
   *   某些平台那天没数据是真话，不该为此重扫。
   * ★ 去重在 `requestHoursFor` 里（`askedHours`），所以这个 effect 每次渲染跑也无害。
   */
  useEffect(() => {
    if (page !== "traffic" || !traffic) return;
    const day = singleDayOf(trafficSt, todayOf(traffic));
    if (!day) return;
    const anyHours = Object.values(traffic.platforms)
      .some((p) => hoursOfDay(p, day) !== null);
    if (!anyHours) requestHoursFor(day);
  }, [page, traffic, trafficSt, requestHoursFor]);

  /**
   * ★ 这是全 app 唯一一条会**主动联网**的数据路径(`useTraffic` 扫的是本机盘,零消耗不联网),
   *   所以 `enabled` 是白名单不是黑名单:**只有这两个页面**要看 grok 额度。
   *   **只有总览**(用户 2026-08-24 两次定稿:先要「号的额度在上面」,后要「grok 的用量
   *   不要放在 AI 用量信息里,放在总览里就好」)。用量页、日志页、设置页一律不触发 ——
   *   那一页整页都是"本机盘扫出来的 token 消耗",而 grok 额度是云端账单,本来就不同源。
   *
   *   grok CLI 活着时抓取交给 `grok-quota-sampler`（约 15s 一轮、推送到 sidecar），
   *   这里的 10min 轮询只是它退出之后的兜底。`enabled` 仍白名单：只挡主动 `run_grok_quota`，
   *   推送通道不受它约束。
   *   ⚠️ 总览是默认页,启动仍可能打一次(token 已过期时本地短路、不发请求)。
   *   这个端点不计费、不消耗额度。
   */
  // ★ 取 `refresh`：交接包 page5 的只读卡底栏有「刷新」（只读号只有这一个操作）。
  //   取数平时仍是自动的 —— 采样器推送 + 10min 兜底轮询；手动刷新是只读 GET，不计费。
  const { snap: grokSnap, busy: grokBusy, err: grokErr, refresh: refreshGrok, last: grokLast } =
    useGrokQuota({ enabled: page === "overview" });
  /**
   * ★ agy 额度。**与上面那条最大的区别:它不联网。**
   *   数据来自本机 agy 进程监听的 loopback 端口,不消耗任何配额、不碰凭证(接口无鉴权),
   *   实测毫秒级。所以上面那段"唯一一条主动联网路径"的说法**只指 grok**,别把这条也算进去。
   *
   *   位置同样**只在总览** —— 沿用用户 2026-08-24 对 grok 的定稿:额度归总览,
   *   用量页只放本机盘扫出来的 token 消耗。两者不同源,混在一页会让人以为可以相减。
   *
   *   新鲜度 2min(不是 grok 的 10min):agy 最紧的窗口是 5h,每 1% ≈ 3 分钟,
   *   10 分钟粒度会让用户看到一个落后三个百分点的数。理由详见 `useAgyQuota`。
   */
  const { snap: agySnap, busy: agyBusy, err: agyErr, refresh: refreshAgy } =
    useAgyQuota({ enabled: page === "overview" });
  // Claude 档的额度（状态栏转写，读本机文件）与各家实时速度（与托盘 / 刘海同源）—— 只在总览的那一档读。
  const { quota: claudeQuota, err: claudeErr, refresh: refreshClaude } =
    useClaudeQuota(page === "overview" && provider === "claude");
  const { live, error: liveErr } = useLive();
  /** 自动切号开关（codex）。真源是 localStorage `codexbar_settings.autoSwitchEnabled`（`useAutoSwitch` 读它）。 */
  const toggleAutoSwitch = () => {
    // ★ 从真源现读再翻转（2026-10-22 评审）：设置页也能改这个开关，按挂载时那份 state 翻会写反
    const next = !getSettings().autoSwitchEnabled;
    patchSettings({ autoSwitchEnabled: next });
    setAutoSwitch(next);
    showToast(next ? "✓ 自动切号 已开启" : "自动切号 已关闭");
  };
  // 离开设置页回来时重读（设置页与总览同在主窗口，设置页改完不广播）
  useEffect(() => { setAutoSwitch(getSettings().autoSwitchEnabled); }, [page]);
  // ★★ 这一段**必须排在 `agySnap` 之后**：它读 `agySnap`，而 `const` 有暂时性死区。
  //    放在前面时页面**整页白屏**，只在 harness 的 `errors` 探针里留一句
  //    `Cannot access 'je' before initialization`（压缩后的变量名）——
  //    零渲染的页面量出来正好是「零溢出、零报错」，看着像通过（本仓记过的假阴性）。
  // ★★ 2026-09-24：Gemini 的「正在使用 / 下一个」改由 `agy/pool.py::pick`（`read_agy_board`）给出，
  //   前端**不再自己排**。原来这里有一段「在各号都测到的窗口上比最小值」的推荐逻辑（`agyBest`），
  //   它既不看置顶、不看停用、也不看 15% 阈值 —— 与 wrapper 真正装进去的号是两份实现，
  //   codex 那边已经因此栽过（界面报一个根本不会被挑的号）。整段理由见 git 历史与 CHANGELOG B70。

  return (
    // ★ `cb-light` 供 App.css 的滚动条规则按主题反色 —— 白色拇指在浅色底上等于隐形。
    //   加这个 class 之前那条规则是**死规则**(写完顺手核了一下才发现根节点没有它)。
    <div className={theme === "light" ? "cb-root cb-light" : "cb-root"} data-nav-count={navN}
         style={{ position: "relative", width: "100vw", height: "100vh", display: "flex", flexDirection: "column", background: t.appBg, color: t.text, fontFamily: "'Space Grotesk'", borderRadius: winUI ? 12 : 0, overflow: "hidden", boxShadow: t.shadow, transition: "background-color .35s ease, color .35s ease" }}>

      {/* Title bar —— 只剩 Windows 那一版（macOS 用户 2026-10-22「顶部占位的地方去掉」：红黄绿进侧栏顶、眼睛与版本进侧栏底） */}
      {winUI && <div data-tauri-drag-region style={{ height: 38, flexShrink: 0, display: "flex", alignItems: "center", padding: "0 14px", gap: 8, borderBottom: `1px solid ${t.chromeBorder}`, background: t.chromeBg, position: "relative", transition: "background-color .35s ease" }}>
        {/* ★ 窗口控制:macOS 左上红黄绿 / Windows 右上 ─ □ ✕(见下方 winCtl)。
            位置是 OS 级肌肉记忆,属于「必须各平台原生」那一类,不能统一。 */}
        {!winUI && <>
          <span onClick={() => { invoke("set_main_visible", { show: false }).catch(() => {}); }} style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57", cursor: "pointer" }} title="隐藏" />
          <span onClick={() => win.minimize()} style={{ width: 12, height: 12, borderRadius: "50%", background: "#febc2e", cursor: "pointer" }} title="最小化" />
          <span onClick={() => { win.toggleMaximize().catch(() => {}); }} style={{ width: 12, height: 12, borderRadius: "50%", background: "#28c840", cursor: "pointer" }} title="缩放" />
        </>}
        <span data-tauri-drag-region style={{ position: "absolute", left: 0, right: 0, textAlign: "center", fontSize: 12.5, fontWeight: 600, letterSpacing: ".02em", color: t.titleText, pointerEvents: "none" }}>AICoop</span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <span onClick={togglePrivacy} title={privacy ? "打码中 — 邮箱与 account_id 已遮蔽,可安全截图。点击恢复" : "打码:遮蔽邮箱与 account_id,方便截图分享"}
            style={{ display: "grid", placeItems: "center", width: 24, height: 20, borderRadius: 6, cursor: "pointer",
                     color: privacy ? t.accentText : t.muted, background: privacy ? t.accent : "transparent", transition: "background .2s, color .2s" }}>
            {privacy ? <IconEyeOff /> : <IconEye />}
          </span>
          {/* 日夜切换已移到设置页（交接包 2026-10-19 page 5：标题栏只留隐私眼睛）。 */}
          <span style={{ fontSize: 11, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{ver ? `v${ver}` : ""}</span>
          {/* ★ Windows 窗口控制:右上 ─ □ ✕。按 Windows 规范做,不是把红绿灯挪个位置 ——
              ① 无圆角、无间距、**齐平右上角**(贴边是 Fitts 定律的角落优势,Windows 用户靠它盲点);
              ② 每格 46×整条标题栏高,不是 24×20 的小图标;
              ③ hover **变亮**(Windows 与 macOS 反向),关闭键 hover 变 #e81123 红底白字;
              ④ 必须比上面那些工具图标更靠右,否则用户会点到主题切换。
              关闭走 `set_main_visible(false)` 而不是真退出:本 app 常驻托盘,
              真退出的入口在设置页(与 macOS 一致)。 */}
          {winUI && (
            <div style={{ display: "flex", alignSelf: "stretch", marginRight: -14, marginLeft: 6 }}>
              {([
                ["─", "最小化", () => { win.minimize().catch(() => {}); }, false],
                ["□", "最大化 / 还原", () => { win.toggleMaximize().catch(() => {}); }, false],
                ["✕", "隐藏到托盘", () => { invoke("set_main_visible", { show: false }).catch(() => {}); }, true],
              ] as [string, string, () => void, boolean][]).map(([glyph, label, onClick, danger]) => (
                <span key={label} title={label} onClick={onClick}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = danger ? "#e81123" : t.chromeHoverBg;
                        e.currentTarget.style.color = danger ? "#fff" : t.text;
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = "transparent";
                        e.currentTarget.style.color = t.muted;
                      }}
                      style={{ display: "grid", placeItems: "center", width: 46, alignSelf: "stretch",
                               fontSize: 12, cursor: "pointer", color: t.muted, userSelect: "none",
                               transition: "background .15s, color .15s" }}>{glyph}</span>
              ))}
            </div>
          )}
        </div>
      </div>}

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* Sidebar — AICoop P10_Nav（components/NavRail.tsx） */}
        {/* 侧栏再点「Token 消耗」= 回总览（R2 §2「侧栏图标返回」）。 */}
        <NavRail t={t} page={page} onPage={(pg) => { if (pg === "traffic") setDrill(null); setPage(pg); }}
                 headH={winUI ? 0 : 26}
                 head={winUI ? undefined : (
                   <div data-win-lights style={{ display: "flex", gap: 7, flexShrink: 0 }}>
                     <span onClick={() => { invoke("set_main_visible", { show: false }).catch(() => {}); }} style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57", cursor: "pointer" }} title="隐藏" />
                     <span onClick={() => win.minimize()} style={{ width: 12, height: 12, borderRadius: "50%", background: "#febc2e", cursor: "pointer" }} title="最小化" />
                     <span onClick={() => { win.toggleMaximize().catch(() => {}); }} style={{ width: 12, height: 12, borderRadius: "50%", background: "#28c840", cursor: "pointer" }} title="缩放" />
                   </div>)}
                 foot={winUI ? undefined : <>
                   <span data-privacy-toggle onClick={togglePrivacy} title={privacy ? "打码中 — 邮箱与 account_id 已遮蔽,可安全截图。点击恢复" : "打码:遮蔽邮箱与 account_id,方便截图分享"}
                         style={{ display: "grid", placeItems: "center", width: 28, height: 22, borderRadius: 6, cursor: "pointer",
                                  color: privacy ? t.accentText : t.muted, background: privacy ? t.accent : "transparent", transition: "background .2s, color .2s" }}>
                     {privacy ? <IconEyeOff /> : <IconEye />}
                   </span>
                   {/* 版本走 `fullVersion()`（`X.Y.Z+B`）：B 换一行，窄栏放得下 */}
                   <span data-app-version title={ver ? `v${ver}` : undefined}
                         style={{ fontSize: 9.5, lineHeight: 1.25, color: t.muted, fontFamily: "'JetBrains Mono'", textAlign: "center", whiteSpace: "pre" }}>
                     {ver ? `v${ver.replace("+", "\n+")}` : ""}
                   </span>
                 </>} />

        {/* Content —— 去掉标题栏后，顶上一条带（`HEADER_BAND`）里点空白处拖窗口、双击缩放；控件照常（`windowDrag.ts`） */}
        <div style={{ position: "relative", flex: 1, minWidth: 0, padding: 16, display: "flex", flexDirection: "column", overflow: "hidden" }}
             data-drag-band
             onMouseDown={winUI ? undefined : (e) => {
               if (e.button !== 0 || e.detail !== 1 || !isBlankHeader(e.target, e.currentTarget, e.clientY)) return;
               e.preventDefault();
               win.startDragging().catch(() => {});
             }}
             onDoubleClick={winUI ? undefined : (e) => {
               if (isBlankHeader(e.target, e.currentTarget, e.clientY)) win.toggleMaximize().catch(() => {});
             }}>
          {page === "overview" && (
            <Overview t={t} isDark={theme === "dark"} privacy={privacy} provider={provider} setProvider={setProvider}
              colors={{ codex: colorOf(traffic, "codex"), claude: colorOf(traffic, "claude"),
                        gemini: colorOf(traffic, "agy"), grok: colorOf(traffic, "grok") }}
              state={state} accounts={accounts} inUseNode={inUseNode} currentNode={currentNode}
              lastRefreshAt={lastRefreshAt} freshness={freshness} loadingAction={loadingAction} run={run} showToast={showToast} pendingDel={pendingDel} deferDelete={deferDelete}
              integration={integration} onConnect={() => setPage("settings")}
              board={board} boardErr={boardErr}
              agyPool={agyPool} agyBoard={agyBoard} agyBoardErr={agyBoardErr}
              agySnap={agySnap} agyBusy={agyBusy} agyErr={agyErr} refreshAgy={refreshAgy}
              grokSnap={grokSnap} grokBusy={grokBusy} grokErr={grokErr} refreshGrok={refreshGrok} grokLast={grokLast}
              claudeQuota={claudeQuota} claudeErr={claudeErr} refreshClaude={refreshClaude}
              live={live} liveErr={liveErr}
              autoSwitch={autoSwitch} toggleAutoSwitch={toggleAutoSwitch}
              agyOrder={cardOrder["gemini"]} setAgyOrder={(ids) => setOrderFor("gemini", ids)}
              preview={preview} makeDrag={makeDrag}
              platOff={{ agy: !!platPrefs.by?.agy?.off, grok: !!platPrefs.by?.grok?.off }}
              loadDetail={(aid) => invoke<AccountDetail>("read_account_detail", { aid }).catch(() => null)}
              onNav={(pg) => { setDrill(null); setPage(pg); }}
              onOpenUsage={(pk) => { setDrill(pk); setPage("traffic"); }}
              onLogs={() => setPage("logs")} />
          )}

          {page === "relay" && <RelayPage t={t} onOpenOverview={() => { setProvider("codex"); setPage("overview"); }} />}

          {page === "traffic" && (drill
            ? <PlatformPage t={t} data={traffic} raw={trafficRaw} cacheMode={cacheMode} prefs={platPrefs}
                            pk={drill} st={trafficSt} setSt={setTrafficSt}
                            onBack={() => setDrill(null)} busy={trafficBusy}
                            onSwitch={setDrill} onRefresh={refreshTraffic} />
            : <TrafficPage t={t} data={traffic} raw={trafficRaw} cacheMode={cacheMode} prefs={platPrefs}
                           st={trafficSt} setSt={setTrafficSt}
                           onDrill={setDrill} busy={trafficBusy} err={trafficErr}
                           onRefresh={refreshTraffic} />)}
          {page === "logs" && <LogsPage t={t} pools={rotPools} />}
          {page === "settings" && <SettingsPage t={t} theme={theme} onTheme={changeTheme} />}
          {page === "requests" && <RequestsPage t={t} privacy={privacy} nav={reqNav} />}
        </div>
      </div>

      <ToastStack items={toasts} isDark={theme === "dark"} onHold={holdToasts} onDismiss={dismissToast} />
      {!winUI && <WindowGrip />}
    </div>
  );
}
