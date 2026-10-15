import { useLayoutEffect, useRef, useState } from "react";
import { quantizeDown } from "../resizeMath";

/**
 * 量一个 flex 撑满容器的可用高度，给只认像素高度的子组件（`StackedArea`）用。
 *
 * ★ 容器必须是 `flex: 1 1 0` + **显式** `minHeight`。`minHeight: auto` 时下限 = 内容高，
 *   而内容高正是按这里量出的数画的 —— 窗口缩小时它缩不回去，会一直撑着。
 */
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
