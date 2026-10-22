// 菜单栏弹窗（交接包 2026-10-19 page4 · 4f）的纯逻辑。★ 零 import —— 测试用
// `node --experimental-strip-types` 直接跑（CI 没有 node_modules，见 CLAUDE.md §4）。
//
// 这里只放「判据」：低额度、排序、通知合并、探针连点判据、Claude 额度解析。
// 怎么画在组件里；判据只有这一份，组件与测试共用。

// ── 低额度 ───────────────────────────────────────────────────────────────

/** 交接包 4f：「任一窗口 < 10%：整行淡橙红底、号名和该条变橙红」。严格小于。 */
export const LOW_PCT = 10;

/**
 * ★ 判的是**显示出来的整数**（与刘海 `notchSegs.ts::segColor` 同一条纪律）：剩 9.6% 时行上写
 * 「10%」，那它就不能是红的；剩 9.4% 写「9%」就必须红。判原值会让数字和颜色互相矛盾。
 */
export function isLow(pct: number | null | undefined): boolean {
  return typeof pct === "number" && Number.isFinite(pct) && Math.round(pct) < LOW_PCT;
}

/** 一行里最紧的那个窗口（读不到的窗口不参与；全读不到 ⇒ null，不是 0）。 */
export function tightestOf(pcts: readonly (number | null | undefined)[]): number | null {
  let m: number | null = null;
  for (const p of pcts) {
    if (typeof p !== "number" || !Number.isFinite(p)) continue;
    if (m == null || p < m) m = p;
  }
  return m;
}

// ── 排序 ─────────────────────────────────────────────────────────────────

export interface SortKey {
  /** 最紧窗口的剩余 %；null = 读不到（未探测）。 */
  tight: number | null;
  inUse: boolean;
  next: boolean;
}

/**
 * 「按可用排序」（交接包 4f 账号块表头）。顺序：
 *   ① 有窗口 < 10% 的号 —— 最紧的排最前（Gemini 低额度画板的「最紧的排最前」）；
 *   ② 在用；③ 下一个；④ 其余按最紧窗口降序；⑤ 读不到的排最后。
 * 同档内保持原顺序（稳定），切号时行不会无故跳。
 */
export function sortByAvailability<T extends SortKey>(rows: readonly T[]): T[] {
  const rank = (r: T): number => {
    if (isLow(r.tight)) return 0;
    if (r.inUse) return 1;
    if (r.next) return 2;
    if (r.tight == null) return 4;
    return 3;
  };
  return rows
    .map((r, i) => ({ r, i, k: rank(r) }))
    .sort((a, b) => {
      if (a.k !== b.k) return a.k - b.k;
      if (a.k === 0 || a.k === 3) {
        const d = a.k === 0 ? (a.r.tight as number) - (b.r.tight as number)
                            : (b.r.tight as number) - (a.r.tight as number);
        if (d !== 0) return d;
      }
      return a.i - b.i;
    })
    .map((x) => x.r);
}

/** 账号块表头左半。有低额度的号时排序规则变了，表头必须跟着说。 */
export function blockTitle(rows: readonly SortKey[]): string {
  return rows.some((r) => isLow(r.tight)) ? "账号 · 最紧的排最前" : "账号 · 按可用排序";
}

// ── 通知条 ───────────────────────────────────────────────────────────────

export type NoticeTone = "bad" | "warn";

export interface Notice {
  /** 稳定身份（React key + 「关掉这一条」的记忆键）。 */
  id: string;
  tone: NoticeTone;
  /** 同色调内越小越紧急。 */
  urgency: number;
  text: string;
  /** 可关（只有重置卡那一条：它会自己过期，连挂三天关不掉是噪音）。 */
  dismissible?: boolean;
}

/**
 * 多条告警合并成一条（交接包 4f「通知条」）：只显示最紧急一条 +「还有 N 条」。
 * 紧急度：红（池见底 / 低额度）> 琥珀（重置卡作废 / 订阅到期）；同色按 `urgency` 升序，再按 id。
 */
export function mergeNotices(list: readonly Notice[]): { head: Notice | null; rest: Notice[] } {
  const toneRank = (t: NoticeTone): number => (t === "bad" ? 0 : 1);
  const sorted = [...list].sort((a, b) =>
    toneRank(a.tone) - toneRank(b.tone) || a.urgency - b.urgency || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return { head: sorted[0] ?? null, rest: sorted.slice(1) };
}

/** 「号C 5h 只剩 8% · 0h54m 后回满」。回满时间读不到就不说「后回满」。 */
export function lowNotice(id: string, name: string, win: string, pct: number, refill: string | null): Notice {
  // ★ 只有真的是一段时长（含数字）才说「后回满」；「未启动 / 待确认 / —」拼上去是一句病句。
  const tail = refill && /\d/.test(refill) ? ` · ${refill} 后回满` : "";
  return { id: `low:${id}:${win}`, tone: "bad", urgency: pct, text: `${name} ${win} 只剩 ${Math.round(pct)}%${tail}` };
}

/** 整池都没号可用（每个读得到的号都 < 10%，且至少读到一个）。 */
export function poolDry(rows: readonly SortKey[]): boolean {
  const known = rows.filter((r) => r.tight != null);
  return known.length > 0 && known.every((r) => isLow(r.tight));
}

export function poolDryNotice(platform: string): Notice {
  return { id: `dry:${platform}`, tone: "bad", urgency: -1, text: `${platform} 池见底 · 所有号都不到 ${LOW_PCT}%` };
}

/** 订阅到期提醒的窗口（天）。交接包示例「号D 订阅 7 天后到期」。 */
export const SUB_WARN_DAYS = 7;

/** `YYYY-MM-DD` 到期日 → 还剩几天（向下取整）。读不到 ⇒ null。 */
export function daysUntil(isoDate: string, nowMs: number): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) return null;
  const [y, m, d] = isoDate.split("-").map(Number);
  const end = new Date(y, m - 1, d).getTime();
  if (!Number.isFinite(end)) return null;
  return Math.floor((end - nowMs) / 86_400_000);
}

/** 重置卡「快作废」的唯一判据（`CardBadge.tsx::isCardExpiring` 调它）。`cardDays` 未知 ⇒ 不算快作废（不编）。 */
export function cardExpiring(cards: number, cardDays: number | undefined, warnDays: number): boolean {
  return cards > 0 && cardDays != null && cardDays <= warnDays;
}

/**
 * 卡片底栏的短日期（用户 2026-10-21「到期日期挡住了」⇒ 选「短日期」）：一年内的写 `MM-DD`，更远的才写全。
 * 认不出的原样返回（`—` 之类）。完整日期放悬浮。
 */
export function shortDate(iso: string, nowMs: number): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso;
  const [y, m, d] = iso.split("-").map(Number);
  const t = new Date(y, m - 1, d).getTime();
  return Math.abs(t - nowMs) <= 300 * 86_400_000 ? iso.slice(5) : iso;
}

export interface ExpiryAcct {
  aid: string; node: string; exp: string; expStale: boolean;
  cards: number; cardDays?: number; cardExp?: string; cardsExpiring: number;
}
export interface ExpiryWarn {
  key: string; aid: string; node: string;
  kind: "card" | "sub";
  /** 还剩几天（卡是小数天，订阅是整日历天，0 = 今天）。排序用：越近越靠前。 */
  days: number;
  date: string;
  /** 卡：几张快作废（明细只给到最早那张时按 1 张算，同菜单栏横幅）。订阅恒 1。 */
  count: number;
}

/**
 * 总览「快到期」堆叠警告的条目（用户 2026-10-21：快到期的做成悬浮堆叠警告）。
 * 判据与菜单栏通知条**同一套**：卡 = `cardExpiring`（≤ warnDays 天），订阅 = `daysUntil` 在 0…subDays（日期不可信的不算）。
 * 调用方传活号与停用号（卡会过期，停不停用都一样），不传失效号。
 */
export function expiryWarnings(accts: readonly ExpiryAcct[], nowMs: number, warnDays: number, subDays: number): ExpiryWarn[] {
  const out: ExpiryWarn[] = [];
  for (const a of accts) {
    if (cardExpiring(a.cards, a.cardDays, warnDays)) {
      out.push({ key: `card:${a.aid}`, aid: a.aid, node: a.node, kind: "card", days: a.cardDays ?? 0,
                 date: a.cardExp ?? "", count: Math.min(a.cards, a.cardsExpiring || 1) });
    }
    const left = a.expStale ? null : daysUntil(a.exp, nowMs);
    if (left != null && left >= 0 && left <= subDays) {
      out.push({ key: `sub:${a.aid}`, aid: a.aid, node: a.node, kind: "sub", days: left, date: a.exp, count: 1 });
    }
  }
  return out.sort((x, y) => x.days - y.days || (x.kind === y.kind ? 0 : x.kind === "card" ? -1 : 1));
}

export function subNotice(id: string, name: string, days: number, date: string): Notice {
  const when = days <= 0 ? "今天" : `${days} 天后`;
  return { id: `sub:${id}`, tone: "warn", urgency: days + 0.5, text: `${name} 订阅 ${when}到期（${date}）` };
}

// ── 点击探针（计费） ────────────────────────────────────────────────────────
// ★ 用户 2026-10-21「探针的功能 修改点击即可」：取代交接包 4f 的「按住 0.6 s」（再往前是两段确认）。
//   花钱的控件仍和免费按钮长得不一样（琥珀 + ⚡ +「计费」），只是不再要求确认动作。

/** 同一颗按钮两次执行至少隔这么久：双击、手抖连点只算一次（单号一次 <1% 周额度，全池 = 号数倍）。 */
export const PROBE_GAP_MS = 1500;

/** 这一下点击该不该真的执行。`last` = 这颗按钮上一次执行的时刻（`null` = 还没执行过）。 */
export function probeShouldFire(last: number | null, now: number, loading: boolean): boolean {
  if (loading) return false;
  return last == null || now - last >= PROBE_GAP_MS;
}

// ── Claude 额度（`read_statusline_quota`，契约 PLAN §2.2） ──────────────────

export interface ClaudeWin {
  /** 剩余 % = 100 − used_pct。 */
  rem: number;
  /** 回满时刻（epoch 秒）；null = 来源不给（plan-usage-history 没有重置时间）。 */
  resetsAt: number | null;
  /** 窗口未启动：旧窗口已过重置点，**且**之后的状态栏读数没有再报这个窗口 ⇒ 100%，↻ 写「未启动」。 */
  idle?: boolean;
}

export interface ClaudeQuota {
  source: "statusline" | "plan-usage-history" | "none";
  capturedAt: number | null;
  fiveH: ClaudeWin | null;
  week: ClaudeWin | null;
}

const toSec = (v: unknown): number | null => {
  if (typeof v !== "number" || !Number.isFinite(v) || v <= 0) return null;
  return v > 1e12 ? Math.floor(v / 1000) : v;
};

function claudeWin(w: unknown, capturedAt: number | null): ClaudeWin | null {
  if (!w || typeof w !== "object") return null;
  const o = w as Record<string, unknown>;
  const used = o.used_pct;
  if (typeof used !== "number" || !Number.isFinite(used)) return null;
  // ★ 窗口已过重置时刻：那个「已用」属于旧窗口，不能当现值（statusline_quota 标了 `expired`）。
  //   重置点之后又有一份状态栏读数（`capturedAt` 晚于重置点）却没再报这个窗口 ⇒ Claude Code 自己说
  //   「没有在走的窗口」，即未启动、剩 100%（实测 2026-10-19：重置后 Claude Code 不带 five_hour，
  //   下一次请求后才带回 `used 0`）。重置后没有任何新读数 ⇒ 证不了，仍是「读不到」（同 codex
  //   `test_expired_reset_without_a_fresh_reading_is_not_zero` 那条）。
  if (o.expired === true) {
    const rs = toSec(o.resets_at);
    return rs != null && capturedAt != null && capturedAt > rs ? { rem: 100, resetsAt: null, idle: true } : null;
  }
  return { rem: Math.max(0, Math.min(100, 100 - used)), resetsAt: toSec(o.resets_at) };
}

/** 读不到 / 形状不对 ⇒ null（「读不到」，界面写 —，绝不当 0）。 */
export function parseClaudeQuota(raw: unknown): ClaudeQuota | null {
  let o: unknown = raw;
  if (typeof raw === "string") {
    try { o = JSON.parse(raw); } catch (_e: unknown) { return null; }
  }
  if (!o || typeof o !== "object") return null;
  const c = (o as Record<string, unknown>).claude;
  if (!c || typeof c !== "object") return null;
  const r = c as Record<string, unknown>;
  const src = r.source === "statusline" || r.source === "plan-usage-history" ? r.source : "none";
  const cap = toSec(r.captured_at);
  return {
    source: src,
    capturedAt: cap,
    fiveH: claudeWin(r.five_hour, cap),
    week: claudeWin(r.seven_day, cap),
  };
}

/** 读数陈旧阈值（秒）。与 `helpers.ts::QUOTA_STALE_SEC` 同值（30 分钟）。 */
export const STALE_SEC = 30 * 60;

export function isStale(capturedAt: number | null, nowSec: number): boolean {
  return capturedAt != null && nowSec - capturedAt > STALE_SEC;
}

// ── 版式 ─────────────────────────────────────────────────────────────────

/**
 * 号名列宽。交接包写死 46（示意数据全是「号A」两个字）；真实号名可能是 `tomyhuohuo`，
 * 46 会把它截成「tom…」。按同一块里最长的名字估宽（CJK 13.5 / 其余 8，13.5px 字），
 * 下限 46（= 设计值）、上限 84（再宽两根条就短到读不出），超出省略号。整块共用一个宽度，列才对得齐。
 */
export function nameColWidth(names: readonly string[]): number {
  let w = 0;
  for (const n of names) {
    let x = 0;
    for (const ch of n) x += /[　-鿿＀-￯]/.test(ch) ? 13.5 : 8;
    if (x > w) w = x;
  }
  return Math.max(46, Math.min(84, Math.ceil(w)));
}

/**
 * 临界阻尼弹簧的 CSS `linear()` 近似（交接包 README「动效曲线」，代码原样）。
 * response 0.36 s、0.55 s 内落定；n = 30 个采样点。
 */
export function critSpring(resp = 0.36, T = 0.55, n = 30): string {
  const w = (2 * Math.PI) / resp;
  const pts: string[] = [];
  for (let i = 0; i <= n; i++) {
    pts.push((i === n ? 1 : 1 - (1 + (w * T * i) / n) * Math.exp((-w * T * i) / n)).toFixed(3));
  }
  return `linear(${pts.join(", ")})`;
}

/** 弹窗关掉多久之内重开算「误关」、保持原样（用户 2026-10-22：「重新打开就是默认位置，1 分钟内重新打开依旧保持上一次」）。 */
export const REOPEN_KEEP_MS = 60_000;

/** 这次弹出要不要回到默认（账号页 · Codex 档）。`hiddenAt` = 上次收起的时刻；没收起过（启动后第一次）⇒ 不动，用存下的。 */
export function reopenResets(hiddenAt: number | null, now: number): boolean {
  return hiddenAt != null && now - hiddenAt >= REOPEN_KEEP_MS;
}
