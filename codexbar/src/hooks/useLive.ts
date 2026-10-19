import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { parseLive, type LiveSnapshot } from "../live";

/**
 * 「谁在跑、多快」：先读一次 `read_live`，之后只收 Rust 推的 `tps-live`。
 * ★ 读失败保留上一份（§7.0b），`error` 单独给，UI 自己决定怎么说。
 */
export function useLive(): { live: LiveSnapshot | null; error: string | null } {
  const [live, setLive] = useState<LiveSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    return () => { alive = false; un.then((f) => f()).catch(() => undefined); };
  }, []);

  return { live, error };
}
