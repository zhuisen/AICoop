import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { dayKeys, dayMetrics, filterPlatform, parsePayload, rowsForDay, PLATFORM_ORDER } from "../../requests";

/**
 * 「今日」Tab 各家均速：今天这家所有请求 t/s 的平均（`requests.ts::dayMetrics`，与请求页同一个算法）。
 *
 * ★ 不复用 `useRequests`：那个 hook 依赖设置页模块、10 s 轮询整张两天的表，菜单栏只要四个数。
 *   这里只在今日 Tab 可见时读一次 + 每 60 s 一次。
 * ★ 读不到（命令还没合入 / 账本坏了）⇒ 保留上一份；一次都没读到 ⇒ 空对象，界面写 —（不写 0）。
 */
export function useTodayTps(enabled: boolean): Record<string, number | null> {
  const [by, setBy] = useState<Record<string, number | null>>({});
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const load = async () => {
      try {
        const p = parsePayload(await invoke<string>("read_requests"));
        if (!alive || (!p.ok && !p.requests.length)) return;
        const today = dayKeys(p, Date.now()).today;
        const rows = rowsForDay(p.requests, today);
        const out: Record<string, number | null> = {};
        for (const k of PLATFORM_ORDER) out[k] = dayMetrics(filterPlatform(rows, k)).avgTps;
        setBy(out);
      } catch (_e: unknown) {
        // 保留上一份（§7.0b）：这次没读到 ≠ 今天没有请求。
      }
    };
    void load();
    const id = window.setInterval(() => { void load(); }, 60_000);
    return () => { alive = false; window.clearInterval(id); };
  }, [enabled]);
  return by;
}
