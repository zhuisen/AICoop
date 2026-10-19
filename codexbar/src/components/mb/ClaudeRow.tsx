import QuotaRow, { type WinCell } from "./QuotaRow";
import { isStale, type ClaudeQuota, type ClaudeWin } from "../../mbLogic";
import { fmtEta, fmtAgo } from "../../helpers";

/**
 * 菜单栏里的 Claude 行（交接包 2026-10-19 · 4f）：一个号「本机」，5h / 周来自
 * `read_statusline_quota`（状态栏转写；没有时退回 Claude.app 的 plan-usage-history）。
 *
 * ★ 偏离交接包（PLAN §4）：交接包写「Claude 可切号、可探针」。本机只有 1 个 Claude 号，仓库也没有
 *   Claude 账号池后端（切号要写 Claude Code 凭证，已定不碰）⇒ 这一行**不出「切换」**，底栏也不给探针。
 * ★ 剩余 = 100 − 已用（`mbLogic.parseClaudeQuota` 已换算）。读不到写 —，**绝不写 0**。
 * ★ plan-usage-history 没有重置时间 ⇒ ↻ 写 —。读数超过 30 分钟 ⇒ 两格降不透明度，悬浮说出是多久前的。
 */
export default function ClaudeRow({ quota, isDark, nowSec, onOpen }: {
  quota: ClaudeQuota | null;
  isDark: boolean;
  nowSec: number;
  onOpen: () => void;
}) {
  const stale = !!quota && isStale(quota.capturedAt, nowSec);
  const ago = quota?.capturedAt ? fmtAgo(quota.capturedAt) : null;
  const srcNote = quota?.source === "plan-usage-history" ? "来自 Claude.app（没有重置时间）" : "来自 Claude Code 状态栏";
  const cell = (w: ClaudeWin | null, label: string): WinCell => w
    ? { label, pct: w.rem, refill: w.idle ? "未启动" : w.resetsAt ? fmtEta(w.resetsAt) : "—", dim: stale,
        refillTitle: w.idle ? "上一个窗口已重置，之后的状态栏读数没有再报这个窗口" : w.resetsAt ? undefined : "这个来源不给重置时间",
        title: `${srcNote}${ago ? ` · ${ago}的读数` : ""}` }
    : { label, pct: null, refill: "—", title: "这一格读不到 —— 跑一次 Claude Code 后会补上" };
  const has = !!quota && (quota.fiveH != null || quota.week != null);
  return (
    <QuotaRow platform="claude" isDark={isDark} name="本机" readOnly onOpen={onOpen}
              sub={<span style={{ color: stale ? "var(--warn)" : "var(--tx3)" }}
                         title={ago ? `${srcNote} · ${ago}` : srcNote}>
                     {stale ? `${ago ?? "旧"}读数` : quota?.source === "plan-usage-history" ? "Claude.app" : "状态栏"}</span>}
              wins={has ? [cell(quota!.fiveH, "5h"), cell(quota!.week, "周")] : undefined}
              note="— 额度读不到 · 跑一次 Claude Code 后显示"
              data={{ "data-mb-claude": has ? (stale ? "stale" : "ok") : "none" }} />
  );
}
