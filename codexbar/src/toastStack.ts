/**
 * Toast 堆的几何（交接包 P5 §7）—— 纯函数、零 import，`node --experimental-strip-types` 可直接跑。
 *
 * k = 距最新那条的序号（最新 k=0 在最前）。
 *   收起：`translateY(-k*8) scale(max(.86, 1-k*.05))`，k>2 透明；容器高 `40 + min(2, n-1)*8`。
 *   展开：`translateY(-k*48) scale(1)` 全不透明；容器高 `40 + (n-1)*48`。
 */
export interface ToastPose { y: number; scale: number; opacity: number }
export interface ToastGeom { height: number; items: ToastPose[] }

export function toastStackGeom(n: number, open: boolean): ToastGeom {
  if (n <= 0) return { height: 0, items: [] };
  const items: ToastPose[] = [];
  for (let i = 0; i < n; i++) {
    const k = n - 1 - i;
    items.push(open
      ? { y: -k * 48, scale: 1, opacity: 1 }
      : { y: -k * 8, scale: Math.max(0.86, 1 - k * 0.05), opacity: k > 2 ? 0 : 1 - k * 0.2 });
  }
  return { height: open ? 40 + (n - 1) * 48 : 40 + Math.min(2, n - 1) * 8, items };
}
