import { useLayoutEffect, useRef, useState } from "react";
import { nextCompact } from "../resizeMath";

/**
 * 总览顶栏「一行放下」（用户 2026-10-15：「最小窗口的情况下总览页面顶部要一行展示所有……
 * 太小放不下，刷新全池、检查 token、探针、定时、切号都减少字数并附上图标就够了」）。
 *
 * 判据：顶栏各块（标题+档位 / 动作条）**自然宽度之和**放不放得下。放不下 ⇒ 动作条换短名 + 图标；
 * 短名也放不下才退回原来的整块换行（**绝不裁、绝不断字**，同 GhostButton 的 nowrap）。
 *
 * ★ 紧凑态里量不到全名的宽度（全名不在 DOM 里），所以记住**上一次全名态量到的宽度**来判「回得去吗」。
 *   不记就会：窗口放大 → 切回全名 → 又放不下 → 切紧凑 …… 每帧来回翻（§7.2「每帧调用必须幂等」）。
 */
export function useOneRowHeader(gap: number, deps: unknown[]): {
  ref: React.RefObject<HTMLDivElement | null>; compact: boolean;
} {
  const ref = useRef<HTMLDivElement | null>(null);
  const [compact, setCompact] = useState(false);
  // ★ 当前档存 ref，不进 effect 依赖：原来 `compact` 在依赖里，每次翻档都拆掉 RO 重建、再同步量一次。
  const compactRef = useRef(false);
  const lastFull = useRef(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = (): void => {
      const kids = Array.from(el.children) as HTMLElement[];
      const need = kids.reduce((s, k) => s + k.offsetWidth, 0) + gap * Math.max(0, kids.length - 1);
      const cur = compactRef.current;
      if (!cur) lastFull.current = need;
      const next = nextCompact(cur, need, el.clientWidth, lastFull.current);
      if (next !== cur) { compactRef.current = next; setCompact(next); }
    };
    const ro = new ResizeObserver(check);
    ro.observe(el);
    Array.from(el.children).forEach((k) => ro.observe(k));
    check();
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gap, ...deps]);
  return { ref, compact };
}
