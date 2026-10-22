/**
 * 设置页「Claude 实测速度」那一行的状态 → 文案（`claude_otel_env.py status --json` 的契约）。
 * ★ 零 import：`tests/test_claude_otel_env.py` 用 `node --experimental-strip-types` 直接跑（CI 没有 node_modules）。
 */

export interface ClaudeOtelStatus {
  ok: boolean;
  state: "off" | "partial" | "on" | "conflict" | "error";
  ui: "off" | "partial" | "on_receiving" | "on_waiting" | "on_down" | "conflict" | "error";
  error: string | null;
  conflicts: string[];
  settings: string;
  receiver: { last_post_at: number | null; listening: boolean | null; error: string | null; port_open: boolean | null };
}

export const CLAUDE_OTEL_DESC =
  "开了之后 Claude Code 把每次请求的耗时与 token 发到本机接收端，不含对话内容；新开的 Claude Code 会话生效";

/** 开关画成「开」吗。`null` = 读不到（画成半透明，不假装是关着的）。 */
export function claudeOtelOn(st: ClaudeOtelStatus | null): boolean | null {
  if (!st || st.state === "error") return null;
  return st.state === "on";
}

/** 冲突时不让点：点了也不会写。 */
export function claudeOtelLocked(st: ClaudeOtelStatus | null): boolean {
  return !!st && st.state === "conflict";
}

function hhmm(sec: number, now: Date): string {
  const d = new Date(sec * 1000);
  const p = (n: number): string => String(n).padStart(2, "0");
  const t = `${p(d.getHours())}:${p(d.getMinutes())}`;
  return d.toDateString() === now.toDateString() ? t : `${p(d.getMonth() + 1)}-${p(d.getDate())} ${t}`;
}

/** 说明下面那一行（`⚠` 开头 = 琥珀）。`null` = 不画。`readErr` = IPC 本身失败。 */
export function claudeOtelWarn(st: ClaudeOtelStatus | null, readErr: string | null, now: Date = new Date()): string | null {
  if (readErr) return `⚠ 读不到状态：${readErr}`;
  if (!st) return null;
  // 写入被拒（冲突 / 文件刚被改过）时 `ok=false`，原因优先于状态。
  if (!st.ok && st.error && st.state !== "conflict") return `⚠ ${st.error}`;
  switch (st.ui) {
    case "conflict": {
      const n = st.conflicts.length;
      const head = st.conflicts.slice(0, 2).join("、");
      return `⚠ 已有别的 OTel 配置（${head}${n > 2 ? ` 等 ${n} 项` : ""}），没有改动`;
    }
    case "on_receiving":
      return st.receiver.last_post_at ? `已收到数据 · 最近 ${hhmm(st.receiver.last_post_at, now)}` : null;
    case "on_waiting":
      return "⚠ 还没收到数据：重开 Claude Code 会话";
    case "on_down":
      return st.receiver.error ? `⚠ ${st.receiver.error}` : "⚠ 接收端没在运行：在「账号池接入」装常驻服务";
    case "partial":
      // ★ 只有一部分键是我们的值（另一部分被删了 / 没写全）：开关画成「关」，点一下会补齐（全方面评审 §6）
      return "⚠ 只配好了一部分：点开关补齐";
    case "error":
      return st.error ? `⚠ ${st.error}` : "⚠ 读不到 Claude Code 的设置";
    default:
      return null;
  }
}
