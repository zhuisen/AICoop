import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { Theme } from "../theme";
import { maskId } from "../helpers";
import PlatformLogo from "../components/PlatformLogo";
import { useRequests } from "../hooks/useRequests";
import {
  PLATFORM_NAME, PLATFORM_ORDER, DASH, accountLabel, cacheRate, dayKeys, dayMetrics, daySummary, emptyCopy,
  filterPlatform, fmtHHMM, fmtInt, fmtSecs, fmtTokens, fmtTps, fmtWhen, footerText, modelName,
  rowsForDay, selectedIndex, slowWhy, sourceLabel, sourceNote, timeSplit, toMs, ttftTone, tzLabel,
  type ReqDay, type ReqFilter, type ReqPlatform, type ReqRow, type Tone,
  rowStale,
} from "../requests";

/**
 * 「请求」页 · 1:1 复刻交接包 2026-10-19 `page3-requests/code/RequestsV2*.html`
 * （深色 / 浅色 / 空列表 / 读失败四块画板；数值照抄内联样式与 `renderVals()`）。
 *
 * 逐条看每次请求的用量、首字、速度、耗时；只保留最近 2 天；数据只读本机磁盘。
 * 纯逻辑（筛选、指标、格式化）在 `requests.ts`（零 import，有行为闸）。
 *
 * ## 与画板的偏离（都写了理由）
 * 1. **页框**：侧栏 / 标题栏 / 内容区内边距用 app 现有的外壳（16/20，画板 18/22），
 *    与其余五页一致（项目 §5c 页面统一性）。
 * 2. **选中档的颜色走 `t.accent` / `t.accentText`**。浅色画板写的是 `#2dd4bf` 底 + `#eef1f5` 字，
 *    对比度约 1.6:1，读不清；交接包 README 的浅色 accent 是 `#0E9F8E`。
 * 3. **窄窗横向滚动**：9 列（7 个定宽 + 8 个列距）在 860 宽下装不下 —— 列表框只有 ~441px，
 *    定宽部分就要 486px。画板只画了 1200 宽。这里让表格有最小宽度、**在列表自己的框里横向滚**，
 *    页面根仍不滚；表头在同一个滚动容器里，横滚时与内容一起走，不会错位。
 * 4. **读失败时 logo 不降透明度**：画板把整张列表降到 55%，连 logo 一起；交接包 README 规定
 *    logo 任何状态都不变暗，所以只降文字。
 * 5. **空列表时详情栏不画 logo**：画板在没有选中行时仍放一个 `<img src="">`，渲染成破图标。
 * 6. **数据来源小字按实际来源写**（`requests.ts::sourceNote`），不照抄画板的示意来源。
 * 7. **Scroll Fade 的初值按实际尺寸算**（AICoop 阶段 6）：画板初值 `scB:1`，内容不溢出时底部渐隐也亮着；
 *    这里挂载 / 换数据 / 改尺寸 / 滚动时各量一次，只在变化时写状态。
 * 8. **读失败时表头也降到 55%**（画板整个滚动容器降，表头在里面）；logo 仍不降（偏离 4）。
 * 9. **速度读不到只写「—」**，不带「 t/s」单位（Spec「读不到写 —」）。
 * 10. **均速取实测行的中位数**，不是画板的算术平均 —— 与后端 `avg_tps`、托盘 / 刘海的「均」同一个数（`requests.ts::dayMetrics`）。
 * 11. 读失败且从未读到过：空态写「读不到请求账本 / 读到之后会出现在这里」（画板没有这一态）。
 */

/** 交接包里本页专用、`theme.ts` 里没有的几个值。其余一律取 `t`（两套主题已与画板逐值一致）。 */
const PAL = {
  dark: {
    selRow: "#222a34", amber: "#E0901C", warnBg: "rgba(224,144,28,.12)", warnFg: "#f0c58a",
    errTitle: "#f6c4c1",
    stripe: "repeating-linear-gradient(135deg, rgba(255,255,255,.12) 0 4px, rgba(255,255,255,.04) 4px 8px)",
    num: { codex: "#5eead4", claude: "#F09A76", agy: "#7ab8ff", grok: "#b9aefb" } as Record<ReqPlatform, string>,
  },
  light: {
    selRow: "#eaf0f5", amber: "#b4690e", warnBg: "rgba(224,144,28,.14)", warnFg: "#8a4f06",
    errTitle: "#b42318",
    stripe: "repeating-linear-gradient(135deg, rgba(0,0,0,.12) 0 4px, rgba(0,0,0,.04) 4px 8px)",
    num: { codex: "#0e9f8e", claude: "#c2562f", agy: "#2b6fd6", grok: "#6b5bd6" } as Record<ReqPlatform, string>,
  },
};
const ERR = { bg: "rgba(224,82,77,.12)", line: "rgba(224,82,77,.3)", btn: "rgba(224,82,77,.45)", icon: "#E0524D" };

const NUM: CSSProperties = { fontFamily: "'JetBrains Mono', monospace", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" };
const NOWRAP: CSSProperties = { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };
export const REQ_GRID = "52px minmax(0, 1.3fr) minmax(0, 1fr) 58px 62px 58px 58px 76px 58px";
/** 表格最小宽度（见文件头偏离 3）。1200 宽时列表框 ~781px，大于它，与画板一模一样。 */
const TABLE_MIN_W = 700;
const HEADERS = ["时间", "模型", "来源", "账号", "输入", "输出", "首字", "速度", "耗时"];
const STALE_OPACITY = 0.55;

function localTz(): string {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const part = new Intl.DateTimeFormat("en-US", { timeZoneName: "short" })
      .formatToParts(new Date()).find((p) => p.type === "timeZoneName");
    return tzLabel(zone, part?.value ?? "");
  } catch {
    return "";
  }
}

export interface ReqNav { platform: ReqPlatform | null; n: number }

export default function RequestsPage({ t, privacy, nav }: { t: Theme; privacy: boolean; nav?: ReqNav }) {
  const pal = t.isDark ? PAL.dark : PAL.light;
  const { payload, readAt, err, failed, retry } = useRequests(true);
  const [day, setDay] = useState<ReqDay>("today");
  const [f, setF] = useState<ReqFilter>("all");
  const [selKey, setSelKey] = useState<string | null>(null);
  const tz = useMemo(localTz, []);

  // 托盘悬停面板 / 刘海卡片的「请求页 →」带着平台过来（`open-main-page`）。
  useEffect(() => {
    if (!nav || nav.n === 0) return;
    setF(nav.platform ?? "all");
    setDay("today");
    setSelKey(null);
  }, [nav]);

  const keys = dayKeys(payload, Date.now());
  const all = useMemo(() => rowsForDay(payload?.requests ?? [], day === "today" ? keys.today : keys.yest),
    [payload, day, keys.today, keys.yest]);
  const list = useMemo(() => filterPlatform(all, f), [all, f]);
  // 右上角跟着左边的筛选走（用户 2026-10-22）：选哪家就是哪家今天的数，「全部」= 今天所有请求
  const m = useMemo(() => dayMetrics(list), [list]);
  // 右侧「今天总计」：选了一家 ⇒ 这一家；「全部」⇒ 各家一行（不跨 AI 合计）
  //   ★ 各家按当天 token（输入含缓存 + 输出）降序（用户 2026-10-25「都要这样排序」），原来是固定的平台顺序。
  const sums = useMemo(() => (f === "all" ? PLATFORM_ORDER : [f]).map((p) => ({ p, s: daySummary(filterPlatform(all, p)) }))
    .filter((x) => f !== "all" || x.s.n > 0)
    .sort((a, b) => (b.s.input + b.s.output) - (a.s.input + a.s.output)), [all, f]);
  const sel = selectedIndex(list, selKey);
  const r: ReqRow | undefined = list[sel];
  const stale = err != null;
  // 表头只在「全部读不到」时降；每一行只看它自己那一家（`rowStale`）
  const dim = rowStale(failed, "") ? STALE_OPACITY : 1;
  const toneColor = (tone: Tone) => (tone === "amber" ? pal.amber : tone === "muted" ? t.muted : t.text);
  const acct = (a: string | null) => accountLabel(a, privacy, (s) => maskId(s, true));
  const empty = list.length === 0;
  const ec = emptyCopy(all.length, day);

  const pick = (fn: () => void) => () => { fn(); setSelKey(null); };
  const segBtn = (on: boolean): CSSProperties => ({
    height: 28, padding: "0 12px", borderRadius: 7, border: 0, fontFamily: "inherit", fontSize: 13,
    cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6, whiteSpace: "nowrap",
    background: on ? t.accent : "transparent", color: on ? t.accentText : t.text2,
  });
  const segGroup: CSSProperties = {
    display: "inline-flex", padding: 3, borderRadius: 10, border: `1px solid ${t.divider}`,
    background: t.cardBg, gap: 2, flexShrink: 0,
  };
  const kpi = (label: string, value: string, unit: string) => (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
      <span style={{ fontSize: 11, color: t.muted, whiteSpace: "nowrap" }}>{label}</span>
      <span style={{ ...NUM, fontSize: 17, fontWeight: 600 }}>{value}{value !== DASH && <span style={{ fontSize: 11, fontWeight: 400, color: t.muted }}> {unit}</span>}</span>
    </div>
  );
  const field = (label: string, value: string, color?: string) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
      <span style={{ fontSize: 11, color: t.muted, whiteSpace: "nowrap" }}>{label}</span>
      <b style={{ ...NUM, fontSize: 15, fontWeight: 500, color: color ?? t.text }}>{value}</b>
    </div>
  );

  // Scroll Fade（画板 `onSc`）：能往上滚 ⇒ 表头下方渐隐；还有下文 ⇒ 底部渐隐。只在变化时写状态。
  const scRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const [fade, setFade] = useState({ top: false, bot: false, headH: 37 });
  const measure = useCallback(() => {
    const el = scRef.current;
    if (!el) return;
    const top = el.scrollTop > 2, bot = el.scrollTop + el.clientHeight < el.scrollHeight - 2;
    const headH = headRef.current?.offsetHeight ?? 37;
    setFade((f) => (f.top === top && f.bot === bot && f.headH === headH ? f : { top, bot, headH }));
  }, []);
  useLayoutEffect(measure, [measure, list.length, day, f, stale]);
  useEffect(() => {
    const el = scRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure]);
  const clear = t.isDark ? "rgba(20,26,34,0)" : "rgba(255,255,255,0)";

  const split = r ? timeSplit(r) : null;
  const why = r ? slowWhy(r) : null;
  const rate = r ? cacheRate(r.input, r.cached) : null;

  return (
    <div data-page-body="requests"
         style={{ flex: 1, minHeight: 0, minWidth: 0, display: "flex", flexDirection: "column", gap: 14, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", flexShrink: 0 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 700, whiteSpace: "nowrap" }}>请求</h1>
        <div role="group" aria-label="日期" style={segGroup}>
          <button type="button" data-req-day="today" onClick={pick(() => setDay("today"))} style={segBtn(day === "today")}>今天</button>
          <button type="button" data-req-day="yest" onClick={pick(() => setDay("yest"))} style={segBtn(day === "yest")}>昨天</button>
        </div>
        <div role="group" aria-label="筛选" style={segGroup}>
          <button type="button" data-req-filter="all" onClick={pick(() => setF("all"))} style={segBtn(f === "all")}>全部</button>
          {PLATFORM_ORDER.map((p) => (
            <button key={p} type="button" data-req-filter={p} onClick={pick(() => setF(p))} style={segBtn(f === p)}>
              <PlatformLogo platform={p} isDark={t.isDark} size={13} />{PLATFORM_NAME[p]}
            </button>
          ))}
        </div>
        {/* 画板用 `flex:1` 占位把指标推到右边；换成 `marginLeft:auto` —— 860 宽下标题行折成两行时，
            占位留在第一行，指标会掉到第二行的**左边**；`auto` 外边距在哪一行都把它推到右边。 */}
        <div data-req-kpis style={{ display: "flex", gap: 22, alignItems: "baseline", marginLeft: "auto" }}>
          {kpi(day === "today" ? "今天" : "昨天", m.n ? String(m.n) : DASH, "次")}
          {kpi("均速", fmtTps(m.avgTps), "t/s")}
          {kpi("首字中位", m.ttftMedianS == null ? DASH : m.ttftMedianS.toFixed(1), "s")}
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", gap: 14 }}>
        <section aria-label="请求列表"
                 style={{ minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column", border: `1px solid ${t.cardBorder}`, borderRadius: 14, background: t.cardBg, overflow: "hidden" }}>
          {stale && (
            <div role="alert" data-req-banner
                 style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", background: ERR.bg, borderBottom: `1px solid ${ERR.line}`, flexShrink: 0 }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={ERR.icon} strokeWidth="2" strokeLinecap="round" aria-hidden="true" style={{ flexShrink: 0 }}>
                <circle cx="12" cy="12" r="9" /><path d="M12 7v6M12 16.5v.5" />
              </svg>
              <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
                <span style={{ fontSize: 12.5, fontWeight: 600, color: pal.errTitle, ...NOWRAP }}>读不到请求账本</span>
                <span title={err ?? undefined} style={{ fontSize: 11.5, color: t.text2, ...NOWRAP }}>
                  {(readAt != null ? `下面是 ${fmtHHMM(readAt)} 读到的结果` : "还没有读到过结果")}；原因：{err}，下次刷新会自动重试
                </span>
              </div>
              <button type="button" onClick={retry}
                      style={{ height: 28, padding: "0 12px", borderRadius: 7, border: `1px solid ${ERR.btn}`, background: "transparent", color: pal.errTitle, fontFamily: "inherit", fontSize: 12, cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0 }}>
                重试
              </button>
            </div>
          )}
          {/* ★★ 表头在滚动容器**里面**、sticky 置顶（交接包「容易遗漏」第 1 条）：
              放在外面的话，一出滚动条内容区就变窄，列和表头错位。闸 tests/test_requests_page.py。 */}
          <div ref={scRef} data-req-scroll onScroll={measure} style={{ flex: 1, minHeight: 0, overflow: "auto", paddingBottom: 4 }}>
            {/* 画板把 6px 横向内边距放在滚动容器上；这里放进内层，表头的 -6px 外边距才不会被量成溢出。 */}
            <div style={{ minWidth: TABLE_MIN_W + 12, padding: "0 6px", boxSizing: "border-box" }}>
              <div ref={headRef} data-req-head
                   style={{ position: "sticky", top: 0, zIndex: 1, display: "grid", gridTemplateColumns: REQ_GRID, columnGap: 8, padding: "10px 16px", margin: "0 -6px 4px", fontSize: 11, color: t.muted, background: t.cardBg, borderBottom: `1px solid ${t.divider}` }}>
                {HEADERS.map((h) => <span key={h} style={{ textAlign: "center", whiteSpace: "nowrap", opacity: dim }}>{h}</span>)}
              </div>
              <i data-req-fade="top" data-on={fade.top ? 1 : 0} aria-hidden="true"
                 style={{ position: "sticky", top: fade.headH, zIndex: 1, display: "block", height: 28, margin: "-4px -6px -24px",
                          background: `linear-gradient(${t.cardBg}, ${clear})`, opacity: fade.top ? 1 : 0,
                          transition: "opacity .15s ease-out", pointerEvents: "none" }} />
              {list.map((x, i) => {
                const tone = ttftTone(x.ttft_ms);
                const rd = rowStale(failed, x.platform) ? STALE_OPACITY : 1;
                return (
                  <div key={x.key} data-req-row={i} onClick={() => setSelKey(x.key)}
                       style={{ display: "grid", gridTemplateColumns: REQ_GRID, columnGap: 8, alignItems: "center", height: 34, padding: "0 10px", borderRadius: 7, background: i === sel ? pal.selRow : "transparent", fontSize: 12.5, cursor: "pointer" }}>
                    <span style={{ ...NUM, fontSize: 11.5, color: t.muted, textAlign: "center", opacity: rd }}>{fmtHHMM(toMs(x.t_end))}</span>
                    <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, minWidth: 0, whiteSpace: "nowrap" }}>
                      <PlatformLogo platform={x.platform} isDark={t.isDark} size={14} alt={PLATFORM_NAME[x.platform]} />
                      <span style={{ ...NUM, fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", opacity: rd }}>{modelName(x.model)}</span>
                    </span>
                    <span style={{ color: t.text2, fontSize: 12, textAlign: "center", ...NOWRAP, opacity: rd }}>{sourceLabel(x.platform, x.source)}</span>
                    <span style={{ color: t.text2, textAlign: "center", ...NOWRAP, opacity: rd }}>{acct(x.account)}</span>
                    <span style={{ ...NUM, textAlign: "center", opacity: rd }}>{fmtTokens(x.input)}</span>
                    <span style={{ ...NUM, textAlign: "center", opacity: rd }}>{fmtInt(x.output)}</span>
                    <span style={{ ...NUM, textAlign: "center", color: toneColor(tone), opacity: rd }}>{fmtSecs(x.ttft_ms)}</span>
                    <span style={{ ...NUM, textAlign: "center", fontWeight: 600, color: x.tps == null ? t.muted : pal.num[x.platform], opacity: rd }}>
                      {fmtTps(x.tps)}{x.tps != null && <span style={{ fontSize: 10, fontWeight: 400, color: t.muted }}> t/s</span>}
                    </span>
                    <span style={{ ...NUM, textAlign: "center", color: t.text2, opacity: rd }}>{fmtSecs(x.total_ms)}</span>
                  </div>
                );
              })}
              <i data-req-fade="bot" data-on={fade.bot ? 1 : 0} aria-hidden="true"
                 style={{ position: "sticky", bottom: 0, zIndex: 1, display: "block", height: 32, margin: "-32px -6px 0",
                          background: `linear-gradient(${clear}, ${t.cardBg})`, opacity: fade.bot ? 1 : 0,
                          transition: "opacity .15s ease-out", pointerEvents: "none" }} />
            </div>
            {empty && (
              <div data-req-empty style={{ padding: "90px 24px", display: "flex", flexDirection: "column", alignItems: "center", gap: 8, textAlign: "center" }}>
                <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke={t.muted} strokeWidth="1.5" strokeLinecap="round" aria-hidden="true"><path d="M4 7h11M4 12h16M4 17h8" /></svg>
                <div style={{ fontSize: 14, fontWeight: 600, color: t.text, whiteSpace: "nowrap" }}>{stale && !payload ? "读不到请求账本" : ec.title}</div>
                <div style={{ fontSize: 12, color: t.muted, maxWidth: 300, lineHeight: 1.55 }}>{stale && !payload ? "读到之后会出现在这里" : ec.sub}</div>
              </div>
            )}
          </div>
          <div style={{ padding: "8px 16px", borderTop: `1px solid ${t.divider}`, fontSize: 11, color: t.muted, display: "flex", justifyContent: "space-between", gap: 12, flexShrink: 0 }}>
            <span style={{ ...NOWRAP, minWidth: 0 }}>{footerText(day, list.length, tz)}</span>
            <span style={{ whiteSpace: "nowrap", flexShrink: 0 }}>只保留最近 2 天</span>
          </div>
        </section>

        <aside aria-label="请求详情" data-req-detail
               style={{ display: "flex", flexDirection: "column", gap: 16, padding: 18, border: `1px solid ${t.cardBorder}`, borderRadius: 14, background: t.cardBg, minHeight: 0, minWidth: 0, overflowY: "auto" }}>
          {/* 用户 2026-10-22：「选择 claude 右侧不只是只有单条请求的内容，还有今天总请求的总结」 */}
          <div data-req-summary={f} style={{ display: "flex", flexDirection: "column", gap: 10, paddingBottom: 14, borderBottom: `1px solid ${t.divider}`, flexShrink: 0 }}>
            <div style={{ fontSize: 11, color: t.muted, ...NOWRAP }}>{day === "today" ? "今天" : "昨天"}总计{f === "all" ? " · 各家分开算" : ` · ${PLATFORM_NAME[f]}`}</div>
            {f !== "all" && sums[0] && (() => {
              const x = sums[0].s;
              return <>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "12px 16px" }}>
                  {field("请求", x.n ? `${x.n} 次` : DASH)}
                  {field("均速", x.avgTps != null ? `${fmtTps(x.avgTps)} t/s` : DASH, x.avgTps != null ? pal.num[f] : t.muted)}
                  {field("输入", x.n ? fmtTokens(x.input) : DASH)}
                  {field("输出", x.n ? fmtTokens(x.output) : DASH)}
                  {field("缓存", x.cacheRate == null ? DASH : `${x.cacheRate} %`)}
                  {field("首字中位", x.ttftMedianS == null ? DASH : `${x.ttftMedianS.toFixed(1)} s`)}
                </div>
                {x.n > 0 && <div data-req-summary-measured style={{ fontSize: 11, color: t.muted, ...NOWRAP }}>均速只算有实测速度的 {x.measured} / {x.n} 条</div>}
              </>;
            })()}
            {f === "all" && (sums.length === 0
              ? <div style={{ fontSize: 12, color: t.muted }}>{DASH}</div>
              : sums.map(({ p, s: x }) => (
                <div key={p} data-req-summary-row={p} style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", columnGap: 12, alignItems: "center", fontSize: 12.5 }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0, ...NOWRAP }}>
                    <PlatformLogo platform={p} isDark={t.isDark} size={14} />{PLATFORM_NAME[p]}
                    <span style={{ ...NUM, color: t.muted, fontSize: 11.5 }}>{x.n} 次</span>
                  </span>
                  <span style={{ ...NUM, color: t.text2, textAlign: "right" }}>{fmtTokens(x.input + x.output)}</span>
                  <span style={{ ...NUM, fontWeight: 600, textAlign: "right", color: x.avgTps != null ? pal.num[p] : t.muted }}>
                    {fmtTps(x.avgTps)}{x.avgTps != null && <span style={{ fontSize: 10, fontWeight: 400, color: t.muted }}> t/s</span>}
                  </span>
                </div>
              )))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ ...NUM, fontSize: 11, color: t.muted }}>{r ? fmtWhen(toMs(r.t_end), tz) : ""}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
              {r && <PlatformLogo platform={r.platform} isDark={t.isDark} size={18} />}
              <span style={{ ...NUM, fontSize: 17, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>{r ? modelName(r.model) : DASH}</span>
            </div>
            <div style={{ fontSize: 12.5, color: t.text2, ...NOWRAP }}>
              {r ? `${PLATFORM_NAME[r.platform]} · ${sourceLabel(r.platform, r.source)} · ${acct(r.account)}` : ""}
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "14px 16px" }}>
            {field("输入", r ? fmtTokens(r.input) : DASH)}
            {field("缓存", rate == null ? DASH : `${rate} %`)}
            {field("输出", r ? fmtInt(r.output) : DASH)}
            {field("首字", r ? fmtSecs(r.ttft_ms) : DASH, r && ttftTone(r.ttft_ms) === "amber" ? pal.amber : (r ? t.text : t.muted))}
            {field("速度", r && r.tps != null ? `${fmtTps(r.tps)} t/s` : DASH, r && r.tps != null ? pal.num[r.platform] : t.muted)}
            {field("总耗时", r ? fmtSecs(r.total_ms) : DASH)}
            {field("请求数（本会话）", r && r.session_req_n != null ? String(r.session_req_n) : DASH)}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 11, color: t.muted }}>耗时构成</div>
            {r && split?.kind === "split" && <>
              <div data-req-split style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", gap: 2 }}>
                <i style={{ display: "block", flex: split.ttftMs, background: pal.amber }} />
                <i style={{ display: "block", flex: split.genMs, background: pal.num[r.platform] }} />
              </div>
              <div style={{ display: "flex", gap: 16, fontSize: 11.5, color: t.text2, whiteSpace: "nowrap" }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><i style={{ display: "block", width: 8, height: 8, borderRadius: 2, background: pal.amber }} />首字 {fmtSecs(split.ttftMs)}</span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><i style={{ display: "block", width: 8, height: 8, borderRadius: 2, background: pal.num[r.platform] }} />生成 {fmtSecs(split.genMs)}</span>
              </div>
            </>}
            {r && split?.kind === "none" && <>
              <div data-req-nosplit style={{ height: 8, borderRadius: 4, background: pal.stripe }} />
              <div style={{ fontSize: 11.5, color: t.text2, whiteSpace: "nowrap" }}>{split.why}</div>
            </>}
          </div>
          {why && (
            <div data-req-slow style={{ padding: "10px 12px", borderRadius: 8, background: pal.warnBg, color: pal.warnFg, fontSize: 12, lineHeight: 1.5 }}>{why}</div>
          )}
          <div style={{ marginTop: "auto", paddingTop: 12, borderTop: `1px solid ${t.divider}`, fontSize: 11.5, lineHeight: 1.55, color: t.muted }}>
            {r ? sourceNote(r) : ""}
          </div>
        </aside>
      </div>
    </div>
  );
}
