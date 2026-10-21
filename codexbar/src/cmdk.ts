/**
 * ⌘K 命令面板的纯逻辑（交接包 P5 §8）—— 零 import，`node --experimental-strip-types` 可直接跑。
 */

/** `label` 或 `hint` 小写包含输入即保留，最多 7 条。 */
export function cmdkFilter<T extends { label: string; hint: string }>(items: readonly T[], q: string): T[] {
  const s = q.trim().toLowerCase();
  return items.filter((it) => !s || it.label.toLowerCase().includes(s) || it.hint.toLowerCase().includes(s)).slice(0, 7);
}

/** ↑/↓ 移动高亮，夹在首尾（不绕回）。 */
export function cmdkMove(k: number, d: 1 | -1, n: number): number {
  if (n <= 0) return 0;
  return Math.max(0, Math.min(n - 1, k + d));
}

/** 只认 ⌘K / Ctrl+K（不带 Shift / Alt），其它组合都不是它。 */
export function isCmdK(e: { metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean; key: string }): boolean {
  return (e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "k";
}
