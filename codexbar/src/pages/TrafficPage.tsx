import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { type Theme, modelColor } from "../theme";
import PriceStack, { cacheNotes } from "../components/tk/PriceStack";
import { priceWarnings } from "../rates";
import Toast from "../components/Toast";
import { introEnabled } from "../hooks/useIntro";
import type { Bucket, CacheMode, Coverage, PlatformPrefs, RangeState, TrafficData } from "../traffic";
import { PILLS, addDays, countsCacheRead, coverageNote, coveragePct, diffDays, effGran, granLabel, orderedKeys, prevSum,
         resolveRange, tickTitle, todayOf, topModels } from "../traffic";
import { quantizeDown } from "../resizeMath";
import { type Density, changePct, densityOf, fmtIntL, fmtTokL, fmtUsdL, peakOf, sgn, shortDate, titleSize,
         trendOf, twoCol } from "../tokenView";
import TkArea, { type TkLayer } from "../components/tk/TkArea";
import { KpiGrid, PLogo, PlatChips, RangeSeg, RefreshAgo } from "../components/tk/TkParts";
import { buildKpis, platRows, rangeText, skeletonKpis, type PlatRow } from "../components/tk/tkModel";
import { MONO, SPR9, tkPal } from "../components/tk/tkPal";
import "../components/tk/tk.css";

/** 内容宽 → 密度档用窗口宽判（稿：W ≤ 860 → 860 档，≤ 1000 → 1000 档）。 */
export function useWinDensity(): { L: Density; W: number } {
  const [W, setW] = useState(() => window.innerWidth);
  useEffect(() => {
    const on = () => setW(window.innerWidth);
    window.addEventListener("resize", on);
    return () => { window.removeEventListener("resize", on); };
  }, []);
  return { L: densityOf(W), W };
}

export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // ★ 向下取到 4px：拖窗口时图表不逐像素重画（同 `useFillHeight`，test_resize_less_work）。向下取 ⇒ 永不比容器宽。
    setW(quantizeDown(el.clientWidth));
    const ro = new ResizeObserver(() => setW(quantizeDown(el.clientWidth)));
    ro.observe(el);
    return () => { ro.disconnect(); };
  }, []);
  return [ref, w];
}

/** 切档方向（往后切从右滑入，往前切从左滑入）与 A/B 交替（重播用两套 keyframes）。 */
export function useDirAnim(key: string): string | undefined {
  // 设置页「入场动效」关或系统减弱动态效果 ⇒ 切档不滑（introEnabled 两者都看）。
  const [on] = useState(() => introEnabled());
  const order = [...PILLS, "custom"] as string[];
  const prev = useRef(key);
  const n = useRef(0);
  const dir = useRef<"R" | "L">("R");
  if (prev.current !== key) {
    dir.current = order.indexOf(key) >= order.indexOf(prev.current) ? "R" : "L";
    n.current += 1;
    prev.current = key;
  }
  return on && n.current ? `tk${dir.current}${n.current % 2 ? "A" : "B"} .22s cubic-bezier(.2,.9,.3,1) both` : undefined;
}

/**
 * Token 消耗 · 总览（AICoop R2_Token / W1000 / W860，1:1）。数据源是各 CLI 自己写在本机的 transcript，零额度消耗。
 *
 * 结构：顶栏（含平台胶囊）→ 7 个指标 → 按平台堆叠面积图 → 两列平台行 → 平台卡片。
 * ★ 一屏规则（README §3.4 / 用户 2026-10-14）：顶栏与胶囊钉住，其余在页面自己的滚动容器里滚（偏离 R2-1）。
 * 偏离清单在 `scratch/aicoop_20261021/PLAN.md`（R2-*）。
 */
export default function TrafficPage({ t, data, raw, cacheMode, prefs, st, setSt, onDrill, busy, err, onRefresh }: {
  t: Theme;
  /** 已按缓存口径重塑 —— 一切合计/图表/费用都用它 */
  data: TrafficData | null;
  /** 只未套「缓存口径」这一层（平台偏好已套过）。只给缓存命中用。 */
  raw: TrafficData | null;
  cacheMode: CacheMode;
  /** 平台呈现偏好。**这里只用它的 `order` 排列表**（用户排过就照用户的，偏离 R2-3）。 */
  prefs: PlatformPrefs;
  st: RangeState;
  setSt: (s: RangeState) => void;
  onDrill: (platform: string) => void;
  busy: boolean;
  err: string | null;
  onRefresh?: () => void;
}): React.ReactElement {
  const p = tkPal(t);
  const { L, W } = useWinDensity();
  const [solo, setSolo] = useState<string | null>(null);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [host, cw] = useWidth<HTMLDivElement>();
  const today = useMemo(() => todayOf(data), [data]);
  const range = useMemo(() => resolveRange(st, today), [st, today]);
  const isToday = st.preset === "today";
  const anim = useDirAnim(st.preset === "custom" ? `custom:${range.s}:${range.e}` : st.preset);
  const toastT = useRef(0);
  const showToast = useCallback((m: string) => {
    setToast(m);
    window.clearTimeout(toastT.current);
    toastT.current = window.setTimeout(() => setToast(null), 1800);
  }, []);
  // 入场动效：只在**进入页面**那一次（设置页「入场动效」开关管它）。
  const [intro] = useState(() => introEnabled());

  const rows = useMemo(() => (data ? platRows(t, data, st, today) : []), [t, data, st, today]);
  const soloOk = solo && rows.some((r) => r.key === solo) ? solo : null;
  /** 两列行 / 胶囊的顺序：用户在设置里排过就照用户的，没排过的按本期 Token 降序。 */
  const list = useMemo(() => {
    const by = new Map(rows.map((r) => [r.key, r]));
    return orderedKeys(rows.map((r) => r.key), prefs, (k) => by.get(k)?.total ?? 0).map((k) => by.get(k)!).filter(Boolean);
  }, [rows, prefs]);
  const labels = rows[0]?.labels ?? [];
  // 价格待核：最近 30 天用过的模型（不随所选区间变 —— 换个区间警告就消失，会让人以为价格表好了）
  const priceWarns = useMemo(() => {
    if (!data) return [];
    const from = addDays(today, -29);
    const used: { model: string; platform: string }[] = [];
    for (const [k, pl] of Object.entries(data.platforms)) {
      for (const [d, b] of Object.entries(pl.days ?? {})) {
        if (d < from) continue;
        for (const [m, mb] of Object.entries(b.models ?? {})) if ((mb.total ?? 0) > 0) used.push({ model: m, platform: k });
      }
    }
    return priceWarnings(used, today);
  }, [data, today]);
  const days = diffDays(range.s, range.e);
  const gran = isToday ? null : effGran(st, days);
  const kpis = data ? buildKpis({ t, data, raw, rows, sel: soloOk ? [soloOk] : null, st, today, L, cacheMode, single: false }) : [];

  const layers: TkLayer[] = rows.map((r) => ({
    key: r.key, name: r.name, color: r.color, num: r.num,
    values: r.buckets.map((b) => (soloOk && soloOk !== r.key ? 0 : b.total)),
  }));
  // 浮层逐行 = 平台注册顺序（不按值排、零值也列）；选中单平台时只列它。
  const regOrder = data ? Object.keys(data.platforms) : [];
  const tipRows = (soloOk ? layers.filter((l) => l.key === soloOk)
    : regOrder.map((k) => layers.find((l) => l.key === k)).filter((x): x is TkLayer => !!x));
  const thisYear = today.slice(0, 4);
  const tipTitle = (i: number) => {
    const l = labels[i] ?? "";
    if (l.length > 10) return `${l.slice(5, 10)} ${l.slice(11)}:00`;
    return l.length === 7 ? tickTitle(l) : l;
  };
  const CH = L === 0 ? 236 : L === 1 ? 222 : 210;
  const soloRow = soloOk ? rows.find((r) => r.key === soloOk) ?? null : null;
  const tc = useMemo(() => twoCol(list.length), [list.length]);
  const left = list.slice(0, tc.perCol), right = list.slice(tc.perCol);
  const rowCols = L === 0 ? "16px 112px minmax(0,1fr) 68px 50px 78px 10px"
    : L === 1 ? "16px 96px minmax(0,1fr) 62px 46px 72px 10px" : "16px minmax(0,1fr) 60px 46px 70px 10px";
  const maxTot = Math.max(1, rows[0]?.total ?? 1);
  const grand = Math.max(1, rows.reduce((s, r) => s + r.total, 0));
  // 卡片按「今天这一天」的 token 降序（用户 2026-10-15），与卡底「今日」和 `data-today` 同一个数。
  const cards = useMemo(() => [...list].sort((a, b) => todayTok(data, b.key, today) - todayTok(data, a.key, today)),
                        [list, data, today]);
  const periodName = st.preset === "7d" ? "近 7 天" : st.preset === "30d" ? "近 30 天" : st.preset === "year" ? "年度"
    : `${range.s.slice(5)} → ${range.e.slice(5)}`;

  const row = (r: PlatRow, first: boolean) => (
    <button key={r.key} type="button" data-plat-row={r.key} onClick={() => onDrill(r.key)}
            onMouseEnter={() => setHoverKey(r.key)} onMouseLeave={() => setHoverKey(null)}
            title={`${fmtIntL(r.rounds, 0)} 轮 · 点击查看 ${r.name} 消耗`}
            style={{ display: "grid", gridTemplateColumns: rowCols, alignItems: "center", columnGap: 10, height: tc.rowH,
                     padding: "0 6px", border: 0, borderTop: first ? 0 : `1px solid ${p.hair}`,
                     background: soloOk === r.key ? `${r.color}1f` : hoverKey === r.key ? p.hoverRow : "transparent",
                     color: p.text, textAlign: "left", cursor: "pointer", borderRadius: 6, fontFamily: "inherit",
                     transition: `background .2s ease-out, height .42s ${SPR9}`, minWidth: 0 }}>
      <PLogo k={r.key} color={r.color} size={16} isDark={t.isDark} />
      <span style={{ display: "flex", alignItems: "baseline", gap: 5, overflow: "hidden", minWidth: 0 }}>
        <span style={{ fontSize: 14, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
        {r.src && <span style={{ fontSize: 10.5, color: p.label, fontFamily: MONO }}>{r.src}</span>}
      </span>
      {L < 2 && (
        <span style={{ height: 6, borderRadius: 3, background: p.track, overflow: "hidden" }}>
          <span style={{ display: "block", height: "100%", width: `${Math.max(1, (r.total / maxTot) * 100).toFixed(1)}%`,
                         background: r.color, transition: `width .55s ${SPR9}` }} />
        </span>
      )}
      <span style={{ fontFamily: MONO, fontSize: 14, fontWeight: 600, textAlign: "right" }}>{fmtTokL(r.total, L)}</span>
      <span style={{ fontFamily: MONO, fontSize: 12, color: p.text2, textAlign: "right" }}>{((r.total / grand) * 100).toFixed(1)}%</span>
      <span style={{ fontFamily: MONO, fontSize: 13, color: p.amber, textAlign: "right" }}>{fmtUsdL(r.cost, L)}</span>
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M3.5 1.5L7 5 3.5 8.5" stroke={p.label} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
    </button>
  );

  return (
    <div data-token-page className={intro ? "tk-intro" : undefined}
         style={{ display: "flex", flexDirection: "column", minHeight: 0, height: "100%", gap: 12,
                  padding: `0 ${L < 2 ? 6 : 0}px 0`, whiteSpace: "nowrap" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, height: 34, flexShrink: 0 }}>
        <h1 style={{ margin: 0, fontSize: titleSize(W), fontWeight: 700, flexShrink: 0 }}>消耗</h1>
        {/* 数据来源的披露常驻在这里（刷新按钮在首扫完成前不出现，评审）。 */}
        <span data-src title="汇总各 CLI 写在本机的 transcript · 不消耗额度"
              style={{ fontSize: 12, color: p.label, fontFamily: MONO, cursor: "help" }}>ⓘ</span>
        {/* ★ 平台胶囊并进标题行（用户 2026-10-22「全部 Claude Codex… 放在消耗的右侧」），省掉第二行 */}
        <PlatChips t={t} chips={list.map((r) => ({ key: r.key, name: r.name, color: r.color }))} sel={soloOk}
                   onPick={setSolo} withAll L={L} aria="按平台筛选" fit />
        {/* 弱提示一律进这一个悬浮堆叠（用户 2026-10-22）：价格待核 + 缓存口径（原 CacheChip，口径不是 full 时数字会换一套口径） */}
        <PriceStack t={t} items={priceWarns} extra={cacheNotes(cacheMode)} />
        <span data-range-label style={{ fontSize: 12, color: p.label, fontFamily: MONO, flexShrink: 0 }}>
          {rangeText(st, today, labels, gran && gran !== "day" ? granLabel(gran) : null)}
        </span>
        <RefreshAgo t={t} generatedAt={data?.generated_at ?? null} L={L} busy={busy} onRefresh={onRefresh} />
        <RangeSeg t={t} st={st} today={today} L={L} onChange={setSt} onToast={showToast} />
      </div>
      {toast && <Toast msg={toast} t={t} />}
      {err && <div style={{ fontSize: 11, color: p.down, flexShrink: 0 }}>✗ {err}</div>}

      <div ref={host} data-traffic-list style={{ flex: "1 1 0", minHeight: 0, overflowY: "auto", overflowX: "hidden",
                                                  display: "flex", flexDirection: "column", gap: 12, paddingBottom: 8 }}>
        {!data ? (
          <>
            <KpiGrid t={t} borderColor={p.border} items={skeletonKpis(L, isToday, countsCacheRead(cacheMode))} />
            {busy && <div style={{ fontSize: 12, color: p.label }}>首次扫描本机 CLI 记录中（约 18s，之后走缓存）…</div>}
          </>
        ) : (
          <>
            <KpiGrid t={t} items={kpis} anim={anim} borderColor={soloRow ? `${soloRow.color}66` : p.border} />
            {!!labels.length && cw > 0 && (
              <div className="tk-dir" style={{ animation: anim?.replace(".22s", ".26s").replace("both", ".03s both") }}>
                <TkArea t={t} width={cw} height={CH} labels={labels} layers={layers} rows={tipRows} rowLogo
                        fmt={(n) => fmtTokL(n, L)} unit={soloRow ? `token · ${soloRow.name}` : "token"}
                        tipTitle={tipTitle} focus={hoverKey && !soloOk ? hoverKey : null} onPick={onDrill} />
              </div>
            )}
            <section data-two-col style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 1px minmax(0,1fr)",
                                           columnGap: L < 2 ? 24 : 16, height: tc.h, flexShrink: 0,
                                           borderTop: `1px solid ${p.line}`, borderBottom: `1px solid ${p.line}` }}>
              <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>{left.map((r, i) => row(r, i === 0))}</div>
              <div style={{ background: t.isDark ? "rgba(255,255,255,.28)" : "rgba(0,0,0,.2)" }} />
              <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>{right.map((r, i) => row(r, i === 0))}</div>
            </section>
            <div style={{ fontSize: 13, fontWeight: 600, color: p.text2, height: 18, flexShrink: 0 }}>平台卡片</div>
            <div data-cards style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, flexShrink: 0 }}>
              {cards.map((r) => (
                <TkCard key={r.key} t={t} r={r} L={L} data={data} today={today} st={st} isToday={isToday}
                        periodName={periodName} thisYear={thisYear} hot={soloOk === r.key}
                        coverage={data.platforms[r.key]?.coverage} onDrill={() => onDrill(r.key)} />
              ))}
              {/* 没坐满一行时的占位（旧页就有，偏离 R2-12）：平台由 scan.py 的注册表决定，不写死某一家。 */}
              {cards.length < 4 && (
                <div style={{ border: `1px dashed ${p.line}`, borderRadius: 12, display: "grid", placeItems: "center",
                              color: p.label, fontSize: 11.5, minHeight: 150, textAlign: "center", lineHeight: 1.6 }}>
                  更多平台<br /><span style={{ fontSize: 10 }}>在 traffic/scan.py 的注册表加一行</span>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function todayTok(data: TrafficData | null, k: string, today: string): number {
  return data?.platforms[k]?.days[today]?.total ?? 0;
}

/** 平台卡片（R2 §5）：头 · 本期大数 + 环比 + 费用 · 今日构成 / 本期趋势 · 底行今日与轮数。 */
function TkCard({ t, r, L, data, today, st, isToday, periodName, thisYear, hot, coverage, onDrill }: {
  t: Theme; r: PlatRow; L: Density; data: TrafficData; today: string; st: RangeState; isToday: boolean;
  periodName: string; thisYear: string; hot: boolean; coverage?: Coverage; onDrill: () => void;
}) {
  const p = tkPal(t);
  const [hov, setHov] = useState(false);
  const base = isToday ? data.platforms[r.key]?.days[addDays(today, -1)]?.total ?? null
    : prevSum(data, st, today, r.key)?.total ?? null;
  const ch = changePct(r.total, base);
  const tk = trendOf(ch);
  const todayB: Bucket | undefined = data.platforms[r.key]?.days[today];
  const vals = r.buckets.map((b) => b.total);
  const pk = peakOf(vals);
  const tops = todayB ? topModels([todayB], 3) : [];
  const mix = todayB ? Object.entries(todayB.models ?? {}).map(([m, v]) => ({ m, v: v.total }))
    .filter((x) => x.v > 0).sort((a, b) => b.v - a.v) : [];
  const mixTot = Math.max(1, mix.reduce((s, x) => s + x.v, 0));
  const max = Math.max(1, ...vals);
  const n = vals.length;
  // 只有一个桶 ⇒ 画满宽水平线（单点没有线段，旧写法会画成一个尖三角，评审）。
  const line = n === 1 ? `M0 ${(50 - (vals[0] / max) * 44).toFixed(1)} L300 ${(50 - (vals[0] / max) * 44).toFixed(1)}`
    : vals.map((v, i) => `${i ? "L" : "M"}${((i / Math.max(1, n - 1)) * 300).toFixed(1)} ${(50 - (v / max) * 44).toFixed(1)}`).join(" ");
  // 本期 Top 模型与占比（旧卡就有，评审：非今日档不能静默丢掉）。
  const periodTop = isToday ? null : topModels(r.buckets, 1)[0] ?? null;
  const cov = coveragePct(coverage);
  return (
    // ★ 整卡可点（旧卡就是，保留；稿只有「明细 →」可点，偏离 R2-10）。
    <section className="tk-entc" data-plat-card={r.name} data-today={todayTok(data, r.key, today)}
             onClick={onDrill} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
             style={{ borderRadius: 12, background: p.panel, padding: "12px 14px 10px", display: "flex",
                      flexDirection: "column", gap: 6, minWidth: 0, cursor: "pointer",
                      border: `1px solid ${hot || hov ? r.color : p.border}`, transition: "border-color .3s ease-out" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
        <PLogo k={r.key} color={r.color} size={18} isDark={t.isDark} />
        {/* 名字是认平台的唯一依据，不让位；860 档卡太窄时先收掉来源小字与「明细」二字。 */}
        <span style={{ fontSize: 14.5, fontWeight: 600, flexShrink: 0 }}>{r.name}</span>
        {r.src && L < 2 && <span style={{ fontSize: 10.5, color: p.label, fontFamily: MONO }}>{r.src}</span>}
        {/* 采集不完整的平台当场标出来（旧卡就有，偏离 R2-11）。 */}
        {cov != null && (
          <span title={coverageNote(coverage)} style={{ fontSize: 9.5, fontWeight: 700, fontFamily: MONO, padding: "1px 4px",
                        borderRadius: 4, color: p.amber, background: "rgba(224,144,28,.14)", flexShrink: 0 }}>
            覆盖 {cov < 1 ? "<1" : cov.toFixed(0)}%
          </span>
        )}
        <span style={{ flex: 1 }} />
        <button type="button" onClick={(e) => { e.stopPropagation(); onDrill(); }}
                style={{ height: 22, padding: "0 4px", borderRadius: 6, border: 0, background: "transparent",
                         color: p.label, fontSize: 12, cursor: "pointer", fontFamily: "inherit", flexShrink: 0 }}
                title="明细">{L < 2 ? "明细 →" : "→"}</button>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
        <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 22, fontWeight: 700, color: r.num }}>
          {fmtTokL(r.total, L)}
        </span>
        <span style={{ fontFamily: MONO, fontSize: 11.5, color: tk === "up" ? p.up : tk === "down" ? p.down : p.label,
                       overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>{sgn(ch)}</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontFamily: MONO, fontSize: 12.5, color: p.amber, flexShrink: 0 }}>{fmtUsdL(r.cost, L)}</span>
      </div>
      {isToday ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 5, height: 72 }} aria-label="今日模型构成">
          <div style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", gap: 1, background: p.track }}>
            {mix.map((x) => <span key={x.m} style={{ flex: `${(x.v / mixTot) * 100} 0 0`, background: modelColor(x.m) }} />)}
          </div>
          {tops.map((m) => (
            <div key={m.model} style={{ display: "grid", gridTemplateColumns: "9px minmax(0,1fr) auto 36px", alignItems: "center",
                                        columnGap: 7, height: 17, fontSize: 11.5, fontFamily: MONO }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: modelColor(m.model) }} />
              <span style={{ color: p.text2, overflow: "hidden", textOverflow: "ellipsis" }}>{m.model.replace(/^claude-/, "")}</span>
              <span style={{ color: p.text }}>{fmtTokL(m.total, L)}</span>
              <span style={{ color: p.label, textAlign: "right" }}>{(m.share * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 3, height: 72 }}>
          <div style={{ display: "flex", fontSize: 10.5, fontFamily: MONO, color: p.label, gap: 6, minWidth: 0 }}>
            <span style={{ flexShrink: 0 }}>{periodName}</span>
            <span style={{ flex: 1 }} />
            {pk && <span style={{ flexShrink: 0 }}>{L === 2 ? "Max" : "峰值"} {fmtTokL(pk.v, L)} · {shortDate(r.labels[pk.i] ?? "", thisYear)}</span>}
          </div>
          <svg viewBox="0 0 300 54" preserveAspectRatio="none" style={{ width: "100%", height: 54, display: "block" }}>
            <line x1="0" x2="300" y1="52" y2="52" stroke={p.line} vectorEffect="non-scaling-stroke" />
            {n > 0 && <path d={`${line} L300 52 L0 52 Z`} fill={r.color} fillOpacity={0.16} />}
            {n > 0 && <path d={line} fill="none" stroke={r.color} strokeWidth={1.6} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />}
          </svg>
        </div>
      )}
      <div style={{ display: "flex", fontSize: 11.5, fontFamily: MONO, gap: 6, borderTop: `1px solid ${p.hair}`,
                    paddingTop: 6, color: p.label }}>
        <span style={{ flexShrink: 0 }}>今日 <span style={{ color: p.text }}>{fmtTokL(todayB?.total ?? 0, L)}</span></span>
        {periodTop && (
          <span data-card-top title={`本期用得最多的模型：${periodTop.model} · ${(periodTop.share * 100).toFixed(1)}%`}
                style={{ overflow: "hidden", textOverflow: "ellipsis", minWidth: 0, color: p.text2 }}>
            · {periodTop.model.replace(/^claude-/, "")} {(periodTop.share * 100).toFixed(0)}%
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span style={{ flexShrink: 0 }}>{fmtIntL(r.rounds, L)} 轮</span>
      </div>
    </section>
  );
}

