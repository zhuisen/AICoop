import { useEffect, useState } from "react";
import type { ToastItem } from "../hooks/useStore";
import { toastStackGeom } from "../toastStack";

/**
 * 主窗口的 Toast 堆（交接包 P5 §7）：最多 4 条叠在底部正中，最新的在最前；悬停展开、并暂停计时；
 * 每条各自带「撤销」（只撤它自己那一步）。几何只在 `toastStack.ts` 一处算（纯函数，有行为闸）。
 * 菜单栏仍是单条 `Toast`（它是另一张稿）。
 */
export default function ToastStack({ items, isDark, onHold, onDismiss }: {
  items: ToastItem[]; isDark: boolean; onHold: (h: boolean) => void; onDismiss: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const n = items.length;
  // ★ 堆空了就解除悬停：最后一条被「撤销」点掉时堆缩成 0 高、`pointer-events:none`，
  //   `mouseleave` 再也不会来 ⇒「悬停暂停」卡死，之后每条 toast 都不消失、延迟删除永远不执行（真点击闸抓到的）。
  useEffect(() => { if (n === 0 && open) { setOpen(false); onHold(false); } }, [n, open, onHold]);
  const g = toastStackGeom(n, open);
  return (
    <div data-toast-stack={n} data-open={open ? "" : undefined}
         onMouseEnter={() => { setOpen(true); onHold(true); }}
         onMouseLeave={() => { setOpen(false); onHold(false); }}
         style={{ position: "absolute", left: "50%", bottom: 24, width: 360, marginLeft: -180, zIndex: 40,
                  height: g.height, pointerEvents: n ? "auto" : "none" }}>
      {items.map((x, i) => {
        const s = g.items[i];
        return (
          <div key={x.id} className="cb-toast" data-toast={x.id}
               style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 40, padding: "0 14px", boxSizing: "border-box",
                        display: "flex", alignItems: "center", gap: 10, borderRadius: 10, zIndex: 10 + i,
                        background: isDark ? "rgba(10,12,16,.94)" : "rgba(255,255,255,.97)",
                        boxShadow: isDark ? "0 0 0 1px rgba(255,255,255,.12), 0 10px 26px rgba(0,0,0,.45)"
                                          : "0 0 0 1px rgba(0,0,0,.1), 0 10px 26px rgba(0,0,0,.18)",
                        color: isDark ? "#fff" : "#161b22", fontSize: 13, transformOrigin: "50% 100%",
                        transform: `translateY(${s.y}px) scale(${s.scale})`, opacity: s.opacity,
                        transition: "transform .45s cubic-bezier(.34,1.3,.64,1), opacity .25s ease-out" }}>
            <i style={{ width: 8, height: 8, borderRadius: 4, background: x.color, flexShrink: 0 }} />
            <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{x.msg}</span>
            {x.undo && (
              <span role="button" tabIndex={0} data-toast-undo=""
                    onClick={() => { const u = x.undo; onDismiss(x.id); u?.(); }}
                    onKeyDown={(e) => { if (e.key === "Enter") { const u = x.undo; onDismiss(x.id); u?.(); } }}
                    style={{ height: 22, padding: "0 8px", borderRadius: 6, border: `1px solid ${isDark ? "rgba(255,255,255,.2)" : "rgba(0,0,0,.18)"}`,
                             color: isDark ? "#5eead4" : "#0a7a6e", fontSize: 12, display: "inline-flex", alignItems: "center",
                             cursor: "pointer", flexShrink: 0, userSelect: "none" }}>撤销</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
