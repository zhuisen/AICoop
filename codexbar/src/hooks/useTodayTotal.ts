import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { applyCacheMode, applyPlatformPrefs, todayView, type TrafficData } from "../traffic";
import { useCacheMode } from "./useCacheMode";
import { usePlatformPrefs } from "./usePlatformPrefs";

/**
 * 「今日 N」总数：用量快照（全部 AI，含 Kimi / DeepSeek）按缓存口径 + 平台偏好重塑后的 `todayView().totalTok`，
 * 与菜单栏「今日」Tab、刘海卡片同一个数（2026-10-23 token 审查：悬停面板原来用请求账本，只有四家、恒含缓存）。
 * 只读盘（`read_traffic_snapshot`）+ 收 `traffic-updated`，不自己扫。快照还没读到 ⇒ null，调用方退回实时账本。
 */
export function useTodayTotal(): number | null {
  const [traffic, setTraffic] = useState<TrafficData | null>(null);
  const { mode } = useCacheMode();
  const { prefs } = usePlatformPrefs();
  const read = useCallback(() => {
    invoke<string | null>("read_traffic_snapshot").then((raw) => {
      if (!raw) return;
      let d: TrafficData;
      try { d = JSON.parse(raw) as TrafficData; } catch (_e: unknown) { return; }
      setTraffic((prev) => (prev && prev.generated_at >= d.generated_at ? prev : d));
    }).catch((_e: unknown) => undefined);   // 读不到 ⇒ 保留上一份（§7.0b）
  }, []);
  useEffect(() => {
    read();
    const un = listen("traffic-updated", read);
    return () => { void un.then((f) => f()); };
  }, [read]);
  return useMemo(() => todayView(applyPlatformPrefs(applyCacheMode(traffic, mode), prefs))?.totalTok ?? null,
                 [traffic, mode, prefs]);
}
