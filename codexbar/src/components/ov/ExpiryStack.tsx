import type { CSSProperties } from "react";
import { cardLeftText } from "../../helpers";
import { shortDate, type ExpiryWarn } from "../../mbLogic";
import { IcTicket } from "./OvCard";

const Warn = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M12 3 2 20h20L12 3Z" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" />
    <path d="M12 10v4.5M12 17.2v.3" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);

function text(w: ExpiryWarn): string {
  if (w.kind === "card") return `${w.count} 张重置卡 ${cardLeftText(w.days)}后作废`;
  return w.days <= 0 ? "订阅今天到期" : `订阅 ${w.days} 天后到期`;
}

/**
 * 总览「快到期」堆叠警告（用户 2026-10-21：「快到期的弄 animate UI 的那种悬浮堆叠警告显示」）。
 *
 * ★ 自己写，不装 `@animate-ui`（PLAN 偏离 1：许可证）。形状照它的 notification stack：
 *   收着时是一枚琥珀角标，身后叠着两层「纸」（条目数 ≥2 / ≥3 才叠）；悬停 / 键盘聚焦时条目从叠着的位置
 *   依次展开成一列（每条晚 35 ms，临界阻尼曲线 `--sp`），离开时收回。
 * ★ 折叠用 CSS（`visibility` + `opacity`），不用条件渲染 —— 行为闸读 `--dump-dom`（ui.md §5c）。
 * ★ 浮层 `pointer-events: none`：它只读，不挡下面卡片的点击。判据与菜单栏通知条同一套（`mbLogic::expiryWarnings`）。
 */
export default function ExpiryStack({ items }: { items: ExpiryWarn[] }) {
  if (items.length === 0) return null;
  const now = Date.now();
  return (
    <span className="ov-xs" tabIndex={0} data-ov-expiry={items.length} data-layers={Math.min(items.length, 3)}
          title={items.map((w) => `${w.node} · ${text(w)}${w.date ? `（${w.date}）` : ""}`).join("\n")}>
      <span className="ov-xs-chip"><Warn />{items.length} 项快到期</span>
      <span className="ov-xs-pop" role="tooltip">
        {items.map((w, i) => (
          <span key={w.key} className="ov-xs-it" data-ov-expiry-item={w.kind}
                style={{ "--i": i, zIndex: items.length - i } as CSSProperties}>
            {w.kind === "card" ? <IcTicket /> : <Warn />}
            <b>{w.node}</b>
            <span className="ov-xs-tx">{text(w)}</span>
            {w.date && <span className="ov-xs-dt">{shortDate(w.date.slice(0, 10), now)}</span>}
          </span>
        ))}
      </span>
    </span>
  );
}
