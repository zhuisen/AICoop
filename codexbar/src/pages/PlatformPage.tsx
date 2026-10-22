import React, { useCallback, useMemo, useRef, useState } from "react";
import { type Theme, modelColor } from "../theme";
import { costOf, fmtUSD, priceOf, isPriced, priceWarnings } from "../rates";
import type { TrafficData, RangeState, CacheMode, Bucket, Platform, PlatformPrefs } from "../traffic";
import Seg from "../components/Seg";
import Toast from "../components/Toast";
import { todayOf, resolveRange, diffDays, effGran, granLabel, md, prevSum, tickTitle, orderedKeys, noCacheCostOfBucket } from "../traffic";
import { rangeLabel, bucketsFor, sumBuckets, costOfBucket, savingOfBucket, fmtTok,
         countsCacheRead, countedClasses, mixParts } from "../traffic";
import PriceStack, { cacheNotes } from "../components/tk/PriceStack";
import { type Density, blendWritePrice, breakevenReads, fmtIntL, fmtPt, fmtTokL, fmtUsdL, hitRate, lowHit, modelLabel,
         nonNullRuns, titleSize } from "../tokenView";
import TkArea, { type TkLayer } from "../components/tk/TkArea";
import { InfoI, KpiGrid, PLogo, PlatChips, RangeSeg, RefreshAgo } from "../components/tk/TkParts";
import { buildKpis, platRows, rangeText } from "../components/tk/tkModel";
import { MONO, SPR9, tkPal } from "../components/tk/tkPal";
import { useDirAnim, useWidth, useWinDensity } from "./TrafficPage";
import "../components/tk/tk.css";

const SRC: Record<string, string> = {
  claude: "~/.claude/projects/**/*.jsonl",
  codex: "~/.codex/sessions/**/rollout-*.jsonl",
  grok: "~/.grok/sessions/*/*/updates.jsonl",
  // ★ agy 的主源是它**自己的会话库**（2026-09-09 起）：`gen_metadata` 里的 protobuf
  //   带四类 token。wrapper 账本降级为并集兜底，只补库已经没了的那些会话。
  //   覆盖率徽章保留 —— 缺口（被 agy 清理掉的旧会话）是真的补不回来。
  agy: "~/.gemini/antigravity-cli/conversations/*.db",
};

// ★★ 这里原有 `AgyQuotaBars`（agy 额度条）与 `CoverageBanner`（覆盖率横幅），
//    2026-09-09 用户拍板删除，**连同组件本体一起删**，不留骨架 ——
//    留一份没人渲染的组件，下一个人会以为它还在页面上（本仓记过的死代码形态）。
//    额度属于**账号**不属于**用量**，它的家在总览的额度卡。
//    要恢复请从 git 历史取。

/** 平台详情(交接稿 §5–§8)。 */
/**
 * 「总量」档的三类 token（用户 2026-08-15 从 5 张整页 mock 里选的「绝对量堆叠」）。
 *
 * ⚠️ **已知取舍,不是缺陷**:本机真实比例是 缓存读 ~95% / 未命中输入 ~4.5% / 输出 ~0.5%,
 * 所以后两条带在 216px 高的图里只有 ~10px 和 ~1px —— 构成基本读不出来。用户看过
 * 100% 堆叠与双轨两个替代版后仍选了这个(要的是真实量级),所以**别再"修"成另外两种**。
 * 补偿手段是图例里直接写占比数字,让读不出来的部分有数兜底。
 *
 * 自下而上 = 占比降序,与总览同规则(大的贴基线)。
 */
const TOTAL_CLASSES = [
  // ★ 名字必须短。浮层只有 **130px** 宽，`输入（命中缓存）` 在 10px 等宽下会被省略号截掉 ——
  //   那正是这个浮层唯一要说的事。`缓存读` 与项目里其它地方(费率卡列名、缓存计入口径、构成行)
  //   用的是同一个词，不再造第二套说法；`新输入` 覆盖 uncached_in + cache_write 的语义：
  //   首次发送的内容，不管有没有顺带写进缓存。全称放 `full`，给图例的 title 用。
  { key: "cache_read",  name: "缓存读", full: "输入 · 命中缓存（按输入价 10% 上下计费）",
    pick: (b: Bucket) => b.cache_read,
    shade: (c: string) => mixHex(c, "#000000", 0.62) },
  { key: "uncached_in", name: "新输入", full: "输入 · 未命中缓存（含首次写入缓存的部分，按全价计费）",
    pick: (b: Bucket) => b.uncached_in + b.cache_write,
    shade: (c: string) => c },
  { key: "output",      name: "输出",   full: "模型生成的 token，单价最高",
    pick: (b: Bucket) => b.output,
    shade: (c: string) => mixHex(c, "#ffffff", 0.68) },
] as const;

/**
 * 单价显示。**不能一律 `toFixed(2)`** —— MiMo 输入价 $0.435 会显示成 $0.43（少 1.1%），
 * DeepSeek 缓存读 $0.044 会变 $0.04。亚元价按三位显示。
 */
function money(x: number): string {
  return x >= 1 ? x.toFixed(2) : x.toFixed(3);
}

/** 平台色的明暗阶。三类是**同一个量的三部分**,用顺序色阶(便宜→贵)比三个无关色相更好读。 */
function mixHex(hex: string, to: string, amt: number): string {
  const h = (x: string) => [1, 3, 5].map((i) => parseInt(x.slice(i, i + 2), 16));
  const [r1, g1, b1] = h(hex), [r2, g2, b2] = h(to);
  const m = (a: number, b: number) => Math.round(a + (b - a) * amt).toString(16).padStart(2, "0");
  return `#${m(r1, r2)}${m(g1, g2)}${m(b1, b2)}`;
}


/** 路由分账行。只有 scan 真的分出账的平台（目前只有 codex）才渲染。 */
function RouteSplit({ t, p, labels, rangeTxt }: {
  t: Theme; p?: Platform;
  /** 当前档位实际画出来的那些日期。**分账只对这批日子求和** ——
   *  同一页上两个数不同窗口是本仓栽过的错（119M vs 9,004M）。 */
  labels: string[];
  rangeTxt: string;
}): React.ReactElement | null {
  const bp = p?.by_provider;
  if (!bp) return null;
  // ★ 「今日」档的标签是 `YYYY-MM-DDTHH`（小时），而分账只按日存 ——
  //   取前 10 位归回日期，再去重。
  const want = new Set(labels.map((l) => l.slice(0, 10)));
  // ★ 显式类型:`Object.entries(...).map(() => [id, total])` 会被推成
  //   `(string | number)[]`，后面的算术全部报错。用对象数组，别用元组。
  const rows: Array<{ id: string; total: number }> = Object.entries(bp)
    .map(([id, perDay]) => {
      let total = 0;
      for (const [d, b] of Object.entries(perDay)) if (want.has(d)) total += b.total;
      return { id, total };
    })
    .filter((r) => r.total > 0)
    .sort((a, b) => b.total - a.total);
  if (rows.length === 0) return null;
  const sum = rows.reduce((a, r) => a + r.total, 0);
  // 账号池的两个 id 是内部名 —— 前端自己给文案；中转站用用户起的显示名。
  const nameOf = (id: string): string =>
    id === "rotateproxy" ? "账号池（代理轮换）"
      : id === "openai" ? "单号直连"
      : id === "unknown" ? "未标注（旧 rollout）"
      : (p?.provider_labels?.[id] ?? id + "（未登记）");
  // ★★ **三分类,不是二分类。** 原来"不是账号池就算中转站" —— 而真实快照里已经有
  //    第 4 个 provider `openai-nows`（38,627 token，09-07 那次 WS 实验的临时 provider，
  //    config 里早就没有了）。它被算成"经中转站"、染上金额琥珀、还进了费用脚注 ——
  //    而它一分钱中转站的账都没走过。
  //    判据改成**是不是登记在册的中转站**（`provider_labels` 里有），
  //    而不是"排除法"。排除法的清单永远追不上现实。
  // ★ 2026-09-10 起 rollout 里再没有中转站戳记（全是 rotateproxy），所以这一栏
  //   恒为空 —— 保留判据只为兼容改动前的历史数据。中转站的归属见下面的 `billed`。
  const isRelay = (id: string): boolean => Boolean(p?.provider_labels?.[id]);
  const isPool = (id: string): boolean => id === "rotateproxy" || id === "openai";
  const relayTok = rows.filter((r) => isRelay(r.id)).reduce((a, r) => a + r.total, 0);
  // ★★ 中转站账单，按当前档位求和。与上面的 `rows` **不同源**：那边是本机 rollout，
  //    这边是中转站自己的 `/usage`。两者**不可相加** —— 这批 token 也在 rotateproxy 里。
  const billed = Object.entries(p?.relay_billed ?? {})
    .map(([id, perDay]) => {
      let total = 0, cost = 0;
      for (const [d, b] of Object.entries(perDay)) {
        if (!want.has(d)) continue;
        total += b.total; cost += b.actual_cost;
      }
      return { id, total, cost };
    })
    .filter((r) => r.total > 0)
    .sort((a, b) => b.total - a.total);
  const billedTok = billed.reduce((a, r) => a + r.total, 0);
  const billedCost = billed.reduce((a, r) => a + r.cost, 0);
  return (
    // ★★ 2026-09-09 用户定稿：整块折叠进一个角标，**悬浮才展开**。
    //    页面上常驻四行路由明细 + 一条费用免责，占了 KPI 之前最贵的一段版面，
    //    而它一天看一次就够。★ 但内容**仍留在 DOM 里**（CSS 控制可见性）——
    //    条件渲染会让本仓所有基于 `--dump-dom` 的行为闸静默失效。
    <div data-route-split className="cb-hoverwrap"
         style={{ margin: "2px 0 10px", fontSize: 11.5 }}>
      {/* ★★ **触发浮层的元素不许再挂 `title`**（用户 2026-09-21）：悬浮时原生提示与
          自定义浮层**同时弹出两层**，而它们说的是同一件事。
          ⚠️ 顺带删掉一句假话 —— 那个 title 写着「近 90 天」，而浮层里的窗口
            2026-09-10 起就跟着页面档位走（现在是 30d）。**披露层说旧事实**
            比不说更糟，它正好会让人按错误的窗口去读这几个数。 */}
      <span data-route-badge
            style={{ display: "inline-flex", alignItems: "center", gap: 5,
                     padding: "2px 8px", borderRadius: 7, cursor: "help", userSelect: "none",
                     border: `1px solid ${relayTok > 0 ? "#E0A21C" : t.ghostBorder}`,
                     color: relayTok > 0 ? "#E0A21C" : t.muted }}>
        {relayTok > 0 ? "⚠️" : "ⓘ"}
        <span style={{ fontWeight: 600 }}>路由分账</span>
      </span>
      {/* ★ 挪进标题行后浮层要**靠左对齐角标**并留出右侧余量：
          `minWidth: 320` 在窄窗下会顶出容器（本仓 UI 规范:溢出算 bug）。 */}
      <div className="cb-hoverpop"
           style={{ minWidth: 300, maxWidth: "min(460px, 60vw)", padding: "11px 13px", borderRadius: 10,
                    background: t.cardBg, border: `1px solid ${t.cardBorder}`,
                    boxShadow: t.shadow, color: t.muted, whiteSpace: "nowrap",
                    /* ★★ 三列网格，不是一行行的内联文本（用户 2026-09-21：「对称点」）。
                       原来每行是 `名称 数值 · 占比` 顺排，名称一长一短 ⇒ 数值与占比
                       **每行都落在不同的 x 上**，读的时候要横着找。
                       全局 `ui-design.md` 写得很直接：**数字右对齐成列（mono 保证对齐），
                       标签左对齐** —— 这里正是它。 */
                    display: "grid", gridTemplateColumns: "1fr auto auto",
                    columnGap: 12, rowGap: 5, alignItems: "baseline",
                    /* ★ 字号显式写在浮层上（用户：「字体清晰点」）。外层角标是 11.5，
                       继承过来数字偏小；12.5 是在这块宽度里不换行的上限。 */
                    fontSize: 12.5 }}>
        {/* ★★ 窗口跟着页面档位走（2026-09-10）。此前后端只下发 90 天一个合计,
            这里只好写死"近 90 天" —— 今日档旁边挂着 90 天的数，正是本仓在 scan 侧
            栽过的那个"同页两个数不同窗口"（119M vs 9,004M）。现在按日下发、按档求和。 */}
        <span style={{ gridColumn: "1 / -1", fontWeight: 700, color: t.text }}>
          路由 · {rangeTxt}
        </span>
        {rows.map((r) => (
          <React.Fragment key={r.id}>
            <span style={{ color: t.text2 }}>{nameOf(r.id)}</span>
            {/* ★ 金额琥珀只给**真的在花钱**的那条路由。未登记/未标注走中性色 ——
                颜色在本仓是有语义的,乱用等于把语义稀释掉。 */}
            <b style={{ textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums",
                        color: isRelay(r.id) ? "#E0A21C" : isPool(r.id) ? t.text : t.muted }}>
              {fmtTok(r.total)}
            </b>
            <span style={{ textAlign: "right", fontFamily: MONO,
                           fontVariantNumeric: "tabular-nums", color: t.muted }}>
              {((r.total / sum) * 100).toFixed(1)}%
            </span>
          </React.Fragment>
        ))}
        {billed.length > 0 && (
          <>
            <span style={{ gridColumn: "1 / -1", fontWeight: 700, color: t.text, marginTop: 5 }}>
              中转站账单 · {rangeTxt}
            </span>
            {billed.map((r) => (
              <React.Fragment key={r.id}>
                <span style={{ color: t.text2 }}>{nameOf(r.id)}</span>
                <b style={{ textAlign: "right", fontFamily: MONO, color: "#E0A21C",
                            fontVariantNumeric: "tabular-nums" }}>{fmtTok(r.total)}</b>
                <span style={{ textAlign: "right", fontFamily: MONO, color: t.muted,
                               fontVariantNumeric: "tabular-nums" }}>
                  实扣 {fmtUSD(r.cost)}
                </span>
              </React.Fragment>
            ))}
          </>
        )}
        {(relayTok > 0 || billedTok > 0) && (
          /* ★★ 用户 2026-09-21：「具体的说明不要了」。原来这里是五行解释性文字，
             把一个 8 行的浮层撑成 13 行，而其中大半是**为什么**而不是**是什么**。
             ⚠️ 但**披露本身不能跟着删** —— 它说的是一条仍然成立的事实：这批 token
             已经含在「账号池」那一行里（代理转发时 codex 只记 `rotateproxy`），
             与下方按 OpenAI 牌价折算的「总费用」**不是一个口径，相加就是错的**。
             所以这里压缩的是**解释**，不是**披露**（同 GrokCard 那条：省掉的是解释）。
             ★ 全文没有消失：它在 `.claude/rules/traffic.md` 与本文件的注释里。 */
          <span data-route-footnote
                style={{ gridColumn: "1 / -1", color: "#E0A21C", whiteSpace: "normal",
                         marginTop: 6, paddingTop: 6, borderTop: `1px solid ${t.divider}`,
                         fontSize: 11, lineHeight: 1.55 }}>
            ⚠️ 其中 {fmtTok(relayTok + billedTok)} 经中转站
            {billedCost > 0 && <> · 实扣 {fmtUSD(billedCost)}</>}
            {billedTok > 0 && <> · 已含在「账号池」行内</>}
            {" · "}<b>勿与下方「总费用」相加</b>
          </span>
        )}
      </div>
    </div>
  );
}


/**
 * 模型表列（R2 §6）：1000 去掉输入 / 输出牌价，860 再去掉占比条。表头与数据行共用。
 * ★ 口径不计缓存读时「缓存命中」整列删除（同 KPI / 缓存四格，08-11 定稿「不同口径 = 不同页面」）。
 */
function modelCols(L: Density, hit: boolean): string {
  const tail = hit ? " 64px" : "";
  if (L === 0) return `10px minmax(120px,180px) minmax(0,1fr) 80px 56px 70px 88px 72px 72px 76px${tail}`;
  if (L === 1) return `10px minmax(120px,180px) minmax(0,1fr) 80px 56px 70px 88px 76px${tail}`;
  return `10px minmax(0,1fr) 80px 56px 70px 88px 76px${tail}`;
}

/**
 * 迷你趋势（缓存四格）。`null` = 这个桶没有分母 ⇒ **断开**，线和填充都不跨过缺测段（阶段 4 评审）。
 * 只有一个桶 ⇒ 画满宽水平线（单点没有线段可画）。
 */
function Mini({ vals, color, refV, refColor }: { vals: (number | null)[]; color: string; refV?: number | null; refColor: string }) {
  const runs = nonNullRuns(vals);
  if (!runs.length) return <svg viewBox="0 0 200 34" style={{ width: "100%", height: 34, marginTop: 4 }} />;
  const all = runs.flat().map((x) => x[1]);
  if (refV != null) all.push(refV);
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const n = Math.max(1, vals.length - 1);
  const X = (i: number) => (i / n) * 200, Y = (v: number) => 31 - ((v - lo) / (hi - lo)) * 27;
  const seg = (r: [number, number][]) => (vals.length <= 1 || r.length === 1
    ? (vals.length <= 1 ? [[0, r[0][1]], [200, r[0][1]]] as [number, number][] : [[X(r[0][0]) - 2, r[0][1]], [X(r[0][0]) + 2, r[0][1]]] as [number, number][])
    : r.map(([i, v]) => [X(i), v] as [number, number]));
  return (
    <svg viewBox="0 0 200 34" preserveAspectRatio="none" style={{ width: "100%", height: 34, marginTop: 4, display: "block" }}>
      {refV != null && <line x1="0" x2="200" y1={Y(refV)} y2={Y(refV)} stroke={refColor} strokeWidth="1" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />}
      {runs.map((r, k) => {
        const pts = seg(r);
        const line = pts.map(([x, v], j) => `${j ? "L" : "M"}${x.toFixed(1)} ${Y(v).toFixed(1)}`).join(" ");
        return (
          <g key={k}>
            <path d={`${line} L${pts[pts.length - 1][0].toFixed(1)} 34 L${pts[0][0].toFixed(1)} 34 Z`} fill={color} fillOpacity={0.14} />
            <path d={line} fill="none" stroke={color} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
          </g>
        );
      })}
    </svg>
  );
}

/**
 * 单个 AI 的消耗页（AICoop R2_Detail / 1000 / 860，1:1）。
 * 顶栏（← Token 消耗 · logo · 「X 消耗」· 刷新 · 时间范围）→ 平台胶囊 → 7 个指标 → 按模型堆叠面积图 → 缓存命中 → 模型表 → 费用口径。
 * ★ 保留（设计里没有、但已有且不能删，偏离 R2-*）：分模型 / 总量切换、模型行点击隔离、路由分账角标、缓存口径牌、
 *   数据源路径（并进来源小字的悬停提示）、估算价 `*`、加载态。
 */
export default function PlatformPage({ t, data, raw, cacheMode, prefs, pk, st, setSt, onBack, busy, onSwitch, onRefresh }: {
  t: Theme;
  /** 已按缓存口径重塑 —— 合计/图表/费用都用它 */
  data: TrafficData | null;
  /** 未重塑。缓存命中、本期构成用它。 */
  raw: TrafficData | null;
  cacheMode: CacheMode;
  /** 平台偏好：胶囊顺序与总览同一套（用户排过就照用户的）。 */
  prefs?: PlatformPrefs;
  pk: string;
  /** 时间范围。★ 与总览页**同一份状态**（两页之间保持）。 */
  st: RangeState; setSt: (s: RangeState) => void;
  onBack: () => void; busy: boolean;
  /** 胶囊直接切平台（带形变，不回总览）。 */
  onSwitch?: (pk: string) => void;
  onRefresh?: () => void;
}): React.ReactElement {
  const p = tkPal(t);
  const { L, W } = useWinDensity();
  const [mode, setMode] = useState<"models" | "total">("models");
  const [iso, setIso] = useState<Set<string>>(new Set());
  /** 「总量」档里被隔离的 token 类（点图例摘掉缓存读，剩下两类按自己的量级铺满）。 */
  const [isoCls, setIsoCls] = useState<Set<string>>(new Set());
  const [hm, setHm] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [host, cw] = useWidth<HTMLDivElement>();
  const today = useMemo(() => todayOf(data), [data]);
  const range = useMemo(() => resolveRange(st, today), [st, today]);
  const rangeDays = diffDays(range.s, range.e);
  const isToday = st.preset === "today";
  const anim = useDirAnim(st.preset === "custom" ? `custom:${range.s}:${range.e}` : st.preset);
  const toastT = useRef(0);
  const showToast = useCallback((m: string) => {
    setToast(m);
    window.clearTimeout(toastT.current);
    toastT.current = window.setTimeout(() => setToast(null), 1800);
  }, []);
  const [lastPk, setLastPk] = useState(pk);
  if (lastPk !== pk) { setLastPk(pk); setHm(null); setIso(new Set()); }

  const rows = useMemo(() => (data ? platRows(t, data, st, today) : []), [t, data, st, today]);
  const me = rows.find((r) => r.key === pk) ?? null;
  const chipRows = useMemo(() => {
    if (!prefs) return rows;
    const by = new Map(rows.map((r) => [r.key, r]));
    return orderedKeys(rows.map((r) => r.key), prefs, (k) => by.get(k)?.total ?? 0).map((k) => by.get(k)!).filter(Boolean);
  }, [rows, prefs]);
  const c = me?.color ?? "#5b6472";
  const v = useMemo(() => {
    if (!data?.platforms[pk]) return null;
    const { labels, buckets } = bucketsFor(data, pk, st, today);
    const agg = sumBuckets(buckets);
    const rb = raw?.platforms[pk] ? bucketsFor(raw, pk, st, today).buckets : buckets;
    const ragg = sumBuckets(rb);
    const models = Object.entries(agg.models)
      .map(([m, mv]) => {
        const r = ragg.models[m];
        return { m, ...mv, cost: costOf(mv, m, pk), hit: r ? hitRate(r.cache_read, r.uncached_in, r.cache_write) : null };
      })
      .sort((a, b) => b.total - a.total);
    return { labels, buckets, rb, agg, ragg, models, cost: costOfBucket(agg, pk), saving: savingOfBucket(agg, pk) };
  }, [data, raw, pk, st, today]);
  const kpis = data && me ? buildKpis({ t, data, raw, rows, sel: [pk], st, today, L, cacheMode, single: true }) : [];

  const totalClasses = TOTAL_CLASSES.filter(
    (cl) => (cl.key !== "cache_read" || countsCacheRead(cacheMode)) && !isoCls.has(cl.key));
  const shown = (v?.models ?? []).filter((m) => !iso.has(m.m));
  const layers: TkLayer[] = mode === "models"
    ? shown.map((m) => ({ key: m.m, name: modelLabel(m.m), color: modelColor(m.m),
                          values: (v?.buckets ?? []).map((b) => b.models?.[m.m]?.total ?? 0) }))
    : totalClasses.map((cl) => ({ key: cl.key, name: cl.name, color: cl.shade(c),
                                   values: (v?.buckets ?? []).map((b) => cl.pick(b)) }));
  const labels = v?.labels ?? [];
  const tipTitle = (i: number) => {
    const l = labels[i] ?? "";
    const w = mode === "models" ? "" : " · 总量";
    if (l.length > 10) return `${l.slice(5, 10)} ${l.slice(11)}:00${w}`;
    return `${l.length === 7 ? tickTitle(l) : l}${w}`;
  };
  const CH = L === 0 ? 236 : L === 1 ? 222 : 210;
  const gran = isToday ? null : effGran(st, rangeDays);
  const rangeTxt = st.preset === "custom" ? `${md(range.s)}→${md(range.e)}` : rangeLabel(st.preset);

  // —— 缓存命中四格（R2 §6 · 视图 G）——
  const cache = useMemo(() => {
    if (!v) return null;
    const a = v.ragg;
    const hit = hitRate(a.cache_read, a.uncached_in, a.cache_write);
    const pb = raw ? prevSum(raw, st, today, pk) : null;
    const ph = pb ? hitRate(pb.cache_read, pb.uncached_in, pb.cache_write) : null;
    const top = v.models[0];
    const q = top ? priceOf(top.m, pk) : null;
    // 写价按本期 1h / 5m 两档的实际占比加权（只有 Claude 有 1h 档）。
    const h1 = a.cache_write > 0 ? Math.min(a.cache_write_1h ?? 0, a.cache_write) / a.cache_write : 0;
    const be = q ? breakevenReads(q.in, q.cacheRead, blendWritePrice(q.in, q.cacheWrite, h1)) : null;
    const ratio = a.cache_write > 0 ? a.cache_read / a.cache_write : null;
    const perReq = v.agg.rounds > 0 ? v.cost / v.agg.rounds : null;
    const noCache = v.agg.rounds > 0 ? noCacheCostOfBucket(v.agg, pk) / v.agg.rounds : null;
    return {
      hit, dpt: hit != null && ph != null ? hit - ph : null, be, ratio, perReq, noCache,
      hitS: v.rb.map((b) => hitRate(b.cache_read, b.uncached_in, b.cache_write)),
      ratioS: v.rb.map((b) => (b.cache_write > 0 ? b.cache_read / b.cache_write : null)),
      saveS: v.buckets.map((b) => savingOfBucket(b, pk)),
      reqS: v.buckets.map((day) => (day.rounds > 0 ? costOfBucket(day, pk) / day.rounds : null)),
    };
  }, [v, raw, st, today, pk]);
  const avgHit = cache?.hit ?? null;

  const mix = useMemo(() => {
    if (!raw?.platforms[pk]) return null;
    const parts = mixParts(sumBuckets(bucketsFor(raw, pk, st, today).buckets), cacheMode);
    return parts.length ? parts.map((x) => `${x.name} ${x.pct.toFixed(1)}%`).join(" · ") : null;
  }, [raw, pk, st, today, cacheMode]);
  // 「标 * 的是估算价」原是表下常驻的琥珀脚注 ⇒ 并进标题行的弱提示堆叠（同「消耗」页的价格待核）
  const priceWarns = useMemo(() => priceWarnings((v?.models ?? []).map((m) => ({ model: m.m, platform: pk })), today), [v, pk, today]);
  const hitCol = countsCacheRead(cacheMode);
  const cols = modelCols(L, hitCol);
  const dpt = fmtPt(cache?.dpt ?? null);
  const gridCell: React.CSSProperties = { borderRadius: 10, background: p.panel2, border: `1px solid ${p.hair}`,
    padding: "10px 12px 8px", display: "flex", flexDirection: "column", gap: 2, minWidth: 0 };
  const R: React.CSSProperties = { textAlign: "right", fontFamily: MONO, fontVariantNumeric: "tabular-nums" };

  return (
    <div data-token-detail style={{ display: "flex", flexDirection: "column", minHeight: 0, height: "100%", gap: 12,
                                    padding: `0 ${L < 2 ? 6 : 0}px 0`, whiteSpace: "nowrap" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, height: 34, flexShrink: 0, minWidth: 0 }}>
        <button type="button" onClick={onBack} aria-label="返回 Token 消耗" data-back
                style={{ height: 30, padding: "0 10px 0 6px", borderRadius: 8, border: `1px solid ${t.isDark ? "rgba(255,255,255,.12)" : "rgba(0,0,0,.12)"}`,
                         background: "transparent", color: p.text2, fontSize: 13, display: "inline-flex", alignItems: "center",
                         gap: 4, cursor: "pointer", fontFamily: "inherit", flexShrink: 0 }}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 3L5 8l5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          {L < 2 && "Token 消耗"}
        </button>
        <PLogo k={pk} color={c} size={24} isDark={t.isDark} />
        {/* ★ 标题是唯一可收缩的那一格：860 下带路由角标 + 口径牌 + 自定义区间时整行放不下，先省略标题（评审）。 */}
        <h1 style={{ margin: 0, fontSize: titleSize(W), fontWeight: 700, minWidth: 0, flexShrink: 1, overflow: "hidden",
                     textOverflow: "ellipsis" }}>{me?.name ?? data?.platforms[pk]?.name ?? pk} 消耗</h1>
        {/* 来源小字（只有 Gemini 写 agy）；数据源路径并进它的悬停提示（偏离 R2-13）。 */}
        <span data-src title={`${SRC[pk] ?? ""}${SRC[pk] ? " · " : ""}读本地 transcript · 不消耗额度`}
              style={{ fontSize: 12, color: p.label, fontFamily: MONO, cursor: "help" }}>{me?.src ?? "ⓘ"}</span>
        <RouteSplit t={t} p={data?.platforms[pk]} labels={labels} rangeTxt={rangeTxt} />
        {/* 弱提示进悬浮堆叠（用户 2026-10-22）：缓存口径 + 这一家用到的模型里价格待核的（行尾 * 是同一件事） */}
        <PriceStack t={t} items={priceWarns} extra={cacheNotes(cacheMode)} />
        <span style={{ flex: 1 }} />
        <RefreshAgo t={t} generatedAt={data?.generated_at ?? null} L={L} busy={busy} onRefresh={onRefresh} />
        <RangeSeg t={t} st={st} today={today} L={L} onChange={setSt} onToast={showToast} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4, height: 26, flexShrink: 0, minWidth: 0 }}>
        <PlatChips t={t} chips={chipRows.map((r) => ({ key: r.key, name: r.name, color: r.color }))} sel={pk}
                   onPick={(k) => { if (k) (onSwitch ?? (() => {}))(k); }} withAll={false} L={L} aria="切换平台" />
        <span style={{ flex: 1 }} />
        {/* 分模型 / 总量（用户 2026-08-15 选的「绝对量堆叠」，保留，偏离 R2-14）。
            ★ 评审：原来叠在图右上角，盖住顶格线并截走右侧几个桶的悬停 ⇒ 挪到胶囊行。 */}
        <Seg opts={["models", "total"] as const} cur={mode} on={setMode}
             label={(x) => (x === "models" ? "分模型" : "总量")} t={t} />
        <span data-range-label style={{ fontSize: 12, color: p.label, fontFamily: MONO, flexShrink: 0 }}>
          {rangeText(st, today, labels, gran && gran !== "day" ? granLabel(gran) : null)}
        </span>
      </div>
      {toast && <Toast msg={toast} t={t} />}

      <div ref={host} data-platform-scroll style={{ flex: "1 1 0", minHeight: 0, overflowY: "auto", overflowX: "hidden",
                                                     display: "flex", flexDirection: "column", gap: 12, paddingBottom: 8 }}>
        {busy && !data && <div style={{ fontSize: 12, color: p.label }}>扫描中…</div>}
        {data && kpis.length > 0 && <KpiGrid t={t} items={kpis} anim={anim} borderColor={p.border} />}
        {!!labels.length && cw > 0 && (
          <div className="tk-dir" style={{ position: "relative", animation: anim?.replace(".22s", ".26s").replace("both", ".03s both") }}>
            <TkArea t={t} width={cw} height={CH} labels={labels} layers={layers} fmt={(n) => fmtTokL(n, L)} unit="token"
                    tipTitle={tipTitle} focus={mode === "models" ? hm : null} />
          </div>
        )}
        {mode === "total" && v && (
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 11, fontFamily: MONO, color: p.text2, flexShrink: 0 }}>
            {TOTAL_CLASSES.filter((cl) => cl.key !== "cache_read" || countsCacheRead(cacheMode)).map((cl) => {
              const sum = v.buckets.reduce((n, b) => n + cl.pick(b), 0);
              const pct = v.agg.total ? (sum / v.agg.total) * 100 : 0;
              const off = isoCls.has(cl.key);
              return (
                <span key={cl.key} title={`${cl.full}\n点击可把它从图里摘掉（只影响这张图，不改口径/费用/总量）`}
                      onClick={() => setIsoCls((z) => {
                        const nx = new Set(z);
                        if (nx.has(cl.key)) nx.delete(cl.key); else nx.add(cl.key);
                        const avail = TOTAL_CLASSES.filter((x) => x.key !== "cache_read" || countsCacheRead(cacheMode)).length;
                        return nx.size >= avail ? z : nx;
                      })}
                      style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer",
                               opacity: off ? 0.38 : 1, transition: "opacity .15s", textDecoration: off ? "line-through" : "none" }}>
                  <span style={{ width: 9, height: 9, borderRadius: 2, background: cl.shade(c), flexShrink: 0 }} />
                  {cl.name}<span style={{ color: p.label }}>{fmtTok(sum)} · {pct.toFixed(2)}%</span>
                </span>
              );
            })}
          </div>
        )}

        {cache && countsCacheRead(cacheMode) && (
          <section data-cache-grid style={{ borderRadius: 12, background: p.panel, border: `1px solid ${p.border}`,
                                            padding: "12px 16px 14px", display: "flex", flexDirection: "column", gap: 10, flexShrink: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, height: 22 }}>
              <span title="缓存命中 = 缓存读 ÷（缓存读 + 输入）；输入含缓存写" style={{ display: "inline-flex", alignItems: "center", gap: 6,
                            fontSize: 14, fontWeight: 600 }}>缓存命中<InfoI color={p.label} /></span>
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 12, color: p.label, fontFamily: MONO }}>{rangeText(st, today, labels, null)}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 10 }}>
              <div style={gridCell} title={`按 token 加权${mix ? ` · 本期构成 ${mix}` : ""}`} data-cache-cell="hit">
                <span style={{ fontSize: 12, color: p.label }}>命中率</span>
                <span style={{ display: "flex", alignItems: "center", gap: 10, height: 30 }}>
                  <span style={{ fontFamily: MONO, fontSize: 22, fontWeight: 700, color: p.accent }}>{cache.hit == null ? "—" : `${cache.hit.toFixed(1)}%`}</span>
                  <span style={{ fontFamily: MONO, fontSize: 11.5, color: dpt.trend === "up" ? p.up : dpt.trend === "down" ? p.down : p.label }}>
                    {dpt.text}
                  </span>
                </span>
                <Mini vals={cache.hitS} color={p.accent} refColor={p.axis} />
                <span style={{ fontSize: 10.5, color: p.label, fontFamily: MONO, overflow: "hidden", textOverflow: "ellipsis" }}>缓存读 ÷（缓存读 + 输入）</span>
              </div>
              <div style={gridCell} data-cache-cell="ratio" title={cache.be != null ? `按 ${v?.models[0]?.m ?? ""} 牌价：写入多付的钱，被读约 ${cache.be.toFixed(2)} 次就省回来` : undefined}>
                <span style={{ fontSize: 12, color: p.label }}>读写比</span>
                <span style={{ display: "flex", alignItems: "center", gap: 10, height: 30 }}>
                  <span style={{ fontFamily: MONO, fontSize: 22, fontWeight: 700 }}>{cache.ratio == null ? "—" : `${cache.ratio.toFixed(1)}×`}</span>
                  <span style={{ fontFamily: MONO, fontSize: 11.5, color: p.label }}>
                    {cache.ratio == null ? "自动缓存" : cache.be == null ? "" : cache.ratio >= cache.be ? "已回本" : "未回本"}
                  </span>
                </span>
                {cache.ratio == null ? <svg viewBox="0 0 200 34" style={{ width: "100%", height: 34, marginTop: 4 }} />
                  : <Mini vals={cache.ratioS} color={c} refV={cache.be} refColor={p.axis} />}
                <span style={{ fontSize: 10.5, color: p.label, fontFamily: MONO, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {cache.ratio == null ? "该平台缓存写入不额外计费"
                    : `每写入 1 份缓存被读的次数${cache.be != null ? ` · 虚线 = 回本 ${cache.be.toFixed(2)}×` : ""}`}
                </span>
              </div>
              <div style={gridCell} data-cache-cell="saved">
                <span style={{ fontSize: 12, color: p.label }}>已省</span>
                <span style={{ display: "flex", alignItems: "center", gap: 10, height: 30 }}>
                  <span style={{ fontFamily: MONO, fontSize: 22, fontWeight: 700, color: p.up }}>{fmtUsdL(v?.saving ?? 0, L)}</span>
                  <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", marginLeft: "auto", lineHeight: "14px", fontSize: 11, minWidth: 0 }}>
                    <span style={{ color: p.label }}>费用的</span>
                    <span style={{ fontFamily: MONO, fontSize: 12, color: p.text }}>{v && v.cost > 0 ? `${(v.saving / v.cost).toFixed(1)} 倍` : "—"}</span>
                  </span>
                </span>
                <Mini vals={cache.saveS} color={p.up} refColor={p.axis} />
                <span style={{ fontSize: 10.5, color: p.label, fontFamily: MONO, overflow: "hidden", textOverflow: "ellipsis" }}>若无缓存需多付的部分</span>
              </div>
              <div style={gridCell} data-cache-cell="per-req">
                <span style={{ fontSize: 12, color: p.label }}>每请求成本</span>
                <span style={{ display: "flex", alignItems: "center", gap: 10, height: 30 }}>
                  <span style={{ fontFamily: MONO, fontSize: 22, fontWeight: 700, color: p.amber }}>{cache.perReq == null ? "—" : fmtUsdL(cache.perReq, L)}</span>
                  <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", marginLeft: "auto", lineHeight: "14px", fontSize: 11, minWidth: 0 }}>
                    <span style={{ color: p.label }}>无缓存</span>
                    <span style={{ fontFamily: MONO, fontSize: 12, color: p.text }}>{cache.noCache == null ? "—" : fmtUsdL(cache.noCache, L)}</span>
                  </span>
                </span>
                <Mini vals={cache.reqS} color={p.amber} refColor={p.axis} />
                <span style={{ fontSize: 10.5, color: p.label, fontFamily: MONO, overflow: "hidden", textOverflow: "ellipsis" }}>请求数不变而它上升 = 缓存在失效</span>
              </div>
            </div>
          </section>
        )}

        {!!v?.models.length && (
          <section data-platform-table style={{ display: "flex", flexDirection: "column", flexShrink: 0, borderTop: `1px solid ${p.line}` }}>
            <div style={{ display: "grid", gridTemplateColumns: cols, alignItems: "center", columnGap: 12, height: 32,
                          fontSize: 11.5, color: p.label, padding: "0 6px" }}>
              <span /><span>模型</span>{L < 2 && <span />}
              <span style={{ textAlign: "right" }}>Token</span><span style={{ textAlign: "right" }}>占比</span>
              <span style={{ textAlign: "right" }}>轮数</span><span style={{ textAlign: "right" }}>等效费用</span>
              {L === 0 && <><span style={{ textAlign: "right" }}>输入 $/M</span><span style={{ textAlign: "right" }}>输出 $/M</span></>}
              <span style={{ textAlign: "right" }}>费用/百万</span>{hitCol && <span style={{ textAlign: "right" }}>缓存命中</span>}
            </div>
            {v.models.map((m) => {
              const q = priceOf(m.m, pk);
              // 「总量」档的图不分模型 ⇒ 行点击不隔离、也不变暗（评审：原来行变暗而图不变）。
              const isoOk = mode === "models";
              const off = isoOk && iso.has(m.m);
              const est = !isPriced(m.m);
              return (
                <div key={m.m} data-model-row={m.m}
                     onClick={isoOk ? () => setIso((z) => { const nx = new Set(z); if (nx.has(m.m)) nx.delete(m.m); else nx.add(m.m); return nx; }) : undefined}
                     onMouseEnter={() => setHm(m.m)} onMouseLeave={() => setHm(null)}
                     title={`${est ? "该型号不在费率表里，按同平台最接近的档位估算" : ""}${est && isoOk ? " · " : ""}${isoOk ? "点击从图里摘掉 / 放回" : ""}` || undefined}
                     style={{ display: "grid", gridTemplateColumns: cols, alignItems: "center", columnGap: 12, height: 38,
                              borderTop: `1px solid ${p.hair}`, padding: "0 6px", borderRadius: 6, cursor: isoOk ? "pointer" : "default",
                              background: hm === m.m ? p.hoverRow : "transparent", opacity: off ? 0.38 : 1,
                              transition: "background .15s ease-out, opacity .15s" }}>
                  <span style={{ width: 10, height: 10, borderRadius: 3, background: modelColor(m.m) }} />
                  <span title={m.m} style={{ fontFamily: MONO, fontSize: 13.5, overflow: "hidden", textOverflow: "ellipsis" }}>{modelLabel(m.m)}</span>
                  {L < 2 && (
                    <span style={{ height: 6, borderRadius: 3, background: p.track, overflow: "hidden" }}>
                      <span style={{ display: "block", height: "100%", background: modelColor(m.m), transition: `width .55s ${SPR9}`,
                                     width: `${(m.total / Math.max(1, v.models[0].total)) * 100}%` }} />
                    </span>
                  )}
                  <span style={{ ...R, fontSize: 14, fontWeight: 600 }}>{fmtTokL(m.total, L)}</span>
                  <span style={{ ...R, fontSize: 12.5, color: p.text2 }}>{((m.total / Math.max(1, v.agg.total)) * 100).toFixed(1)}%</span>
                  <span style={{ ...R, fontSize: 12.5, color: p.text2 }}>{fmtIntL(m.rounds, L)}</span>
                  <span style={{ ...R, fontSize: 13.5, color: p.amber }}>{fmtUsdL(m.cost, L)}</span>
                  {L === 0 && <>
                    <span style={{ ...R, fontSize: 12.5, color: p.text2 }}>${money(q.in)}{est && <span style={{ color: p.amber }}> *</span>}</span>
                    <span style={{ ...R, fontSize: 12.5, color: p.text2 }}>${money(q.out)}</span>
                  </>}
                  <span style={{ ...R, fontSize: 12.5, color: p.label }} title="等效费用 ÷ 该模型 token 数">
                    {m.total > 0 ? `$${(m.cost / (m.total / 1e6)).toFixed(3)}` : "—"}{L > 0 && est && <span style={{ color: p.amber }}> *</span>}
                  </span>
                  {hitCol && (
                    <span style={{ ...R, fontSize: 12.5, color: lowHit(m.hit, avgHit) ? p.down : p.text2 }}
                          title={lowHit(m.hit, avgHit) ? "低于平台均值 1.5 pt 以上" : undefined}>
                      {m.hit == null ? "—" : `${m.hit.toFixed(1)}%`}
                    </span>
                  )}
                </div>
              );
            })}
          </section>
        )}
        <div style={{ fontSize: 11.5, color: p.label, flexShrink: 0, display: "flex", gap: 6, alignItems: "center" }}>
          <span title="费用 = 各类 token 分别乘单价求和；牌价取自各家官网，费率表在 src/rates.ts">
            费用 = {countedClasses(cacheMode)} 类 token × 牌价（2026-09-29）· 等效 API 成本，订阅制下非实付
          </span>
        </div>
      </div>
    </div>
  );
}
