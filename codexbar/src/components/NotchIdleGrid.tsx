import { emit } from "@tauri-apps/api/event";
import PlatformLogo, { type LogoPlatform } from "./PlatformLogo";
import { IDLE_SNOOZE_EVENT, type IdleWarn, type PanelCell, type Snoozed } from "../idleTray";
import { NAME, tone } from "../idleGridLayout";
import * as N from "../notchIdle";

/**
 * 刘海屏版空闲额度格子（AICoop P11 `P11_NotchHover` ③「停在刘海上 · 展开」）。版面常量在 `notchIdle.ts`。
 * 窗口、靠近 / 停留 / 收起判定都在 Rust `notch.rs`；这里只画。数据与托盘悬停面板同一份（菜单栏 webview 推 `idle-panel`）。
 * ★ 恒深色（刘海是黑的）；没有标题栏、底栏、白点；点格子 ⇒ 打开该 AI 总览（Kimi / DeepSeek ⇒ 用量详情）。
 * ★ 出现：.16 s 淡入 + .32 s 弹簧从上方 6.67 pt（画板 10 ÷ 1.5）、96% 落下；收起倒放（先淡出上移，光晕随后再收）。
 */
export default function NotchIdleGrid({ cells, snoozed, warns, open, reduce, hov, onHov, onPick }: {
  cells: PanelCell[];
  /** 藏起来的几家（同悬停面板）：底部一行一家，带「撤销」。 */
  snoozed: Snoozed[];
  /** 周额度 < 10%：那一家格子左上角的小红牌（同悬停面板 A1）。 */
  warns: IdleWarn[];
  open: boolean;
  reduce: boolean;
  /** 光标停在哪一格（网页 mouseenter 或 Rust `notch-hover`）：高亮 + 右上角倒计时换成 ×（同悬停面板 B1）。 */
  hov: string | null;
  onHov: (key: string | null) => void;
  onPick: (key: string) => void;
}) {
  const g = N.notchGrid(cells.length, snoozed.length);
  const on = open && (cells.length > 0 || snoozed.length > 0);
  const weekOf = new Map(warns.map((w) => [w.key, w.rem]));
  const snooze = (key: string, undo = false) => { void emit(IDLE_SNOOZE_EVENT, { key, undo }).catch(() => undefined); };
  const tr = reduce ? "opacity 150ms" : "opacity .16s ease-out, transform .32s cubic-bezier(.2,.9,.25,1)";
  return (
    <div className="ni-panel" data-notch-idle data-notch-idle-h={g.h} data-notch-idle-w={g.w} aria-hidden={!on}
         style={{ height: g.h, width: g.w, left: `calc(50% - ${g.w / 2}px)`, opacity: on ? 1 : 0, pointerEvents: on ? "auto" : "none",
                  transform: on || reduce ? "none" : "translateY(-6.67px) scale(.96)", transition: tr }}>
      <i className="ni-bridge" aria-hidden="true" />
      {cells.map((c, k) => {
        const p = g.pos[k];
        const t = tone(c.key);
        const ringC = c.main === null ? "transparent" : c.low ? N.LOW : t.num(true);
        const dash = N.RING_C * (c.main === null ? 0 : c.main / 100);
        const h = on && hov === c.key;
        return (
          <div key={c.key} className="ni-cell" data-notch-idle-cell={c.key} data-in-bar={c.inBar ? 1 : 0}
               title={`打开 ${NAME[c.key] ?? c.key} ${N.cellTarget(c.key).page === "overview" ? "总览" : "用量详情"}`}
               onClick={() => onPick(c.key)} onMouseEnter={() => onHov(c.key)}
               onMouseLeave={() => { if (hov === c.key) onHov(null); }} data-notch-idle-hov={h ? 1 : 0}
               style={{ filter: h ? "brightness(1.3)" : "none", left: p.x, top: p.y, width: g.cw, height: g.ch,
                        background: t.tint(c.inBar ? 0.16 : 0.09), boxShadow: `inset 0 0 0 1px ${t.tint(c.inBar ? 0.42 : 0.14)}` }}>
            {weekOf.has(c.key) && <span className="ni-wk nh-mono" data-notch-idle-week={weekOf.get(c.key)}>周{Math.round(weekOf.get(c.key)!)}%</span>}
            {c.reset && <span className="ni-reset nh-mono" data-notch-idle-reset style={{ opacity: h ? 0 : 1 }}>{weekOf.has(c.key) ? c.reset.replace(/^↻ /, "") : c.reset}</span>}
            {/* 悬停时右上角倒计时换成 ×，点了藏到重置（同悬停面板 B1；CSS 显隐，不条件渲染） */}
            <span className="ni-x" data-notch-idle-hide={c.key} title={`隐藏 ${NAME[c.key] ?? c.key}，${c.reset ? c.reset.replace("↻ ", "") + " 后" : "重置后"}自动回来`}
                  onClick={(e) => { e.stopPropagation(); snooze(c.key); }}
                  style={{ opacity: h ? 1 : 0, pointerEvents: h ? "auto" : "none" }}>×</span>
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
      {snoozed.map((z, i) => (
        <div key={z.key} className="ni-note" data-notch-idle-snoozed={z.key}
             style={{ left: N.PAD + 4, right: N.PAD + 4, top: g.noteTop + i * N.NOTE_H, height: N.NOTE_H }}>
          已隐藏 {NAME[z.key] ?? z.key}，{z.reset && z.reset !== "—" ? `↻${z.reset} 后` : "重置后"}自动回来 ·
          <span className="ni-undo" data-notch-idle-undo={z.key} onClick={(e) => { e.stopPropagation(); snooze(z.key, true); }}>撤销</span>
        </div>
      ))}
    </div>
  );
}
