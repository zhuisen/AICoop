/**
 * Toast 堆的计时状态机（交接包 P5 §7）—— 零 import，`node --experimental-strip-types` 可直接跑。
 *
 * ★ 为什么单独成一个纯模块（四方评审 2026-10-22，三方都指到这里）：
 *   - 「删除」靠 toast 到期才真发 `remove` ⇒ 到期回调必须**恰好一次**：到点、被挤出各一次，撤销零次。
 *     原来挤出时的回调排在 React state updater 里，updater 可能被重放或丢弃 ⇒ 次数没有保证。
 *   - 悬停是**暂停**：记下剩余时间，离开后按剩余时间续上。原来只是到点时再等 1.2 s，
 *     悬停 10 s 后离开会在 1.2 s 内消失（并提交删除），用户读不完也来不及撤销。
 * 这里只算「谁该在什么时候到期、谁被挤出」，副作用（回调、计时器、渲染）全在调用方。
 */

export interface TQItem { id: number; due: number; left: number }
export interface TQState { items: TQItem[]; held: boolean }

export const tqEmpty = (): TQState => ({ items: [], held: false });

/** 加一条；超出 `max` 时最老的被挤出（挤出 = 撤销窗口没了，调用方当它到点）。 */
export function tqPush(s: TQState, id: number, ms: number, now: number, max: number): { s: TQState; evicted: number[] } {
  const items = [...s.items, { id, due: now + ms, left: ms }];
  const cut = Math.max(0, items.length - max);
  return { s: { ...s, items: items.slice(cut) }, evicted: items.slice(0, cut).map((x) => x.id) };
}

/** 原地换字：计时从现在重算。不在堆里 ⇒ 原样返回（调用方另起一条）。 */
export function tqRearm(s: TQState, id: number, ms: number, now: number): TQState {
  return { ...s, items: s.items.map((x) => (x.id === id ? { id, due: now + ms, left: ms } : x)) };
}

export function tqHas(s: TQState, id: number): boolean {
  return s.items.some((x) => x.id === id);
}

export function tqRemove(s: TQState, id: number): TQState {
  return { ...s, items: s.items.filter((x) => x.id !== id) };
}

/** 悬停：每条记下剩余时间并停表；离开：按剩余时间续上。重复调用是空操作（幂等）。 */
export function tqHold(s: TQState, h: boolean, now: number): TQState {
  if (h === s.held) return s;
  if (h) return { held: true, items: s.items.map((x) => ({ ...x, left: Math.max(0, x.due - now) })) };
  return { held: false, items: s.items.map((x) => ({ ...x, due: now + x.left })) };
}

/** 到点的那些（悬停中一条都不到点）。 */
export function tqDue(s: TQState, now: number): { s: TQState; expired: number[] } {
  if (s.held) return { s, expired: [] };
  const expired = s.items.filter((x) => x.due <= now).map((x) => x.id);
  return expired.length ? { s: { ...s, items: s.items.filter((x) => x.due > now) }, expired } : { s, expired };
}

/** 下一次该醒来的时刻；悬停中或空堆 ⇒ null（不挂计时器）。 */
export function tqNext(s: TQState): number | null {
  if (s.held || !s.items.length) return null;
  return Math.min(...s.items.map((x) => x.due));
}
