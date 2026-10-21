import { CARD_WARN_DAYS, type Account } from "../helpers";
import { cardExpiring } from "../mbLogic";

/**
 * 重置卡的共用判据与颜色。★ 原来这里还有「重置卡 ×N」角标组件本体与它的隐形占位（`CardBadgeGhost`）——
 * 2026-10-19 总览换成交接包 page5 的卡片之后，角标由 `AccountCard` 的底栏直接画（同一个判据 `isCardExpiring`），
 * 占位不再需要（等高由外壳的固定槽位保证），两者随之删除（ui.md §5c：删组件连同本体）。
 */
export const AMBER = "#E0901C";
export const AMBER_TEXT = "#f2b45c";

/** True when this account holds a card that is about to lapse. Single source of truth for the badge,
 *  the card border, the row's left rail and the pool banner, so they can never disagree. */
export function isCardExpiring(a: Account): boolean {
  return cardExpiring(a.cards, a.cardDays, CARD_WARN_DAYS);
}
