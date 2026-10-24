/**
 * **账号池**的平台清单 —— 主窗总览的分档 Tab 与菜单栏的 logo 芯片行**共用这一份**
 * （菜单栏 v4 交接稿 §9.1：「平台集合单一数据源」）。
 *
 * ★★★ **这不是「AI 用量」那张表。** 两者回答的是不同的问题，用户 2026-09-13 拍板分开：
 *
 *     账号池（本文件，3 家）  = 我有凭证、能管的号     → codex / gemini / grok
 *     AI 用量（scan.py 注册表，8 家）= 本机哪些 CLI 落了盘 → 还含 claude / kimi / deepseek / mimo / …
 *
 *   强行统一会让用量页少掉 Claude（本机占 77.8%），或让账号页多出五个管不了的档。
 *
 * ★ `colorKey` 与 `key` **故意不同名**：账号池这边叫 `gemini`（用户定的叫法），
 *   而取色要去用量注册表里找，那家在 `scan.py` 里的键是 `agy`。
 *   一律走 `colorOf(traffic, colorKey)`，别在组件里写死色值。
 */
export type PoolKey = "codex" | "claude" | "gemini" | "grok";

export interface PoolPlatform {
  key: PoolKey;
  label: string;
  /** 去 `colorOf(traffic, …)` 取识别色用的键（= `traffic/scan.py` 注册表里的键）。 */
  colorKey: string;
  /** 这一档的账号**是怎么轮换的**。三家机制根本不同，不写就会被当成一样的。 */
  note: string;
  /**
   * 这一档有没有「检查 token / 探针」这两个动作。
   *
   * ★★★ **只有 codex 有，这是与 v4 稿的一处刻意偏离。** 稿 §5 把 Grok 也算进
   *   「刷新全池｜检查 token｜探针」那一组，但那假设 grok 也有自己的账号池与探针；
   *   本机的实测事实是：grok 是**单号只读**，而 `探针` 跑的是 `codex-rotate probe --all`
   *   —— 它扣的是 **codex** 的额度。挂在 Grok 档上就是用户看着 grok 的卡按下去、
   *   花的是另一家的钱，正是本仓判过死刑的那一类。稿与事实冲突时以事实为准。
   */
  codexActions: boolean;
  /** 加号时要用户去终端敲的命令（没有就给一句说明）。 */
  addHint: string;
}

export const POOL_PLATFORMS: readonly PoolPlatform[] = [
  { key: "codex", label: "Codex", colorKey: "codex", codexActions: true,
    note: "账号池 · 经本地代理逐请求换号 · 5h/周双窗口",
    addHint: "加号：终端里跑 `codex-rotate login`" },
  // ★ 2026-10-19 交接包 page5：总览平台档 Codex → Claude → Gemini → Grok（同光晕顺序）。
  //   Claude 本机只有 1 个号、没有账号池后端 ⇒ 这一档只看额度，不切号、不探针（PLAN §4）。
  { key: "claude", label: "Claude", colorKey: "claude", codexActions: false,
    note: "Claude Code · 本机 1 个号 · 只看额度",
    addHint: "Claude 只有本机一个号 —— 登录由 Claude Code 自己管" },
  { key: "gemini", label: "Gemini", colorKey: "agy", codexActions: false,
    // ★ 「启动前换凭证」是**设计事实**不是缺陷：agy 只在进程启动时读凭证，
    //   所以换号只对下一次启动生效，已经开着的会话不受影响。
    note: "Antigravity · 启动前换凭证（agy 只在启动时读）",
    addHint: "加号：终端里跑 `agy-rotate login`" },
  { key: "grok", label: "Grok", colorKey: "grok", codexActions: false,
    note: "Grok · 单号 · 周窗口",
    addHint: "grok 是单号 —— 登录由 grok CLI 自己管" },
] as const;

export const platformOf = (k: PoolKey): PoolPlatform =>
  POOL_PLATFORMS.find(p => p.key === k) ?? POOL_PLATFORMS[0];

/**
 * 总览上 `⌘1~⌘N` 切到第几档（用户 2026-10-16：「command+数字是切换 codex、gemini、grok，
 * 而不是切换对应的账号」）。★ 序号就是 Tab 的显示顺序 —— 两者都读 `POOL_PLATFORMS`。
 * 超出档数返回 `undefined`（⌘4~⌘9 什么也不做，绝不落到别的动作上）。
 */
export const poolKeyAt = (idx: number): PoolKey | undefined =>
  Number.isInteger(idx) && idx >= 0 ? POOL_PLATFORMS[idx]?.key : undefined;

const STORE_KEY = "codexbar_provider";

/**
 * 记住的分档 —— **只在这一次运行里记**（sessionStorage）。
 * ★ 用户 2026-10-24「为什么默认还是跳到 gemini？超过 1 分钟后也是」：原来存 localStorage、跨启动永远记住，
 *   上次停在 Gemini，之后每次重启 / 部署、每次没点名平台的打开都回 Gemini。WKWebView 退出即清 sessionStorage ⇒
 *   冷启动恒为 Codex；运行中隐藏 ≥ 1 分钟再打开回 Codex 由 `landingProvider` + Rust 的 `fresh` 管（同菜单栏弹窗 10-22 那条）。
 * 仍认旧值 `google` / `xai`（2026-09-13 之前的写法）。
 */
export function loadPoolKey(): PoolKey {
  try {
    const v = sessionStorage.getItem(STORE_KEY);
    if (v === "google" || v === "gemini") return "gemini";
    if (v === "xai" || v === "grok") return "grok";
    if (v === "claude") return "claude";
  } catch { /* 读不了，落到默认 */ }
  return "codex";
}

export function savePoolKey(k: PoolKey): void {
  try { sessionStorage.setItem(STORE_KEY, k); } catch { /* 写不了，忽略 */ }
}

/** 默认档。 */
export const DEFAULT_POOL_KEY: PoolKey = "codex";

/**
 * 主窗口这次打开落在哪一档。`named` = 入口点名的平台（托盘右键 / 账号行 / 额度格子）；
 * `fresh` = 冷启动或隐藏 ≥ 1 分钟后再打开（Rust 判，`main-open-page` 带过来）。
 * 点名的优先；没点名：新的一次打开回默认，否则保持当前档（1 分钟内重开多半是误关）。
 */
export function landingProvider(cur: PoolKey, named: PoolKey | null, fresh: boolean): PoolKey {
  return named ?? (fresh ? DEFAULT_POOL_KEY : cur);
}
