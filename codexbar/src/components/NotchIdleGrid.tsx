import PlatformLogo, { type LogoPlatform } from "./PlatformLogo";
import type { PanelCell } from "../idleTray";
import { NAME, tone } from "../idleGridLayout";
import * as N from "../notchIdle";

/**
 * 刘海屏版空闲额度格子（AICoop P11 `P11_NotchHover` ③「停在刘海上 · 展开」）。版面常量在 `notchIdle.ts`。
 * 窗口、靠近 / 停留 / 收起判定都在 Rust `notch.rs`；这里只画。数据与托盘悬停面板同一份（菜单栏 webview 推 `idle-panel`）。
 * ★ 恒深色（刘海是黑的）；没有标题栏、底栏、白点；点格子 ⇒ 打开该 AI 总览（Kimi / DeepSeek ⇒ 用量详情）。
 * ★ 出现：.16 s 淡入 + .32 s 弹簧从上方 6.67 pt（画板 10 ÷ 1.5）、96% 落下；收起倒放（先淡出上移，光晕随后再收）。
 */
export default function NotchIdleGrid({ cells, open, reduce, onPick }: {
  cells: PanelCell[];
  open: boolean;
  reduce: boolean;
  onPick: (key: string) => void;
}) {
  const g = N.notchGrid(cells.length);
  const on = open && cells.length > 0;
  const tr = reduce ? "opacity 150ms" : "opacity .16s ease-out, transform .32s cubic-bezier(.2,.9,.25,1)";
  return (
    <div className="ni-panel" data-notch-idle data-notch-idle-h={g.h} aria-hidden={!on}
         style={{ height: g.h, opacity: on ? 1 : 0, pointerEvents: on ? "auto" : "none",
                  transform: on || reduce ? "none" : "translateY(-6.67px) scale(.96)", transition: tr }}>
      <i className="ni-bridge" aria-hidden="true" />
      {cells.map((c, k) => {
        const p = g.pos[k];
        const t = tone(c.key);
        const ringC = c.main === null ? "transparent" : c.low ? N.LOW : t.num(true);
        const dash = N.RING_C * (c.main === null ? 0 : c.main / 100);
        return (
          <div key={c.key} className="ni-cell" data-notch-idle-cell={c.key} data-in-bar={c.inBar ? 1 : 0}
               title={`打开 ${NAME[c.key] ?? c.key} ${N.cellTarget(c.key).page === "overview" ? "总览" : "用量详情"}`}
               onClick={() => onPick(c.key)}
               style={{ left: p.x, top: p.y, width: g.cw, height: g.ch,
                        background: t.tint(c.inBar ? 0.16 : 0.09), boxShadow: `inset 0 0 0 1px ${t.tint(c.inBar ? 0.42 : 0.14)}` }}>
            {c.reset && <span className="ni-reset nh-mono" data-notch-idle-reset>{c.reset}</span>}
            <svg className="ni-ring" width={N.RING} height={N.RING} viewBox={`0 0 ${N.RING} ${N.RING}`}
                 style={{ left: (g.cw - N.RING) / 2, top: N.RING_TOP }} aria-hidden="true">
              <circle cx={N.RING / 2} cy={N.RING / 2} r={N.RING_R} fill="none" stroke="rgba(255,255,255,.08)" strokeWidth={N.RING_SW} />
              <circle cx={N.RING / 2} cy={N.RING / 2} r={N.RING_R} fill="none" stroke={ringC} strokeWidth={N.RING_SW}
                      strokeLinecap="round" strokeDasharray={`${dash.toFixed(2)} ${N.RING_C.toFixed(2)}`}
                      transform={`rotate(-90 ${N.RING / 2} ${N.RING / 2})`} />
            </svg>
            <span className="ni-logo" style={{ left: (g.cw - N.LOGO) / 2, top: N.RING_TOP + (N.RING - N.LOGO) / 2 }}>
              <PlatformLogo platform={c.key as LogoPlatform} isDark size={N.LOGO} />
            </span>
            <span className="ni-main nh-mono" data-notch-idle-main={c.main === null ? "—" : Math.round(c.main)} data-notch-idle-stale={c.stale ? 1 : 0}
                  title={c.stale ? "这次没读到，显示的是上一次读到的数" : undefined}
                  style={{ color: c.main === null ? "var(--tx3)" : c.low ? N.LOW : c.stale ? "var(--tx2)" : "var(--tx)" }}>
              {c.main === null ? "—" : `${Math.round(c.main)}%`}
            </span>
          </div>
        );
      })}
    </div>
  );
}
