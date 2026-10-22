import { useCallback, useEffect, useRef, useState } from "react";
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
  rec: DawnStatus | null; busy: boolean; failed: boolean;
  toggle: () => Promise<void>; setTime: (hhmm: string) => Promise<void>;
} {
  // ★ 读数**带着它属于哪一家**（阶段 A 评审）：总览两档共用同一个 `DawnChip` 位置，切到 Gemini 后读失败的话，
  //   留着的会是 Codex 那份 —— 点开关就按 Codex 的状态给 Gemini 发 `--enable`。不是这一家的读数一律当没读到。
  const [got, setGot] = useState<{ kind: DawnKind; rec: DawnStatus } | null>(null);
  const [failed, setFailed] = useState<DawnKind | null>(null);
  const [busy, setBusy] = useState(false);
  const cur = useRef(kind); cur.current = kind;
  const rec = got && got.kind === kind ? got.rec : null;

  const load = useCallback(async () => {
    const k = kind;
    try {
      const raw = k === "codex"
        ? await invoke<string>("read_dawn_status")
        : await invoke<string>("run_agy_rotate", { args: ["dawn-probe", "--status"] });
      const last = raw.trim().split("\n").pop();
      if (!last) throw new Error("empty");      // 空输出 ≠ `{}`（那会画成「关」且可点）
      const r = JSON.parse(last) as DawnStatus;
      if (cur.current !== k) return;            // 回来时已经切到另一家 ⇒ 丢掉
      setGot({ kind: k, rec: r }); setFailed(null);
    } catch {
      // ★ 读不到 ≠「关」（2026-10-22 评审）：定时探针是会自动花钱的东西，读失败画成「关」会掩盖它其实还在跑。
      //   第一次就失败 ⇒ 没有读数（胶囊画「—」、开关不可点、说明写「读不到」）；之前读到过 ⇒ 留着上次的。
      if (cur.current === k) setFailed(k);
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

  // 不知道现在是开是关时不许点：点了就是盲写一个方向。★ 最近一次读失败、手里只有旧读数也一样（阶段 B 评审）——
  //   CLI / 另一个窗口可能已经改过，按旧状态翻转就可能翻反。
  const stale = failed === kind;
  const toggle = useCallback(async () => { if (rec && !stale) await write([rec.enabled ? "--disable" : "--enable"]); }, [rec, stale, write]);
  const setTime = useCallback(async (hhmm: string) => { if (rec && !stale) await write(["--time", hhmm]); }, [rec, stale, write]);
  return { rec, busy, failed: stale, toggle, setTime };
}
