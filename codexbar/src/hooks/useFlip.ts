import { useLayoutEffect, useRef, type RefObject } from "react";

/**
 * 网格里的卡片换位置时走 FLIP 动画（交接包 P5 §1.3：置顶 / 取消置顶 / 删除后补位 / 排序变化，
 * `transform .55s cubic-bezier(.34,1.3,.64,1)`，带一点过冲）。
 *
 * ★ 稿里是绝对定位 + 每张卡算 translate3d；这里**保留 CSS grid**、只在顺序变了的那一帧做 FLIP ——
 *   拖拽排序（`useCardDrag`）直接在这些节点上写 `transform`，而它的前提是「卡片的自然位置 = grid 槽位」。
 *   改成绝对定位就得把那套已经调了四轮的拖拽手感重写一遍（CLAUDE.md §7.2）。
 * ★ 位置用 `offsetLeft/Top`（不含 transform）：拖拽或上一段动画写着的 transform 不会污染「旧位置」。
 * ★ `drag`（拖拽预览顺序）：拖拽中、以及提交那一帧都不播 —— 拖拽中卡片由 `useCardDrag` 写 transform，
 *   FLIP 清 transform 会把被拖的卡弹回去；提交那一刻卡片已经在新槽位上，再从旧槽位飞一次就是假的回跳。
 *   比较放在 layout effect 里（不在 render 里写 ref：StrictMode 双渲染会把「变了」吃掉，评审 Opus L1/L2）。
 * ★ 减弱动态效果时不播。
 */
export function useFlip(ref: RefObject<HTMLElement | null>, sig: string, drag: unknown): void {
  const prev = useRef(new Map<string, { x: number; y: number }>());
  const prevSig = useRef(sig);
  const prevDrag = useRef(drag);
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;
    const els = Array.from(root.querySelectorAll<HTMLElement>(":scope > [data-flip]"));
    const now = new Map(els.map((el) => [el.dataset.flip ?? "", { x: el.offsetLeft, y: el.offsetTop }]));
    const reduce = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const skip = drag != null || drag !== prevDrag.current;
    prevDrag.current = drag;
    if (sig !== prevSig.current && !skip && !reduce) {
      for (const el of els) {
        const o = prev.current.get(el.dataset.flip ?? ""), c = now.get(el.dataset.flip ?? "");
        if (!o || !c || (o.x === c.x && o.y === c.y)) continue;
        el.style.transition = "none";
        el.style.transform = `translate3d(${o.x - c.x}px, ${o.y - c.y}px, 0)`;
        void el.offsetWidth;                       // 先把「旧位置」提交给浏览器，再放手让它过渡回去
        el.style.transition = "transform .55s cubic-bezier(.34,1.3,.64,1)";
        el.style.transform = "";
        const done = (e: TransitionEvent) => { if (e.propertyName !== "transform") return; el.style.transition = ""; el.removeEventListener("transitionend", done); };
        el.addEventListener("transitionend", done);
      }
    }
    prev.current = now;
    prevSig.current = sig;
  });
}
