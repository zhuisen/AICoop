/**
 * 窗口缩放时用到的纯判断（2026-10-16 从两个 hook 里搬出来）。
 *
 * ★ 这里**零 import**：测试用 `node --experimental-strip-types` 直接加载真文件，
 *   而 CI 不装 npm 依赖 —— 写在 hook 文件里时，hook 顶层的 `import … from "react"` 让 CI 上
 *   这几条测试全红（v1.10.0 的 ci 运行实测），本机有 node_modules 所以看不出来。
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
