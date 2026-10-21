import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { parsePayload, type ReqRow } from "../requests";

/**
 * 请求账本的只读快照（`read_requests` → `traffic/requests.py --json`，最近 2 个本地自然日）。
 * 代理轮换页（每号 t/s）与中转站页（今日每入口次数、账号池今日请求 / token）共用。
 * ★ 读不到 ⇒ 保持上一次的行（首次就是空表），不清空。但 `ok` 只说**最近一次成功的读数还算新**
 *   （10 分钟内、且是今天读的）：评审阶段 5 —— 一次成功之后 `ok` 永远为真，取数一直失败时
 *   旧快照被当成现在的读数，跨午夜还会把昨天的快照筛成「今日 0」。2 分钟重读一次。
 */
export function useReqLedger(): { rows: ReqRow[]; ok: boolean; at: number | null } {
  const [rows, setRows] = useState<ReqRow[]>([]);
  const [at, setAt] = useState<number | null>(null);
  const [, tick] = useState(0);
  useEffect(() => {
    let alive = true;
    const go = () => {
      tick((n) => n + 1);
      invoke<string>("read_requests")
        .then((raw) => {
          if (!alive) return;
          const pl = parsePayload(raw);
          if (pl.requests.length || pl.ok) setRows(pl.requests);
          if (pl.ok) setAt(Date.now() / 1000);
        })
        .catch(() => { /* 读不到 ⇒ 沿用上一次的行；`at` 不动，过 10 分钟 `ok` 自己变假 */ });
    };
    go();
    const id = setInterval(go, 120_000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return { rows, ok: reqFresh(at, Date.now() / 1000), at };
}

/** 最近一次成功读数还算不算「现在」：10 分钟内且同一个本地自然日。 */
export function reqFresh(at: number | null, nowSec: number): boolean {
  if (at == null || nowSec - at > 600) return false;
  return new Date(at * 1000).toDateString() === new Date(nowSec * 1000).toDateString();
}
