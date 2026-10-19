// 「谁在跑、多快」的共享纯逻辑（零 import —— 测试用 node --experimental-strip-types 直接跑）。
//
// 数据来自 `traffic/requests.py --live`（Rust 每 2s 跑一次，事件 `tps-live` 推给所有 webview）。
// 交接包 2026-10-19 全局规则，所有入口（托盘胶囊 / 悬停面板 / 刘海卡片 / 菜单栏在跑条 / 总览在用号）同源同值：
//   · 速度只在同一个 AI 内合计；任何界面都不出现跨 AI 合计。
//   · 在跑但还没完成第一条响应 ⇒ `—`，不写 0，也不计入合计。
//   · t/s 只写数字，不加「≈」「估」。

export type PlatformKey = "codex" | "claude" | "agy" | "grok";

/** 固定顺序，与光晕 / 托盘槽位一致。 */
export const PLATFORM_ORDER: PlatformKey[] = ["codex", "claude", "agy", "grok"];

export const PLATFORM_NAME: Record<PlatformKey, string> = {
  codex: "Codex", claude: "Claude", agy: "Gemini", grok: "Grok",
};

/** 交接包 README「平台顺序与颜色」。main = 主色 / 光晕；num = 数字色（按底色深浅）。 */
export const PLATFORM_HUE: Record<PlatformKey, { main: string; numDark: string; numLight: string }> = {
  codex: { main: "#2DD4BF", numDark: "#5EEAD4", numLight: "#0E9F8E" },
  claude: { main: "#E0784F", numDark: "#F09A76", numLight: "#C2562F" },
  agy: { main: "#4D9FFF", numDark: "#7AB8FF", numLight: "#2B6FD6" },
  grok: { main: "#8B7CF6", numDark: "#B9AEFB", numLight: "#6B5BD6" },
};

export function numColor(k: PlatformKey, theme: "dark" | "light"): string {
  return theme === "light" ? PLATFORM_HUE[k].numLight : PLATFORM_HUE[k].numDark;
}

export interface LiveSession {
  id: string;
  title: string;
  tps: number | null;
  tokens: number;
  last_t_end: number | null;
  active: boolean;
}

export interface LivePlatform {
  running: boolean;
  n_sessions: number;
  tps: number | null;
  tokens_today: number;
  sessions: LiveSession[];
}

export interface LiveSnapshot {
  v: number;
  generated_at: number;
  platforms: Partial<Record<PlatformKey, LivePlatform>>;
  today: { tokens: number; avg_tps: number | null; n: number };
}

/** 后端给的 JSON 字符串 → 快照；形状不对返回 null（「读不到」，不是「没人在跑」）。 */
export function parseLive(raw: unknown): LiveSnapshot | null {
  let o: unknown = raw;
  if (typeof raw === "string") {
    try { o = JSON.parse(raw); } catch (_e: unknown) { return null; }
  }
  if (!o || typeof o !== "object") return null;
  const r = o as Record<string, unknown>;
  if (typeof r.platforms !== "object" || r.platforms === null) return null;
  const today = (r.today && typeof r.today === "object" ? r.today : {}) as Record<string, unknown>;
  return {
    v: typeof r.v === "number" ? r.v : 0,
    generated_at: typeof r.generated_at === "number" ? r.generated_at : 0,
    platforms: r.platforms as LiveSnapshot["platforms"],
    today: {
      tokens: typeof today.tokens === "number" ? today.tokens : 0,
      avg_tps: typeof today.avg_tps === "number" ? today.avg_tps : null,
      n: typeof today.n === "number" ? today.n : 0,
    },
  };
}

export interface RunningRow {
  key: PlatformKey;
  tps: number | null;
  tokens: number;
  sessions: LiveSession[];
  nSessions: number;
}

/** 在跑的平台，按固定顺序。tps 只在同一平台内合计（后端已算，这里兜底重算一次以防后端字段缺失）。 */
export function runningRows(snap: LiveSnapshot | null): RunningRow[] {
  if (!snap) return [];
  const out: RunningRow[] = [];
  for (const k of PLATFORM_ORDER) {
    const p = snap.platforms[k];
    if (!p || !p.running) continue;
    const sessions = (p.sessions ?? []).filter((s) => s.active);
    out.push({
      key: k,
      tps: typeof p.tps === "number" ? p.tps : sumTps(sessions),
      tokens: sessions.reduce((a, s) => a + (s.tokens || 0), 0) || p.tokens_today || 0,
      sessions,
      nSessions: p.n_sessions || sessions.length,
    });
  }
  return out;
}

/** 有数的才相加；全部没数 ⇒ null（显示 —）。 */
export function sumTps(sessions: { tps: number | null }[]): number | null {
  let acc = 0;
  let any = false;
  for (const s of sessions) {
    if (typeof s.tps === "number" && Number.isFinite(s.tps)) { acc += s.tps; any = true; }
  }
  return any ? acc : null;
}

/** t/s 显示：整数，读不到写 —。 */
export function fmtTps(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? String(Math.round(v)) : "—";
}

/** Token：≥ 1M 写 1.2M，否则 860k（< 1k 写原数）。 */
export function fmtTokens(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return Math.round(n / 1e3) + "k";
  return String(Math.round(n));
}
