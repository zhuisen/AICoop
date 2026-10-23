import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { applyLiveCacheMode, parseLive, type LiveSnapshot } from "../live";
import { useCacheMode } from "./useCacheMode";

/**
 * 「谁在跑、多快」：先读一次 `read_live`，之后只收 Rust 推的 `tps-live`。
 * ★ 读失败保留上一份（§7.0b），`error` 单独给，UI 自己决定怎么说。
 * ★ token 数已按设置里的「缓存计入口径」重塑（`applyLiveCacheMode`）——所有入口同一个口径。
 */
export function useLive(): { live: LiveSnapshot | null; error: string | null } {
  const [live, setLive] = useState<LiveSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { mode } = useCacheMode();

  useEffect(() => {
    let alive = true;
    invoke<string>("read_live")
      .then((raw) => {
        if (!alive) return;
        const s = parseLive(raw);
        if (s) { setLive(s); setError(null); } else setError("实时速度数据格式不对");
      })
      .catch((e: unknown) => { if (alive) setError(String(e)); });
    const un = listen<string>("tps-live", (ev) => {
      const s = parseLive(ev.payload);
      if (s) { setLive(s); setError(null); }
    });
    // ★ Rust 跑 `--live` 失败 / 超时时广播它（全方面评审 §8：原来没人听，面板照画旧 t/s，与托盘的「—」对不上）。
    //   旧数留着（§7.0b），只记原因；下一份 `tps-live` 到了就清
    const unErr = listen<string>("tps-live-error", (ev) => { setError(String(ev.payload || "读不到实时速度")); });
    return () => {
      alive = false;
      un.then((f) => f()).catch(() => undefined);
      unErr.then((f) => f()).catch(() => undefined);
    };
  }, []);

  const shaped = useMemo(() => applyLiveCacheMode(live, mode), [live, mode]);
  return { live: shaped, error };
}
