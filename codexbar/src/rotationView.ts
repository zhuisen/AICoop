/**
 * 代理轮换页（AICoop P7，阶段 5）的纯判断。★ 零 import —— 测试用 `node --experimental-strip-types` 直接加载。
 * 规格摘录：`scratch/aicoop_20261021/P7P8_extract.md` P7-1 / P7-2。偏离：PLAN 第 41 条。
 */

export type RotDensity = 0 | 1 | 2;

/** 稿 §1.0：随窗口宽变的列宽与开关。 */
export interface RotLayout {
  L: RotDensity; acctW: number; cols: [number, number, number, number]; colsSum: number;
  segPad: number; showAgo: boolean; showMeta: boolean; todCols: string;
}

export function rotLayout(W: number): RotLayout {
  const w860 = W <= 860, w1000 = W <= 1000;
  const cols: [number, number, number, number] = w860 ? [56, 38, 44, 48] : w1000 ? [66, 44, 50, 78] : [76, 50, 56, 90];
  return {
    L: w860 ? 2 : w1000 ? 1 : 0,
    acctW: w860 ? 100 : w1000 ? 118 : 136,
    cols, colsSum: cols.reduce((s, x) => s + x, 0) + 4 * 12,
    segPad: w860 ? 8 : 12, showAgo: !w860, showMeta: !w860,
    todCols: w860 ? "50px 64px" : w1000 ? "56px 96px" : "64px 104px",
  };
}

/** 块内时长只写分钟（`132m`，不写 `2h12m`）；写不下 ⇒ ""（稿 §2.4）。 */
export function fitDur(secs: number, px: number): string {
  const s = `${Math.round(secs / 60)}m`;
  return s.length * 6.3 + 4 <= px ? s : "";
}

/** `Nm`（只用分钟，稿 §2.8）。 */
export function mins(secs: number): string {
  return `${Math.round(secs / 60)}m`;
}

/** 本地时钟 `HH:MM`（`sec` = 同时带秒）。 */
export function clockOf(ts: number, sec = false): string {
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}${sec ? `:${p(d.getSeconds())}` : ""}`;
}

/** 「太短」提示要建议切到哪一档：24h → 6h，6h → 1h，1h 没有更细的档。 */
export function zoomTo(hours: number): number | null {
  return hours === 24 ? 6 : hours === 6 ? 1 : null;
}

export interface AxisMark { x: number; label: string }

/**
 * 时间线横轴（稿 §2.5 + 偏离 P7-2）。整点按**本机时钟**对齐（稿里终点写死 23:10）。
 * 主刻度：24h 每 2 小时（≤1000 宽每 3 小时）· 6h 每小时 · 1h 每 15 分钟；小刻度：每小时 / 每半小时 / 每 5 分钟。
 * ★ 稿件缺陷：860 下 `21:00` 与「现在」重叠 —— 这里按**像素**避让（标签半宽 + 「现在」宽），不按百分比。
 */
export function rotAxis(start: number, end: number, hours: number, narrow: boolean, trackPx: number):
  { major: AxisMark[]; minor: number[] } {
  const span = Math.max(1, end - start);
  const majorMin = hours <= 1 ? 15 : hours <= 6 ? 60 : narrow ? 180 : 120;
  const minorMin = hours <= 1 ? 5 : hours <= 6 ? 30 : 60;
  const d = new Date(start * 1000);
  d.setSeconds(0, 0);
  d.setMinutes(Math.ceil(d.getMinutes() / minorMin) * minorMin);
  const major: AxisMark[] = [], minor: number[] = [];
  const nowW = 30, half = 18;
  for (let guard = 0; guard < 2000 && d.getTime() / 1000 <= end; guard++) {
    const ts = d.getTime() / 1000;
    const x = (ts - start) / span;
    const dayMin = d.getHours() * 60 + d.getMinutes();
    if (dayMin % majorMin === 0) {
      const clear = (1 - x) * trackPx > nowW + half + 4;
      if (clear) major.push({ x, label: clockOf(ts) });
    }
    minor.push(x);
    d.setMinutes(d.getMinutes() + minorMin);
  }
  return { major, minor };
}

/** 5h 额度色（P7 稿 §1.4：<10 红 · <50 琥珀 · 否则绿）。读不到 ⇒ "none"（画「—」，不画满）。 */
export function quota5hTone(p: number | null | undefined): "bad" | "warn" | "ok" | "none" {
  if (p == null || !Number.isFinite(p)) return "none";
  return p < 10 ? "bad" : p < 50 ? "warn" : "ok";
}

/** 中位数（null 不计）。没有 ⇒ null。 */
export function median(xs: readonly (number | null | undefined)[]): number | null {
  const v = xs.filter((x): x is number => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

// ── 账号 × 时段（7d / 14d / 30d，稿 §1.5 / §2.7）────────────────────────────

export interface SegLite { acc: string; start: number; end: number }
export interface MarkLite { acc: string; t: number; kind: string }
export interface TodRow {
  acc: string;
  /** 48 个半小时格：本期有几天在这半小时上岗（重叠 ≥ 10 分钟才算）。 */
  days: number[];
  /** 48 个半小时格：断流次数。 */
  errs: number[];
  /** 本期在岗总时长（秒）。 */
  secs: number;
  /** 在岗最密的连续 6 格（3 小时）起点；本期没上过岗 ⇒ null。 */
  best: number | null;
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

/** 同号的段先求区间并集：并发会话（Gemini 同号两个窗口）不许把在岗时长数两遍（评审 codex 阶段 5）。 */
export function unionSegs(segs: readonly SegLite[]): SegLite[] {
  const by = new Map<string, SegLite[]>();
  for (const s of segs) if (s.end > s.start) (by.get(s.acc) ?? by.set(s.acc, []).get(s.acc)!).push(s);
  const out: SegLite[] = [];
  for (const [acc, xs] of by) {
    xs.sort((a, b) => a.start - b.start);
    let cur: SegLite | null = null;
    for (const x of xs) {
      if (cur && x.start <= cur.end) cur.end = Math.max(cur.end, x.end);
      else { if (cur) out.push(cur); cur = { acc, start: x.start, end: x.end }; }
    }
    if (cur) out.push(cur);
  }
  return out;
}

/** 本期每号每天每半小时是否在岗 + 断流计次（按本机时区分天）。 */
export function todGrid(accs: readonly string[], segs: readonly SegLite[], marks: readonly MarkLite[]): TodRow[] {
  const over = new Map<string, number>();   // acc|day|slot → 秒
  const secs = new Map<string, number>();
  for (const s of unionSegs(segs)) {
    secs.set(s.acc, (secs.get(s.acc) ?? 0) + Math.max(0, s.end - s.start));
    const d = new Date(s.start * 1000);
    d.setSeconds(0, 0);
    d.setMinutes(d.getMinutes() >= 30 ? 30 : 0);
    for (let guard = 0; guard < 5000 && d.getTime() / 1000 < s.end; guard++) {
      const a = d.getTime() / 1000, b = a + 1800;
      const o = Math.min(b, s.end) - Math.max(a, s.start);
      if (o > 0) {
        const k = `${s.acc}|${dayKey(d)}|${d.getHours() * 2 + (d.getMinutes() >= 30 ? 1 : 0)}`;
        over.set(k, (over.get(k) ?? 0) + o);
      }
      d.setMinutes(d.getMinutes() + 30);
    }
  }
  const rows = new Map<string, TodRow>(accs.map((a) => [a, { acc: a, days: new Array(48).fill(0), errs: new Array(48).fill(0),
                                                            secs: secs.get(a) ?? 0, best: null }]));
  for (const [k, v] of over) {
    if (v < 600) continue;
    const [acc, , slot] = k.split("|");
    const r = rows.get(acc);
    if (r) r.days[Number(slot)] += 1;
  }
  for (const m of marks) {
    if (m.kind !== "stream_err") continue;
    const r = rows.get(m.acc);
    if (!r) continue;
    const d = new Date(m.t * 1000);
    r.errs[d.getHours() * 2 + (d.getMinutes() >= 30 ? 1 : 0)] += 1;
  }
  for (const r of rows.values()) r.best = bestWindow(r.days);
  return [...rows.values()];
}

/** 连续 6 格（3 小时）里在岗天数和最大的那段起点（0…42）；全 0 ⇒ null。同分取最早。 */
export function bestWindow(days: readonly number[]): number | null {
  let best = -1, at: number | null = null;
  for (let b = 0; b <= 42; b++) {
    let s = 0;
    for (let k = 0; k < 6; k++) s += days[b + k] ?? 0;
    if (s > best) { best = s; at = b; }
  }
  return best > 0 ? at : null;
}

/** 半小时格 → `HH:MM`（`b = 48` ⇒ `00:00`）。 */
export function slotClock(b: number): string {
  const m = (b % 48) * 30;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** 常用时段写法：宽窗 `20:30–23:30`；860 写 `20–23 点`（稿 §2.7）。 */
export function bestText(b: number | null, narrow: boolean): string {
  if (b == null) return "—";
  if (narrow) {
    const h = Math.floor(b / 2), p = (n: number) => String(n % 24).padStart(2, "0");
    return `${p(h)}–${p(h + 3)} 点`;
  }
  return `${slotClock(b)}–${slotClock(b + 6)}`;
}

/** 卡片底部那句结论（稿 §2.7）。 */
export function todConclusion(rows: readonly TodRow[]): string {
  const tot = new Array(48).fill(0);
  let worst: TodRow | null = null, worstN = 0;
  for (const r of rows) {
    let n = 0;
    r.errs.forEach((e, i) => { tot[i] += e; n += e; });
    if (n > worstN) { worstN = n; worst = r; }
  }
  const peak = Math.max(...tot);
  if (!(peak > 0) || !worst) return "本期没有断流。";
  const b = tot.indexOf(peak);
  return `断流最集中在 ${slotClock(b)}–${slotClock(b + 1)}（${peak} 次）；${worst.acc} 本期断流最多（${worstN} 次）。`;
}

/** 格子着色的强度（0…1）。在岗：`0.12 + c/N·0.85`；断流：`0.15 + er/erMax·0.8`（稿 §2.7）。 */
export function todAlpha(mode: "duty" | "err", c: number, n: number, er: number, erMax: number): number {
  if (mode === "duty") return c > 0 ? 0.12 + (c / Math.max(1, n)) * 0.85 : 0;
  return er > 0 ? 0.15 + (er / Math.max(1, erMax)) * 0.8 : 0;
}

// ── 轮换记录（稿 §1.6 / §2.6）──────────────────────────────────────────────

export type RecKind = "err" | "fail" | "switch" | "pro" | "429" | "stream" | "billed" | "safe" | "probe";
export type RecFilter = "all" | "switch" | "fail" | "429" | "err" | "billed";

export interface EvLite { t: number; type: string; from: string | null; to: string | null; reason: string; text: string; accs: string[] }
export interface Rec {
  key: string; t: number; kind: RecKind; from: string | null; to: string | null;
  /** 「A → B · 原因」那一句（不含上一号的驻留统计）。 */
  head: string;
  /** 上一号的驻留 / token / 请求（原文案后半，挪进展开面板首行，信息不丢）。 */
  prevStats: string | null;
  /** 接班号这一段的时长（秒）：到下一次换号为止；最后一次 = 到窗口终点。只对换号有。 */
  onDuty: number | null;
  accs: string[];
}

/** 事件 → 记录类型。★ 三类失败的计费含义不同，不合并（`billed` 是唯一危险级）。 */
export function recKind(e: EvLite): RecKind {
  // ★ 「Pro 保底接管」是换号事件的**原因**（`type` 仍是 switch），不是一种事件类型。
  if (e.type === "switch") return e.reason === "stream_err" ? "err" : e.reason === "pro_fallback" ? "pro" : "switch";
  if (e.type === "failover") return "fail";
  if (e.type === "cool_429") return "429";
  if (e.type === "stream_err") return "stream";
  if (e.type === "billed_unknown") return "billed";
  if (e.type === "safe_switch") return "safe";
  return "probe";
}

export function recMatches(k: RecKind, f: RecFilter): boolean {
  if (f === "all") return true;
  if (f === "switch") return k === "switch" || k === "pro";
  if (f === "fail") return k === "fail";
  if (f === "429") return k === "429";
  if (f === "err") return k === "err" || k === "stream";
  return k === "billed";
}

const SWITCHY: RecKind[] = ["err", "fail", "switch", "pro"];

/** 事件（新→旧）→ 记录（新→旧），带接班时长。 */
export function recsOf(evs: readonly EvLite[], windowEnd: number): Rec[] {
  const asc = [...evs].sort((a, b) => a.t - b.t);
  const out: Rec[] = [];
  let nextSwitchT = windowEnd;
  for (let i = asc.length - 1; i >= 0; i--) {
    const e = asc[i];
    const kind = recKind(e);
    const sw = SWITCHY.includes(kind);
    const cut = e.text.indexOf(" · 上号 ");
    let head = (cut >= 0 ? e.text.slice(0, cut) : e.text).replace(/\*\*/g, "");
    // ★ 稿写「流中断 · 未换号，重试成功」—— 「重试成功」我们观测不到（代理对计费断流不重试）；
    //   是否随后换号由同号 120 s 内有没有换号事件判（偏离 P7-12）。
    if (kind === "stream" && e.from) {
      const after = asc.some((x) => x.from === e.from && x.t >= e.t && x.t - e.t <= 120 && SWITCHY.includes(recKind(x)));
      head = `${e.from} 流中断 · ${after ? "随后换号" : "未换号"} · 已计费`;
    } else if (kind === "429" && e.from) {
      head = `${e.from} 被限流，进入冷却`;
    }
    out.push({
      key: `${e.type}:${e.t}:${e.from ?? ""}:${e.to ?? ""}:${i}`, t: e.t, kind, from: e.from, to: e.to,
      head,
      prevStats: cut >= 0 ? e.text.slice(cut + 3) : null,
      onDuty: sw ? Math.max(0, nextSwitchT - e.t) : null,
      accs: e.accs,
    });
    if (sw) nextSwitchT = e.t;
  }
  return out;
}

export function recCounts(recs: readonly Rec[]): Record<RecFilter, number> {
  const c: Record<RecFilter, number> = { all: recs.length, switch: 0, fail: 0, "429": 0, err: 0, billed: 0 };
  for (const r of recs) for (const f of ["switch", "fail", "429", "err", "billed"] as RecFilter[]) if (recMatches(r.kind, f)) c[f] += 1;
  return c;
}

/** 原始日志的级别（稿 §1.6：错误红 · 警告黄 · 成功平台色）。 */
export function logLevel(text: string): "bad" | "warn" | "ok" | "plain" {
  const s = text.toLowerCase();
  if (text.includes("✗") || /\b(401|403|5\d\d)\b|committed|invalidated|marked dead|error/.test(s)) return "bad";
  if (/stream err|cooled|429|send err|skip|⚠/.test(s)) return "warn";
  if (/\bok\b|200|switch|→ \[|✓/.test(s)) return "ok";
  return "plain";
}

/** 展开日志：该时刻前后 `win` 秒的行，按时间升序；`mark` = 离事件时刻最近的那一行。 */
export function logsAround<T extends { t: number | null }>(lines: readonly T[], t: number, win = 90): { rows: T[]; mark: number } {
  const rows = lines.filter((l): l is T & { t: number } => l.t != null && Math.abs(l.t - t) <= win)
    .sort((a, b) => a.t - b.t);
  let mark = -1, d = Infinity;
  rows.forEach((l, i) => { const x = Math.abs(l.t - t); if (x < d) { d = x; mark = i; } });
  return { rows, mark };
}
