import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { parseClaudeQuota, type ClaudeQuota } from "../mbLogic";

/**
 * Claude 本机账号的 5h / 周额度：`invoke("read_statusline_quota")`（PLAN §2.2 / §2.3，
 * 跑 `traffic/statusline_quota.py --read`，只读本机盘，不联网、不碰凭证）。
 *
 * ★ 「读不到」不覆盖「已读到」（CLAUDE.md §7.0b）：命令失败 / 输出坏了 ⇒ 保留上一份，只置 `err`。
 * ★ 只在 `enabled` 时读（菜单栏停在 Claude 档、或要给通知条算低额度时）。每 60 s 一次 +
 *   托盘弹出时一次 —— 状态栏转写本身就只在 Claude Code 刷新状态栏时才变，读得再勤也没有新数。
 * ★ 后端命令可能还不存在（Rust 切片未合入）：invoke 抛错 ⇒ `quota` 仍为 null，界面写 —。
 */
export function useClaudeQuota(enabled: boolean): { quota: ClaudeQuota | null; err: string | null; refresh: () => void } {
  const [quota, setQuota] = useState<ClaudeQuota | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const inflight = useRef(false);

  const load = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    try {
      const raw = await invoke<string>("read_statusline_quota");
      const q = parseClaudeQuota(raw);
      if (q) { setQuota(q); setErr(null); } else setErr("额度转写的格式不对");
    } catch (e: unknown) {
      setErr(String(e));
    } finally {
      inflight.current = false;
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void load();
    const id = window.setInterval(() => { void load(); }, 60_000);
    const un = listen("menubar-shown", () => { void load(); });
    return () => { window.clearInterval(id); void un.then((f) => f()); };
  }, [enabled, load]);

  const refresh = useCallback(() => { void load(); }, [load]);
  return { quota, err, refresh };
}
