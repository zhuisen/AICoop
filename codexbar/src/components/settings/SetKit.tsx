import { useLayoutEffect, useRef, useState } from "react";
import type { Theme } from "../../theme";
import "./settings.css";

/**
 * 设置页 S1 的积木（AICoop P9，阶段 6；规格 `scratch/aicoop_20261021/P3P9_extract.md` P9.1）。
 * 行本身是 `SettingsPage.tsx::OneLineRow`（旧闸按它的名字取行块，名字不改）。
 * ★ 全部在模块作用域：写在页面 render 里每次都是新组件类型，开关 / 分段的过渡会变成死代码（本仓 `Seg` 那条）。
 * 偏离（PLAN 第 43 条）：分段选中块用临界阻尼 .24 s，不照稿 .4 s 过冲（同一份稿的「性能规矩」写着选中类不回弹）。
 */

/** 一组：组标题 + 一张卡。 */
export function SGroup({ t, id, title, note, children }: {
  t: Theme; id: string; title: string; note?: string; children: React.ReactNode;
}): React.ReactElement {
  return (
    <section data-set-group={id} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, paddingLeft: 2, minWidth: 0 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text2, whiteSpace: "nowrap" }}>{title}</span>
        {note && <span style={{ fontSize: 12, color: t.muted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{note}</span>}
      </div>
      <div className="set-card" style={{ borderRadius: 12, background: t.cardBg, border: `1px solid ${t.cardBorder}`, padding: "0 14px",
                                          ["--setLine" as string]: t.divider } as React.CSSProperties}>
        {children}
      </div>
    </section>
  );
}

/** 开关 36×20。`on == null` = 读不到（半透明、不可点，不是「关」）。按住时白钮向中间拉长 3 px（CSS `:active`）。 */
export function Toggle({ t, on, onClick, busy, attrs }: {
  t: Theme; on: boolean | null; onClick: () => void; busy?: boolean; attrs?: Record<string, string>;
}): React.ReactElement {
  const dead = busy || on == null;
  return (
    <div role="switch" aria-checked={on == null ? undefined : on} aria-disabled={dead || undefined}
         className={`set-tg${on ? " on" : ""}`} {...attrs}
         onClick={() => { if (!dead) onClick(); }}
         style={{ width: 36, height: 20, borderRadius: 10, position: "relative", flexShrink: 0,
                  cursor: dead ? "default" : "pointer", opacity: dead ? 0.5 : 1,
                  background: on ? t.accent : t.isDark ? "rgba(255,255,255,.18)" : "rgba(0,0,0,.16)" }}>
      <i className="set-knob" />
    </div>
  );
}

/**
 * 单选分段：选中块滑到新选项（量真实宽度，不按字符估）。保留 `data-seg`（harness 的 `segRows` 探针认它）。
 */
export function SegSlide<T extends string | number>({ t, opts, cur, label, on, attrs }: {
  t: Theme; opts: readonly T[]; cur: T; label: (v: T) => string; on: (v: T) => void; attrs?: Record<string, string>;
}): React.ReactElement {
  const box = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState<{ x: number; w: number } | null>(null);
  const idx = opts.indexOf(cur);
  useLayoutEffect(() => {
    const b = box.current?.querySelectorAll<HTMLElement>("[data-seg-opt]")[idx];
    setPill(b ? { x: b.offsetLeft, w: b.offsetWidth } : null);
  }, [idx, opts.length, t.isDark]);
  return (
    <div ref={box} data-seg={opts.map(String).join("|")} {...attrs}
         style={{ position: "relative", display: "inline-flex", padding: 2, gap: 2, borderRadius: 8, flexShrink: 0,
                  border: `1px solid ${t.ghostBorder}`, background: t.isDark ? "#0e1117" : "#eef1f5" }}>
      {pill && <i className="set-pill" style={{ transform: `translateX(${pill.x - 2}px)`, width: pill.w, background: t.accent }} />}
      {opts.map((o) => {
        const sel = o === cur;
        return (
          <button key={String(o)} type="button" data-seg-opt={String(o)} aria-pressed={sel} onClick={() => on(o)}
                  className="set-seg-btn"
                  style={{ position: "relative", height: 24, padding: "0 10px", borderRadius: 6, border: 0, background: "transparent",
                           fontSize: 12.5, fontFamily: "inherit", whiteSpace: "nowrap", cursor: "pointer",
                           color: sel ? t.accentText : t.text2 }}>{label(o)}</button>
        );
      })}
    </div>
  );
}

/** 多选：各项自己淡入底色，没有滑块。 */
export function MultiSeg({ t, items, attrs }: {
  t: Theme; attrs?: Record<string, string>;
  items: { k: string; label: React.ReactNode; on: boolean | null; onClick: () => void; attrs?: Record<string, string>; title?: string }[];
}): React.ReactElement {
  return (
    <div {...attrs} style={{ display: "inline-flex", padding: 2, gap: 2, borderRadius: 8, flexShrink: 0,
                             border: `1px solid ${t.ghostBorder}`, background: t.isDark ? "#0e1117" : "#eef1f5" }}>
      {items.map((x) => (
        <button key={x.k} type="button" aria-pressed={x.on == null ? undefined : x.on} disabled={x.on == null} title={x.title} {...x.attrs}
                onClick={() => { if (x.on != null) x.onClick(); }} className="set-seg-btn"
                style={{ height: 24, padding: "0 10px", borderRadius: 6, border: 0, fontSize: 12.5, fontFamily: "inherit",
                         whiteSpace: "nowrap", cursor: x.on == null ? "default" : "pointer", opacity: x.on == null ? 0.5 : 1,
                         display: "inline-flex", alignItems: "center", gap: 5,
                         background: x.on ? (t.isDark ? "rgba(45,212,191,.22)" : "rgba(14,159,142,.16)") : "transparent",
                         color: x.on ? t.text : t.text2, transition: "background-color .2s ease-out, color .2s ease-out" }}>{x.label}</button>
      ))}
    </div>
  );
}

/** 普通按钮（h26）。`kind`：ghost / primary / danger。 */
export function SBtn({ t, kind = "ghost", onClick, children, attrs, disabled, title }: {
  t: Theme; kind?: "ghost" | "primary" | "danger"; onClick: () => void; children: React.ReactNode;
  attrs?: Record<string, string>; disabled?: boolean; title?: string;
}): React.ReactElement {
  const bad = t.isDark ? "#FF8A73" : "#c23f3a";
  const st = kind === "primary" ? { bd: t.accent, bg: t.accent, fg: t.accentText, w: 600 }
    : kind === "danger" ? { bd: t.isDark ? "rgba(255,138,115,.55)" : "rgba(194,63,58,.5)", bg: "transparent", fg: bad, w: 500 }
      : { bd: t.ghostBorder, bg: "transparent", fg: t.text2, w: 400 };
  return (
    <button type="button" title={title} disabled={disabled} {...attrs} onClick={onClick} className="set-btn"
            style={{ height: 26, padding: "0 11px", borderRadius: 7, border: `1px solid ${st.bd}`, background: st.bg, color: st.fg,
                     fontWeight: st.w, fontSize: 12.5, fontFamily: "inherit", whiteSpace: "nowrap", cursor: disabled ? "default" : "pointer",
                     opacity: disabled ? 0.5 : 1 }}>{children}</button>
  );
}

/**
 * 「预设档位」：数值改成档位分段（P9 Spec「数值用预设档位」）。存着的值不在档位里 ⇒ 多一档「N 天」照样选中，不改存储值直到用户点。
 * 存着的是坏值（NaN / ≤0 / 非数字）⇒ 不加那一档（不画「NaN 天」）。
 */
export function presetOpts(presets: readonly number[], cur: number): number[] {
  if (typeof cur !== "number" || !Number.isFinite(cur) || cur <= 0 || presets.includes(cur)) return [...presets];
  return [...presets, cur].sort((a, b) => a - b);
}
