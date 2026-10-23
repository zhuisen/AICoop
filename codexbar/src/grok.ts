/**
 * grok 周额度的类型与**文案单一真源**。
 *
 * 数据来自仓库根的 `grok-quota`（从 xAI 客户端抓包得到的 `GET /v1/billing?format=credits`，非官方公开 API）。
 * 它与本页下半部分的 token 统计**不同源**：那边是扫本机 `~/.grok` 下的 updates.jsonl，
 * 这边是 xAI 云端的 credits 账单。两个数不可加、不可互推。
 *
 * ⚠️ 别在块注释里写带 `**` + `/` 的 glob —— 那个组合就是块注释的结束符，注释会在那里
 * 被悄悄截断、后面整段当代码解析。这条注释本身就踩过一次（报错点在十几行之外，看不出真因）。
 */

/** ★ 闭集，必须与 `grok-quota` 里的 `REASONS` 逐字相等。
 *  闸在 `tests/test_grok_reason_copy.py`：两边都从源解析，新增一个只改一边就红。 */
export type GrokReason =
  | "token_expired"
  | "unauthorized"
  | "auth_file_missing"
  | "auth_file_unreadable"
  | "auth_file_empty"
  | "bad_payload"
  | "http_error"
  | "network_error"
  | "rate_limited";

export interface GrokQuota {
  /** ★★ 0–100 的**已用**百分比，不是剩余。喂进 `quotaColor()` 前必须换向 —— 见 `grokRemPct`。 */
  used_percent: number;
  /** ★ 响应里没有 `creditUsagePercent`（proto3 省略零值）⇒ 后端按「已用 0」推断。界面按下限显示（剩 ≥99%）并写「推断」。 */
  used_inferred?: boolean;
  period_type: string | null;
  period_start: number | null;
  period_end: number | null;
  window_minutes: number | null;
  products: { product: string | null; used_percent: number }[];
  on_demand_cap: number | null;
  on_demand_used: number | null;
  prepaid_balance: number | null;
}

export interface GrokAccount {
  account_key: string | null;
  user_id: string | null;
  email: string | null;
  token_expires_at: number | null;
  available: boolean;
  reason: GrokReason | null;
  detail: string | null;
  http_status: number | null;
  /** ★ `available === false` 时恒 `null`，绝不是 0 —— 0% 是"这周没用"的合法值。 */
  quota: GrokQuota | null;
  /** 降级时搬运的上一次成功读数。**字段名不同**，消费方不可能误当现值。 */
  last_good: { used_percent: number; fetched_at: number; period_end: number | null; used_inferred?: boolean } | null;
  /** 套餐名（`/v1/settings` 的 `subscription_tier_display`，一天读一次，读不到留上次的）。旧 sidecar 没有。 */
  plan?: { name: string; at: number } | null;
  /** 被 429 后，到这个 epoch 秒之前 `grok-quota` 不再发请求。 */
  retry_at?: number | null;
}

export interface GrokSnapshot {
  schema: number;
  fetched_at: number;
  auth_path: string;
  accounts: GrokAccount[];
}

/**
 * ★★ 两个取数函数**名字里都带方向**，且不导出裸数字。
 *
 * 起因是一个会静默画错色的坑：`helpers.ts` 的 `quotaColor()` 吃的是**剩余**
 * （账号池那边 `winRem = 100 - used_percent`），而 grok 接口给的是**已用**。
 * 35% 已用直接传进去会得琥珀（"警告"），而实际剩 65% 该是绿 —— **颜色完全反相，
 * 而且不报错**。同一个 app 里同时存在两种方向时，靠调用点自觉换算迟早有一处漏。
 */
export function grokUsedPct(a: GrokAccount | null | undefined): number | null {
  if (!a?.quota) return null;
  // ★ 推断的 0：按下限 1 算（剩 99），绝不画成「满 100」—— 只知道「不到 1%」，不知道是不是正好 0（用户 2026-10-23 选）
  return a.quota.used_inferred ? Math.max(1, a.quota.used_percent) : a.quota.used_percent;
}

/** 显示的这个数是不是推断出来的（字段缺席 ⇒ 本周用量不到 1%）—— 现值或降级时沿用的旧值都算。 */
export function grokInferred(a: GrokAccount | null | undefined): boolean {
  if (!a) return false;
  return a.available ? !!a.quota?.used_inferred : !!a.last_good?.used_inferred;
}

/** 推断时的说明（悬停提示 / 卡片小字共用一句）。 */
export const GROK_INFERRED_NOTE = "xAI 没返回本周用量（它省略 0 值）⇒ 推断本周用量不到 1%，按剩 99% 下限显示；用量到 1% 后变实测";
export function grokRemPct(a: GrokAccount | null | undefined): number | null {
  const used = grokUsedPct(a);
  return used == null ? null : 100 - used;
}
/**
 * 陈旧读数的剩余百分比。**换向只在这里做一次** —— 调用点写 `100 - lg.used_percent`
 * 就等于把方向知识复制了一份，而复制出去的那份迟早漏改（这条闸在 `tests/test_grok_direction.py`）。
 */
export function grokLastGoodRemPct(a: GrokAccount | null | undefined, nowSec: number = Date.now() / 1000): number | null {
  const lg = a?.last_good;
  if (!lg) return null;
  // ★ 那次读数所在的周期已经结束 ⇒ 「已用」属于上一个周期 ⇒ 读不到（不是 0，也不是满）。
  //   不判它，token 一直刷不新时，周期末之后各处仍画上周的 0% 红，而倒计时同时写「已重置」（2026-10-21 复查）。
  if (lg.period_end != null && lg.period_end <= nowSec) return null;
  return 100 - (lg.used_inferred ? Math.max(1, lg.used_percent) : lg.used_percent);
}

export type GrokTone = "amber" | "red" | "muted";

/** 降级态的色调。`unauthorized` 单独给红：那是"需要人去处理"，其余都是"下次刷新会自愈"。 */
export function grokReasonTone(a: GrokAccount): GrokTone {
  switch (a.reason) {
    case "unauthorized": return "red";
    case "auth_file_missing":
    case "auth_file_empty": return "muted";
    default: return "amber";
  }
}

/**
 * 降级文案的**唯一出处**（同 `traffic.ts` 的 `coverageNote` 纪律）。
 *
 * 每条都必须做到两件事，缺一条这个函数就白写了：
 * ① **明说这不是「额度为 0」** —— 0% 是合法值，用户没别的办法分辨；
 * ② **给出下一步动作** —— 项目吃过亏的反例是 erp-v3 那条让用户"重试"的提示，
 *    而重试根本修不了它指的那个状态。
 */
/** 套餐徽章文字：免费档不画（同 codex 只画 PRO、agy 只画 ULTRA —— 常态不值得占位）。 */
export function grokBadgePlan(a: GrokAccount | null | undefined): string {
  const n = a?.plan?.name ?? "";
  return /^free$/i.test(n) ? "" : n;
}

/**
 * 手动刷新之后的 toast（用户 2026-10-23「grok 点刷新没有对应的 UI 交互反应」）。
 * token 已过期时 grok-quota **不发请求、几十毫秒就回来**，转圈一闪而过、数字不变 —— 看上去就是没点中。
 * 所以失败时按原因说一句「为什么没变、要做什么」，不只写「刷新失败」。长解释仍在卡上的标记悬停里（`grokReasonNote`）。
 */
export function grokRefreshToast(ok: boolean, a: GrokAccount | null | undefined): string {
  if (ok) return "已刷新 Grok · 免费";
  switch (a?.reason) {
    case "token_expired": return "Grok token 已过期 · 在终端起一次 grok 会话会自动续期，再点刷新";
    case "unauthorized": return "✗ xAI 拒绝了 Grok token · 需要重新登录 grok";
    case "rate_limited": return "xAI 限流中 · 到点后自动重试";
    case "network_error": return "✗ 连不上 xAI · 稍后再试";
    case "auth_file_missing": case "auth_file_empty": return "本机没有 grok 登录信息 · 先登录 grok CLI";
    default: return "✗ Grok 额度这次没读到 · 稍后再试";
  }
}

export function grokReasonNote(a: GrokAccount): string {
  const when = a.token_expires_at
    ? new Date(a.token_expires_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "";
  switch (a.reason) {
    case "token_expired":
      return `grok 的 access token ${when ? `已在 ${when} ` : "已"}过期（约 6 小时有效期）。`
        // ★ 「起一次会话」是实测措辞,不是随手写的:`grok --version` **不会**续期(实测指纹不变),
        //   要真正起一次 TUI 才会(实测 expires_at 前推 6 小时、key 指纹变了)。
        //   说成"跑一次 grok"会让人用 --version 试一下,然后以为这条提示是错的。
        + `这不是「额度为 0」——在终端起一次 grok 会话（不必发消息）它就会自己续期，下次刷新即恢复。`;
    case "unauthorized":
      return `xAI 拒绝了这个 token（HTTP ${a.http_status ?? 401}）。可能是被撤销或换了账号，`
        + `需要重新登录 grok。这不是「额度为 0」。`;
    case "auth_file_missing":
      return `本机没有 ~/.grok/auth.json。装了 grok CLI 并登录过之后才会有额度可读。`;
    case "auth_file_unreadable":
      return `读到了 ~/.grok/auth.json 但解析不了（grok CLI 可能正在改写它）。`
        + `这不是「额度为 0」，下次刷新会自动重试。`;
    case "auth_file_empty":
      return `~/.grok/auth.json 里没有任何账号条目。`;
    case "bad_payload":
      return `xAI 返回了 200，但响应里没有额度字段（接口可能改了）。这不是「额度为 0」。`;
    case "http_error":
      return `xAI 返回 HTTP ${a.http_status ?? "?"}。这不是「额度为 0」，下次刷新会自动重试。`;
    case "rate_limited": {
      const at = a.retry_at
        ? new Date(a.retry_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "";
      return `xAI 限流了（HTTP 429）${at ? `，要求 ${at} 之后再取` : ""}。`
        + `这不是「额度为 0」，到点前不再发请求，到点后自动重试。`;
    }
    case "network_error":
      return `连不上 xAI${a.detail ? `（${a.detail.split("\n")[0].slice(0, 80)}）` : ""}。`
        + `这不是「额度为 0」，下次刷新会自动重试。`;
    default:
      return `额度暂时读不到。这不是「额度为 0」，下次刷新会自动重试。`;
  }
}

/**
 * 这台机器上**该不该显示 grok 额度**。总览卡与菜单栏行必须用同一个判据 ——
 * 两边各写一份，迟早出现「主窗有、菜单栏没有」。
 *
 * 分两层，语义完全不同：
 * ① **自动**：`auth_file_missing` / `auth_file_empty` = 这台机器压根没有 grok。
 *    这是**确定的否定**，不是"读不到" —— 所以隐藏是诚实的，不违反「读不到 ≠ 确实没有」。
 *    没装 grok 的人不该看到一张永久写着「你没装 grok」的卡：那是一盏永远亮着、
 *    又不需要任何动作的灯，只会训练人忽略所有提示（项目已判过死刑的形态）。
 * ② **手动**：用户在设置页 ›「AI 平台管理」停用了 grok（`prefs.by.grok.off`）。
 *    **复用既有开关，不新造第二套** —— 那个开关的语义本来就是「别给我看这家」。
 *
 * ★ `snap == null`（还没取过）也返回 false：宁可晚 1 秒出现，也不要让没装 grok 的人
 * 先闪一下「未探测」再消失。
 */
export function grokQuotaVisible(
  snap: GrokSnapshot | null | undefined,
  opts: { disabled?: boolean } = {},
): boolean {
  if (opts.disabled) return false;
  if (!snap || !snap.accounts.length) return false;
  const a = snap.accounts[0];
  return a.reason !== "auth_file_missing" && a.reason !== "auth_file_empty";
}
