import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Theme } from "../../theme";
import type { RangeState, RangePreset } from "../../traffic";
import { PILLS, matchPreset, md, rangeLabel, resolveRange } from "../../traffic";
import PlatformLogo from "../PlatformLogo";
import RangePopover from "../RangePopover";
import { type Density, segWidth } from "../../tokenView";
import { EASE, MONO, logoKey, tkPal } from "./tkPal";

/** 官方 logo；没有 logo 的平台（MiMo、宿主源路由出的未知平台）退回平台色圆点（偏离 R2-6）。 */
export function PLogo({ k, color, size, isDark }: { k: string; color: string; size: number; isDark: boolean }) {
  const lk = logoKey(k);
  if (lk) return <PlatformLogo platform={lk} isDark={isDark} size={size} />;
  const d = Math.round(size * 0.64);
  return <span data-logo-fallback={k}
               style={{ width: size, height: size, display: "inline-grid", placeItems: "center", flexShrink: 0 }}>
    <span style={{ width: d, height: d, borderRadius: "50%", background: color }} />
  </span>;
}

export function InfoI({ color }: { color: string }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ flexShrink: 0 }}>
      <circle cx="6" cy="6" r="5" stroke={color} strokeWidth="1" />
      <path d="M6 5.2v3M6 3.4v.2" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

/**
 * 刷新：图标 +「N mins」（绿；超过 30 分钟琥珀；860 只留图标），完整时间在悬停提示。
 * ★ 稿上没有点击 —— 现行「点了重扫、扫描中转圈」是已有功能，保留（偏离 R2-3）。
 * 颜色分级沿用旧 `StaleHint`：≤ 30 分钟灰、> 30 分钟琥珀（稿里琥珀正是 43 分钟没刷新）。
 */
export function RefreshAgo({ t, generatedAt, L, busy, onRefresh, hint }: {
  t: Theme; generatedAt: number | null; L: Density; busy: boolean; onRefresh?: () => void;
  /** 点击做什么（悬停提示后半句）。默认是 Token 页的「重新扫描本机 CLI 记录」。 */
  hint?: string;
}) {
  const p = tkPal(t);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => { clearInterval(id); };
  }, []);
  if (generatedAt == null) return null;
  const at = new Date(generatedAt * 1000);
  const mins = Math.max(0, Math.floor((now - at.getTime()) / 60_000));
  // 用户 2026-10-22：绿色、「分钟」写 min / mins、不要「前」
  const ago = mins < 1 ? "刚刚" : mins >= 60 ? `${Math.floor(mins / 60)} h` : `${mins} ${mins === 1 ? "min" : "mins"}`;
  const tz = new Intl.DateTimeFormat("en-US", { timeZoneName: "short" }).formatToParts(at)
    .find((x) => x.type === "timeZoneName")?.value ?? "";
  const hhmm = at.toTimeString().slice(0, 5);
  const color = busy ? p.accent : mins > 30 ? p.amber : p.up;
  return (
    <span data-refresh onClick={busy ? undefined : onRefresh}
          title={busy ? "扫描中…" : `上次刷新 ${hhmm}（${tz}）· ${hint ?? "点击重新扫描本机 CLI 记录（只读本地文件，不消耗额度）"}`}
          style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12.5, color,
                   fontFamily: MONO, cursor: busy || !onRefresh ? "default" : "pointer",
                   userSelect: "none", whiteSpace: "nowrap", flexShrink: 0 }}>
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none"
           style={{ animation: busy ? "cbSpin .8s linear infinite" : "none", transformOrigin: "center" }}>
        <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3" stroke={color}
              strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {L < 2 && <span>{busy ? "扫描中" : ago}</span>}
    </span>
  );
}

/**
 * 时间范围分段（稿：滑块 200 ms、按下即响应）。「范围 ▾」打开现行的自定义范围弹层
 * （稿内是空操作；自定义范围早已 1:1 实装，偏离 R2-5）。选了自定义后，末项写区间、旁边出 ✕。
 */
export function RangeSeg({ t, st, today, L, onChange, onToast }: {
  t: Theme; st: RangeState; today: string; L: Density;
  onChange: (s: RangeState) => void; onToast: (m: string) => void;
}) {
  const p = tkPal(t);
  const [open, setOpen] = useState(false);
  const isCustom = st.preset === "custom";
  const r = resolveRange(st, today);
  const items: { key: RangePreset; label: string }[] = [
    ...PILLS.map((k) => ({ key: k, label: rangeLabel(k) })),
    { key: "custom", label: isCustom ? `${md(r.s)} → ${md(r.e)}` : L === 2 ? "范围" : "范围 ▾" },
  ];
  const ws = items.map((x) => segWidth(x.label, L));
  const si = Math.max(0, items.findIndex((x) => x.key === st.preset));
  const x0 = ws.slice(0, si).reduce((a, w) => a + w + 2, 0);
  const pick = (k: RangePreset) => {
    if (k === "custom") { setOpen((o) => !o); return; }
    setOpen(false);
    if (st.preset === k) return;
    // 切回固定档时分格复位成 auto（同 RangeBar：gran 是给某个自定义区间选的）。
    onChange({ ...st, preset: k, gran: "auto" });
  };
  return (
    <div style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
      <div data-seg="range" role="group" aria-label="时间范围"
           style={{ position: "relative", display: "inline-flex", padding: 3, borderRadius: 10, gap: 2,
                    border: `1px solid ${t.isDark ? "rgba(255,255,255,.12)" : "rgba(0,0,0,.12)"}`,
                    background: p.panel }}>
        <i aria-hidden style={{ position: "absolute", left: 3, top: 3, height: 28, width: ws[si], borderRadius: 7,
                                background: p.accent, transform: `translate3d(${x0}px,0,0)`,
                                transition: `transform .2s ${EASE}, width .2s ${EASE}`, willChange: "transform" }} />
        {items.map((x, i) => (
          <button key={x.key} type="button" data-range={x.key} aria-pressed={i === si}
                  onMouseDown={(e) => { if (e.button === 0) pick(x.key); }}
                  onClick={(e) => { if (e.detail === 0) pick(x.key); }}
                  style={{ position: "relative", height: 28, width: ws[i], padding: 0, borderRadius: 7, border: 0,
                           fontSize: 13, background: "transparent", cursor: "pointer", whiteSpace: "nowrap",
                           fontFamily: "inherit", color: i === si ? p.accentOn : p.text2,
                           transition: "color .15s ease-out" }}>{x.label}</button>
        ))}
      </div>
      {isCustom && (
        <span title="清除，回到 30d" role="button"
              onClick={() => {
                setOpen(false);
                onChange({ ...st, preset: "30d", custom: null });
                onToast("已回到 30d · 上次范围可从「范围」恢复");
              }}
              style={{ display: "grid", placeItems: "center", width: 20, height: 20, borderRadius: 5,
                       cursor: "pointer", color: p.label }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
               style={{ stroke: "currentColor", strokeWidth: 2.6 }}><path d="M6 6l12 12M18 6L6 18" /></svg>
        </span>
      )}
      {open && (
        <RangePopover st={st} today={today} t={t} onClose={() => setOpen(false)}
          onApply={({ range, gran, compare }) => {
            setOpen(false);
            // ★ 只有分格选 auto 才归并回固定档：固定档的分格恒为 auto，归并会静默吞掉用户选的「按周 / 按月」（评审）。
            const hit = gran === "auto" ? matchPreset(range, today) : null;
            onChange(hit
              ? { ...st, preset: hit, custom: null, lastCustom: range, gran: "auto", compare }
              : { ...st, preset: "custom", custom: range, lastCustom: range, gran, compare });
            onToast(`范围已应用 · ${md(range.s)} → ${md(range.e)}`);
          }} />
      )}
    </div>
  );
}

export interface Chip { key: string; name: string; color: string }

/** 平台胶囊（稿：高 26 · 内边距 10 · 间距 4；选中只换底色和描边）。 */
export function PlatChips({ t, chips, sel, onPick, withAll, L, aria, fit }: {
  t: Theme; chips: Chip[]; sel: string | null; onPick: (k: string | null) => void;
  withAll: boolean; L: Density; aria: string;
  /** 占满行里剩下的宽；带名字放不下 ⇒ 只留图标（选中的那个和「全部」仍带名字），不在半个胶囊处截断。 */
  fit?: boolean;
}) {
  const p = tkPal(t);
  const box = useRef<HTMLDivElement>(null);
  const fullW = useRef(0);
  const [tight, setTight] = useState(false);
  const sig = chips.map((c) => c.key + c.name).join("|");
  useEffect(() => { fullW.current = 0; setTight(false); }, [sig]);
  useLayoutEffect(() => {
    const el = box.current;
    if (!fit || !el) return;
    // 带名字时量一次全宽；之后只拿「这一格给了多宽」比它 —— 容器是 flex:1，宽度与内容无关，不会来回抖
    const check = () => {
      if (!tight) { fullW.current = el.scrollWidth; if (el.scrollWidth > el.clientWidth + 1) setTight(true); }
      else if (fullW.current && el.clientWidth >= fullW.current) setTight(false);
    };
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit, tight, sig, sel]);
  const btn = (key: string | null, name: string, color: string | null) => {
    const on = sel === key;
    const showName = key === null || (L < 2 && !tight) || (on && (tight || !withAll));
    const bg = on ? (color ? `${color}24` : p.selAll) : "transparent";
    const bd = on ? (color ? `${color}99` : p.selAllBorder) : p.idleBorder;
    return (
      <button key={key ?? "*"} type="button" data-chip={key ?? "all"} aria-pressed={on} title={name}
              onMouseDown={(e) => { if (e.button === 0 && !on) onPick(key); }}
              onClick={(e) => { if (e.detail === 0 && !on) onPick(key); }}
              style={{ height: 26, minWidth: 26, padding: `0 ${showName ? 10 : 5}px`, boxSizing: "border-box",
                       borderRadius: 13, border: `1px solid ${bd}`, background: bg,
                       color: on ? p.text : p.text2, fontSize: 12.5, fontWeight: 500, fontFamily: "inherit",
                       display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 5,
                       flexShrink: 0, cursor: "pointer", whiteSpace: "nowrap",
                       transition: "background .2s ease-out, border-color .2s ease-out, color .2s ease-out" }}>
        {key !== null && <PLogo k={key} color={color ?? p.label} size={14} isDark={t.isDark} />}
        {showName && <span>{name}</span>}
      </button>
    );
  };
  return (
    // 平台多到一行放不下时在行内横滚（不撑破页面），不显示滚动条。
    <div ref={box} role="group" aria-label={aria} data-chips-tight={tight ? "1" : "0"}
         style={{ display: "flex", alignItems: "center", gap: 4, minWidth: 0, overflowX: "auto", scrollbarWidth: "none",
                  ...(fit ? { flex: "1 1 0" } : {}) }}>
      {withAll && btn(null, "全部", null)}
      {chips.map((c) => btn(c.key, c.name, c.color))}
    </div>
  );
}

export interface TkKpi {
  /** `n` + `fmt`：可滚动的数值（数字滚动开着时从 0 滚到 `n`，滚完显示的仍是 `value`）。 */
  label: string; value: string; n?: number; fmt?: (v: number) => string; full?: string; color?: string; sub?: string; subColor?: string;
  tip?: string; info?: boolean; labelLogo?: { k: string; color: string }; valueLogo?: { k: string; color: string };
}

/** 7 格指标条（稿：任何宽度一行 7 列，数字 24、标签 12.5，标签是青色）。 */
export function KpiGrid({ t, items, borderColor, anim, roll = 1 }: {
  t: Theme; items: TkKpi[]; borderColor: string; anim?: string;
  /** 数字滚动进度（`useNumberRoll`）；不给 = 1 = 直接显示。 */
  roll?: number;
}) {
  const p = tkPal(t);
  return (
    <div data-kpis className="tk-dir" style={{ display: "grid", gridTemplateColumns: `repeat(${items.length}, minmax(0,1fr))`,
                  rowGap: 12, borderRadius: 12, background: p.panel, border: `1px solid ${borderColor}`,
                  padding: "12px 0", flexShrink: 0, transition: "border-color .3s ease-out", animation: anim }}>
      {items.map((k) => (
        <div key={k.label} className="tk-entk" data-kpi={k.label}
             style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, minWidth: 0, padding: "0 6px" }}>
          <span title={k.tip} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12.5,
                                       color: p.accent, whiteSpace: "nowrap" }}>
            {k.labelLogo && <PLogo k={k.labelLogo.k} color={k.labelLogo.color} size={13} isDark={t.isDark} />}
            {k.label}
            {k.info && <InfoI color={p.label} />}
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 7, maxWidth: "100%", height: 30 }}>
            {k.valueLogo && <PLogo k={k.valueLogo.k} color={k.valueLogo.color} size={24} isDark={t.isDark} />}
            <span data-kpi-value title={k.full} style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 24,
                                          fontWeight: 700, lineHeight: "30px", color: k.color ?? p.text,
                                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {/* ★ 进度落在 [0,1) 才用它算（同旧 `KpiStrip` 的第二道防线）：滚完、或进度异常，一律显示真值 */}
              {k.n != null && k.fmt && roll >= 0 && roll < 1 ? k.fmt(k.n * roll) : k.value}
            </span>
          </span>
          <span data-kpi-sub style={{ fontSize: 11.5, color: k.subColor ?? p.label, fontFamily: MONO, maxWidth: "100%",
                         overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minHeight: 15 }}>
            {k.sub ?? ""}
          </span>
        </div>
      ))}
    </div>
  );
}
