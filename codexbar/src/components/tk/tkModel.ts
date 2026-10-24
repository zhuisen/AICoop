import type { Theme } from "../../theme";
import type { Bucket, CacheMode, RangeState, TrafficData } from "../../traffic";
import { MIN_COMPARE_DAYS, addDays, bucketsFor, colorOf, costOfBucket, countsCacheRead, diffDays, md, prevNote, prevSum,
         resolveRange, savingOfBucket, sumBuckets } from "../../traffic";
import { type Density, changePct, displayName, fmtIntL, fmtTokL, fmtUsdL, hitRate, sgn, trendOf } from "../../tokenView";
import { numColor, tkPal } from "./tkPal";
import type { TkKpi } from "./TkParts";

export interface PlatRow {
  key: string; name: string; src: string | null; color: string; num: string;
  labels: string[]; buckets: Bucket[]; agg: Bucket; total: number; rounds: number; cost: number; saving: number;
}

/** 每个平台在当前区间的合计。顺序 = 本期 Token 降序（图层、两列行、胶囊都按它）。 */
export function platRows(t: Theme, data: TrafficData, st: RangeState, today: string): PlatRow[] {
  return Object.keys(data.platforms).map((k) => {
    const { labels, buckets } = bucketsFor(data, k, st, today);
    const agg = sumBuckets(buckets);
    const dn = displayName(k, data.platforms[k].name);
    const color = colorOf(data, k);
    return { key: k, name: dn.name, src: dn.src, color, num: numColor(t, k, color), labels, buckets, agg,
             total: agg.total, rounds: agg.rounds, cost: costOfBucket(agg, k), saving: savingOfBucket(agg, k) };
  }).sort((a, b) => b.total - a.total);
}

/** 昨日整天的合计（今日档的「较昨日」）。拿不到 ⇒ null。 */
export function yesterdayOf(data: TrafficData, today: string, keys: string[]): { tok: number; cost: number } | null {
  const yd = addDays(today, -1);
  let tok = 0, cost = 0, seen = false;
  for (const k of keys) {
    const b = data.platforms[k]?.days[yd];
    if (b) { seen = true; tok += b.total; cost += costOfBucket(b, k); }
  }
  return seen ? { tok, cost } : null;
}

/**
 * 7 个指标（R2 §3）。`sel` = 只算这几家（总览选中单个平台 / 消耗页）；`null` = 全部。
 * ★ 不计入缓存读时「缓存命中」整格删除（用户 2026-08-11 定稿，偏离 R2-4）。
 */
export function buildKpis(o: {
  t: Theme; data: TrafficData; raw: TrafficData | null; rows: PlatRow[]; sel: string[] | null; st: RangeState;
  today: string; L: Density; cacheMode: CacheMode; single: boolean;
}): TkKpi[] {
  const { t, data, raw, rows, sel, st, today, L, cacheMode, single } = o;
  const p = tkPal(t);
  const isToday = st.preset === "today";
  const r = resolveRange(st, today);
  const days = Math.max(1, diffDays(r.s, r.e));
  const use = sel ? rows.filter((x) => sel.includes(x.key)) : rows;
  const grand = rows.reduce((s, x) => s + x.total, 0);
  const tok = use.reduce((s, x) => s + x.total, 0);
  const rounds = use.reduce((s, x) => s + x.rounds, 0);
  const cost = use.reduce((s, x) => s + x.cost, 0);
  const saving = use.reduce((s, x) => s + x.saving, 0);
  const keys = use.map((x) => x.key);
  const only = keys.length === 1 ? keys[0] : undefined;
  let prev: { tok: number; cost: number } | null;
  if (isToday) prev = yesterdayOf(data, today, keys);
  else {
    const pb = prevSum(data, st, today, only);
    prev = pb ? { tok: pb.total, cost: costOfBucketAll(data, st, today, keys) } : null;
  }
  const cTok = changePct(tok, prev?.tok), cCost = changePct(cost, prev?.cost);
  const tc = (c: number | null) => {
    const k = trendOf(c);
    return k === "up" ? p.up : k === "down" ? p.down : p.label;
  };
  const s2 = L === 2;
  const vsTxt = s2 ? "较上期" : prevNote(st, today);
  // ★ 「无上期数据」只在**确实该比、却取不到上期**时说（评审）：关了环比、区间 < 7 天、上期为 0
  //   都不是「没有数据」，那几种不写副标。
  const wantPrev = !isToday && st.compare && days >= MIN_COMPARE_DAYS;
  const noPrev = wantPrev && !prev ? (st.preset === "year" ? "无去年数据" : "无上期数据") : undefined;
  const one = single || (sel?.length === 1);
  const selRow = one ? use[0] : null;
  const top = rows[0];
  const shareRow = one ? selRow : top;
  const share = shareRow && grand > 0 ? (shareRow.total / grand) * 100 : null;
  const out: TkKpi[] = [
    { label: one ? "Token" : s2 ? "Token" : "总 Token", value: fmtTokL(tok, L), n: tok, fmt: (v) => fmtTokL(v, L), full: fmtTokL(tok, 0),
      color: one && selRow ? selRow.num : undefined, labelLogo: one && selRow && !single ? { k: selRow.key, color: selRow.color } : undefined,
      sub: `环比 ${sgn(cTok)}`, subColor: tc(cTok) },
    { label: s2 ? "请求" : "请求数", value: fmtIntL(rounds, L), n: rounds, fmt: (v) => fmtIntL(Math.round(v), L), full: fmtIntL(rounds, 0),
      sub: isToday ? "今日" : `日均 ${fmtIntL(rounds / days, L)}` },
    isToday
      ? { label: "较昨日", value: sgn(cTok), color: tc(cTok), sub: "vs 昨日" }
      : { label: "日均", value: fmtTokL(tok / days, L), n: tok / days, fmt: (v) => fmtTokL(v, L), full: fmtTokL(tok / days, 0),
          sub: prev && cTok != null ? vsTxt : noPrev },
    { label: s2 ? "费用" : "等效费用", value: fmtUsdL(cost, L), n: cost, fmt: (v) => fmtUsdL(v, L), full: fmtUsdL(cost, 0), color: p.amber, info: true,
      tip: "4 类 token × 牌价算出的等效 API 成本，订阅制下非实付",
      sub: saving > 0 ? `${s2 ? "省" : "缓存已省"} ${fmtUsdL(saving, L)}` : undefined },
    isToday
      ? { label: s2 ? "费用较昨" : "费用较昨日", value: sgn(cCost), color: tc(cCost) }
      : { label: s2 ? "日均费" : "日均费用", value: fmtUsdL(cost / days, L), n: cost / days, fmt: (v) => fmtUsdL(v, L), full: fmtUsdL(cost / days, 0),
          color: p.amber, sub: `环比 ${sgn(cCost)}`, subColor: tc(cCost) },
    { label: one ? (s2 ? "占比" : "占全部") : s2 ? "最大" : "最大占比",
      value: share == null ? "—" : `${Math.round(share)}%`, full: share == null ? undefined : `${share.toFixed(1)}%`,
      color: shareRow?.color, valueLogo: shareRow ? { k: shareRow.key, color: shareRow.color } : undefined,
      sub: "按 Token" },
  ];
  if (countsCacheRead(cacheMode)) {
    // ★ 必须从 `raw` 算：`data` 已按口径重塑（这里口径计入缓存读，两者其实相同，但别依赖这一点）。
    let cr = 0, un = 0, cw = 0;
    for (const k of keys) {
      const b = sumBuckets(bucketsFor(raw ?? data, k, st, today).buckets);
      cr += b.cache_read; un += b.uncached_in; cw += b.cache_write;
    }
    const h = hitRate(cr, un, cw);
    out.push({ label: s2 ? "缓存" : "缓存命中", value: h == null ? "—" : `${h.toFixed(1)}%`, info: true,
               tip: "缓存读 ÷（缓存读 + 输入），按 token 加权；输入含缓存写", sub: "输入侧" });
  }
  return out;
}

/** 上一等长周期的费用（各平台按自己的单价算再相加）。 */
function costOfBucketAll(data: TrafficData, st: RangeState, today: string, keys: string[]): number {
  let c = 0;
  for (const k of keys) {
    const b = prevSum(data, st, today, k);
    if (b) c += costOfBucket(b, k);
  }
  return c;
}

/** 胶囊行右侧的区间文字。今日 `MM-DD 00:00 → HH:00`；年度 `YYYY-MM → YYYY-MM`；非按天时带上粒度（偏离 R2-7）。 */
export function rangeText(st: RangeState, today: string, labels: string[], granWord: string | null): string {
  const r = resolveRange(st, today);
  if (st.preset === "today") {
    const last = labels[labels.length - 1];
    return `${md(today)} 00:00 → ${last && last.length > 10 ? last.slice(11) : "00"}:00`;
  }
  const base = st.preset === "year" ? `${r.s.slice(0, 7)} → ${r.e.slice(0, 7)}` : `${md(r.s)} → ${md(r.e)}`;
  return granWord ? `${base} · ${granWord}` : base;
}

/**
 * 首扫完成前的 7 格骨架：格数与短标签和加载后一致（不跳列），每一格都是「—」——
 * 空窗期写 `0 · $0.000` 是一句错的陈述（LoadingSaysNothingNotZero）。
 */
export function skeletonKpis(L: Density, isToday: boolean, cache: boolean): TkKpi[] {
  const s2 = L === 2;
  const labels = [s2 ? "Token" : "总 Token", s2 ? "请求" : "请求数", isToday ? "较昨日" : "日均",
    s2 ? "费用" : "等效费用", isToday ? (s2 ? "费用较昨" : "费用较昨日") : (s2 ? "日均费" : "日均费用"),
    s2 ? "最大" : "最大占比"];
  if (cache) labels.push(s2 ? "缓存" : "缓存命中");
  return labels.map((label) => ({ label, value: "—", sub: "读取中" }));
}
