/**
 * 续航色带「这一段写不写得下名字」的判据（`RunwayHero` 用；纯函数，可在 node 里直接跑）。
 *
 * ★ 2026-10-15 三方评审：拖窗口时 RO 每帧 `setBarW`，整块续航条每像素重渲染一次，
 *   而真正影响画面的只有「哪几段写得下名字」这一组布尔。把它压成一个签名，
 *   **签名变了才 setState** —— 拖一路通常只翻转几次。
 */

/** 10px JetBrains Mono 700 的字宽：ASCII 约 6.2px，CJK 是整个字身 10px。
 *  ⚠️ 字宽随色带字号走（2026-09-21 从 9px 抬到 10px）——**两个数必须一起改**。 */
export function textW(s: string): number {
  return [...s].reduce((a, c) => a + (c.charCodeAt(0) > 255 ? 10 : 6.2), 0);
}

/** 权重 `w`（占 `total` 的比例）在 `barW` 像素宽的色带里写得下 `label` 吗。量不到宽度时一律不写。 */
export function segFits(w: number, total: number, barW: number, label: string): boolean {
  return barW > 0 && total > 0 && (w / total) * barW >= textW(label) + 8;
}

/** 每段写不写得下的签名（"101…"）。只在它变化时才需要重渲染。 */
export function fitSignature(items: [number, string][], total: number, barW: number): string {
  return items.map(([w, l]) => (segFits(w, total, barW, l) ? "1" : "0")).join("");
}
