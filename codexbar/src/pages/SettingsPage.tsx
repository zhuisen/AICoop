import { fullVersion, isWindowsUI } from "../helpers";
import { notchRowDesc, notchRowWarn, surfaceDesc, type NotchStatus } from "../notchSegs";
import { useState, useEffect, useMemo, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import ConnectorPanel from "../components/ConnectorPanel";
// ★ 外链走本仓自己的 `open_url`,**不用 `@tauri-apps/plugin-shell` 的 `open`**:
//   那条路是 `open::that_detached`,spawn 完直接 drop `Child`,每点一次留一具僵尸
//   (装机版 v1.6.3 实测,pid 36012)。理由全文在 `lib.rs::open_url` 的注释里。
const openExternal = (url: string): Promise<void> => invoke("open_url", { url });
// ★ 版本号只从 tauri 运行期取,前端不再写死。此前"版本号同步 5 处"里有 3 处在前端,
//   发一次版要手改三个字符串,漏一个就显示错版本。现在只剩 tauri.conf.json + Cargo.toml 两处。
import logo from "../../src-tauri/icons/128x128@2x.png";
import { enable as enableAutostart, disable as disableAutostart, isEnabled as isAutostartEnabled } from "@tauri-apps/plugin-autostart";
import type { Theme } from "../theme";
import { MultiSeg, SBtn, SegSlide, SGroup, Toggle, presetOpts } from "../components/settings/SetKit";
import { isNewer } from "../semver";
import ShimText from "../components/ShimText";
import CmdRules from "../components/settings/CmdRules";
import { useWinDensity } from "./TrafficPage";
import { titleSize } from "../tokenView";
import { AMBER_TEXT } from "../components/CardBadge";
import { platformColor } from "../theme";
import { useCacheMode } from "../hooks/useCacheMode";
import { usePlatformPrefs } from "../hooks/usePlatformPrefs";
import type { TrafficData, PlatformPrefs } from "../traffic";
import { CACHE_MODES, cacheModeLabel, cacheModeDesc, orderedKeys, fmtTok } from "../traffic";
import { sourceNotes } from "../scanHealth";
import { TRAY_KEYS } from "../idleTray";
import PlatformLogo, { type LogoPlatform } from "../components/PlatformLogo";

/** 有官方 logo 的几家（`PlatformLogo`）。其余平台（MiMo / OpenClaw…）没有 logo，用识别色方块占同一个位置。 */
const LOGO_KEYS: readonly string[] = ["codex", "claude", "agy", "grok", "kimi", "deepseek"];
import { CLAUDE_OTEL_DESC, claudeOtelLocked, claudeOtelOn, claudeOtelWarn, type ClaudeOtelStatus } from "../claudeOtel";

/** 菜单栏标题样式(用户 2026-08-12 从 demo 里三选一)。索引与 Rust 的 TRAY_STYLE 一一对应。 */
export const TRAY_STYLES = ["full", "mid", "min", "today"] as const;
export type TrayStyle = (typeof TRAY_STYLES)[number];
export const trayStyleLabel = (v: TrayStyle): string =>
  v === "full" ? "完整" : v === "mid" ? "简" : v === "min" ? "极简" : "今日";
/** 预览用的示例串。**和 Rust 的 `format_tray_title` 必须一致** —— 两处各写一份迟早分叉。 */
export const trayStyleSample = (v: TrayStyle): string => {
  return (v === "full" ? "pro1 周 67% ↻5d21h"
            : v === "mid" ? "pro1 67%"
            : v === "min" ? "67%"
            : "67% 🔹 1.29B");
};
export const trayStyleDesc = (v: TrayStyle): string =>
  v === "full" ? "标签 + 窗口 + 余量 + 重置倒计时。信息最全，也最宽（约 148px），菜单栏挤时最先被系统截掉。"
  : v === "mid" ? "标签 + 余量。知道是哪个号、还剩多少，但不占重置倒计时那段宽度。"
  : v === "min" ? "只有余量百分比，最窄（约 48px）。适合菜单栏很挤、只想扫一眼的场景。"
  : "余量 + 今日全平台 token。账号池与用量并到一行；今日数每几分钟变一次，宽度会小幅抖动。";

interface Settings {
  autoSwitchEnabled: boolean;
  autoSwitchThreshold: number;
  subExpiryWarnDays: number;
  tokenExpiryWarnHours: number;
  dockVisible: boolean;
  notchHud: boolean;
  tpsTray: boolean;
  trayStyle: TrayStyle;
  intro: boolean;
  /** 数字滚动（用户 2026-10-24 单独一个开关，放在入场动效下面）：KPI 数字从 0 滚到实际值、菜单栏在跑时 t/s 逐位滚动。 */
  numberRoll: boolean;
  /** 「显示位置 = 刘海屏、托盘已藏」这件事说过了没有（升级提示只说一次，samchen #5 ③）。 */
  surfaceNoticed: boolean;
  autoRefresh: boolean;
  /** 空闲托盘（AICoop P11 §7）：空闲时菜单栏画 AI 图标（true）还是原来的文字标题（false）。 */
  idleIcons: boolean;
  idleSlots: 2 | 3;
  idleRankBy: "requests" | "tokens";
  /** 「排序依据」默认改成 Token 数那次的一次性迁移已做过（见 `load`）。 */
  idleRankMigrated?: boolean;
  idleDays: 7 | 14 | 30;
  /** 固定到菜单栏（最多 2 家，平台 key）。 */
  idlePinned: string[];
  idleGlow: boolean;
  idleHello: "off" | "daily" | "idle1h";
  /** 悬停面板（P9 S1「悬停面板」组）。样式目前只有「格子 · 精简」。 */
  idleHoverScope: "used" | "all" | "bar";
  idleHoverMax: 4 | 8;
  idleHoverReset: boolean;
  idleHoverUnconnected: boolean;
}

const DEFAULTS: Settings = {
  autoSwitchEnabled: false,
  autoSwitchThreshold: 15,
  subExpiryWarnDays: 7,
  tokenExpiryWarnHours: 48,
  dockVisible: false,        // 默认保持纯菜单栏形态(现有行为)
  notchHud: false,           // 刘海屏版本默认**关**(PR #1 作者 2026-10-17 定;交接包 2026-10-19 DECISIONS「刘海屏版本」沿用),
                             // 只在带刘海的屏幕上有效。★ 键名沿用旧「刘海额度条」的 `notchHud` —— 改名 = 老用户的偏好丢失
  tpsTray: true,             // 「在跑时显示 t/s」默认**开**(交接包 page 1)。关 = 托盘始终是额度标题
  trayStyle: "full",         // 默认沿用现状,不动老用户的菜单栏
  intro: true,               // 入场动效默认开。关掉是**完全不播**,不是播快一点
  numberRoll: true,          // 数字滚动默认开（v2.0.0 改版前一直在滚，那次重写把它弄丢了）
  surfaceNoticed: false,
  autoRefresh: true,         // 后台自动保鲜默认**开**(现有行为)。关掉只停后台心跳,
                             // 「打开页面/弹出托盘就刷新」照旧 —— 见 useTraffic 的 autoRefreshEnabled()
  idleIcons: true,           // P11 §7 默认「AI 图标」；文字标题四档仍在（选它时 `trayStyle` 生效）
  idleSlots: 3,
  idleRankBy: "tokens",      // 用户 2026-10-22「空闲时展示的 AI 按最近 14 天 token 量最多的排序」（原默认请求数）
  idleDays: 14,
  idlePinned: [],
  idleGlow: true,
  idleHello: "daily",
  idleHoverScope: "used",
  idleHoverMax: 4,
  idleHoverReset: true,
  idleHoverUnconnected: false,
};

/** 空闲托盘设置变了：菜单栏 webview（`useIdleTray`）收到后重读并重发 `set_idle_tray`。localStorage 跨 webview 不推送。 */
export const IDLE_TRAY_EVENT = "idle-tray-settings";
const IDLE_NAME: Record<string, string> = { codex: "Codex", claude: "Claude", agy: "Gemini", grok: "Grok", kimi: "Kimi", deepseek: "DeepSeek" };

const KEY = "codexbar_settings";

function load(): Settings {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}") as Partial<Settings>;
    // 设置是整份写盘的：改过任何一项的人，旧默认「请求数」也被存了下来，光改 DEFAULTS 他们看不到。迁移一次；
    // 之后再在设置页选「请求数」会连同 `idleRankMigrated: true` 一起存下，不会再被改回去。
    if (!raw.idleRankMigrated) { raw.idleRankBy = "tokens"; raw.idleRankMigrated = true; }
    return { ...DEFAULTS, ...raw };
  } catch { return DEFAULTS; }
}
function save(s: Settings) { localStorage.setItem(KEY, JSON.stringify(s)); }

export function getSettings(): Settings { return load(); }

/**
 * ★ 日夜主题（交接包 2026-10-19「日夜切换移到设置」）。**一个键、所有 webview 共用**：
 *   主窗口、菜单栏弹窗、悬停面板都读 `codexbar_theme`；设置页改完发 `theme-changed`，各 webview 收到后重读。
 *   刘海卡片不跟：刘海本身是黑的，卡片恒深色（交接包 4e 只给了深色）。
 *   ⚠️ 此前主窗口的主题只活在 App 的 state 里、每次启动回深色；`codexbar_theme` 是菜单栏自己那份。
 *   现在合成一份 ⇒ 曾在菜单栏选过浅色的用户，升级后主窗口也是浅色（同一个选择，不是新偏好）。
 */
export const THEME_KEY = "codexbar_theme";
export type ThemeName = "dark" | "light";
export function loadTheme(): ThemeName {
  try {
    const v = localStorage.getItem(THEME_KEY);
    if (v === "light" || v === "dark") return v;
  } catch { /* 读不到 localStorage ⇒ 默认深色 */ }
  return "dark";
}
export function saveTheme(v: ThemeName): void {
  try { localStorage.setItem(THEME_KEY, v); } catch { /* 写不了也照样广播，本次会话内各窗口仍一致 */ }
  void emit("theme-changed", v).catch(() => {});
}

/** 一行只写一件事、不折行；放不下就省略号，全文在悬浮里。 */
/** 浅色底上的琥珀字：`AMBER` 在白底只有 ~2.4:1，取总览 `--ovWarnTx` 同一个值（F5 量过）。 */
const WARN_TX_LIGHT = "#8a5a0e";
const ONE_LINE: React.CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };

/**
 * 从设置页之外改一两项。**别在别处再写一遍 `localStorage.setItem("codexbar_settings", …)`** ——
 * 那个 key 字面量此前已经在 `App.tsx` 里重复了一次，多一处就多一个改了这边忘那边的地方。
 */
export function patchSettings(patch: Partial<Settings>): Settings {
  const next = { ...load(), ...patch };
  save(next);
  return next;
}



/**
 * 数值设置：滑块（粗调）+ **可直接输入的数字框**（精调）。
 *
 * 用户 2026-09-07：「滑块滚动不太精准能滚到想要的数值」。
 *
 * ★★ **必须定义在模块作用域**，不能写在页面组件的 render 里。写在 render 里时它每次渲染
 *   都是一个**新的组件类型**，React 会整个卸载重建 —— 对滑块只是掉帧（本仓 `Seg` 那条），
 *   但对**输入框是致命的**：每敲一个字符就重建一次，焦点丢失、根本打不进字。
 *   这个组件原本就在 render 里，所以加输入框的第一步是先把它搬出来。
 *
 * ★ 输入用**草稿态**而不是直接回写：边打边 clamp 的话，想输 "25" 会在打完 "2" 的瞬间
 *   被钳到 min=5 变成 "5"，第二个字符就再也接不上了。所以打字期间不校验，
 *   **失焦或回车才提交并 clamp**；非法输入直接丢弃、回落到当前值。
 *
 * ★★ `onKeyDown` 必须 `stopPropagation`：全局键盘处理里有 ⌘+数字快捷键（2026-10-16 起是总览切档，
 *   此前是切号 —— 改名输入框上踩过）。设置页本身不响应它，拦住是为了别让下一个快捷键漏进输入框。
 */
function NumInput({ value, onChange, min, max, suffix, t }: {
  value: number; onChange: (v: number) => void; min: number; max: number; suffix: string; t: Theme;
}): React.ReactElement {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = (raw: string): void => {
    const n = Number(raw.trim());
    setDraft(null);
    if (!raw.trim() || !Number.isFinite(n)) return;          // 非法 ⇒ 丢弃，回落当前值
    onChange(Math.min(max, Math.max(min, Math.round(n))));
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <input type="range" min={min} max={max} value={value}
             onChange={e => onChange(Number(e.target.value))}
             style={{ width: 72, accentColor: t.accent }} />
      <input
        value={draft ?? String(value)}
        title={`可直接输入（${min}–${max}${suffix}）；超出范围会被钳到边界`}
        inputMode="numeric"
        onChange={e => setDraft(e.target.value)}
        onFocus={e => e.currentTarget.select()}
        onBlur={e => commit(e.target.value)}
        onKeyDown={e => {
          e.stopPropagation();                                // ★ 别让 ⌘+数字快捷键漏进来
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") { setDraft(null); e.currentTarget.blur(); }
        }}
        style={{
          width: 42, textAlign: "right", fontSize: 12, fontWeight: 600,
          color: t.accent, background: t.ghostBg, fontFamily: "'JetBrains Mono'",
          fontVariantNumeric: "tabular-nums",
          border: `1px solid ${t.ghostBorder}`, borderRadius: 6, padding: "3px 5px",
          outline: "none",
        }} />
      <span style={{ fontSize: 12, fontWeight: 600, color: t.accent,
                     fontFamily: "'JetBrains Mono'", width: 14 }}>{suffix}</span>
    </div>
  );
}

/**
 * 设置行（AICoop P9 S1：行高 44、名称 14/500、副标题一行 12、放不下省略号、全文在悬浮里）。
 * `warn` = 第二行原因（刘海屏「开着但没显示」），单独一行，不跟在说明末尾被省略掉。`info` = ⓘ（全页只有「缓存计入口径」一处）。
 * ★ 控件是这一行的**直接子元素**（不包一层）：旧闸按 `控件.parentElement.firstElementChild` 找这一行的文字列。
 * ★ 模块作用域（同 `NumInput`）：写在 render 里每次都是新组件类型，开关的 transition 会变成死代码。
 */
function OneLineRow({ t, label, desc, warn, title, info, indent = 0, dim, children }: {
  t: Theme; label: string; desc?: string; warn?: string | null; title?: string; info?: string; indent?: number; dim?: boolean;
  children?: React.ReactNode;
}): React.ReactElement {
  return (
    <div className="set-row" style={{ display: "flex", alignItems: "center", gap: 12, minHeight: 44, padding: `7px 0 7px ${indent}px`, boxSizing: "border-box" }}>
      <div title={title ?? desc} style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0, opacity: dim ? 0.4 : 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: t.text, whiteSpace: "nowrap" }}>{label}</div>
          {info && <span data-set-info title={info} style={{ width: 14, height: 14, borderRadius: 7, flexShrink: 0, display: "grid", placeItems: "center",
                                                             boxShadow: `inset 0 0 0 1.2px ${t.muted}`, color: t.muted, fontSize: 10, cursor: "help" }}>i</span>}
        </div>
        {desc && <div style={{ fontSize: 12, color: t.muted, ...ONE_LINE }}>{desc}</div>}
        {warn && <div data-row-warn style={{ fontSize: 12, marginTop: 2, ...ONE_LINE,
                                              color: !warn.startsWith("⚠") ? t.muted : t.isDark ? AMBER_TEXT : WARN_TX_LIGHT }}>{warn}</div>}
      </div>
      <span style={{ flex: 1, minWidth: 8 }} />
      {children}
    </div>
  );
}

/**
 * 「Claude 实测速度」开关（默认关）。开 = `claude_otel_env.py enable`：把 12 个 OTel 变量合并进
 * `~/.claude/settings.json` 的 `env`（只碰这 12 个键、已有别的 OTel 配置就不写、先备份、原子写）。
 * ★ 真源是 settings.json 本身，不在 localStorage —— 用户手改过、或另一台 app 改过，进页面现读就对。
 * ★ 模块作用域（同 `OneLineRow`）：写在 render 里每次都是新组件类型，开关的 transition 会变成死代码。
 */
function ClaudeOtelRow({ t }: { t: Theme }): React.ReactElement {
  const [st, setSt] = useState<ClaudeOtelStatus | null>(null);
  const [readErr, setReadErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = useCallback(async (action: "status" | "enable" | "disable") => {
    try {
      const raw = await invoke<string>("claude_otel", { action });
      setSt(JSON.parse(raw) as ClaudeOtelStatus);
      setReadErr(null);
    } catch (e: unknown) {
      setReadErr(String(e));               // ★ 读不到 ≠ 已关闭：开关画成半透明，原因写在下面一行
    }
  }, []);
  useEffect(() => { void run("status"); }, [run]);
  const on = claudeOtelOn(st);
  const locked = claudeOtelLocked(st);
  const toggle = async (): Promise<void> => {
    if (busy || locked || on == null) return;
    setBusy(true);
    try { await run(on ? "disable" : "enable"); } finally { setBusy(false); }
  };
  return (
    <OneLineRow t={t} label="Claude 实测速度" desc={CLAUDE_OTEL_DESC}
                warn={claudeOtelWarn(st, readErr)}
                title={st ? `${CLAUDE_OTEL_DESC}（写入 ${st.settings}）` : CLAUDE_OTEL_DESC}>
      <Toggle t={t} on={on} busy={busy || locked} onClick={() => void toggle()}
              attrs={{ "data-claude-otel-toggle": on == null ? "unknown" : on ? "on" : "off" }} />
    </OneLineRow>
  );
}

export default function SettingsPage({ t, theme, onTheme }: { t: Theme; theme: ThemeName; onTheme: (v: ThemeName) => void }) {
  /** 池子空时允不允许借用已停用的号。★ **读**直接走 `read_state`（值就在 `state.json` 里，
   *  不必再加一条只读 IPC）；**写**才走 `run_rotate` —— 那是真的改状态，该广播。
   *  ⚠️ 存反向（`borrow_off`），所以「开」= 键不存在。 */
  const [borrow, setBorrow] = useState<boolean | null>(null);
  const loadBorrow = useCallback(async () => {
    try {
      const st = await invoke<{ borrow_off?: boolean }>("read_state");
      setBorrow(!st.borrow_off);
    } catch {
      // ★ 读不到就保持 `null` —— 渲染成「—」而不是假装它是开着的。
      setBorrow(null);
    }
  }, []);
  /** 借用开关写失败的原因（全方面评审 §6：原来写失败不提示，开关回弹像什么都没发生）。 */
  const [borrowErr, setBorrowErr] = useState<string | null>(null);
  const toggleBorrow = useCallback(async () => {
    if (borrow == null) return;              // 读不到时不写：`!null` 是 true，会把「不知道」写成「开」
    const next = !borrow;
    try {
      await invoke("run_rotate", { args: ["borrow", next ? "--on" : "--off"] });
      setBorrowErr(null);
    } catch (e: unknown) {
      setBorrowErr(`Codex 没改成：${String(e).slice(0, 80)}`);
    } finally { void loadBorrow(); }
  }, [borrow, loadBorrow]);
  useEffect(() => { void loadBorrow(); }, [loadBorrow]);
  /** Gemini（agy）池的同一个开关（2026-09-24 与 codex 对齐）。真源在 agy 池里 ——
   *  `bin/agy` 在 app 没开时也要读它。读走 `borrow --status --json`（纯读，不广播）。 */
  const [agyBorrow, setAgyBorrow] = useState<boolean | null>(null);
  const loadAgyBorrow = useCallback(async () => {
    try {
      const raw = await invoke<string>("run_agy_rotate", { args: ["borrow", "--status", "--json"] });
      setAgyBorrow(!!(JSON.parse(raw) as { borrow: boolean }).borrow);
    } catch {
      setAgyBorrow(null);                  // ★ 读不到 ≠ 已关闭
    }
  }, []);
  const toggleAgyBorrow = useCallback(async () => {
    if (agyBorrow == null) return;
    const next = !agyBorrow;
    try {
      await invoke("run_agy_rotate", { args: ["borrow", next ? "--on" : "--off"] });
      setBorrowErr(null);
      void emit("agy-pool-updated");      // 续航条的「下一个」可能随之变化
    } catch (e: unknown) {
      setBorrowErr(`Gemini 没改成：${String(e).slice(0, 80)}`);
    } finally { void loadAgyBorrow(); }
  }, [agyBorrow, loadAgyBorrow]);
  useEffect(() => { void loadAgyBorrow(); }, [loadAgyBorrow]);
  const [s, setS] = useState(load);
  const update = (patch: Partial<Settings>) => {
    const next = { ...s, ...patch }; setS(next); save(next);
  };
  const updIdle = (patch: Partial<Settings>) => { update(patch); void emit(IDLE_TRAY_EVENT).catch(() => {}); };

  const { mode: cacheMode, setMode: setCacheMode } = useCacheMode();
  const [confirmQuit, setConfirmQuit] = useState(false);
  const [autostart, setAutostart] = useState(false);
  const [autostartBusy, setAutostartBusy] = useState(false);
  useEffect(() => { isAutostartEnabled().then(setAutostart).catch(() => {}); }, []);
  // 刘海条：进设置页时问一次「现在有没有刘海屏 / 显示着没有」，不改任何状态
  const [notchSt, setNotchSt] = useState<NotchStatus | null>(null);
  const [notchErr, setNotchErr] = useState<string | null>(null);
  useEffect(() => {
    if (isWindowsUI()) return;
    invoke<NotchStatus>("notch_status").then((st) => setNotchSt(st ?? null)).catch(() => setNotchSt(null));
  }, []);
  const toggleAutostart = async () => {
    if (autostartBusy) return;
    setAutostartBusy(true);
    try {
      if (autostart) { await disableAutostart(); setAutostart(false); }
      else { await enableAutostart(); setAutostart(true); }
    } catch (e) { console.error(e); }
    setAutostartBusy(false);
  };

  const win = isWindowsUI();
  const { W } = useWinDensity();
  // 平台行要的是「有哪几家、各自多少量」，扫描行要上次扫描的源状态。不在设置页触发扫描；
  // ★ 别处扫完（`traffic-updated`）就重读快照（~1 ms）：「数据源状态」写着「每次刷新自动更新」，
  //   原来只在挂载时读一次（全方面评审 §6）。读失败留着上次的。
  const [snap, setSnap] = useState<TrafficData | null>(null);
  useEffect(() => {
    const read = (): void => {
      invoke<string | null>("read_traffic_snapshot")
        .then((raw) => { if (raw) setSnap(JSON.parse(raw) as TrafficData); })
        .catch(() => { /* 没扫过就没有快照，平台列表回落到偏好里记过的键 */ });
    };
    read();
    const un = listen("traffic-updated", read);
    return () => { void un.then((f) => f()); };
  }, []);
  // ★ 读不到要说是哪一端：一端读不到时另一端照常显示、照常可点（评审 P6-gemini-2）。
  const UNREAD = "读不到这项设置 —— 不是「已关闭」，是这次没读到";
  const borrowDesc = borrowErr ? `⚠ ${borrowErr}`
    : borrow == null && agyBorrow == null ? UNREAD
    : borrow == null ? `Codex 读不到（不是「已关闭」）· Gemini ${agyBorrow ? "借用" : "不借"}`
    : agyBorrow == null ? `Gemini 读不到（不是「已关闭」）· Codex ${borrow ? "借用" : "不借"}`
    : borrow || agyBorrow ? "借用时在总览顶部标红说明"
    : "都不借：无号可用时不动你停用的号";
  const cacheShort = cacheMode === "full" ? "四类 token 全计入（原始口径）" : cacheMode === "noRead" ? "不计缓存读" : "缓存读写都不计";

  return (
    // ★ 外层内容区是 `overflow: hidden`(App.tsx),**每个页面自带滚动容器**是本项目的约定 ——
    //   总览和用量页都有,设置页原来漏了,于是窗口一矮下面的「关于」整块就被裁掉、没有滚动条
    //   (用户 2026-08-09 实测截图)。加页面时别忘这一条。
    // ★ AICoop P9 S1：7 组单列、最大宽 860。改动即时生效，没有保存按钮。偏离见 PLAN 第 43 条。
    <div data-page-body="settings" style={{ display: "flex", flexDirection: "column", gap: 12,
                  minHeight: 0, height: "100%", overflowY: "auto",
                  // 滚动条压住右侧滑块/开关不好点,给一点右内边距
                  paddingRight: 4 }}>
      {/* 用户 2026-10-22「设置界面的内容需要识别 AICoop 尺寸大小，位置都要居中显示」：最大宽 860 不变，窗口更宽时整列居中 */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, minHeight: 34, flexShrink: 0, maxWidth: 860,
                    width: "100%", alignSelf: "center" }}>
        <h1 style={{ margin: 0, fontSize: titleSize(W), fontWeight: 700 }}>设置</h1>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: t.muted, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap" }}>改动即时生效</span>
      </div>
      <div data-settings-col style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 860, paddingBottom: 20,
                                      width: "100%", alignSelf: "center" }}>

      <SGroup t={t} id="general" title="通用">
        <OneLineRow t={t} label="开机自启" desc="登录 macOS 后常驻菜单栏" title="登录 macOS 时自动启动，后台常驻菜单栏。">
          <Toggle t={t} on={autostart} busy={autostartBusy} onClick={() => void toggleAutostart()} />
        </OneLineRow>
        <OneLineRow t={t} label="在程序坞显示" desc="主界面打开时占一格，可 ⌘Tab 切换"
                    title="开启后主界面打开时在 Dock 占一格，可 ⌘Tab 切换；关掉主界面立刻让出位置。即时生效，无需重启。">
          <Toggle t={t} on={s.dockVisible} onClick={() => {
            const next = !s.dockVisible;
            update({ dockVisible: next });
            invoke("set_dock_visible", { on: next }).catch(() => {});
          }} />
        </OneLineRow>
        {/* ★ 日夜切换（交接包 2026-10-19：从标题栏 / 菜单栏弹窗移到设置）。写 `codexbar_theme` + 广播
            `theme-changed`（`saveTheme`），主窗口、菜单栏弹窗、悬停面板都跟着变。「跟随系统」没有后端（PLAN 43），不放。 */}
        <OneLineRow t={t} label="外观" desc="深色 / 浅色"
                    title="深色 / 浅色。主窗口、菜单栏弹窗、悬停面板一起切换；刘海卡片始终深色。">
          <div data-theme-row style={{ display: "inline-flex", padding: 2, gap: 2, borderRadius: 8, flexShrink: 0,
                                       border: `1px solid ${t.ghostBorder}`, background: t.isDark ? "#0e1117" : "#eef1f5" }}>
            {(["dark", "light"] as const).map((v) => {
              const on = theme === v;
              return (
                <span key={v} data-theme-pick={v} data-on={on ? 1 : 0} role="button" onClick={() => onTheme(v)} className="set-seg-btn"
                      style={{ height: 24, padding: "0 10px", borderRadius: 6, display: "inline-flex", alignItems: "center",
                               fontSize: 12.5, whiteSpace: "nowrap", cursor: "pointer", userSelect: "none",
                               color: on ? t.accentText : t.text2, background: on ? t.accent : "transparent" }}>
                  {v === "light" ? "浅色" : "深色"}
                </span>
              );
            })}
          </div>
        </OneLineRow>
        {/* ★ 动效开关（用户 2026-08-16）。关掉＝**完全不播**，不是播快一点 —— 与 `prefers-reduced-motion` 同语义。 */}
        <OneLineRow t={t} label="入场动效" desc="图表揭开、指标上浮"
                    title="打开「Token 消耗」页时，7 个指标依次上浮、平台卡片随后出现。关掉后直接到位（系统里开了「减弱动态效果」时本来就不播）。">
          <Toggle t={t} on={s.intro} onClick={() => update({ intro: !s.intro })} />
        </OneLineRow>
        {/* ★ 数字滚动（用户 2026-10-24「数字动效也没了，需要新增，并在设置处理」→ 单独新开关，放在入场动效下面）。
            v2.0.0 消耗页重写（`1f12bb3`）把 KPI 的 0→实际值滚动删了，「入场动效」的说明却还写着「数字滚动」（四方评审 4/4）。
            管两处：主窗口 KPI（`useNumberRoll`）· 菜单栏在跑胶囊的逐位滚动（Rust `set_number_roll`，启动时 App.tsx 重发）。 */}
        <OneLineRow t={t} label="数字滚动" desc="指标从 0 滚到实际值；菜单栏 t/s 逐位滚动"
                    title="打开「Token 消耗」或平台页、换时间档时，指标数字从 0 滚到实际值；菜单栏在跑时 t/s 变化逐位滚动。关掉后直接显示（系统里开了「减弱动态效果」时本来就不滚）。">
          <Toggle t={t} on={s.numberRoll} attrs={{ "data-number-roll-toggle": "" }} onClick={() => {
            const next = !s.numberRoll;
            update({ numberRoll: next });
            invoke("set_number_roll", { on: next }).catch(() => {});
          }} />
        </OneLineRow>
      </SGroup>

      <SGroup t={t} id="menubar" title="菜单栏与刘海" note="托盘相关的设置都在这里">
        {/* ★ 显示位置：菜单栏 / 刘海屏 **只能二选一**（用户 2026-10-24；选刘海屏 =「整个托盘图标都藏起来」）。
            存储键与命令沿用刘海屏版本的 `notchHud` / `set_notch_hud`：刘海屏 = 开，菜单栏 = 关。藏托盘在 Rust `notch.rs::sync_tray`：
            只在刘海窗口真的在时藏 —— 没有刘海屏（外接屏 / 合盖）或建窗失败，托盘照样显示，否则 app 没有入口。
            开 = Rust 建窗口 + 装鼠标监听，关 = 销毁窗口。启动时由 App.tsx 再应用一次。Windows 没有刘海，整行不画。
            ★ 选了刘海屏但没显示 ⇒ 第二行说出原因（`notchRowWarn`）。 */}
        {!win && (
        <OneLineRow t={t} label="显示位置" desc={surfaceDesc(s.notchHud)} warn={notchRowWarn(s.notchHud, notchSt, notchErr)}
                    title={notchRowDesc(s.notchHud, notchSt, notchErr)}>
          <SegSlide t={t} opts={["menubar", "notch"] as const} cur={s.notchHud ? "notch" : "menubar"} attrs={{ "data-notch-toggle": "" }}
                    label={(v) => (v === "notch" ? "刘海屏" : "菜单栏")} on={(v) => {
            const next = v === "notch";
            if (next === s.notchHud) return;
            update({ notchHud: next, surfaceNoticed: true });   // 自己在这里选的，不用再提示
            setNotchErr(null);
            invoke<NotchStatus>("set_notch_hud", { on: next })
              .then((st) => setNotchSt(st ?? null))
              // ★ 失败就拨回去并说原因 —— 不许出现「选的是刘海屏、屏幕上什么都没有、也没人说为什么」
              .catch((e: unknown) => {
                setS((p) => { const n = { ...p, notchHud: !next }; save(n); return n; });
                setNotchErr(String(e).slice(0, 120));
              });
          }} />
        </OneLineRow>
        )}
        {/* ★ 空闲时菜单栏（AICoop P11 / P9 S1）。AI 图标 = 空闲托盘；文字标题 = 原来的四档（下面换成「文字标题样式」，托盘 6 行隐藏）。
            设置改完广播 `IDLE_TRAY_EVENT`：选位与取数在常驻的菜单栏 webview（`useIdleTray`）。 */}
        {!win && (
        <OneLineRow t={t} label="空闲时菜单栏" desc={s.idleIcons ? "显示 2–3 家 AI 图标，用掉的额度变灰" : "显示文字标题（原来的样式）"}
                    title="只影响没有 AI 在跑的时候；在跑时始终是 t/s 胶囊。">
          <SegSlide t={t} opts={["icons", "text"] as const} cur={s.idleIcons ? "icons" : "text"} attrs={{ "data-idle-icons": "" }}
                    label={(v) => (v === "icons" ? "AI 图标" : "文字标题")} on={(v) => updIdle({ idleIcons: v === "icons" })} />
        </OneLineRow>
        )}
        {/* ★ 菜单栏标题样式。Rust 侧存在 `TRAY_STYLE`(atomic),这里改完立刻调命令刷标题;启动时由 App.tsx 再应用一次。 */}
        {(win || !s.idleIcons) && (
        <OneLineRow t={t} label="文字标题样式" desc={trayStyleDesc(s.trayStyle)}>
          <span style={{ height: 26, padding: "0 10px", borderRadius: 6, display: "inline-flex", alignItems: "center", flexShrink: 0,
                         fontSize: 12.5, fontFamily: "'JetBrains Mono'", color: t.text, whiteSpace: "nowrap",
                         background: t.isDark ? "#0a0e12" : "#f6f8fb", border: `1px solid ${t.cardBorder}`, boxSizing: "border-box" }}>
            {trayStyleSample(s.trayStyle)}
          </span>
          <SegSlide t={t} opts={TRAY_STYLES} cur={s.trayStyle} label={trayStyleLabel}
                    on={(v) => {
                      update({ trayStyle: v });
                      invoke("set_tray_style", { style: TRAY_STYLES.indexOf(v) }).catch(() => {});
                    }} />
        </OneLineRow>
        )}
        {/* ★ 在跑时显示 t/s（交接包 page 1 托盘胶囊，默认开；S1 没有这一行 —— 可以加不可以减，PLAN 43）。
            Rust 的开关是进程内 atomic、默认关，所以 App.tsx 每次启动重发一次（同 `set_tray_style`）。 */}
        {!win && (
        <OneLineRow t={t} label="在跑时显示 t/s" desc="有 AI 在跑时，菜单栏换成各家 logo + 实时 t/s"
                    title="有 AI 在跑时，菜单栏标题换成各家 logo + 实时 t/s；鼠标移上去看各会话速度。关掉 = 始终显示额度标题">
          <Toggle t={t} on={s.tpsTray} attrs={{ "data-tps-toggle": "" }} onClick={() => {
            const next = !s.tpsTray;
            update({ tpsTray: next });
            invoke("set_tps_tray", { enabled: next }).catch(() => {});
          }} />
        </OneLineRow>
        )}
        {!win && s.idleIcons && (<>
        <OneLineRow t={t} label="菜单栏显示几家" desc={s.idleSlots === 3 ? "常驻 2 家 + 动态 1 家" : "只放常驻 2 家"}
                    title="按排名或手动固定；第 3 家是排名第 3 的那家，剩余 < 10% 的插队占第 3 位，带红点。">
          <SegSlide t={t} opts={[2, 3] as const} cur={s.idleSlots} label={(v) => `${v} 家`} on={(v) => updIdle({ idleSlots: v })} />
        </OneLineRow>
        <OneLineRow t={t} label="排序依据" desc="决定常驻哪 2 家和悬停面板顺序" title="按统计窗口内的请求数或 Token 数降序。">
          <SegSlide t={t} opts={["requests", "tokens"] as const} cur={s.idleRankBy}
                    label={(v) => (v === "requests" ? "请求数" : "Token 数")} on={(v) => updIdle({ idleRankBy: v })} />
        </OneLineRow>
        <OneLineRow t={t} label="统计窗口" desc="排名、插队、悬停面板共用" title="只统计这段时间内用过的平台；每天 00:00（本机时区）重算。">
          <SegSlide t={t} opts={[7, 14, 30] as const} cur={s.idleDays} label={(v) => `${v} 天`} on={(v) => updIdle({ idleDays: v })} />
        </OneLineRow>
        <OneLineRow t={t} label="固定到菜单栏"
                    desc={s.idlePinned.length ? `已固定：${s.idlePinned.map((k) => IDLE_NAME[k] ?? k).join("、")}` : "不固定 · 按排名自动选常驻 2 家"}
                    title="最多 2 家；固定的优先占常驻位，选第 3 家时挤掉最早固定的。">
          <div data-idle-pin style={{ display: "flex", gap: 4, flexShrink: 0 }}>
            {TRAY_KEYS.map((k) => {
              const on = s.idlePinned.includes(k);
              return (
                <span key={k} data-pin={k} data-on={on ? 1 : 0} role="button" aria-pressed={on} title={IDLE_NAME[k]}
                      onClick={() => updIdle({ idlePinned: on ? s.idlePinned.filter((x) => x !== k) : [...s.idlePinned, k].slice(-2) })}
                      className="set-seg-btn"
                      style={{ width: 30, height: 26, borderRadius: 7, boxSizing: "border-box", display: "grid", placeItems: "center", cursor: "pointer",
                               border: `1px solid ${on ? "rgba(45,212,191,.6)" : t.ghostBorder}`,
                               background: on ? "rgba(45,212,191,.16)" : "transparent" }}>
                  <span style={{ display: "grid", opacity: on ? 1 : 0.55 }}><PlatformLogo platform={k as LogoPlatform} isDark={t.isDark} size={15} /></span>
                </span>
              );
            })}
          </div>
        </OneLineRow>
        <OneLineRow t={t} label="鼠标靠近光晕" desc="鼠标移近托盘时，每个 logo 后亮起平台色光晕" title="系统开「减弱动态效果」时不显示。">
          <Toggle t={t} on={s.idleGlow} attrs={{ "data-idle-glow": "" }} onClick={() => updIdle({ idleGlow: !s.idleGlow })} />
        </OneLineRow>
        <OneLineRow t={t} label="打招呼"
                    desc={s.idleHello === "off" ? "不打招呼" : s.idleHello === "idle1h" ? "每次空闲超过 1 小时后靠近时，logo 依次轻跳" : "每天第一次靠近托盘时，logo 依次轻跳一下"}
                    title="有 AI 在跑、悬停面板开着、减弱动态效果或专注模式时跳过。">
          <SegSlide t={t} opts={["off", "daily", "idle1h"] as const} cur={s.idleHello}
                    label={(v) => (v === "off" ? "关闭" : v === "daily" ? "每天一次" : "空闲 1 小时后")} on={(v) => updIdle({ idleHello: v })} />
        </OneLineRow>
        </>)}
      </SGroup>

      {/* ★ 悬停面板（P9 S1「悬停面板」组；P11 §6）。样式只有「格子 · 精简」（「列表 · 全量」未做，不放一个点了没反应的选项）。 */}
      {!win && (
      <SGroup t={t} id="hover" title="悬停面板" note="鼠标移到菜单栏时弹出的各家剩余额度">
        <OneLineRow t={t} label="悬停显示哪些" desc="菜单栏里的排最前" title="「用过的」= 统计窗口内用过的平台；没用过的不显示。点格子打开该 AI 总览。">
          <SegSlide t={t} opts={["used", "all", "bar"] as const} cur={s.idleHoverScope}
                    label={(v) => (v === "used" ? "用过的" : v === "all" ? "全部" : "只看菜单栏")} on={(v) => updIdle({ idleHoverScope: v })} />
        </OneLineRow>
        <OneLineRow t={t} label="悬停最多显示" desc={s.idleHoverMax === 4 ? "一行 4 家" : "两行 8 家"}>
          <SegSlide t={t} opts={[4, 8] as const} cur={s.idleHoverMax} label={(v) => (v === 4 ? "4 家 · 一行" : "8 家 · 两行")}
                    on={(v) => updIdle({ idleHoverMax: v })} />
        </OneLineRow>
        <OneLineRow t={t} label="悬停细节" desc="格子大数字固定是 5h 额度；按量计费的不写重置时间"
                    title="重置时间放在格子右上角小字：Codex / Claude 是 5 小时窗口倒计时，Gemini 是每日重置时刻；按量计费的不写。">
          <MultiSeg t={t} attrs={{ "data-idle-detail": "" }} items={([["idleHoverReset", "重置时间"], ["idleHoverUnconnected", "未接入"]] as const).map(([k, lab]) => ({
            k, label: lab, on: s[k], onClick: () => updIdle({ [k]: !s[k] }), attrs: { "data-detail": k, "data-on": s[k] ? "1" : "0" },
          }))} />
        </OneLineRow>
      </SGroup>
      )}

      <SGroup t={t} id="pool" title="账号池 · 轮换" note="额度低自动切号在总览各 AI 页也能开关">
        {/* ★ 账号池接入（Connector）：一次性的装机动作，但用户随时可能回来撤销 —— 全部动作与状态原样保留（S1 只画了一行，PLAN 43）。 */}
        <div className="set-sub" style={{ padding: "12px 0" }}><ConnectorPanel t={t} embedded /></div>
        <CmdRules t={t} />
        {/* ★★ 用户 2026-09-21 拍板加的开关：「我明明停止轮换了，应该就不能去调用」。真源在 `state.json` / agy 池，**不在 localStorage**。
            S1 并成一行多选（Codex | Gemini）；读不到的那一项半透明、不可点 —— 读不到 ≠ 已关闭。 */}
        <OneLineRow t={t} label="池子空时借用已停用的号"
                    desc={borrowDesc}
                    title={"只在一个可用的号都没有时临时借一个你停用的号，并在总览顶部标红。关掉：Codex 无号可用时直接报错；Gemini 不换号、照用当前号跑。"}>
          <MultiSeg t={t} items={[
            { k: "codex", label: "Codex", on: borrow, onClick: () => void toggleBorrow(), attrs: { "data-borrow": "codex" },
              title: borrow == null ? UNREAD : borrow ? "开：池子空时借一个停用的 Codex 号" : "关：宁可 codex 报错" },
            { k: "agy", label: "Gemini", on: agyBorrow, onClick: () => void toggleAgyBorrow(), attrs: { "data-agy-borrow": "" },
              title: agyBorrow == null ? UNREAD : agyBorrow ? "开：启动 agy 时池子空就借一个停用的号" : "关：不换号，agy 照用当前号跑" },
          ]} />
        </OneLineRow>
        {/* S1 把「额度低自动切号」移出设置页（总览各 AI 页有开关）；阈值没有别处可放，可以加不可以减 ⇒ 两行都留（PLAN 43）。 */}
        <OneLineRow t={t} label="额度低自动切号" desc="当前号额度低于阈值时自动切到最佳号（默认关）">
          <Toggle t={t} on={s.autoSwitchEnabled} onClick={() => update({ autoSwitchEnabled: !s.autoSwitchEnabled })} />
        </OneLineRow>
        {s.autoSwitchEnabled && (
          <OneLineRow t={t} label="自动切号阈值" desc="当前号剩余额度低于此值（%）时触发" indent={18}>
            <NumInput value={s.autoSwitchThreshold} onChange={v => update({ autoSwitchThreshold: v })} min={5} max={50} suffix="%" t={t} />
          </OneLineRow>
        )}
        {/* ★ 数值用预设档位（S1）。存着的值不在档位里（老用户设过 5 天 / 14 天）⇒ 多一档照样选中，不改存储值直到用户点。 */}
        <OneLineRow t={t} label="订阅到期提醒" desc="剩余天数 ≤ 此值时在卡片和通知中提醒" title="按本机时区的日期计算。">
          <SegSlide t={t} opts={presetOpts([1, 2, 3, 7], s.subExpiryWarnDays)} cur={s.subExpiryWarnDays} label={(v) => `${v} 天`}
                    on={(v) => update({ subExpiryWarnDays: v })} attrs={{ "data-sub-warn": "" }} />
        </OneLineRow>
        <OneLineRow t={t} label="Token 过期提醒" desc="access token 剩余小时 ≤ 此值时提醒">
          <SegSlide t={t} opts={presetOpts([24, 48, 72], s.tokenExpiryWarnHours)} cur={s.tokenExpiryWarnHours} label={(v) => `${v}h`}
                    on={(v) => update({ tokenExpiryWarnHours: v })} attrs={{ "data-token-warn": "" }} />
        </OneLineRow>
      </SGroup>

      <SGroup t={t} id="sources" title="数据源">
        <DiscoverPanel t={t} snap={snap} />
        {/* ★ 缓存计入口径。**token 数与费用同时跟着变**。改动即时同步到菜单栏「今日」（Tauri 事件广播）。全页唯一的 ⓘ。 */}
        <OneLineRow t={t} label="缓存计入口径" desc={cacheShort} title={cacheModeDesc(cacheMode)}
                    info="uncached_in + 缓存读 + 缓存写 + output。四类单价不同。换口径时，总 token 和费用一起重算：不计入的类别不算 token，也不算钱。">
          <SegSlide t={t} opts={CACHE_MODES} cur={cacheMode} on={setCacheMode} label={cacheModeLabel} />
        </OneLineRow>
        {/* ★ 后台自动刷新开关（用户 2026-08-19）。**只管后台心跳这一个触发点**；配套的是「上次刷新」旁边的分级陈旧提示。
            S1 的「刷新间隔」5 档没有后端（`FRESH_MS` 写死 2 分钟，PLAN 43），不放。 */}
        <OneLineRow t={t} label="后台自动刷新" desc={s.autoRefresh ? "每 2 分钟重扫本机 transcript" : "只在打开页面或点刷新时更新"}
                    title="界面开着时每 2 分钟在后台重扫一次本机 transcript。关掉后只在「进入用量页 / 弹出菜单栏 / 点 ↻」时更新——数据变旧时「上次刷新」旁会显示已过去多久，超过 30 分钟转琥珀。">
          <Toggle t={t} on={s.autoRefresh} onClick={() => update({ autoRefresh: !s.autoRefresh })} />
        </OneLineRow>
        <ClaudeOtelRow t={t} />
      </SGroup>

      <SGroup t={t} id="platforms" title="AI 平台" note="停用的不计入总 token 与费用">
        <PlatformSection t={t} snap={snap} />
      </SGroup>

      <SGroup t={t} id="about" title="关于">
        <About t={t} />
        {/* The tray no longer carries a native menu, so this is the quit path. Confirm first — with the Dock icon off
            (the default) a stray click here would leave the menu bar empty with no obvious way back. */}
        <OneLineRow t={t} label="退出 AICoop" desc="完全退出，菜单栏图标消失；只关窗口用 ⌘W">
          {!confirmQuit ? (
            <SBtn t={t} kind="danger" onClick={() => setConfirmQuit(true)} attrs={{ "data-act": "quit" }}>退出</SBtn>
          ) : (<>
            <SBtn t={t} kind="danger" onClick={() => { invoke("quit_app").catch(() => {}); }} attrs={{ "data-act": "quit-confirm" }}>确认退出</SBtn>
            <SBtn t={t} onClick={() => setConfirmQuit(false)}>取消</SBtn>
          </>)}
        </OneLineRow>
      </SGroup>
      </div>
    </div>
  );
}

/**
 * AI 平台管理:改名 / 改色 / 停用 / 排序(用户 2026-08-12)。
 *
 * ★ **这里只管"怎么显示",管不了"有没有数据"**。能扫出哪几家由 `traffic/scan.py` 的注册表决定,
 *   新增一家 = 写一个 `_scan_*` 解析器 —— 实测四家四种 token 形状(还有 DeepSeek 这第五种),
 *   做成让用户填路径的表单等于让它去猜字段名,而那正是会静默算错数的做法。
 *
 * ★ **停用 = 整家从数据里移除,总 token / 总费用跟着扣**(用户定稿)。实现在 `useTraffic` 出口,
 *   不在这里 —— 下游 30+ 处自动跟上。这里只写偏好。
 *
 * ★ 排序**只影响不带数字的平台胶囊**（与这张设置列表本身）。带 token 数的列表、卡片、图例、浮层一律按本期
 *   token 总量降序（用户 2026-10-25「审查所有地方，都要这样进行排序」，取代原「排序影响列表与图例」）。
 *   堆叠图层一直按占比降序("占大头的铺满基线比悬在半空清楚",2026-08-09 看了两版实物定的)。
 *
 * 用 ↑↓ 而不是拖拽:四五行的列表,拖拽要处理 HTML5 DnD 的一堆边界,而本项目键盘可达性本来就是 0,
 * 再加一个只能用鼠标的交互没有收益。
 */
function PlatformSection({ t, snap }: { t: Theme; snap: TrafficData | null }) {
  const { prefs, setPrefs } = usePlatformPrefs();

  // 近 30 个本地自然日（S1「数字为近 30 天」）。原来是快照里全部天数之和，窗口不一定是 30 天。
  const vol30 = useMemo(() => {
    const d = new Date(); d.setDate(d.getDate() - 29);
    const cut = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    return (k: string): number | null => {
      const days = snap?.platforms[k]?.days;
      if (!days) return null;
      return Object.entries(days).filter(([dt]) => dt >= cut).reduce((sum, [, b]) => sum + b.total, 0);
    };
  }, [snap]);

  // ★ 列表必须**包含已停用的**,否则停用之后就再也找不到它、开不回来了。
  //   所以枚举 = 快照里的键 ∪ 偏好里记过的键。
  const keys = useMemo(() => {
    const all = new Set([...Object.keys(snap?.platforms ?? {}), ...Object.keys(prefs.by), ...prefs.order]);
    // ★ 没排过的按**显示的那个数**（近 30 天）降序 —— 原来按快照里全部天数之和，与行上的数对不上。
    return orderedKeys([...all], prefs, (k) => vol30(k) ?? 0);
  }, [snap, prefs, vol30]);

  const patch = (k: string, v: Partial<PlatformPrefs["by"][string]>) =>
    setPrefs({ order: keys, by: { ...prefs.by, [k]: { ...prefs.by[k], ...v } } });

  const move = (i: number, d: -1 | 1) => {
    const next = [...keys];
    const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setPrefs({ ...prefs, order: next });
  };

  const dirty = prefs.order.length > 0 || Object.keys(prefs.by).length > 0;

  return (
    <>
      {keys.length === 0 && (
        <div className="set-row" style={{ minHeight: 44, display: "flex", alignItems: "center", fontSize: 12, color: t.muted }}>
          还没有扫描过，去「Token 消耗」页跑一次就会出现。
        </div>
      )}
      {/* ★ 每家一行：排序 ▲▼ · 识别色 · logo · 名字 · key · 近 30 天 token · 开关。S1 只画了拖柄 + 开关；
          改名 / 改色 / 全部复位 / 无数据 都是现有能力，可以加不可以减（待用户定去留，PLAN 43）。拖拽没做：键盘可达性本来就是 0，
          四五行的列表用 ▲▼ 足够（原注释的理由仍成立）。 */}
      {keys.map((k, i) => {
        const p = snap?.platforms[k];
        const o = prefs.by[k] ?? {};
        const off = !!o.off;
        const color = o.color || p?.color || platformColor(k);
        const missing = !p;      // 偏好里有、快照里没有 ⇒ scan.py 已不再注册它
        const n30 = vol30(k);
        return (
          <div key={k} className="set-row" data-platform-row={k}
               style={{ display: "flex", alignItems: "center", gap: 10, minHeight: 44, padding: "7px 0", boxSizing: "border-box" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              {([-1, 1] as const).map((d) => {
                // 到头了就真的不可点:8px 的箭头本来就难瞄准,再让它"点了没反应"会以为坏了
                const dead = d < 0 ? i === 0 : i === keys.length - 1;
                return (
                  <span key={d} onClick={dead ? undefined : () => move(i, d)} title={dead ? "" : d < 0 ? "上移" : "下移"}
                        style={{ fontSize: 9, lineHeight: 1, padding: "1px 4px", borderRadius: 4, userSelect: "none",
                                 cursor: dead ? "default" : "pointer", color: t.muted, opacity: dead ? 0.35 : 1 }}>
                    {d < 0 ? "▲" : "▼"}
                  </span>
                );
              })}
            </div>
            {/* 原生取色器:WKWebView 里可用,不必自己造一个色板 */}
            <input type="color" value={color} onChange={(e) => patch(k, { color: e.target.value })}
                   title={`${k} 的识别色（图表 / 图例 / 徽章共用）`}
                   style={{ width: 20, height: 20, padding: 0, border: "none", borderRadius: 5, background: "transparent", cursor: "pointer", flexShrink: 0 }} />
            {/* 官方 logo（AICoop 交接包）；没有 logo 的平台画识别色方块，占同一个位置 */}
            <span data-platform-logo={k} style={{ width: 20, height: 20, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, opacity: off ? 0.4 : 1 }}>
              {LOGO_KEYS.includes(k)
                ? <PlatformLogo platform={k as LogoPlatform} isDark={t.isDark} size={20} />
                : <span style={{ width: 12, height: 12, borderRadius: 3, background: color }} />}
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, opacity: off ? 0.4 : 1 }}>
              <input value={o.name ?? p?.name ?? k} onChange={(e) => patch(k, { name: e.target.value })} placeholder={p?.name ?? k}
                     onKeyDown={(e) => e.stopPropagation()}
                     style={{ width: 108, fontSize: 14, fontWeight: 500, fontFamily: "inherit", color: t.text, background: "transparent",
                              border: `1px solid transparent`, borderRadius: 6, padding: "2px 6px", outline: "none" }}
                     onFocus={(e) => { e.currentTarget.style.borderColor = t.ghostBorder; }}
                     onBlur={(e) => { e.currentTarget.style.borderColor = "transparent"; }} title="点一下改名（只改显示名）" />
              <span style={{ fontSize: 11.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{k}</span>
              {missing && (
                <span title="偏好里还留着它，但当前扫描结果里没有这一家（scan.py 未注册或该 CLI 未安装）"
                      style={{ fontSize: 11, fontWeight: 600, color: t.isDark ? AMBER_TEXT : WARN_TX_LIGHT, whiteSpace: "nowrap" }}>无数据</span>
              )}
            </div>
            <span style={{ flex: 1 }} />
            <span title="近 30 天 token" style={{ fontSize: 12.5, color: t.muted, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap" }}>
              {n30 == null ? "—" : fmtTok(n30)}
            </span>
            <Toggle t={t} on={!off} onClick={() => patch(k, { off: !off })}
                    attrs={{ "data-platform-toggle": k, title: off ? "启用：重新计入总量与图表" : "停用：从图表与总量中完全移除（可随时开回来）" }} />
          </div>
        );
      })}
      {dirty && (
        <OneLineRow t={t} label="全部复位" desc="名字、颜色、停用、排序回到默认">
          <SBtn t={t} onClick={() => setPrefs({ order: [], by: {} })}>复位</SBtn>
        </OneLineRow>
      )}
    </>
  );
}

/**
 * 「扫描新数据源」。产出**体检报告**,不自动启用任何东西。
 *
 * ★ 为什么不能一键启用:接一家的实质是写解析器。这个扫描能自动测出的只有「口径」
 *   (哪些字段加起来恒等于 total ⇒ 缓存要不要减),而**测不出去重规则** ——
 *   OpenClaw 那次朴素求和虚高 4.08x,靠的是找到 `responseId` 才消掉的,那一步没法自动。
 *   所以判定干净也只代表"值得写",不代表"可以直接用"。
 *
 * 判定状态四档,颜色对应:ok 青 / ambiguous 琥珀 / reject 红 / unknown 灰。
 * **判不了是常态**(四家里三家判不了),这不是失败,是它唯一的安全性来源。
 */
/**
 * 「数据源状态」（B85 · 用户 2026-10-16 从两版 demo 里选的 A：设置页常驻，不放用量卡）。
 *
 * ★ 数据来自**最近一次常规扫描**的快照（`scan.sources`），不用点「扫描新数据源」——
 *   那个按钮找的是**没注册**的产品，这里说的是**已注册**的源这一轮读成了什么样。
 * ★ 两级：少算了（没解压器 / 读失败 / 有压缩文件没解析）琥珀；没找到 / 空是灰 —— 没装那个 CLI 是常态。
 *   文案只走 `scanHealth.ts::sourceNotes`，别在这里另写一份。
 * ★ 旧快照没有 `sources` ⇒ 整块不画（下一次扫描后才有），**不说「全部正常」** —— 读不到 ≠ 没问题。
 */
function SourceStatusBlock({ t, snap }: { t: Theme; snap: TrafficData | null }) {
  const sources = snap?.scan?.sources;
  if (!sources) return null;
  const notes = sourceNotes(sources);
  const n = Object.values(sources).filter((s) => s.state !== "disabled").length;
  const at = new Date(snap.generated_at * 1000);
  const hhmm = `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
  return (
    <div data-source-status style={{ marginTop: 9, display: "flex", flexDirection: "column", gap: 4,
                                     fontSize: 11, fontFamily: "'JetBrains Mono'" }}>
      <div style={{ fontSize: 10, color: t.muted, marginBottom: 2 }}>
        数据源状态 · 来自 {hhmm} 那次扫描（每次刷新自动更新，不用点按钮）
        {notes.length === 0 && ` · ${n} 个源全部正常`}
      </div>
      {notes.map((x) => (
        <div key={`${x.key}:${x.text}`} data-source-note={x.level}
             style={{ padding: "5px 9px", borderRadius: 7, lineHeight: 1.45,
                      ...(x.level === "warn"
                        ? { color: t.isDark ? "#E0901C" : WARN_TX_LIGHT, background: "rgba(224,144,28,.08)", border: "1px solid rgba(224,144,28,.35)" }
                        : { color: t.muted, border: `1px solid ${t.cardBorder}` }) }}>
          {x.level === "warn" ? "! " : "· "}{x.text}
        </div>
      ))}
    </div>
  );
}

function DiscoverPanel({ t, snap }: { t: Theme; snap: TrafficData | null }) {
  type Cand = {
    root: string; known: boolean; files: number; records: number;
    /** 对应的已注册源 key;新发现的为 null。 */
    key: string | null;
    /** ★ 「已注册」≠「在扫」:被 sources.local.json 停用的源仍报 known,但一条都不解析。 */
    enabled: boolean | null;
    verdict: string; state: "ok" | "ambiguous" | "reject" | "unknown";
    models: { model: string; total: number }[];
  };
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ candidates: Cand[]; roots: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      setRes(JSON.parse(await invoke<string>("run_discover")));
    } catch (e: unknown) {
      setErr(String(e).slice(0, 200));
    } finally {
      setBusy(false);
    }
  };

  /** 启用一个**已注册但被停用**的源,然后重扫报告让状态跟上。 */
  const enable = async (key: string) => {
    try {
      await invoke("set_scan_source", { key, on: true });
      await run();
    } catch (e: unknown) {
      setErr(String(e).slice(0, 200));
    }
  };

  const COLOR: Record<Cand["state"], string> = {
    ok: t.isDark ? "#5eead4" : "#0e7a6e", ambiguous: t.isDark ? "#E0901C" : WARN_TX_LIGHT, reject: "#E0524D", unknown: t.muted,
  };
  // 行内状态（S1）：「N 个源正常 · HH:MM」；有少算的源 ⇒ 琥珀 +「N 处少算」—— 不许静默成「全部正常」（P9.4 #30）。
  const sources = snap?.scan?.sources;
  const notes = sources ? sourceNotes(sources) : [];
  const warnN = notes.filter((x) => x.level === "warn").length;
  // ★ 只数 `ok`：「未找到 / 没有会话文件」不是正常（评审 P6-codex-2）。
  const okN = sources ? Object.values(sources).filter((x) => x.state === "ok").length : 0;
  const at = snap ? new Date(snap.generated_at * 1000) : null;
  const hhmm = at ? `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}` : "";
  const status = busy ? "扫描中…（约 40 秒）" : !sources ? "—" : warnN ? `${warnN} 处少算 · ${hhmm}` : `${okN} 个源正常 · ${hhmm}`;
  const amber = t.isDark ? AMBER_TEXT : WARN_TX_LIGHT;

  return (
    <>
      <OneLineRow t={t} label="扫描新数据源" desc="找本机还有哪些 AI 把用量落了盘，并实测口径"
                  title="已注册但被停用的源可一键启用；新发现的不能——实测只证明了算术（哪些字段之和等于 total），没证明语义（某字段是输入还是输出、算不算缓存读），而四类 token 单价不同，归错类会静默算出错的费用。把结果发给我，我来写解析器。只读本地文件，不联网、不碰凭证。">
        <span data-scan-status={busy ? "run" : warnN ? "warn" : sources ? "ok" : "none"}
              style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap",
                       color: busy ? amber : warnN ? amber : sources ? (t.isDark ? "#5eead4" : "#0e7a6e") : t.muted }}>
          <i style={{ width: 7, height: 7, borderRadius: 4, background: "currentColor", display: "block" }} />{busy ? <ShimText text={status} lift={t.isDark} /> : <span>{status}</span>}
        </span>
        <SBtn t={t} onClick={() => { void run(); }} disabled={busy} attrs={{ "data-act": "discover" }}
              title="遍历本机候选目录,找还有哪些地方存着 AI token 用量。只读本地文件,不联网、不碰凭证">
          {busy ? <ShimText text="扫描中…" lift={t.isDark} /> : res ? "重新扫描" : "扫描"}
        </SBtn>
      </OneLineRow>
      {/* ★ 没东西可显示时整块 `display:none`（仍在 DOM 里，§5c）；分隔线只画在下一行上沿（settings.css）。 */}
      <div className="set-sub" style={{ display: sources || err || res ? "block" : "none", padding: "0 0 12px 18px" }}>
        <SourceStatusBlock t={t} snap={snap} />

        {err && <div style={{ fontSize: 12, color: "#E0524D", marginTop: 8, fontFamily: "'JetBrains Mono'" }}>✗ {err}</div>}

        {res && (
          <div style={{ marginTop: 9, display: "flex", flexDirection: "column", gap: 5 }}>
            <div style={{ fontSize: 12, color: t.muted }}>
              扫了 {res.roots} 个候选目录，{res.candidates.length} 个含 token 用量记录
            </div>
            {res.candidates.map((c) => (
              <div key={c.root} style={{ padding: "8px 12px", borderRadius: 9,
                                         background: t.isDark ? "#0e1319" : "#f6f8fb", border: `1px solid ${t.cardBorder}` }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {/* ★ 三档,不是两档:「已注册」与「在扫」是两件事 —— 被停用的源有解析器却一条都不解析。 */}
                  <span style={{ fontSize: 11, fontWeight: 600, padding: "1px 7px", borderRadius: 5,
                                 color: !c.known ? t.accentText : c.enabled === false ? "#fff" : t.muted,
                                 background: !c.known ? t.accent : c.enabled === false ? "#E0901C" : t.ghostBg }}>
                    {!c.known ? "新发现" : c.enabled === false ? "已停用" : "已注册"}
                  </span>
                  <span style={{ fontSize: 12.5, fontFamily: "'JetBrains Mono'", color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.root}</span>
                  <span style={{ marginLeft: "auto", fontSize: 11.5, color: t.muted, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap" }}>
                    {c.files} 文件 · {c.records} 条
                  </span>
                  {/* ★ 只有「已注册但被停用」能一键启用 —— 它已经有手写解析器。新发现的**不给按钮**：那不是懒，是不能。 */}
                  {c.known && c.enabled === false && c.key && (
                    <SBtn t={t} kind="primary" onClick={() => { void enable(c.key!); }}
                          title="把它从扫描层的停用列表里移除,下次扫描即纳入">启用</SBtn>
                  )}
                </div>
                <div style={{ fontSize: 12, color: COLOR[c.state], marginTop: 4, lineHeight: 1.5 }}>{c.verdict}</div>
                {c.models.length > 0 && (
                  <div style={{ fontSize: 11.5, color: t.muted, marginTop: 3, fontFamily: "'JetBrains Mono'" }}>
                    {c.models.slice(0, 6).map((m) => `${m.model} ${fmtTok(m.total)}`).join(" · ")}
                  </div>
                )}
              </div>
            ))}
            <div style={{ fontSize: 11.5, color: t.muted, lineHeight: 1.6, marginTop: 2 }}>
              判定干净（青色）只说明<b>值得接</b>，不等于能直接用：这个扫描测得出口径，
              <b>测不出去重规则</b>。OpenClaw 那次朴素求和虚高 4.08x，是靠找到 <code>responseId</code> 才消掉的。
              新增一家平台不在这里：能扫出哪几家由 <code>traffic/scan.py</code> 的注册表决定，加一家等于写一个解析器。
            </div>
          </div>
        )}
      </div>
    </>
  );
}

const REPO = "zhuisen/AICoop";
const REPO_URL = `https://github.com/${REPO}`;


type UpdateState =
  | { k: "idle" }
  | { k: "busy" }
  | { k: "latest"; v: string }
  | { k: "new"; v: string; clone: boolean }
  | { k: "err"; msg: string };

function About({ t }: { t: Theme }) {
  const [ver, setVer] = useState("");
  const [up, setUp] = useState<UpdateState>({ k: "idle" });
  // ★ 同 App.tsx：走同一个 `fullVersion()`，别在这里再拼一次 `+B`。
  useEffect(() => { void fullVersion().then(setVer).catch(() => setVer("?")); }, []);

  const check = async () => {
    if (up.k === "busy") return;
    setUp({ k: "busy" });
    try {
      // `{tag, via, clone}`：clone 装法教「git pull + deploy.sh」，安装包装法教「下载新版」（samchen #5）
      const r = JSON.parse(await invoke<string>("check_update")) as { tag: string; clone: boolean };
      setUp(isNewer(r.tag, ver) ? { k: "new", v: r.tag, clone: !!r.clone } : { k: "latest", v: r.tag });
    } catch (e: unknown) {
      setUp({ k: "err", msg: String(e).slice(0, 120) });
    }
  };

  const link: React.CSSProperties = {
    color: t.isDark ? "#5eead4" : "#0e7a6e", cursor: "pointer", textDecoration: "none",
    borderBottom: `1px solid ${t.isDark ? "rgba(94,234,212,.4)" : "rgba(14,122,110,.4)"}`,
  };

  // ★ S1 关于 = 行式：图标 44 + 名称 + 版本状态 + 检查更新；项目地址一行。有新版 / 出错的文案与链接原样保留（README「关于页保留现版」）。
  return (
    <>
      <div className="set-row" data-about style={{ display: "flex", alignItems: "center", gap: 12, minHeight: 60, padding: "10px 0", boxSizing: "border-box" }}>
        <img src={logo} width={44} height={44} alt="AICoop" style={{ borderRadius: 12, flexShrink: 0, boxShadow: "0 4px 14px rgba(0,0,0,.45)" }} />
        <div title="Tauri 2 + React · macOS" style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
          <div style={{ fontSize: 17, fontWeight: 500, color: t.text }}>AICoop</div>
          <div style={{ fontSize: 12.5, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: t.muted }}>
            <span style={{ color: t.isDark ? "#5eead4" : "#0e7a6e" }}>{ver ? `v${ver}` : "…"}</span>
            {up.k === "latest" && <span style={{ color: t.isDark ? "#27B26B" : "#177a46" }}> · ✓ 已是最新（远端 {up.v}）</span>}
            {up.k === "new" && <>
              <span style={{ color: t.isDark ? "#E0A21C" : WARN_TX_LIGHT, fontWeight: 600 }}> · 有新版 {up.v}</span>{" "}
              <span style={link} onClick={() => { void openExternal(`${REPO_URL}/releases`); }}>查看更新说明 ↗</span>
            </>}
            {up.k === "err" && <span title={up.msg} style={{ color: "#E0524D" }}> · ✗ {up.msg}</span>}
          </div>
          {up.k === "new" && (
            <div style={{ fontSize: 12, color: t.muted, fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {up.clone
                ? <>更新：<code>git pull && bash codexbar/scripts/deploy.sh</code></>
                : <>更新：在更新说明页下载新的 .dmg，拖进「应用程序」替换</>}
            </div>
          )}
        </div>
        <span style={{ flex: 1 }} />
        <SBtn t={t} onClick={() => { void check(); }} disabled={up.k === "busy"} attrs={{ "data-act": "check-update" }}
              title="向 GitHub 查最新发布的版本。这是本页唯一联网的动作">
          {up.k === "busy" ? "检查中…" : "检查更新"}
        </SBtn>
      </div>
      <OneLineRow t={t} label="项目地址">
        {/* 外链走本仓 `open_url` 在系统浏览器打开;webview 里直接导航会把整个 app 变成网页 */}
        <span style={{ ...link, fontSize: 12.5, fontFamily: "'JetBrains Mono'" }} onClick={() => { void openExternal(REPO_URL); }}
              title="在浏览器打开">github.com/{REPO} ↗</span>
      </OneLineRow>
    </>
  );
}
