import type { CSSProperties } from "react";
import { SPRING } from "../../tpsHoverLogic";
import type { PriceWarn } from "../../rates";
import { tkPal } from "./tkPal";
import type { Theme } from "../../theme";
import { cacheModeLabel, type CacheMode } from "../../traffic";

const Info = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2.2" />
    <path d="M12 11v5.5M12 7.6v.3" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);

function text(w: PriceWarn): string {
  return w.kind === "promo" ? `优惠价 ${w.date?.slice(5)} 已到期，费用仍按旧价算` : "没有牌价，按同平台兜底价估";
}

/** 堆叠里的另一条弱提示（缓存口径、估算价……）：`head` 是等宽粗体的那一段。 */
export interface StackNote { key: string; head: string; text: string }

/**
 * 缓存口径不是 full 时的那条（原 `CacheChip`）：不在数字旁边说一声，页面会把 34.2B 显示成 0.46B 而毫无提示。
 * 口径名放在粗体那段，排除了什么放后半句；改口径在设置里。
 */
export function cacheNotes(mode: CacheMode): StackNote[] {
  // 条目一行高 30、最宽 340 ⇒ 只写短句。★ 外壳不挂 `title`：停久了系统提示会把展开的内容再弹一遍（用户 2026-10-22）
  return mode === "full" ? [] : [{ key: "cache", head: cacheModeLabel(mode), text: "数字按这个口径算 · 设置里改" }];
}

/**
 * 「消耗」页 / 平台详情页的弱提示堆叠。原来只装「价格待核」；用户 2026-10-22「这些弱警告都改成悬浮折叠警告条」⇒
 * 缓存口径牌（原 `CacheChip`）、「标 * 的是估算价」脚注也并进来（`extra`）。只有价格条目时标签仍是「N 项价格待核」，
 * 混了别的就写「N 项提示」。
 *
 * 原注：Token 消耗页「价格待核」弱警告（用户 2026-10-22 #11「做个弱警告的悬浮堆叠的警告条就好了」）。
 * 与总览「N 项快到期」同一套堆叠（`.ov-xs*`），弱警告档（黄）：它说的是「费用这个估算可能不准」，不是要动手的事。
 * 判据在 `rates.ts::priceWarnings`。
 */
export default function PriceStack({ t, items, extra = [] }: { t: Theme; items: PriceWarn[]; extra?: StackNote[] }) {
  const rows: StackNote[] = [...extra, ...items.map((w) => ({ key: w.key, head: w.model, text: text(w) }))];
  if (rows.length === 0) return null;
  const p = tkPal(t);
  // 底色 / 描边 / 字色走 `.ov-xs[data-level="weak"]`（黄、带透明度，用户 2026-10-22）
  const vars = { "--xsShadow": "none", "--tx": p.text, "--tx3": p.label, "--sp": SPRING } as CSSProperties;
  return (
    <span className="ov-xs" data-level="weak" tabIndex={0} data-price-warn={items.length} data-warn-n={rows.length} data-layers={Math.min(rows.length, 3)} style={vars}>
      <span className="ov-xs-chip"><Info />{rows.length} 项{extra.length ? "提示" : "价格待核"}</span>
      <span className="ov-xs-pop" role="tooltip">
        {rows.map((w, i) => (
          <span key={w.key} className="ov-xs-it" data-price-warn-item={w.key.split(":")[0]}
                style={{ "--i": i, zIndex: rows.length - i } as CSSProperties}>
            <Info />
            <b style={{ fontFamily: "'JetBrains Mono', monospace" }}>{w.head}</b>
            <span className="ov-xs-tx">{w.text}</span>
          </span>
        ))}
      </span>
    </span>
  );
}
