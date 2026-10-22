import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { RotEvent } from "../../overview";

/** 轮换数据里总览要用的那一小块（与日志页 `Rotation` 同一份 JSON，只取三样）。 */
export interface RotationDay {
  events: RotEvent[];
  segments: { acc: string; start?: number; end: number; tokens: number }[];
  generated_at: number;
}

/** 两次「现扫」之间至少隔多久。现扫要遍历 rollout（实测 24h 窗口 1.7 s），总览只要今天的切换与每号最后一次在岗。 */
const RESCAN_MS = 5 * 60_000;
const lastScan: Record<string, number> = {};

function pick(raw: unknown): RotationDay | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (!Array.isArray(o.events) || !Array.isArray(o.segments)) return null;
  return { events: o.events as RotEvent[], segments: o.segments as RotationDay["segments"],
           generated_at: typeof o.generated_at === "number" ? o.generated_at : 0 };
}

/**
 * 「今天的切换」与卡片 ③ 行「上次用 · 今日」的数据源 —— 与日志页**同一个**轮换解析器
 * （codex `traffic/rotation.py`、Gemini `traffic/agy_rotation.py`），不另写一份。
 *
 * ★ codex 先读成品快照 `read_rotation_snapshot`（读盘 ~1 ms），再按 `RESCAN_MS` 节流后台现扫一次；
 *   Gemini 没有快照，直接现扫（同样节流）。
 * ★ 读不到**不清空**已读到的（§7.0b）：失败只记 `err`，界面继续画上一份并照实说「—」。
 */
export function useRotationDay(source: "codex" | "agy", enabled: boolean): { rot: RotationDay | null; err: string | null } {
  const [rot, setRot] = useState<RotationDay | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const busy = useRef(false);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const scan = async (force: boolean) => {
      if (busy.current) return;
      const now = Date.now();
      if (!force && now - (lastScan[source] ?? 0) < RESCAN_MS) return;
      busy.current = true;
      lastScan[source] = now;
      try {
        const r = pick(await invoke(source === "agy" ? "read_agy_rotation" : "read_proxy_rotation", { hours: 24 }));
        if (alive && r) { setRot(r); setErr(null); }
      } catch (e: unknown) {
        if (alive) setErr(String(e).slice(0, 160));
      } finally {
        busy.current = false;
      }
    };
    void (async () => {
      if (source === "codex") {
        try {
          const s = pick(await invoke("read_rotation_snapshot", { hours: 24 }));
          if (alive && s) setRot(s);
        } catch (e: unknown) {
          if (alive) setErr(String(e).slice(0, 160));
        }
      }
      await scan(false);
    })();
    const id = window.setInterval(() => { void scan(false); }, RESCAN_MS);
    const un = listen(source === "agy" ? "agy-live-changed" : "state-changed", () => { void scan(false); });
    return () => { alive = false; window.clearInterval(id); void un.then((f) => f()); };
  }, [source, enabled]);
  return { rot, err };
}
