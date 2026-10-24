import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Theme } from "../../theme";
import { axisTick } from "../../traffic";
import { axisIdx, bandPath, critEase, layerAt, lerpArr, resample, stackTops, yTicks } from "../../tokenView";
import { introEnabled } from "../../hooks/useIntro";
import { EASE, MONO, tkPal } from "./tkPal";
import { PLogo } from "./TkParts";

export interface TkLayer { key: string; name: string; color: string; values: number[]; num?: string }

const X0 = 50, Y1 = 8;

interface Disp { keys: string[]; vals: number[][]; maxV: number }

/** 不做形变：系统「减弱动态效果」或设置页「入场动效」关（两者同语义，任一为关就不动画）。 */
function reduced(): boolean {
  return !introEnabled()
    || (typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

/**
 * Token 消耗页的堆叠面积图（R2 §4）。
 *
 * - 4 个纵轴刻度（0、⅓、⅔、1 × 峰值 × 1.08）、轴线与刻度短线、左上角单位。
 * - 悬停：竖线 + 200 宽浮层，鼠标移动时**滑过去不重弹**（100 ms）；到右侧贴边钳住。
 * - 切换：形变 + 数值插值 560 ms 临界阻尼，可被新的切换打断（`critEase`）；减弱动态效果时直接到位。
 * - ★ 保留（偏离 R2-6/7）：Fritsch–Carlson 单调插值、横轴从末尾锚定抽稀、点图层下钻（`onPick`）。
 * 层顺序 = 调用方给的顺序（自下而上，大的贴基线）。
 */
export default function TkArea({ t, width, height, labels, layers, fmt, unit, tipTitle, rows, focus, onPick, rowLogo }: {
  t: Theme; width: number; height: number; labels: string[]; layers: TkLayer[];
  fmt: (n: number) => string; unit: string; tipTitle: (i: number) => string;
  /** 浮层逐行（总览 = 平台注册顺序、零值也列；消耗页 = 模型序）。缺省 = `layers`。 */
  rows?: TkLayer[];
  /** 模型表悬停：该层不透明 + 浅色描边，其余降到 14%。 */
  focus?: string | null;
  onPick?: (key: string) => void;
  rowLogo?: boolean;
}) {
  const p = tkPal(t);
  const CW = Math.max(200, width), CH = height, Y0 = CH - 26;
  const n = labels.length;
  const st0 = stackTops(layers.map((l) => l.values));
  const rawMax = Math.max(1, ...(st0[st0.length - 1] ?? [1]));
  const target: Disp = { keys: layers.map((l) => l.key), vals: layers.map((l) => l.values), maxV: rawMax * 1.08 };
  // ★ 两个签名：`sig` = 数据集身份（档位 / 起点 / 图层），悬停下标跟它走；`dataSig` 再带上数值，只驱动过渡动画。
  //   数值进了悬停签名的话，心跳刷新时鼠标不动浮层也会消失（全方面评审 2026-10-22 §2）。
  const sig = `${n}|${labels[0] ?? ""}|${target.keys.join(",")}`;
  const dataSig = `${sig}|${target.vals.map((v) => v.join(",")).join(";")}`;

  const [disp, setDisp] = useState<Disp>(target);
  const dispRef = useRef<Disp>(target);
  const raf = useRef(0);
  const first = useRef(true);
  // ★ 悬停下标**带着数据集签名**：换档的第一帧旧下标就作废，不会拿旧索引读新数据画一帧（ui-design.md）。
  const [hover, setHoverRaw] = useState<{ sig: string; i: number }>({ sig: "", i: -1 });
  const setHover = (i: number) => setHoverRaw({ sig, i });
  const wasHover = useRef(false);
  /** 最近一次有效的悬停下标：离开时浮层与竖线**原地**淡出，不跳到最左、不先变成 0（评审）。 */
  const lastHv = useRef(-1);

  useLayoutEffect(() => {
    lastHv.current = -1;
    cancelAnimationFrame(raf.current);
    if (first.current || reduced()) {
      first.current = false;
      dispRef.current = target; setDisp(target);
      return;
    }
    const from = dispRef.current, t0 = performance.now();
    const step = (now: number) => {
      const e = critEase((now - t0) / 560);
      const next: Disp = {
        keys: target.keys,
        vals: target.vals.map((v, j) => {
          const fj = from.keys.indexOf(target.keys[j]);
          return lerpArr(fj >= 0 ? from.vals[fj] : v.map(() => 0), v, e);
        }),
        maxV: from.maxV + (target.maxV - from.maxV) * e,
      };
      dispRef.current = next; setDisp(next);
      if (e < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(raf.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataSig]);

  const xAt = (i: number) => (n <= 1 ? (X0 + CW) / 2 : X0 + (i / (n - 1)) * (CW - X0));
  const yAt = (v: number) => Y0 - (v / Math.max(1, disp.maxV)) * (Y0 - Y1);
  // 切换后、第一帧动画之前，disp 还是旧长度 ⇒ 先重采样到新长度（不闪成 0）。
  const tops = stackTops(target.keys.map((k) => {
    const j = disp.keys.indexOf(k);
    return j >= 0 ? resample(disp.vals[j], n) : new Array(n).fill(0);
  }));
  const pts = (arr: number[]) => arr.map((v, i) => [xAt(i), yAt(v)] as [number, number]);
  const base = new Array(n).fill(0);
  const colW = Math.min((CW - X0) * 0.06, 72);

  const hv = hover.sig === sig && hover.i >= 0 && hover.i < n ? hover.i : -1;
  if (hv >= 0) lastHv.current = hv;
  const sh = hv >= 0 ? hv : lastHv.current < n ? lastHv.current : -1;   // 显示用的下标（淡出期间沿用上一次）
  const sliding = wasHover.current && hv >= 0;
  useEffect(() => { wasHover.current = hv >= 0; });
  const hT = sliding ? `transform .1s ${EASE}, opacity .1s` : "opacity .1s";
  const hx = sh >= 0 ? xAt(sh) : 0;
  const tipLeft = Math.min(hx + 12, CW - 210);
  const tipRows = (rows ?? layers);
  const tipVal = (key: string) => {
    const L = layers.find((l) => l.key === key);
    return sh >= 0 && L ? (L.values[sh] ?? 0) : 0;
  };
  const tipSum = tipRows.reduce((s, r) => s + tipVal(r.key), 0);
  const ticks = axisIdx(n, CW - X0);

  return (
    <section data-tk-chart style={{ position: "relative", width: CW, height: CH, flexShrink: 0, marginTop: 4 }}>
      <svg width={CW} height={CH} viewBox={`0 0 ${CW} ${CH}`} style={{ display: "block", overflow: "visible" }}>
        {[0, 1 / 3, 2 / 3, 1].map((f) => {
          const y = Y0 - f * (Y0 - Y1);
          return <line key={f} x1={X0} x2={CW} y1={y} y2={y} stroke={t.isDark ? "rgba(255,255,255,.06)" : "rgba(0,0,0,.06)"} strokeWidth={1} />;
        })}
        {layers.map((l, j) => {
          const dim = focus != null && focus !== l.key;
          const on = focus != null && focus === l.key;
          return (
            <path key={l.key} data-layer={l.key} d={n ? bandPath(pts(tops[j] ?? base), pts(j ? tops[j - 1] : base), colW) : ""}
                  fill={l.color} fillOpacity={dim ? 0.14 : on ? 1 : 0.9}
                  stroke={on ? p.text : "none"} strokeWidth={on ? 1.5 : 0}
                  onClick={onPick ? () => onPick(l.key) : undefined}
                  style={{ transition: "fill-opacity .18s ease-out", cursor: onPick ? "pointer" : "default" }} />
          );
        })}
        <line x1={X0} x2={X0} y1={Y1} y2={Y0} stroke={p.axis} strokeWidth={1} />
        <line x1={X0} x2={CW} y1={Y0} y2={Y0} stroke={p.axis} strokeWidth={1} />
        {ticks.map((i) => <line key={i} x1={xAt(i)} x2={xAt(i)} y1={Y0} y2={Y0 + 4} stroke={p.axis} strokeWidth={1} />)}
      </svg>
      <i aria-hidden style={{ position: "absolute", left: 0, top: 6, width: 0, height: Y0 - 6,
                              borderLeft: `1px dashed ${p.text2}`, transform: `translate3d(${hx}px,0,0)`,
                              opacity: hv >= 0 ? 1 : 0, transition: hT, pointerEvents: "none" }} />
      {yTicks(disp.maxV).map((v, k) => (
        <span key={k} data-ytick={k} style={{ position: "absolute", left: 0, top: Y0 - (k / 3) * (Y0 - Y1) - 7, width: 44,
                               textAlign: "right", fontSize: 11, lineHeight: "14px", color: p.label, fontFamily: MONO }}>
          {k === 0 ? "0" : fmt(v)}
        </span>
      ))}
      {ticks.map((i) => (
        // ★ 末尾锚定后最后一个标签落在右沿：居中会伸出图外被裁（「10-」），贴边时改右对齐。
        <span key={i} data-xtick style={{ position: "absolute", top: Y0 + 7, left: Math.min(xAt(i) - 30, CW - 60), width: 60,
                                          textAlign: xAt(i) + 30 > CW ? "right" : "center",
                                          fontSize: 11, lineHeight: "14px", color: p.label, fontFamily: MONO }}>
          {axisTick(labels[i])}
        </span>
      ))}
      <span data-unit style={{ position: "absolute", left: 56, top: -4, fontSize: 11, color: p.text2, fontFamily: MONO }}>{unit}</span>
      <div onMouseMove={(e) => {
             const r = e.currentTarget.getBoundingClientRect();
             const x = (e.clientX - r.left) / Math.max(1, r.width);
             const i = Math.max(0, Math.min(n - 1, Math.round(x * (n - 1))));
             if (i !== hv) setHover(i);
           }}
           onMouseLeave={() => setHover(-1)}
           onClick={onPick ? (e) => {
             // 命中层盖在图上：点下去时按**真实横坐标**插值各层上沿、再按纵值找层（保留「点图层进详情」）。
             const r = e.currentTarget.getBoundingClientRect();
             const fx = ((e.clientX - r.left) / Math.max(1, r.width)) * (n - 1);
             const v = ((Y0 - (e.clientY - r.top)) / (Y0 - Y1)) * disp.maxV;
             const j = layerAt(tops, fx, v);
             if (j >= 0) onPick(layers[j].key);
           } : undefined}
           style={{ position: "absolute", left: X0, top: 0, right: 0, height: Y0, cursor: onPick ? "pointer" : "default" }} />
      <div data-tk-tip style={{ position: "absolute", top: 8, left: 0, transform: `translate3d(${tipLeft}px,0,0)`,
                    opacity: hv >= 0 ? 1 : 0, transition: hT, width: 200, padding: "8px 10px", borderRadius: 10,
                    background: p.tipBg, border: `1px solid ${p.tipBorder}`,
                    boxShadow: t.isDark ? "0 16px 40px rgba(0,0,0,.45)" : "0 12px 30px rgba(0,0,0,.14)",
                    display: "flex", flexDirection: "column", gap: 4, pointerEvents: "none", fontSize: 12, zIndex: 3 }}>
        <span style={{ fontFamily: MONO, color: p.label, fontSize: 11 }}>{sh >= 0 ? tipTitle(sh) : ""}</span>
        {tipRows.map((r) => (
          <span key={r.key} data-tip-row={r.key} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {rowLogo ? <PLogo k={r.key} color={r.color} size={13} isDark={t.isDark} />
                     : <span style={{ width: 9, height: 9, borderRadius: 2, background: r.color, flexShrink: 0 }} />}
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: p.text2 }}>{r.name}</span>
            <span style={{ flex: 1 }} />
            <span style={{ fontFamily: MONO, color: rowLogo ? (r.num ?? r.color) : p.text }}>{fmt(tipVal(r.key))}</span>
          </span>
        ))}
        <span style={{ display: "flex", borderTop: `1px solid ${p.border}`, paddingTop: 4, color: p.accent }}>
          合计<span style={{ flex: 1 }} /><span style={{ fontFamily: MONO }}>{fmt(tipSum)}</span>
        </span>
      </div>
    </section>
  );
}
