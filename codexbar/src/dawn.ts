/**
 * 定时探针（codex `dawn-probe` / agy `dawn-probe`）的共用形状与文案。纯函数，零依赖 —— 可在 node 里直接跑。
 *
 * ★ 2026-10-15 起开关从设置页搬到总览各档的工具栏（用户：「定时的功能在设置移动到总览，各 AI 版块上」）。
 *   时间可选，实际在所选时刻起 3 分钟内随机（`dawn_sched.py`）；界面上的「06:00–06:03」由 CLI 的
 *   `--status` 带出来（`window`），这里不自己算第二份。
 */

/** `dawn-probe --status` 的形状（codex 存在 `state.json`，agy 存在 `.agy-pool.json`）。 */
export interface DawnStatus {
  enabled?: boolean; date?: string; at?: number; ok?: number | null; total?: number;
  state?: string; note?: string; targets_today?: string[];
  /** 所选时刻 `HH:MM`。 */
  time?: string;
  /** 「06:00–06:03」—— 随机区间。 */
  window?: string;
  /** 今天实际会在哪一秒跑（epoch 秒，按天固定的随机偏移）。app 内补跑用它判「到点没有」。 */
  due_at?: number;
  /** agy：探完后 5h 真的降了（窗口启动了）的号数。 */
  started?: number | null;
}

export type DawnKind = "codex" | "agy";

/**
 * 「定时到底跑没跑」—— ★ **它是唯一可见的证据**。本项目的 launchd 日历定时被外力改写丢过
 * `StartCalendarInterval`，`runs = 0`、从未运行过，而没有任何一处会为此报红。
 * 所以必须把**上次运行时刻**说出来，不是只说功能开着。
 */
export function dawnDesc(d: DawnStatus | null, kind: DawnKind): string {
  if (!d) return "读取中…";
  const n = d.targets_today?.length ?? 0;
  const who = kind === "codex"
    ? (n ? `${n} 个 Plus 号` : "无存活 Plus 号")
    : (n ? `${n} 个参与轮换的号` : "无参与轮换的号");
  const cost = kind === "codex" ? "各发一次最小计费请求" : "各起一次 agy 探针（每号约 15k token）";
  const win = d.window ?? "06:00–06:03";
  if (!d.enabled) return `关闭中。开启后每天 ${win} 之间随机给 ${who}${cost}，把 5h 窗口启动起来（会花钱）`;
  if (!d.date) return `已开启（${win}），${who}，但**还没有任何一次运行记录** —— 若明天此处仍是空的，说明定时没生效`;
  const when = d.at ? new Date(d.at * 1000).toLocaleString() : d.date;
  const res = d.state === "failed" ? "上次运行出错"
    : d.state === "deferred" ? "给手动探针让路，稍后重试"
    : d.ok == null ? "进行中/未完成" : `${d.ok}/${d.total} 可用`;
  const st = kind === "agy" && d.started != null ? ` · 5h 启动 ${d.started} 个` : "";
  return `已开启（${win}），${who}。上次运行 ${when} · ${res}${st}`;
}

/** 补跑该不该现在起（只读判断，真正的幂等/占天在 CLI）。`now` 是 epoch 秒。 */
export function dawnCatchUpDue(d: DawnStatus | null, today: string, now: number): boolean {
  return !!d?.enabled && d.date !== today && d.due_at != null && now >= d.due_at;
}
