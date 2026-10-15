import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { DawnKind, DawnStatus } from "../dawn";

/**
 * 某一家定时探针的开关 / 时间 / 上次运行。总览工具栏的 `DawnChip` 用。
 *
 * ★★ **真源是 CLI 管的那份文件**（codex `state.json` / agy `.agy-pool.json`），**不是** localStorage ——
 *   launchd 在 app 没开时也要读这个开关，两个真源迟早分叉成「界面说开着、定时器不认」。
 * ★ 读走只读通道：codex `read_dawn_status`（不广播）；agy `run_agy_rotate`（本来就不广播）。
 * ★ 写完**无论成败都回读**：不拿「我打算设成什么」冒充「它现在是什么」。
 */
export function useDawnStatus(kind: DawnKind, active: boolean): {
  rec: DawnStatus | null; busy: boolean;
  toggle: () => Promise<void>; setTime: (hhmm: string) => Promise<void>;
} {
  const [rec, setRec] = useState<DawnStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const raw = kind === "codex"
        ? await invoke<string>("read_dawn_status")
        : await invoke<string>("run_agy_rotate", { args: ["dawn-probe", "--status"] });
      setRec(JSON.parse(raw.trim().split("\n").pop() || "{}") as DawnStatus);
    } catch {
      setRec({});           // 读不到就当「未开启」，不编造一个「已开启」
    }
  }, [kind]);

  useEffect(() => { if (active) void load(); }, [active, load]);

  const write = useCallback(async (args: string[]) => {
    setBusy(true);
    try {
      await (kind === "codex"
        ? invoke("run_rotate", { args: ["dawn-probe", ...args] })
        : invoke("run_agy_rotate", { args: ["dawn-probe", ...args] }));
    } catch {
      // 回读会把真实状态画出来；这里不另报错，避免同一件事两条提示。
    } finally {
      setBusy(false);
      void load();
    }
  }, [kind, load]);

  const toggle = useCallback(() => write([rec?.enabled ? "--disable" : "--enable"]), [rec, write]);
  const setTime = useCallback((hhmm: string) => write(["--time", hhmm]), [write]);
  return { rec, busy, toggle, setTime };
}
