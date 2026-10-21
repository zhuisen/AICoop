import { fullVersion, isWindowsUI } from "../helpers";
import { NOTCH_DESC, notchRowDesc, notchRowWarn, type NotchStatus } from "../notchSegs";
import { useState, useEffect, useMemo, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit } from "@tauri-apps/api/event";
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
import Seg from "../components/Seg";
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
  autoRefresh: boolean;
  /** 空闲托盘（AICoop P11 §7）：空闲时菜单栏画 AI 图标（true）还是原来的文字标题（false）。 */
  idleIcons: boolean;
  idleSlots: 2 | 3;
  idleRankBy: "requests" | "tokens";
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
  autoRefresh: true,         // 后台自动保鲜默认**开**(现有行为)。关掉只停后台心跳,
                             // 「打开页面/弹出托盘就刷新」照旧 —— 见 useTraffic 的 autoRefreshEnabled()
  idleIcons: true,           // P11 §7 默认「AI 图标」；文字标题四档仍在（选它时 `trayStyle` 生效）
  idleSlots: 3,
  idleRankBy: "requests",
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
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { return DEFAULTS; }
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

const IconSun = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9 17.7 6.3M6.3 17.7 4.9 19.1"/></svg>;
const IconMoon = () => <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>;
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
 * 设置行的**不折行**版（交接包全局规则：文字一律 nowrap，放不下先省略号、全文在悬浮里）。
 * `warn` = 第二行原因（刘海屏「开着但没显示」），单独一行，不跟在说明末尾被省略掉。
 * ★ 模块作用域（同 `NumInput`）：写在 render 里每次都是新组件类型，开关的 transition 会变成死代码。
 */
function OneLineRow({ t, label, desc, warn, title, children }: {
  t: Theme; label: string; desc: string; warn?: string | null; title?: string; children: React.ReactNode;
}): React.ReactElement {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", borderBottom: `1px solid ${t.divider}` }}>
      <div title={title ?? desc} style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text, ...ONE_LINE }}>{label}</div>
        <div style={{ fontSize: 10.5, color: t.muted, marginTop: 2, ...ONE_LINE }}>{desc}</div>
        {warn && <div data-row-warn style={{ fontSize: 10.5, marginTop: 2, ...ONE_LINE,
                                              color: !warn.startsWith("⚠") ? t.muted : t.isDark ? AMBER_TEXT : WARN_TX_LIGHT }}>{warn}</div>}
      </div>
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
      <div data-claude-otel-toggle={on == null ? "unknown" : on ? "on" : "off"} onClick={() => void toggle()} style={{
        width: 38, height: 22, borderRadius: 11, padding: 2, flexShrink: 0, marginLeft: 12,
        cursor: busy || locked || on == null ? "default" : "pointer",
        opacity: busy || locked || on == null ? 0.5 : 1,
        background: on ? t.accent : t.barTrack, transition: "background .2s",
      }}>
        <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: on ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
      </div>
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
  const toggleBorrow = useCallback(async () => {
    const next = !borrow;
    try {
      await invoke("run_rotate", { args: ["borrow", next ? "--on" : "--off"] });
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
    const next = !agyBorrow;
    try {
      await invoke("run_agy_rotate", { args: ["borrow", next ? "--on" : "--off"] });
      void emit("agy-pool-updated");      // 续航条的「下一个」可能随之变化
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

  const Row = ({ label, desc, children }: { label: string; desc: string; children: React.ReactNode }) => (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", borderBottom: `1px solid ${t.divider}` }}>
      <div><div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>{label}</div><div style={{ fontSize: 10.5, color: t.muted, marginTop: 2 }}>{desc}</div></div>
      {children}
    </div>
  );


  return (
    // ★ 外层内容区是 `overflow: hidden`(App.tsx),**每个页面自带滚动容器**是本项目的约定 ——
    //   总览和用量页都有,设置页原来漏了,于是窗口一矮下面的「关于」整块就被裁掉、没有滚动条
    //   (用户 2026-08-09 实测截图)。加页面时别忘这一条。
    <div style={{ display: "flex", flexDirection: "column", gap: 0,
                  minHeight: 0, height: "100%", overflowY: "auto",
                  // 滚动条压住右侧滑块/开关不好点,给一点右内边距
                  paddingRight: 4 }}>
      <span style={{ fontSize: 20, fontWeight: 700, marginBottom: 12, flexShrink: 0 }}>设置</span>

      <Row label="开机自启" desc="登录 macOS 时自动启动 AICoop(后台常驻菜单栏)">
        <div onClick={toggleAutostart} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: autostartBusy ? "default" : "pointer",
          background: autostart ? t.accent : t.barTrack, transition: "background .2s", opacity: autostartBusy ? 0.6 : 1,
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: autostart ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </Row>

      {/* desc 是纯文本、不过 markdown —— 写 `**x**` 会原样渲染成星号(2026-08-12 截图里抓到) */}
      <Row label="在程序坞显示" desc="开启后，主界面打开时在 Dock 占一格，可 ⌘Tab 切换；关掉主界面立刻让出位置。即时生效，无需重启">
        <div onClick={() => {
          const next = !s.dockVisible;
          update({ dockVisible: next });
          invoke("set_dock_visible", { on: next }).catch(() => {});
        }} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer",
          background: s.dockVisible ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: s.dockVisible ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </Row>

      {/* ★ 日夜切换（交接包 2026-10-19：从标题栏 / 菜单栏弹窗移到设置）。写 `codexbar_theme` + 广播
          `theme-changed`（`saveTheme`），主窗口、菜单栏弹窗、悬停面板都跟着变。 */}
      <OneLineRow t={t} label="外观" desc="深色 / 浅色。主窗口、菜单栏弹窗、悬停面板一起切换；刘海卡片始终深色">
        <div data-theme-row style={{ display: "flex", alignItems: "center", gap: 2, padding: 2, flexShrink: 0, marginLeft: 12,
                                     border: `1px solid ${t.ghostBorder}`, borderRadius: 9 }}>
          {(["light", "dark"] as const).map((v) => {
            const on = theme === v;
            return (
              <span key={v} data-theme-pick={v} data-on={on ? 1 : 0} onClick={() => onTheme(v)}
                    style={{ display: "flex", alignItems: "center", gap: 5, padding: "4px 11px", borderRadius: 7,
                             fontSize: 11, whiteSpace: "nowrap", cursor: "pointer", userSelect: "none",
                             fontWeight: on ? 700 : 400, color: on ? t.accentText : t.muted,
                             background: on ? t.accent : "transparent", transition: "background .2s, color .2s" }}>
                {v === "light" ? <IconSun /> : <IconMoon />}{v === "light" ? "浅色" : "深色"}
              </span>
            );
          })}
        </div>
      </OneLineRow>

      {/* ★ 刘海屏版本（交接包 2026-10-19 DECISIONS「刘海屏版本」；取代 PR #1 的「刘海额度条」，开关与存储键沿用）。
          开 = Rust 建窗口 + 装鼠标监听，关 = 销毁窗口（不是隐藏，默认关的功能不常驻任何进程）。启动时由 App.tsx 再应用一次。
          Windows 没有刘海，整行不画。★ 开着但没显示 ⇒ 第二行说出原因（`notchRowWarn`）。 */}
      {!isWindowsUI() && (
      <OneLineRow t={t} label="刘海屏版本" desc={NOTCH_DESC} warn={notchRowWarn(s.notchHud, notchSt, notchErr)}
                  title={notchRowDesc(s.notchHud, notchSt, notchErr)}>
        <div data-notch-toggle onClick={() => {
          const next = !s.notchHud;
          update({ notchHud: next });
          setNotchErr(null);
          invoke<NotchStatus>("set_notch_hud", { on: next })
            .then((st) => setNotchSt(st ?? null))
            // ★ 失败就把开关拨回去并说原因 —— 不许出现「开关是开的、屏幕上什么都没有、也没人说为什么」
            .catch((e: unknown) => {
              setS((p) => { const n = { ...p, notchHud: !next }; save(n); return n; });
              setNotchErr(String(e).slice(0, 120));
            });
        }} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer", flexShrink: 0, marginLeft: 12,
          background: s.notchHud ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: s.notchHud ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </OneLineRow>
      )}

      {/* ★ 空闲时菜单栏（AICoop P11 / P9 S1「菜单栏与刘海」）。AI 图标 = 空闲托盘（官方 logo，用掉的部分由上往下变灰）；
          文字标题 = 原来的四档（下面换成「文字标题样式」，托盘 6 行隐藏）。设置改完广播 `IDLE_TRAY_EVENT`：
          选位与取数在常驻的菜单栏 webview（`useIdleTray`），localStorage 跨 webview 不推送。Windows 托盘没有图，整组不画。 */}
      {!isWindowsUI() && (
      <OneLineRow t={t} label="空闲时菜单栏" desc="显示 2–3 家 AI 图标，用掉的额度变灰；在跑时始终是 t/s 胶囊">
        <div style={{ flexShrink: 0, marginLeft: 12 }} data-idle-icons>
          <Seg opts={["icons", "text"] as const} cur={s.idleIcons ? "icons" : "text"} t={t}
               label={(v) => (v === "icons" ? "AI 图标" : "文字标题")}
               on={(v) => updIdle({ idleIcons: v === "icons" })} />
        </div>
      </OneLineRow>
      )}

      {!isWindowsUI() && s.idleIcons && (<>
      <OneLineRow t={t} label="菜单栏显示几家" desc="常驻 2 家 + 动态 1 家（24 h 内最近用过）；剩余 < 10% 的插队占动态位，带红点">
        <div style={{ flexShrink: 0, marginLeft: 12 }}>
          <Seg opts={[2, 3] as const} cur={s.idleSlots} t={t} label={(v) => `${v} 家`} on={(v) => updIdle({ idleSlots: v })} />
        </div>
      </OneLineRow>
      <OneLineRow t={t} label="排序依据" desc="决定常驻哪 2 家和悬停面板顺序">
        <div style={{ flexShrink: 0, marginLeft: 12 }}>
          <Seg opts={["requests", "tokens"] as const} cur={s.idleRankBy} t={t}
               label={(v) => (v === "requests" ? "请求数" : "Token 数")} on={(v) => updIdle({ idleRankBy: v })} />
        </div>
      </OneLineRow>
      <OneLineRow t={t} label="统计窗口" desc="排名、插队、悬停面板共用；每天 00:00（本机时区）重算">
        <div style={{ flexShrink: 0, marginLeft: 12 }}>
          <Seg opts={[7, 14, 30] as const} cur={s.idleDays} t={t} label={(v) => `${v} 天`} on={(v) => updIdle({ idleDays: v })} />
        </div>
      </OneLineRow>
      <OneLineRow t={t} label="固定到菜单栏"
                  desc={s.idlePinned.length ? `固定的先占常驻位；选第 3 家时挤掉最早固定的` : "不固定 · 按排名自动选常驻 2 家"}>
        <div data-idle-pin style={{ display: "flex", gap: 2, padding: 2, flexShrink: 0, marginLeft: 12,
                                     border: `1px solid ${t.ghostBorder}`, borderRadius: 9 }}>
          {TRAY_KEYS.map((k) => {
            const on = s.idlePinned.includes(k);
            return (
              <span key={k} data-pin={k} data-on={on ? 1 : 0}
                    onClick={() => updIdle({ idlePinned: on ? s.idlePinned.filter((x) => x !== k) : [...s.idlePinned, k].slice(-2) })}
                    style={{ padding: "4px 9px", borderRadius: 7, fontSize: 11, whiteSpace: "nowrap", cursor: "pointer",
                             userSelect: "none", fontWeight: on ? 700 : 400, color: on ? t.accentText : t.muted,
                             background: on ? t.accent : "transparent", transition: "background .2s, color .2s",
                             display: "inline-flex", alignItems: "center", gap: 5 }}>
                <PlatformLogo platform={k as LogoPlatform} isDark={t.isDark} size={14} />
                {IDLE_NAME[k]}
              </span>
            );
          })}
        </div>
      </OneLineRow>
      <OneLineRow t={t} label="鼠标靠近光晕" desc="鼠标移近托盘时，每个 logo 后亮起平台色光晕">
        <div data-idle-glow onClick={() => updIdle({ idleGlow: !s.idleGlow })} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer", flexShrink: 0, marginLeft: 12,
          background: s.idleGlow ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: s.idleGlow ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </OneLineRow>
      <OneLineRow t={t} label="打招呼"
                  desc={`${s.idleHello === "idle1h" ? "空闲 1 小时后第一次靠近托盘时" : "每天第一次靠近托盘时"}，logo 依次轻跳一下；有 AI 在跑或面板开着时跳过`}>
        <div style={{ flexShrink: 0, marginLeft: 12 }}>
          <Seg opts={["off", "daily", "idle1h"] as const} cur={s.idleHello} t={t}
               label={(v) => (v === "off" ? "关闭" : v === "daily" ? "每天一次" : "空闲 1 小时后")}
               on={(v) => updIdle({ idleHello: v })} />
        </div>
      </OneLineRow>
      </>)}

      {/* ★ 悬停面板（P9 S1「悬停面板」组；P11 §6）：空闲时悬停托盘弹出各家剩余额度格子，两种空闲托盘都弹。
          样式目前只有「格子 · 精简」（「列表 · 全量」未做，不放一个点了没反应的选项）。 */}
      {!isWindowsUI() && (<>
      <OneLineRow t={t} label="悬停显示哪些" desc="鼠标移到菜单栏时弹出各家剩余额度；菜单栏里的排最前">
        <div style={{ flexShrink: 0, marginLeft: 12 }}>
          <Seg opts={["used", "all", "bar"] as const} cur={s.idleHoverScope} t={t}
               label={(v) => (v === "used" ? "用过的" : v === "all" ? "全部" : "只看菜单栏")} on={(v) => updIdle({ idleHoverScope: v })} />
        </div>
      </OneLineRow>
      <OneLineRow t={t} label="悬停最多显示" desc="一行 4 家；两行 8 家">
        <div style={{ flexShrink: 0, marginLeft: 12 }}>
          <Seg opts={[4, 8] as const} cur={s.idleHoverMax} t={t} label={(v) => (v === 4 ? "4 家 · 一行" : "8 家 · 两行")}
               on={(v) => updIdle({ idleHoverMax: v })} />
        </div>
      </OneLineRow>
      <OneLineRow t={t} label="悬停细节" desc="格子大数字固定是 5h 额度；按量计费的不写重置时间">
        <div data-idle-detail style={{ display: "flex", gap: 2, padding: 2, flexShrink: 0, marginLeft: 12,
                                       border: `1px solid ${t.ghostBorder}`, borderRadius: 9 }}>
          {([["idleHoverReset", "重置时间"], ["idleHoverUnconnected", "未接入的平台"]] as const).map(([k, lab]) => {
            const on = s[k];
            return (
              <span key={k} data-detail={k} data-on={on ? 1 : 0} onClick={() => updIdle({ [k]: !on })}
                    style={{ padding: "4px 9px", borderRadius: 7, fontSize: 11, whiteSpace: "nowrap", cursor: "pointer",
                             userSelect: "none", fontWeight: on ? 700 : 400, color: on ? t.accentText : t.muted,
                             background: on ? t.accent : "transparent", transition: "background .2s, color .2s" }}>
                {lab}
              </span>
            );
          })}
        </div>
      </OneLineRow>
      </>)}

      {/* ★ 菜单栏标题样式。Rust 侧存在 `TRAY_STYLE`(atomic),这里改完立刻调命令刷标题;
          启动时由 App.tsx 再应用一次 —— 否则重启后 Rust 回到默认 0,设置还显示着别的档。 */}
      {(isWindowsUI() || !s.idleIcons) && (
      <Row label="文字标题样式" desc={trayStyleDesc(s.trayStyle)}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0, marginLeft: 12 }}>
          <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono'", color: t.text2,
                         background: t.isDark ? "#0e1319" : t.cardBg, whiteSpace: "nowrap",
                         border: `1px solid ${t.cardBorder}`, padding: "4px 9px", borderRadius: 7 }}>
            {trayStyleSample(s.trayStyle)}
          </span>
          <Seg opts={TRAY_STYLES} cur={s.trayStyle} label={trayStyleLabel} t={t}
               on={(v) => {
                 update({ trayStyle: v });
                 invoke("set_tray_style", { style: TRAY_STYLES.indexOf(v) }).catch(() => {});
               }} />
        </div>
      </Row>
      )}

      {/* ★ 在跑时显示 t/s（交接包 page 1 托盘胶囊，默认开）。Rust 的开关是进程内 atomic、默认关，
          所以 App.tsx 每次启动重发一次（同 `set_tray_style`）。关 ⇒ Rust 立刻画回额度标题（`tray_pill::set_enabled`），
          悬停面板也随之不再弹（`is_running` 先看开关）。Windows 托盘没有文字，整行不画。 */}
      {!isWindowsUI() && (
      <OneLineRow t={t} label="在跑时显示 t/s" desc="有 AI 在跑时，菜单栏标题换成各家 logo + 实时 t/s；鼠标移上去看各会话速度。关掉 = 始终显示额度标题">
        <div data-tps-toggle onClick={() => {
          const next = !s.tpsTray;
          update({ tpsTray: next });
          invoke("set_tps_tray", { enabled: next }).catch(() => {});
        }} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer", flexShrink: 0, marginLeft: 12,
          background: s.tpsTray ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: s.tpsTray ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </OneLineRow>
      )}

      <ClaudeOtelRow t={t} />

      {/* ★ 动效开关（用户 2026-08-16）。关掉＝**完全不播**，不是播快一点 —— 与
          `prefers-reduced-motion` 同语义，两者任一为「关」就不动画。
          只影响主窗那两张图与 KPI；菜单栏没有入场动效，所以不需要跨 webview 广播。 */}
      <Row label="入场动效"
           desc="打开「AI 用量信息」或切时间档时，图表从左往右揭开、KPI 数字从 0 滚上来。关掉后数据直接到位（系统里开了「减弱动态效果」时本来就不播）。">
        <div onClick={() => update({ intro: !s.intro })} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer", flexShrink: 0,
          background: s.intro ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff",
                        transform: s.intro ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </Row>

      {/* ★ 后台自动刷新开关（用户 2026-08-19）。**只管后台心跳这一个触发点** ——
          「进入用量页」与「弹出托盘」两条照常刷新，所以关掉不会得到一个再也不更新的页面。
          关掉的价值是「别在我读数的时候把地板抽走」：每 2 分钟数据静默换一批，正在看的数字会跳，
          跨午夜时整张图还会因为数据集身份变了而重挂。
          ⚠️ 与它配套的是「上次刷新」旁边的分级陈旧提示 —— 没有那个，这就成了一个
          能静默显示旧数字的开关，正是本项目一直在防的那类东西。 */}
      <Row label="后台自动刷新"
           desc="界面开着时每 2 分钟在后台重扫一次本机 transcript。关掉后只在「进入用量页 / 弹出菜单栏 / 点 ↻」时更新——数据变旧时「上次刷新」旁会显示已过去多久，超过 30 分钟转琥珀。">
        <div onClick={() => update({ autoRefresh: !s.autoRefresh })} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer", flexShrink: 0,
          background: s.autoRefresh ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff",
                        transform: s.autoRefresh ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </Row>

      <PlatformSection t={t} />

      {/* ★ 缓存计入口径。**token 数与费用同时跟着变** —— 两者都由那四个互不相交的类算出来,
          只改一个会让「总费用」和「总 token」说的不是同一批数据。改动即时同步到菜单栏「今日」
          (走 Tauri 事件广播;两个 webview 的 localStorage 不互通)。 */}
      <Row label="缓存计入口径" desc={cacheModeDesc(cacheMode)}>
        {/* `Row` 是 space-between,右侧控件默认可被压缩。这一格是三档中文标签(比其余行的开关宽得多),
            窗口拉窄时会被左边那段说明文字挤到变形 —— 固定住它,让说明文字去换行。 */}
        <div style={{ flexShrink: 0, marginLeft: 12 }}>
          <Seg opts={CACHE_MODES} cur={cacheMode} on={setCacheMode} label={cacheModeLabel} t={t} />
        </div>
      </Row>

      <Row label="额度低自动切号" desc="当前号额度低于阈值时自动切到最佳号(默认关)">
        <div onClick={() => update({ autoSwitchEnabled: !s.autoSwitchEnabled })} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer",
          background: s.autoSwitchEnabled ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: s.autoSwitchEnabled ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </Row>
      {s.autoSwitchEnabled && (
        <Row label="自动切号阈值" desc="当前号剩余额度低于此值(%)时触发">
          <NumInput value={s.autoSwitchThreshold} onChange={v => update({ autoSwitchThreshold: v })} min={5} max={50} suffix="%" t={t} />
        </Row>
      )}
      {/* 「每日清晨探针」2026-10-15 搬到总览各档工具栏的「定时」胶囊（`DawnChip`），时间可选。 */}
      {/* ★★ 用户 2026-09-21 拍板加的开关，原话：「我明明停止轮换了，应该就不能去调用」。
          代理的最后一层兜底本来是硬编码的：一个能用的号都没有时忽略 `rotate_off` 借一个
          （理由是「codex 整个不能用」比「多用一个你不想用的号」更糟）。两种都成立，所以做成开关。
          ★ 真源在 `state.json`（代理在 app 没开时也要读它），**不在 localStorage**。
          ★ 存反向：缺省 = 允许借用 = 既有行为；关回默认时**删键**。 */}
      <Row label="池子空时借用已停用的号"
           desc={borrow == null
             ? "读不到这项设置 —— 不是「已关闭」，是这次没读到"
             : borrow
             ? "一个可用的号都没有时，临时借一个你停用的号，并在总览顶部标红说明。关掉 = 宁可 codex 报错"
             : "已关闭：无号可用时代理直接报错，绝不动你停用的号（那段时间 codex 会失败）"}>
        <div onClick={() => void toggleBorrow()} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer",
          background: borrow ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: borrow ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </Row>
      <Row label="Gemini 池子空时借用已停用的号"
           desc={agyBorrow == null
             ? "读不到这项设置 —— 不是「已关闭」，是这次没读到"
             : agyBorrow
             ? "启动 agy 时一个可用的号都没有，就临时借一个你停用的号，并在总览顶部标红说明。关掉 = 不换号，agy 照用当前号跑"
             : "已关闭：无号可用时启动 agy 不换号，绝不动你停用的号"}>
        <div data-agy-borrow onClick={() => void toggleAgyBorrow()} style={{
          width: 38, height: 22, borderRadius: 11, padding: 2, cursor: "pointer",
          background: agyBorrow ? t.accent : t.barTrack, transition: "background .2s",
        }}>
          <div style={{ width: 18, height: 18, borderRadius: 9, background: "#fff", transform: agyBorrow ? "translateX(16px)" : "translateX(0)", transition: "transform .2s" }} />
        </div>
      </Row>
      <Row label="订阅到期预警" desc="订阅剩余天数 ≤ 此值时在卡片和通知中提醒">
        <NumInput value={s.subExpiryWarnDays} onChange={v => update({ subExpiryWarnDays: v })} min={1} max={30} suffix="天" t={t} />
      </Row>
      <Row label="Token 过期预警" desc="access token 剩余小时 ≤ 此值时提醒">
        <NumInput value={s.tokenExpiryWarnHours} onChange={v => update({ tokenExpiryWarnHours: v })} min={6} max={120} suffix="h" t={t} />
      </Row>

      {/* The tray no longer carries a native menu (both mouse buttons open the popover instead), so
          this is the quit path. Confirm first — with the Dock icon off (the default) a stray click
          here would leave the menu bar empty with no obvious way back. */}
      <Row label="退出 AICoop" desc="完全退出(菜单栏图标消失);仅关闭窗口用 ⌘W">
        {!confirmQuit ? (
          <span onClick={() => setConfirmQuit(true)} style={{ fontSize: 11.5, fontWeight: 600, color: "#E0524D", border: "1px solid #E0524D40", padding: "6px 13px", borderRadius: 8, cursor: "pointer", userSelect: "none" }}>退出</span>
        ) : (
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span onClick={() => invoke("quit_app").catch(() => {})} style={{ fontSize: 11.5, fontWeight: 700, color: "#fff", background: "#E0524D", padding: "6px 13px", borderRadius: 8, cursor: "pointer", userSelect: "none" }}>确认退出</span>
            <span onClick={() => setConfirmQuit(false)} style={{ fontSize: 11.5, color: t.muted, padding: "6px 10px", cursor: "pointer", userSelect: "none" }}>取消</span>
          </div>
        )}
      </Row>

      <About t={t} />
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
 * ★ 排序**只影响列表与图例**。堆叠图层仍按占比降序("占大头的铺满基线比悬在半空清楚",
 *   2026-08-09 看了两版实物定的),这次没动它。
 *
 * 用 ↑↓ 而不是拖拽:四五行的列表,拖拽要处理 HTML5 DnD 的一堆边界,而本项目键盘可达性本来就是 0,
 * 再加一个只能用鼠标的交互没有收益。
 */
function PlatformSection({ t }: { t: Theme }) {
  const { prefs, setPrefs } = usePlatformPrefs();
  // 只读一次快照就够:这里要的是"有哪几家、各自多少量",不需要保鲜,也不该在设置页触发扫描。
  const [snap, setSnap] = useState<TrafficData | null>(null);
  useEffect(() => {
    invoke<string | null>("read_traffic_snapshot")
      .then((raw) => { if (raw) setSnap(JSON.parse(raw) as TrafficData); })
      .catch(() => { /* 没扫过就没有快照,列表回落到偏好里记过的键 */ });
  }, []);

  // ★ 列表必须**包含已停用的**,否则停用之后就再也找不到它、开不回来了。
  //   所以枚举 = 快照里的键 ∪ 偏好里记过的键。
  const keys = useMemo(() => {
    const all = new Set([...Object.keys(snap?.platforms ?? {}), ...Object.keys(prefs.by), ...prefs.order]);
    const vol = (k: string) =>
      Object.values(snap?.platforms[k]?.days ?? {}).reduce((s, b) => s + b.total, 0);
    return orderedKeys([...all], prefs, vol);
  }, [snap, prefs]);

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
    <div style={{ padding: "12px 0", borderBottom: `1px solid ${t.divider}` }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>AI 平台</div>
        <div style={{ fontSize: 10.5, color: t.muted, flex: 1 }}>
          改名 · 改色 · 停用 · 排序。停用的不计入总 token 与总费用；排序只影响列表与图例，
          堆叠图仍按占比大的贴基线。
        </div>
        {dirty && (
          <span onClick={() => setPrefs({ order: [], by: {} })}
                style={{ fontSize: 10.5, color: t.muted, cursor: "pointer", whiteSpace: "nowrap",
                         border: `1px solid ${t.ghostBorder}`, padding: "3px 9px", borderRadius: 7 }}>
            全部复位
          </span>
        )}
      </div>

      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        {keys.length === 0 && (
          <div style={{ fontSize: 11, color: t.muted }}>还没有扫描过，去「AI用量信息」页跑一次就会出现。</div>
        )}
        {keys.map((k, i) => {
          const p = snap?.platforms[k];
          const o = prefs.by[k] ?? {};
          const off = !!o.off;
          const color = o.color || p?.color || platformColor(k);
          const missing = !p;      // 偏好里有、快照里没有 ⇒ scan.py 已不再注册它
          return (
            <div key={k} style={{
              display: "flex", alignItems: "center", gap: 8, padding: "7px 9px", borderRadius: 9,
              background: t.isDark ? "#0e1319" : t.cardBg, border: `1px solid ${t.cardBorder}`,
              opacity: off ? 0.5 : 1, transition: "opacity .15s",
            }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                {([-1, 1] as const).map((d) => {
                  // 到头了就真的不可点:8px 的箭头本来就难瞄准,再让它"点了没反应"会以为坏了
                  const dead = d < 0 ? i === 0 : i === keys.length - 1;
                  return (
                    <span key={d} onClick={dead ? undefined : () => move(i, d)}
                          title={dead ? "" : d < 0 ? "上移" : "下移"}
                          style={{ fontSize: 10, lineHeight: 1, padding: "2px 5px", borderRadius: 4,
                                   cursor: dead ? "default" : "pointer", userSelect: "none",
                                   color: dead ? t.muted : t.muted,
                                   background: "transparent", transition: "background .12s" }}
                          onMouseEnter={(e) => { if (!dead) e.currentTarget.style.background = "rgba(255,255,255,.07)"; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
                      {d < 0 ? "▲" : "▼"}
                    </span>
                  );
                })}
              </div>

              {/* 原生取色器:WKWebView 里可用,不必自己造一个色板 */}
              <input type="color" value={color} onChange={(e) => patch(k, { color: e.target.value })}
                     title={`${k} 的识别色（图表 / 图例 / 徽章共用）`}
                     style={{ width: 22, height: 22, padding: 0, border: "none", borderRadius: 6,
                              background: "transparent", cursor: "pointer", flexShrink: 0 }} />

              {/* 官方 logo（AICoop 交接包）；没有 logo 的平台画识别色方块，占同一个位置 */}
              <span data-platform-logo={k} style={{ width: 18, height: 18, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                {LOGO_KEYS.includes(k)
                  ? <PlatformLogo platform={k as LogoPlatform} isDark={t.isDark} size={18} />
                  : <span style={{ width: 12, height: 12, borderRadius: 3, background: color }} />}
              </span>

              <input value={o.name ?? p?.name ?? k} onChange={(e) => patch(k, { name: e.target.value })}
                     placeholder={p?.name ?? k}
                     style={{ width: 108, fontSize: 12, fontFamily: "'JetBrains Mono'", color: t.text,
                              background: "transparent", border: `1px solid ${t.ghostBorder}`,
                              borderRadius: 6, padding: "3px 7px", outline: "none" }} />

              <span style={{ fontSize: 9.5, color: t.muted, fontFamily: "'JetBrains Mono'" }}>{k}</span>

              {missing && (
                <span title="偏好里还留着它，但当前扫描结果里没有这一家（scan.py 未注册或该 CLI 未安装）"
                      style={{ fontSize: 9, fontWeight: 700, color: "#E0901C" }}>无数据</span>
              )}

              <span style={{ marginLeft: "auto", fontSize: 10, color: t.muted,
                             fontFamily: "'JetBrains Mono'", whiteSpace: "nowrap" }}>
                {p ? fmtTok(Object.values(p.days).reduce((s, b) => s + b.total, 0)) : "—"}
              </span>

              <div onClick={() => patch(k, { off: !off })}
                   title={off ? "启用：重新计入总量与图表" : "停用：从图表与总量中完全移除（可随时开回来）"}
                   style={{ width: 34, height: 20, borderRadius: 10, padding: 2, cursor: "pointer",
                            background: off ? t.barTrack : t.accent, transition: "background .2s", flexShrink: 0 }}>
                <div style={{ width: 16, height: 16, borderRadius: 8, background: "#fff",
                              transform: off ? "translateX(0)" : "translateX(14px)", transition: "transform .2s" }} />
              </div>
            </div>
          );
        })}
      </div>

      <DiscoverPanel t={t} snap={snap} />

      <div style={{ fontSize: 10, color: t.muted, marginTop: 9, lineHeight: 1.6 }}>
        ⚠️ <b>新增一家平台不在这里</b>。能扫出哪几家由 <code>traffic/scan.py</code> 的注册表决定——
        加一家等于写一个解析器（实测四家四种 token 形状，DeepSeek 还是第五种），
        做成填路径的表单就只能去猜字段名，那正是会静默算错数的做法。
      </div>
    </div>
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
                        ? { color: "#E0901C", background: "rgba(224,144,28,.08)", border: "1px solid rgba(224,144,28,.35)" }
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
    ok: t.accent, ambiguous: "#E0901C", reject: "#E0524D", unknown: t.muted,
  };

  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${t.divider}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span onClick={() => { void run(); }}
              title="遍历本机候选目录,找还有哪些地方存着 AI token 用量。只读本地文件,不联网、不碰凭证"
              style={{ fontSize: 11.5, fontWeight: 600, whiteSpace: "nowrap",
                       color: busy ? t.muted : t.accentText,
                       background: busy ? t.barTrack : t.accent,
                       padding: "6px 13px", borderRadius: 8,
                       cursor: busy ? "default" : "pointer", userSelect: "none" }}>
          {busy ? "扫描中…（约 40 秒）" : "扫描新数据源"}
        </span>
        <span style={{ fontSize: 10, color: t.muted, lineHeight: 1.5 }}>
          找本机还有哪些 AI 把用量落了盘，并<b>实测</b>它的口径（哪些字段加起来等于 total ⇒ 缓存要不要减）。
          <b>已注册但被停用</b>的源可一键启用；<b>新发现</b>的不能——实测只证明了<b>算术</b>
          （哪些字段之和等于 total），没证明<b>语义</b>（某字段是输入还是输出、算不算缓存读），
          而四类 token 单价不同，归错类会静默算出错的费用。把下面的结果发给我，我来写解析器。
        </span>
      </div>

      <SourceStatusBlock t={t} snap={snap} />

      {err && <div style={{ fontSize: 10.5, color: "#E0524D", marginTop: 8,
                            fontFamily: "'JetBrains Mono'" }}>✗ {err}</div>}

      {res && (
        <div style={{ marginTop: 9, display: "flex", flexDirection: "column", gap: 5 }}>
          <div style={{ fontSize: 10, color: t.muted }}>
            扫了 {res.roots} 个候选目录，{res.candidates.length} 个含 token 用量记录
          </div>
          {res.candidates.map((c) => (
            <div key={c.root} style={{ padding: "7px 10px", borderRadius: 8,
                                       background: t.isDark ? "#0e1319" : t.cardBg,
                                       border: `1px solid ${t.cardBorder}` }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {/* ★ 三档,不是两档:「已注册」与「在扫」是两件事 —— 被停用的源有解析器却一条都不解析,
                    两档写法会让它显示「已注册」而用户以为数据已经在图里了。 */}
                <span style={{ fontSize: 8.5, fontWeight: 700, padding: "2px 6px", borderRadius: 5,
                               color: !c.known ? t.accentText : c.enabled === false ? "#fff" : t.muted,
                               background: !c.known ? t.accent : c.enabled === false ? "#E0901C" : t.ghostBg }}>
                  {!c.known ? "新发现" : c.enabled === false ? "已停用" : "已注册"}
                </span>
                <span style={{ fontSize: 11.5, fontFamily: "'JetBrains Mono'", color: t.text }}>{c.root}</span>
                <span style={{ marginLeft: "auto", fontSize: 9.5, color: t.muted,
                               fontFamily: "'JetBrains Mono'" }}>
                  {c.files} 文件 · {c.records} 条
                </span>
                {/* ★ 只有「已注册但被停用」能一键启用 —— 它已经有手写解析器,启用只是把它从
                    disabled 列表里拿掉。新发现的**不给按钮**:见下方说明,那不是懒,是不能。 */}
                {c.known && c.enabled === false && c.key && (
                  <span onClick={() => { void enable(c.key!); }}
                        title="把它从扫描层的停用列表里移除,下次扫描即纳入"
                        style={{ fontSize: 9.5, fontWeight: 700, padding: "3px 9px", borderRadius: 6,
                                 color: t.accentText, background: t.accent, cursor: "pointer",
                                 userSelect: "none", whiteSpace: "nowrap" }}>
                    启用
                  </span>
                )}
              </div>
              <div style={{ fontSize: 10, color: COLOR[c.state], marginTop: 4, lineHeight: 1.5 }}>
                {c.verdict}
              </div>
              {c.models.length > 0 && (
                <div style={{ fontSize: 9.5, color: t.muted, marginTop: 3,
                              fontFamily: "'JetBrains Mono'" }}>
                  {c.models.slice(0, 6).map((m) => `${m.model} ${fmtTok(m.total)}`).join(" · ")}
                </div>
              )}
            </div>
          ))}
          <div style={{ fontSize: 9.5, color: t.muted, lineHeight: 1.6, marginTop: 2 }}>
            判定干净（青色）只说明<b>值得接</b>，不等于能直接用：这个扫描测得出口径，
            <b>测不出去重规则</b>。OpenClaw 那次朴素求和虚高 4.08x，是靠找到 <code>responseId</code> 才消掉的。
          </div>
        </div>
      )}
    </div>
  );
}

const REPO = "zhuisen/codex-account-rotator";
const REPO_URL = `https://github.com/${REPO}`;

/** 语义化版本比较。**不能按字符串比** —— 那样 0.10.0 会被判成小于 0.9.0。 */
function isNewer(remote: string, current: string): boolean {
  const parse = (v: string) => v.replace(/^v/, "").split(".").map((x) => parseInt(x, 10) || 0);
  const [a, b, c] = parse(remote), [x, y, z] = parse(current);
  return a !== x ? a > x : b !== y ? b > y : c > z;
}

type UpdateState =
  | { k: "idle" }
  | { k: "busy" }
  | { k: "latest"; v: string }
  | { k: "new"; v: string }
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
      const tag = await invoke<string>("check_update");
      setUp(isNewer(tag, ver) ? { k: "new", v: tag } : { k: "latest", v: tag });
    } catch (e: unknown) {
      setUp({ k: "err", msg: String(e).slice(0, 120) });
    }
  };

  const link: React.CSSProperties = {
    color: t.accent, cursor: "pointer", textDecoration: "none",
    borderBottom: `1px solid ${t.accent}44`,
  };

  return (
    <div style={{ marginTop: 22, paddingTop: 16, borderTop: `1px solid ${t.divider}` }}>
      {/* ★ 账号池接入。放在「关于」之前、其余设置之后 —— 它不是日常开关,
          而是**一次性的装机动作**,但用户随时可能回来撤销,所以不藏进二级页面。 */}
      <ConnectorPanel t={t} />

      <div style={{ fontSize: 12, fontWeight: 600, color: t.muted, marginBottom: 12 }}>关于</div>
      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <img src={logo} width={64} height={64} alt="AICoop"
             style={{ borderRadius: 14, flexShrink: 0,
                      boxShadow: "0 4px 16px rgba(0,0,0,.35)" }} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 9 }}>
            <span style={{ fontSize: 19, fontWeight: 700 }}>AICoop</span>
            <span style={{ fontSize: 12.5, fontWeight: 700, color: t.accent,
                           fontFamily: "'JetBrains Mono'" }}>{ver ? `v${ver}` : "…"}</span>
          </div>
          <div style={{ fontSize: 11, color: t.muted, marginTop: 3,
                        fontFamily: "'JetBrains Mono'" }}>
            Tauri 2 + React · macOS
          </div>
          {/* 外链走 shell 插件在系统浏览器打开;webview 里直接导航会把整个 app 变成网页 */}
          <div style={{ fontSize: 11, marginTop: 7, fontFamily: "'JetBrains Mono'" }}>
            <span style={link} onClick={() => { void openExternal(REPO_URL); }}
                  title="在浏览器打开">github.com/{REPO} ↗</span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12,
                        flexWrap: "wrap" }}>
            <span onClick={() => { void check(); }}
                  title="向远端查最新 tag(私有仓库走 git 凭证)。这是本页唯一联网的动作"
                  style={{ fontSize: 11.5, fontWeight: 600,
                           color: up.k === "busy" ? t.muted : t.accentText,
                           background: up.k === "busy" ? t.barTrack : t.accent,
                           padding: "6px 13px", borderRadius: 8,
                           cursor: up.k === "busy" ? "default" : "pointer", userSelect: "none",
                           transition: "background .15s" }}>
              {up.k === "busy" ? "检查中…" : "检查更新"}
            </span>
            {up.k === "latest" && (
              <span style={{ fontSize: 11, color: "#27B26B", fontFamily: "'JetBrains Mono'" }}>
                ✓ 已是最新（远端 {up.v}）
              </span>
            )}
            {up.k === "new" && (
              <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono'" }}>
                <span style={{ color: "#E0A21C", fontWeight: 700 }}>有新版 {up.v}</span>{" "}
                <span style={link} onClick={() => { void openExternal(`${REPO_URL}/releases`); }}>
                  查看更新说明 ↗
                </span>
                <span style={{ color: t.muted }}>　·　更新：<code>git pull && bash codexbar/scripts/deploy.sh</code></span>
              </span>
            )}
            {up.k === "err" && (
              <span style={{ fontSize: 10.5, color: "#E0524D", fontFamily: "'JetBrains Mono'" }}>
                ✗ {up.msg}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
