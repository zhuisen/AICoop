import type { CSSProperties } from "react";
import { SPRING } from "../../tpsHoverLogic";
import type { PriceWarn } from "../../rates";
import { tkPal } from "./tkPal";
import type { Theme } from "../../theme";

const Info = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2.2" />
    <path d="M12 11v5.5M12 7.6v.3" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);

function text(w: PriceWarn): string {
  return w.kind === "promo" ? `优惠价 ${w.date?.slice(5)} 已到期，费用仍按旧价算` : "没有牌价，按同平台兜底价估";
}

/**
 * Token 消耗页「价格待核」弱警告（用户 2026-10-22 #11「做个弱警告的悬浮堆叠的警告条就好了」）。
 * 与总览「N 项快到期」同一套堆叠（`.ov-xs*`），换成中性色：它说的是「费用这个估算可能不准」，不是要动手的事。
 * 判据在 `rates.ts::priceWarnings`。
 */
export default function PriceStack({ t, items }: { t: Theme; items: PriceWarn[] }) {
  if (items.length === 0) return null;
  const p = tkPal(t);
  const vars = { "--xsTx": p.label, "--xsLine": p.border, "--xsBg": p.tipBg, "--xsShadow": "none",
                 "--tx": p.text, "--tx3": p.label, "--sp": SPRING } as CSSProperties;
  return (
    <span className="ov-xs" tabIndex={0} data-price-warn={items.length} data-layers={Math.min(items.length, 3)} style={vars}
          title={items.map((w) => `${w.model} · ${text(w)}`).join("\n")}>
      <span className="ov-xs-chip"><Info />{items.length} 项价格待核</span>
      <span className="ov-xs-pop" role="tooltip">
        {items.map((w, i) => (
          <span key={w.key} className="ov-xs-it" data-price-warn-item={w.kind}
                style={{ "--i": i, zIndex: items.length - i } as CSSProperties}>
            <Info />
            <b style={{ fontFamily: "'JetBrains Mono', monospace" }}>{w.model}</b>
            <span className="ov-xs-tx">{text(w)}</span>
          </span>
        ))}
      </span>
    </span>
  );
}
