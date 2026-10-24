import { useState } from "react";
import PlatformLogo, { type LogoPlatform } from "./PlatformLogo";
import { fmtUSD } from "../rates";
import { fmtTok, cacheModeLabel, type TodayView, type CacheMode } from "../traffic";
import { MONO, NUM_VAR } from "./mb/vars";

/**
 * 摘要行专用的紧凑金额（用户 2026-08-24 定稿：「把金额变成整数，少了三个占位符」）。
 * ★ **`< $10` 仍保两位**：`$0.101` 取整会变成 `$0`，把「有成本」显示成「零成本」。
 */
export function compactUSD(n: number): string {
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}K`;   // $12.3K
  if (n >= 10) return `$${Math.round(n)}`;              // $862
  return fmtUSD(n);                                     // $9.87 / $0.101
}

/** 图的 viewBox：交接包 4f 今日 Tab `svg width=328 height=100`（352 − 两侧 12）。 */
const VW = 328, VH = 100;
/** 横轴最多几个时刻标签。 */
const X_LABELS = 5;

/**
 * Catmull-Rom。⚠️ 这里每层都是"填到基线"的独立面积、自下而上叠画，而且不显示刻度数值（只有悬浮读数，
 * 读的是桶值不是曲线），轻微过冲不会造成误读 —— 全局规则允许的那一种（装饰性）。真要改也只改这一处。
 */
function smooth(pts: [number, number][]): string {
  if (!pts.length) return "";
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(i - 1, 0)], p1 = pts[i];
    const p2 = pts[i + 1], p3 = pts[Math.min(i + 2, pts.length - 1)];
    d += ` C${(p1[0] + (p2[0] - p0[0]) / 6).toFixed(1)} ${(p1[1] + (p2[1] - p0[1]) / 6).toFixed(1)}`
       + ` ${(p2[0] - (p3[0] - p1[0]) / 6).toFixed(1)} ${(p2[1] - (p3[1] - p1[1]) / 6).toFixed(1)}`
       + ` ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}

/** 只有一个采样点时柱子的宽度(viewBox 单位)。 */
const COL_W = VW * 0.12;

/**
 * ★ **一个小时桶要画成柱,不是面积**(2026-08-13 修)：每天 00:00–00:59 只有一个采样点，
 * 一条带至少要两个点；画成横跨全宽的面积等于画一个没发生的事实。
 */
function area(vals: number[], yMax: number): string {
  if (!vals.length) return "";
  if (vals.length === 1) {
    const y = (VH - (vals[0] / yMax) * VH).toFixed(1);
    const x0 = ((VW - COL_W) / 2).toFixed(1), x1 = ((VW + COL_W) / 2).toFixed(1);
    return `M${x0} ${VH} L${x0} ${y} L${x1} ${y} L${x1} ${VH} Z`;
  }
  const pts = vals.map((v, i) => [
    (i / (vals.length - 1)) * VW,
    VH - (v / yMax) * VH,
  ] as [number, number]);
  return `${smooth(pts)} L ${VW} ${VH} L 0 ${VH} Z`;
}

const hourLabel = (h: string): string => `${h.slice(11)}:00`;
const LOGO_KEYS: readonly string[] = ["codex", "claude", "agy", "grok"];

const IconRefresh = ({ spin }: { spin?: boolean }) => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       style={{ animation: spin ? "cbSpin .8s linear infinite" : "none", transformOrigin: "center" }}>
    <path d="M21 12a9 9 0 1 1-3-6.7M21 4v4h-4" />
  </svg>
);

const pctTxt = (d: number): string => `${d >= 0 ? "↑" : "↓"}${Math.abs(d).toFixed(1)}%`;

/**
 * 菜单栏「今日」Tab（交接包 2026-10-19 · 4f，`P4PopRows.html` 第 54 行逐值照抄）：
 *   415M · $188 · 环比徽标 · ↻ 刷新时刻 / 「今日 vs 昨日全天 · 峰值」/ 24 h 堆叠面积图（从左揭开 900 ms）/
 *   各家一行 Token · 费用 · 均速 · 环比（逐行上浮，错开 40 ms）；**0 用量的平台不显示**。
 *
 * ★ 两处刻意偏离画板（坐标轴不说假话，ui.md「菜单栏 v3」那两条照旧）：
 *   ① 横轴标签从真实已过去的小时里取、按真实 x 绝对定位（画板写死 00/06/12/18/现在）；
 *   ② 画板写「今日 vs 昨日同时段」，而这里的环比是与**昨日全天**比（scan.py 只留今天的小时明细），
 *      照抄就是一句关于事实的假话 ⇒ 写「今日 vs 昨日全天」。
 * ★ 均速 = 今天这家所有请求 t/s 的平均（`requests.ts::dayMetrics`，与请求页同源）；拿不到写 —。
 * ★ 悬浮图表：摘要行**就地换成**那一小时的读数（不弹浮层），点图 = 打开工作台 AI用量信息。
 */
export default function MenuBarToday({ view, colors, cacheMode, refreshedAt, busy, isDark, tpsBy,
                                      onRefresh, onOpenPlatform, onOpenOverview }: {
  view: TodayView | null;
  /** 缓存计入口径。数字已在 `useTraffic` 出口重塑过，这里只负责把口径标出来。 */
  cacheMode: CacheMode;
  /** 平台色（`colorOf`，已折进用户偏好）。 */
  colors: Record<string, string>;
  /** 数据的生成时刻(快照时间),不是"现在" */
  refreshedAt: number | null;
  busy: boolean;
  isDark: boolean;
  /** 各家今天的平均 t/s（键 = 请求账本的平台键）。没有的键 = 读不到。 */
  tpsBy: Record<string, number | null>;
  onRefresh: () => void;
  onOpenPlatform: (key: string) => void;
  onOpenOverview: () => void;
}): React.ReactElement {
  const [hvRaw, setHv] = useState<number | null>(null);
  if (!view) {
    return (
      <div className="mb-today" style={{ padding: "26px 16px", textAlign: "center", fontSize: 11.5, color: "var(--tx3)" }}>
        {busy ? "正在首次汇总本机 CLI 记录…" : "暂无数据"}
      </div>
    );
  }

  const { hours, series } = view;
  const per = view.per.filter((p) => p.tok > 0);
  const acc = new Array(hours.length).fill(0) as number[];
  const cum = series.map((s) => {
    s.values.forEach((v, i) => { acc[i] += v; });
    return { key: s.key, top: [...acc] };
  });
  const yMax = Math.max(1, ...acc) * 1.08;

  const n = hours.length;
  const step = [1, 2, 3, 4, 6, 8, 12].find((s) => Math.ceil(n / s) <= X_LABELS) ?? 12;
  const tickIdx = hours.map((_, i) => i).filter((i) => i % step === 0);

  const d = view.deltaPct;
  const hv = hvRaw != null && hvRaw < hours.length ? hvRaw : null;

  return (
    <div className="mb-today mb-slide" style={{ ["--dx" as string]: "28px" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, padding: "6px 12px 16px" }}>
        {/* 摘要行：悬浮图表时就地换成那一小时的读数。★ 这一行绝不换行（用户 2026-08-24 定稿）。 */}
        <div className="mb-today-sum2" style={{ display: "flex", alignItems: "baseline", gap: 10, whiteSpace: "nowrap" }}>
          <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 30, fontWeight: 600, color: "var(--tx)" }}>
            {fmtTok(hv != null ? view.hourTok[hv] : view.totalTok)}</span>
          <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 16, fontWeight: 600, color: "var(--warn)" }}>
            {compactUSD(hv != null ? view.hourCost[hv] : view.totalCost)}</span>
          {hv != null ? (
            <span style={{ fontFamily: MONO, fontSize: 11.5, padding: "1px 6px", borderRadius: 8,
                           color: "var(--accTx)", background: "var(--acc)" }}>{hourLabel(hours[hv])}</span>
          ) : d != null ? (
            <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 11.5, padding: "1px 6px", borderRadius: 8,
                           color: d >= 0 ? "var(--bw)" : "var(--bad)", background: d >= 0 ? "var(--goodBg)" : "var(--badBg)" }}>
              {pctTxt(d)}</span>
          ) : null}
          <span onClick={busy ? undefined : onRefresh}
                title={busy ? "扫描中…" : "重新扫描本机 CLI 记录（只读本地文件，不消耗额度）"}
                style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 4, fontFamily: MONO,
                         fontSize: 11, color: busy ? "var(--acc)" : "var(--tx3)", cursor: busy ? "default" : "pointer" }}>
            <IconRefresh spin={busy} />
            {refreshedAt ? new Date(refreshedAt * 1000).toTimeString().slice(0, 5) : "—"}
          </span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontFamily: MONO, fontSize: 10.5, color: "var(--tx3)",
                      whiteSpace: "nowrap", gap: 8 }}>
          <span>{hv != null ? breakdown(series, colors, hv) : "今日 vs 昨日全天"}</span>
          <span>
            {cacheMode !== "full" && <span style={{ color: "var(--warn)", fontWeight: 700 }}>{cacheModeLabel(cacheMode)} · </span>}
            {view.peak ? `峰值 ${fmtTok(view.peak.v)} · ${hourLabel(view.peak.hour)}` : "今日暂无用量"}
          </span>
        </div>

        {/* 24 h 堆叠图 —— 无 tooltip；整块可点 → 工作台 AI用量信息。 */}
        <div className="mb-today-chart-click" onClick={onOpenOverview} onMouseLeave={() => setHv(null)}
             title="打开工作台 · Token 消耗" style={{ position: "relative", height: 100, overflow: "hidden", cursor: "pointer" }}>
          <svg className="mb-reveal" width="100%" height={VH} viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="none"
               aria-hidden="true" style={{ display: "block" }}>
            {[...cum].reverse().map((c) => (
              <path key={c.key} d={area(c.top, yMax)} fill={colors[c.key]} />
            ))}
            {hv != null && (
              <line x1={xAt(hv, n)} x2={xAt(hv, n)} y1={0} y2={VH} stroke="var(--tx3)" strokeWidth={1}
                    vectorEffect="non-scaling-stroke" pointerEvents="none" />
            )}
            <rect x={0} y={0} width={VW} height={VH} fill="transparent"
                  onMouseMove={(e) => {
                    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
                    const i = Math.round(((e.clientX - r.left) / r.width) * (n - 1));
                    setHv(Math.max(0, Math.min(n - 1, i)));
                  }} />
          </svg>
        </div>
        <div style={{ position: "relative", height: 13, fontFamily: MONO, fontSize: 10, color: "var(--tx3)", whiteSpace: "nowrap" }}>
          {tickIdx.map((i) => (
            <span key={i} style={{
              position: "absolute", left: `${n === 1 ? 50 : (i / (n - 1)) * 100}%`,
              transform: i === 0 ? "translateX(0)" : i === n - 1 ? "translateX(-100%)" : "translateX(-50%)",
            }}>{hourLabel(hours[i])}</span>
          ))}
        </div>

        <div style={{ marginTop: 6 }}>
          <div style={{ display: "grid", gridTemplateColumns: "16px minmax(0, 1fr) 44px 58px 46px 54px", columnGap: 7,
                        height: 22, alignItems: "center", padding: "0 2px", fontSize: 10.5, color: "var(--tx3)", whiteSpace: "nowrap" }}>
            <span /><span>AI</span>
            <span style={{ textAlign: "right" }}>Token</span><span style={{ textAlign: "right" }}>费用</span>
            <span style={{ textAlign: "right" }}>均速</span><span style={{ textAlign: "right" }}>环比</span>
          </div>
          {per.map((p, i) => {
            const tps = tpsBy[p.key];
            return (
              <div key={p.key} className="mb-trow mb-rise" data-mb-today-row={p.key} onClick={() => onOpenPlatform(p.key)}
                   style={{ display: "grid", gridTemplateColumns: "16px minmax(0, 1fr) 44px 58px 46px 54px", columnGap: 7,
                            alignItems: "center", height: 32, padding: "0 2px", borderBottom: "1px solid var(--line)",
                            cursor: "pointer", animationDelay: `${160 + 40 * i}ms` }}>
                {LOGO_KEYS.includes(p.key)
                  ? <PlatformLogo platform={p.key as LogoPlatform} isDark={isDark} size={16} />
                  : <span style={{ width: 10, height: 10, borderRadius: 3, background: colors[p.key], justifySelf: "center" }} />}
                {/* ★ 放不下先藏次要文字（交接包全局规则）：占比放不下就整个换到第二行、被 `height + overflow`
                    藏掉，不会被切成半个字（实测 352 宽下「Claude 99.8%」比这一格宽 ~10px）。 */}
                <span data-mb-namecell="" style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", columnGap: 5,
                               height: 17, overflow: "hidden", minWidth: 0, whiteSpace: "nowrap" }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "var(--tx)", maxWidth: "100%", overflow: "hidden",
                                 textOverflow: "ellipsis" }}>{p.key === "agy" ? "Gemini" : p.name}</span>
                  <span style={{ fontFamily: MONO, fontSize: 10.5, color: "var(--tx3)" }}>{p.pct.toFixed(1)}%</span>
                </span>
                <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12.5, fontWeight: 600,
                               color: "var(--tx)", textAlign: "right", whiteSpace: "nowrap" }}>{fmtTok(p.tok)}</span>
                <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12, color: "var(--warn)",
                               textAlign: "right", whiteSpace: "nowrap" }}>{fmtUSD(p.cost)}</span>
                <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 12, textAlign: "right",
                               whiteSpace: "nowrap", color: tps == null ? "var(--tx3)" : NUM_VAR[p.key] ?? "var(--tx2)" }}>
                  {tps == null ? "—" : Math.round(tps)}<span style={{ fontSize: 9.5, color: "var(--tx3)" }}> t/s</span></span>
                <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 11, textAlign: "right",
                               whiteSpace: "nowrap",
                               color: p.deltaPct == null ? "var(--tx3)" : p.deltaPct >= 0 ? "var(--bw)" : "var(--bad)" }}>
                  {p.deltaPct == null ? "—" : pctTxt(p.deltaPct)}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** 数据点在 viewBox 里的 x。与 `area()` 的取点公式必须一致,否则参考线和曲线对不上。 */
function xAt(i: number, n: number): number {
  return n <= 1 ? VW / 2 : (i / (n - 1)) * VW;
}

/** 某一小时的分平台明细，如 `●82M ●36M`（色块与图同色，一一对应）。 */
function breakdown(
  series: { key: string; name: string; values: number[] }[],
  colors: Record<string, string>,
  i: number,
): React.ReactElement {
  const rows = series
    .map((s) => ({ name: s.name, key: s.key, v: s.values[i] ?? 0 }))
    // ★ 顺序跟图例走 = 今天的 token 总量降序（用户 2026-10-25「都要这样排序」），不按这一小时的值重排。
    .filter((r) => r.v > 0);
  if (!rows.length) return <span style={{ opacity: 0.6 }}>该小时无用量</span>;
  return (
    <span style={{ display: "inline-flex", gap: 8 }}>
      {rows.map((r) => (
        <span key={r.key} title={`${r.name} ${fmtTok(r.v)}`}
              style={{ display: "inline-flex", alignItems: "center", gap: 3.5, whiteSpace: "nowrap" }}>
          <span style={{ width: 7, height: 7, borderRadius: 2, background: colors[r.key], flexShrink: 0 }} />
          {fmtTok(r.v)}
        </span>
      ))}
    </span>
  );
}
