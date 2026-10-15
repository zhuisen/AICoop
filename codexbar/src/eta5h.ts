/**
 * codex 5h「连续用还能撑多久」的文案（用户 2026-10-15：「codex 基本是几分钟用完的。按历史用完的次数去做预测」）。
 * 数在 `codex-rotate::_eta5h` 算（按历史「用完」事件的**连续使用**配速），这里只管怎么说。纯函数，可在 node 里直接跑。
 */
export interface Eta5h {
  /** 剩余的 5h 额度，按历史配速**连续用**还能撑几分钟。 */
  left_min: number;
  /** 一整窗（0→100%）按历史配速连续用多少分钟。 */
  per_window_min: number;
  /** 用了几次「用完」事件。 */
  n: number;
  /** `self` = 这个号自己的历史；`pool` = 本号不足 3 次，借全池的。 */
  scope: "self" | "pool";
}

export function fmtEtaMin(m: number): string {
  if (m < 1) return "<1m";
  if (m < 60) return `${Math.round(m)}m`;
  return `${Math.floor(m / 60)}h${String(Math.round(m % 60)).padStart(2, "0")}m`;
}

/**
 * 全池按**连续使用时间**的续航（`codex-rotate::_burst`；用户 2026-10-15：「全池续航≈98.6 小时，
 * 为什么还是那么多？实际不到半小时几张账号额度都没了」）。旧的钟点小时把空闲平均进去，对连续干活没有意义。
 */
export interface Burst {
  /** 此刻能挑的号合计还能连续用几分钟（每号取 5h 与周里先见底的那个）。 */
  now_min: number;
  /** 全部号（含冷却中）周剩余还能连续用几分钟；换算比值样本不够时 `null`。 */
  week_min: number | null;
  /** 5h 没满的号里最早一次重置还有几小时。 */
  refill_h: number | null;
  /** 1pp 的 5h ≈ 多少 pp 的周；样本不够时 `null`。 */
  wk_per_5h: number | null;
  events: number;
  per_window_min: number | null;
  n: number;
}

/** 连续使用时间拆成「数字 + 单位」：<90 分钟按分钟，否则按小时一位小数。 */
export function splitUse(m: number): [string, string] {
  if (m < 1) return ["<1", "分钟"];
  if (m < 90) return [String(Math.round(m)), "分钟"];
  return [(m / 60).toFixed(1), "小时"];
}

/** 「本周还能连续用」的悬浮说明：口径、换算比值、样本量。 */
export function burstTitle(b: Burst, weeklyLeftPp: number): string {
  return `周窗共剩 ${weeklyLeftPp}pp（可用号合计）。`
    + (b.wk_per_5h != null
      ? `按近期记录 1pp 的 5h ≈ ${b.wk_per_5h}pp 的周，一整窗 5h 连续约 ${b.per_window_min ?? "—"} 分钟`
        + `（${b.events} 次用完）⇒ 换算成连续使用时间。`
      : "周与 5h 的换算样本还不够，算不出来。")
    + "只算真在用的时间；停着不用不会少。";
}

/** 悬浮说明：说清这是**连续使用**的分钟、依据是几次用完、谁的历史。 */
export function eta5hTitle(e: Eta5h): string {
  return `按${e.scope === "self" ? "这个号" : "全池"}过去 ${e.n} 次 5h 用完的配速：`
    + `5h 额度从满到见底，约 ${fmtEtaMin(e.per_window_min)} 连续使用。`
    + `只算真在用的时间（两次请求间隔 >5 分钟算闲置，不计）——停着不用就不会见底。`;
}
