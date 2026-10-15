import { useLayoutEffect, useRef, useState } from "react";

/**
 * 量一个 flex 撑满容器的可用高度，给只认像素高度的子组件（`StackedArea`）用。
 *
 * ★ 容器必须是 `flex: 1 1 0` + **显式** `minHeight`。`minHeight: auto` 时下限 = 内容高，
 *   而内容高正是按这里量出的数画的 —— 窗口缩小时它缩不回去，会一直撑着。
 */
/** 量出来的高度**向下**取到这个步长。 */
export const FILL_STEP = 4;

/**
 * ★ 拖窗口时 RO 每帧都报新高度，每次 setState 都让 `StackedArea` 重算整张样条（2026-10-15 三方评审）。
 *   向下取到 4px：图表每 4px 才重画一次，且**永远不高于容器**（向上取会溢出 1–3px，
 *   一屏页面的根就开始滚）。代价是底部最多空 3px。
 */
export function quantizeDown(px: number, step = FILL_STEP): number {
  return Math.floor(px / step) * step;
}

export function useFillHeight<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [h, setH] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setH(quantizeDown(el.clientHeight));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, h];
}
