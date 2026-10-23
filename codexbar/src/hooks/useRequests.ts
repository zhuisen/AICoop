import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getSettings } from "../pages/SettingsPage";
import { mergePayload, parsePayload, sinceOf, type ReqPayload } from "../requests";

/**
 * 「请求」页取数：`invoke("read_requests")` → `traffic/requests.py --json`（PLAN §2.3 / §2.1）。
 *
 * ★★ **「读不到」不覆盖「已读到」**（CLAUDE.md §7.0b，用户提过三次）：
 *   - IPC 失败 / 输出不是合法 JSON → **保留上次的列表**，只置 `err`；界面把列表降到 55% 不透明
 *     并在上方给红条（读不到请求账本 + 上次读到的时间 + 原因 + 重试）。**绝不清空。**
 *   - 后端自己报 `ok:false`（它按 §2.1 已保留旧账本并给 `stale_since`）→ 采纳它带回的行；
 *     它若一行都没带回来而我们手里有，仍保留我们的（"这次拿到空" ≠ "确实没有"）。
 *   - 第一次就失败 → `payload` 为 null、`err` 有值：页面显示红条 + 空列表，不假装"今天还没有请求"。
 *
 * 轮询 10 s：每条响应写完才出现，后端按游标增量读，一次很便宜。跟随设置页「后台自动刷新」开关，
 * 关掉时只在进页和点「重试」时读（与 `useQuotaSidecar` 同一个开关）。
 */
const POLL_MS = 10_000;
/** 每隔多少次轮询整份读一次（30 × 10 s = 5 分钟）。增量只回 `since` 往前 10 分钟之后的行；
 *  更早的行若被后端改过（少见），靠这次整读补上。 */
const FULL_EVERY = 30;

function autoRefreshEnabled(): boolean {
  try { return getSettings().autoRefresh !== false; } catch { return true; }
}

export interface RequestsState {
  /** 最近一份可用的数据（可能是旧的，见 `err`）。null = 一次都没读到过。 */
  payload: ReqPayload | null;
  /** 这份数据是什么时候读到的（ms）。读失败时就是红条里的「上次读到的时间」。 */
  readAt: number | null;
  /** 最近一次读取失败的原因；null = 最近一次成功。 */
  err: string | null;
  /** 读失败的是哪几家（`"*"` = 全部）；null = 最近一次成功。 */
  failed: string[] | null;
  busy: boolean;
  retry: () => void;
}

export function useRequests(enabled: boolean): RequestsState {
  const [payload, setPayload] = useState<ReqPayload | null>(null);
  const [readAt, setReadAt] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [failed, setFailed] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);
  const alive = useRef(true);
  /** 上一份原文。★ 两天的账本实测 2453 行（本机 2026-10-19）；内容没变就不换 payload，
   *  否则每 10 s 整张表重渲一次。 */
  const lastRaw = useRef<string | null>(null);
  /** 手里那份（给 `since` 用；state 在回调里读不到最新值）。 */
  const held = useRef<ReqPayload | null>(null);
  /** 距上次整读的轮询次数。 */
  const sinceFull = useRef(0);

  const load = useCallback(async (forceFull = false) => {
    if (inflight.current) return;
    inflight.current = true;
    setBusy(true);
    try {
      // ★ 增量（用户 2026-10-23）：手里有数据就只要 `since` 之后的行（实测 4.7 MB → 20 KB），每 5 分钟整读一次兜底。
      const full = forceFull || held.current == null || sinceFull.current >= FULL_EVERY;
      const since = full ? null : sinceOf(held.current);
      const raw = await invoke<string>("read_requests", { since });
      sinceFull.current = since == null ? 0 : sinceFull.current + 1;
      if (!alive.current) return;
      // `generated_at` 每次都变，比较时剔掉它，其余逐字相同才算「没变」。
      const sig = raw.replace(/"generated_at":\s*[\d.]+/, "");
      if (sig === lastRaw.current) {
        setReadAt(Date.now());
        setErr(null); setFailed(null);
        return;
      }
      const p = parsePayload(raw);
      if (p.ok) {
        lastRaw.current = sig;
        const merged = mergePayload(held.current, p);
        held.current = merged;
        setPayload(merged);
        setReadAt(Date.now());
        setErr(null); setFailed(null);
      } else {
        // ★ 第一次就失败且一条都没有 ⇒ 留 null（页面写「读不到请求账本」），不塞空表冒充「今天还没有请求」（全方面评审 §5）
        if (p.requests.length) { held.current = mergePayload(held.current, p); setPayload(held.current); }
        // ★ `readAt` 只在读成功时前进（阶段 B 评审）：`stale_since` 是「从什么时候开始读不到」，不是「数据是什么时候的」——
        //   拿它当读取时刻会把 09:00 的旧数说成 10:05 读到的，第一次就失败时还会写出一个根本不存在的「读到时刻」。
        setErr(p.error ?? "请求账本读取失败");
        setFailed(p.failed.length ? p.failed : ["*"]);
      }
    } catch (e: unknown) {
      if (!alive.current) return;
      // ★ 不动 payload / readAt —— 上次的列表与它的时间原样留着。
      setErr(e instanceof Error ? e.message : String(e));
      setFailed(["*"]);
    } finally {
      inflight.current = false;
      if (alive.current) setBusy(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void load();
    const id = setInterval(() => { if (autoRefreshEnabled()) void load(); }, POLL_MS);
    return () => clearInterval(id);
  }, [enabled, load]);

  const retry = useCallback(() => { void load(true); }, [load]);
  return { payload, readAt, err, failed, busy, retry };
}
