/**
 * Antigravity(agy) 额度的类型与**文案单一真源**。
 *
 * 数据来自仓库根的 `agy-quota`（本机 agy 进程监听的 loopback Connect RPC，
 * `RetrieveUserQuotaSummary`，无鉴权）。**不联网、不消耗任何配额。**
 *
 * 与本页 token 统计**不同源**，且这次的差距比 grok 那边更大：
 * token 那边是 `~/.gemini/antigravity-cli/conversations/*.db`（agy 自己的会话库，
 * 交互式会话一个字都进不来，所以那是**下界**）；这边是 Google 那侧的真实额度水位。
 * 两个数不可加、不可互推 —— 尤其**不能**拿账本去解释额度掉了多少。
 *
 * ★★ 与 grok 的方向**相反**，这是全 app 最容易写反的一处：
 *
 *        grok-quota  → `used_percent`      已用
 *        agy-quota   → `remaining_percent` 剩余
 *
 * 两条链路的卡片长得几乎一样、变量名也都叫 `pct`。所以这里的取数函数**名字里都带方向**，
 * 且不导出裸数字 —— 同 `grok.ts` 的纪律，理由见那份文件里那段「颜色完全反相且不报错」。
 */

import { fmtEta, type AnchorVerdict } from "./helpers";

/** ★ 闭集，必须与 `agy-quota` 里的 `REASONS` 逐字相等。
 *  闸在 `tests/test_agy_reason_copy.py`：两边都从源解析，新增一个只改一边就红。 */
export type AgyReason =
  | "not_installed"
  | "no_process"
  | "not_ready"
  | "no_ports"
  | "bad_payload"
  | "rpc_error"
  | "network_error"
  | "csrf_required";

export interface AgyBucket {
  bucket_id: string | null;
  /** 上游原词：`"weekly"` / `"5h"`。转展示标签走 `agyWinLabel`，别在调用点写 switch。 */
  window: string | null;
  /** ★★ 0–100 的**剩余**百分比。与 grok 的 `used_percent` 方向相反。
   *  `null` = 桶在、上游没给数（proto3 省略零值 ⇒ 可能正是 0）。**读不到，不是满也不是空**。 */
  remaining_percent: number | null;
  reset_at: number | null;
  /** 锚点账本对这个桶的判定（`traffic/quota_anchors.py`，由 `agy-quota` 写）。
   *  ★ agy 是「闲置桶的 `resetTime` 跟着 now 滑」最典型的那个：没有它，这里渲染的
   *  是一个**永远停在 4h5xm** 的倒计时，而且没有任何标记说它是假的。 */
  anchor?: AnchorVerdict;
  /**
   * ★★★ 这一格是**上次看到的**，不是现在读到的 —— 值是那一刻的 unix 秒。
   *
   * 这一格是**上次读到的**数，不是这次：云端摘要偶尔整组不回（2026-10-16 实测同一个号几分钟内来回），
   * 后端沿用上次那组并标上那份读数的时刻（`agy/pool.py::carry_missing_groups`，§7.0b 第 3 问）。
   * （早先它来自 `weekly_seen` —— 「非当值号读不到周」那条结论后来被证伪，B53。）
   * ⚠️ **带着它的桶一律降级显示**（标龄、降不透明度），绝不冒充新鲜读数。
   */
  seen_at?: number;
}

export interface AgyGroup {
  /** 上游 `displayName`，实测两组：`"Gemini Models"` / `"Claude and GPT models"`。 */
  name: string | null;
  buckets: AgyBucket[];
}

export interface AgyQuota {
  groups: AgyGroup[];
}

export interface AgySnapshot {
  schema: number;
  fetched_at: number;
  available: boolean;
  reason: AgyReason | null;
  detail: string | null;
  pid: number | null;
  /** ★★★ **那个 pid 自己认证成了哪个号**（取自 agy 自己的日志 `applyAuthResult:`）。
   *  `null` = 认不出 ⇒ **这份读数不许挂到任何账号卡上**。
   *
   *  本机常有多个长期存活的 agy 进程，身份各不相同；`agy-quota` 打的是「第一个应答的 pid」，
   *  所以这份周额度属于**那个进程**，不属于"当前登录的号"。实测 2026-09-13：
   *  卡上 `user-b` 显示的 `周 99%` 实际来自 pid 24433（`user-a`，起于 09-07）。
   *  归属要有证据 —— 同本仓「按 response_id 精确 join，不按时间猜」。 */
  pid_email?: string | null;
  /** ★ `available === false` 时恒 `null`。
   *  绝不是空对象、更不是满额 —— 上游 `remainingFraction` 缺省值就是 1.0，
   *  这条链路上「失败」与「满格」只隔一个默认值。 */
  quota: AgyQuota | null;
  last_good: { quota: AgyQuota; fetched_at: number | null } | null;
}

/** 上游窗口原词 → 展示标签。与账号卡的 `winLabel` 输出对齐，靠它对上同一条槽位。 */
export function agyWinLabel(window: string | null): string {
  if (window === "weekly") return "周";
  if (window === "5h") return "5h";
  return window || "?";
}

/**
 * 当前该看哪份额度：活数据优先，没有就用降级时搬运的上次读数。
 *
 * ★ 返回值里带 `stale`，**调用点不许自己判断** —— 「这个数是不是现在的」必须跟着数一起走，
 * 分开传迟早有一处只取了数、忘了取那个标志，于是陈旧读数被画成实时值。
 */
export function agyShown(s: AgySnapshot | null | undefined):
  { quota: AgyQuota; stale: boolean; at: number | null } | null {
  if (s?.available && s.quota) return { quota: s.quota, stale: false, at: s.fetched_at };
  if (s?.last_good?.quota) return { quota: s.last_good.quota, stale: true, at: s.last_good.fetched_at };
  return null;
}

/** 全部桶摊平。顺序保持上游给的顺序（Gemini 在前），不排序 —— 排序会让 UI 里的行跳来跳去。 */
export function agyBuckets(q: AgyQuota | null | undefined): { group: string | null; b: AgyBucket }[] {
  return (q?.groups ?? []).flatMap(g => g.buckets.map(b => ({ group: g.name, b })));
}

/**
 * **约束最紧**的那个桶 —— 剩余最少的那个。
 *
 * 这是环里该显示的数：4 个桶里任何一个见底，agy 就用不了了，所以"还剩多少"的答案
 * 只能是最小的那个，不是平均值。★ 与托盘挑窗口的口径一致（`lib.rs` 取 used 最大者）。
 */
export function agyTightest(q: AgyQuota | null | undefined): { group: string | null; b: AgyBucket } | null {
  const all = agyBuckets(q);
  if (!all.length) return null;
  // ★ 有一格读不到，「最紧」就不知道 —— 缺的那格可能正是 0。读不到的那格胜出（环上画「—」）。
  return all.find(x => x.b.remaining_percent == null)
    ?? all.reduce((a, x) => ((x.b.remaining_percent as number) < (a.b.remaining_percent as number) ? x : a));
}

/** 取额度被 Google 拒绝时**该做什么**（来自错误体的 `ErrorInfo.reason` + 验证链接，`agy/pool.py::parse_google_error`）。
 *  ★ 不进 `AgyReason` 闭集：那是 `agy-quota`（本机 RPC）的契约，本机 RPC 不会回这几种。 */
export interface AgyAction { label: string; note: string; url: string | null }

export function agyAction(reason: string | null | undefined, url: string | null | undefined): AgyAction | null {
  const u = url ?? null;
  switch (reason) {
    case "VALIDATION_REQUIRED":
      return { label: "需验证", url: u,
        note: "Google 要求先验证这个号才放行（403 VALIDATION_REQUIRED）。这不是「额度耗尽」，重试也不会好："
          + (u ? "点「需验证 →」在浏览器里完成验证，再点 ↻。"
               : "用这个号起一次 agy，按它给的链接完成验证，再点 ↻。") };
    case "SUBSCRIPTION_REQUIRED":
      return { label: "无许可", url: u,
        note: "这个号没有 Antigravity 的有效许可（403 SUBSCRIPTION_REQUIRED）。这不是「额度耗尽」，"
          + "重试不会好：给它开通，或在卡片上把它摘出轮换。" };
    default:
      return u ? { label: "需处理", url: u,
        note: `Google 拒绝了额度请求（${reason ?? "无 reason"}）并附了处理链接。这不是「额度耗尽」：`
          + "点「需处理 →」看它要什么，再点 ↻。" } : null;
  }
}

/**
 * agy 账号的档位徽章画什么。★ **只画 ULTRA**（用户 2026-10-15 选定）：池里多数是 Pro，
 * 同 codex「Plus 是多数就不画」的口径 —— 只给少数派打标。数据来自 `loadCodeAssist` 的 `paidTier`
 * （`agy/pool.py::plan_of`），读不到就是 null，不画（不猜成 Pro）。
 */
export function agyBadgePlan(plan: string | null | undefined): string {
  return plan === "ultra" ? "ultra" : "";
}

/** `agy-rotate probe --json` 的一条。`q5h` = 探前/探后的 Gemini 5h（百分比），读不到为 null。 */
export interface AgyProbeResult {
  label: string; ok: boolean; note: string;
  q5h?: { before: number; after: number | null; reset: number | null; started: boolean } | null;
}

/** 探针结果 → 一句 toast。★ 用户要看的是「探完 5h 窗口启动了没有」（2026-10-15，同 codex 探针的用法）。
 *  没读到就说没读到；没下降不说「启动了」—— 那是把一个假倒计时说成真的。 */
export function agyProbeToast(rs: AgyProbeResult[]): string {
  const hm = (ts: number | null) => {
    if (!ts) return "?";
    const d = new Date(ts * 1000);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };
  const one = (r: AgyProbeResult): string => {
    if (!r.ok) return `✗ ${r.label} · ${r.note.slice(0, 60)}`;
    const q = r.q5h;
    if (!q || q.after == null) return `✓ ${r.label} · 5h 没读到，无法判断窗口是否启动`;
    if (q.started) return `✓ ${r.label} · 5h ${q.before.toFixed(1)}% → ${q.after.toFixed(1)}% · 窗口已启动，${hm(q.reset)} 重置`;
    return `✓ ${r.label} · 5h 仍 ${q.after.toFixed(1)}%，未见下降（稍后 ↻ 再看）`;
  };
  if (rs.length === 1) return one(rs[0]);
  const ok = rs.filter(r => r.ok);
  const started = ok.filter(r => r.q5h?.started).length;
  const bad = rs.filter(r => !r.ok).map(r => r.label);
  return `探针 ${ok.length}/${rs.length} 可用 · 5h 已启动 ${started} 个`
    + (bad.length ? ` · 失败：${bad.join("、")}` : "");
}

/** 桶在、数没给时，卡与菜单栏行共用的一句话（两个 surface 一份文案）。 */
export const AGY_UNKNOWN_TITLE =
  "上游这一格没给剩余比例 —— 读不到，不是满也不是空（proto3 会省略 0，所以可能正是见底）。"
  + "选号把这个号排在有读数的号之后；点 ↻ 重取一次。";

/**
 * 按窗口聚合成卡片上的条形行：每个窗口标签一行，取该窗口下**最紧**的那组。
 *
 * agy 是 2 组 × 2 窗口 = 4 个数，而卡片只有账号卡那两行的高度。**刻意做减法**：
 * 行上显示的是"这个窗口最紧的是谁、剩多少"，具体哪一组写在 `group` 里由调用点放进 title。
 * 全 4 行铺开会把卡片撑高，破坏九宫格里与账号卡的对齐（那个对齐是像素级调过的）。
 */
export interface AgyWinRow {
  /** `null` = 这个窗口有桶读不到（见 `AgyBucket.remaining_percent`）。 */
  label: string; remaining: number | null; group: string | null; reset_at: number | null;
  anchor?: AnchorVerdict;
  /** 见 `AgyBucket.seen_at` —— 有值 = 这是**上次看到的**读数，必须降级显示。 */
  seen_at?: number;
}

export function agyWinRows(q: AgyQuota | null | undefined): AgyWinRow[] {
  const byWin = new Map<string, AgyWinRow>();
  for (const { group, b } of agyBuckets(q)) {
    const label = agyWinLabel(b.window);
    const cur = byWin.get(label);
    const r = b.remaining_percent;
    if (!cur || (cur.remaining != null && (r == null || r < cur.remaining))) {
      // ★ `anchor` 必须跟着桶一起带下来。丢了它，行上渲染的就还是那个
      //   永远停在 4h5xm 的倒计时 —— 后端算了、前端没接，正是本仓点名的孤儿字段。
      byWin.set(label, { label, remaining: b.remaining_percent, group, reset_at: b.reset_at,
                         anchor: b.anchor, seen_at: b.seen_at });
    }
  }
  // 短窗在前（5h 比周更常变），与账号卡的行序一致。
  return [...byWin.values()].sort((a, b) => (a.label === "5h" ? -1 : b.label === "5h" ? 1 : 0));
}

/**
 * 倒计时该显示什么 —— **两个 surface 的单一真源**（AgyCard 与 AgyRow）。
 *
 * ★★ 本仓在 grok 上栽过一次「同一状态两个 surface 两种画法」，靠截图才发现。
 *    所以这里从一开始就只写一份。
 * ★ 只有账本判定 `floating` **且**该窗口零消耗时才敢说「未启动」；
 *   `unknown` 一律照旧渲染倒计时 —— 拿「还没看够」冒充「确定没启动」是本仓的老毛病。
 * ★ 判定必须核身份（`anchor.reset` 对得上当前 `reset_at`），否则会拿旧窗口的
 *   结论去解释新窗口，而两者渲染出来一模一样。
 */
export function agyResetText(b: { reset_at: number | null; anchor?: AnchorVerdict }):
  { text: string; title: string } {
  const a = b.anchor;
  const sameWindow = a?.reset != null && b.reset_at != null
    && Math.abs(a.reset - b.reset_at) <= AGY_ANCHOR_ID_TOL_SEC;
  if (sameWindow && a?.state === "floating" && (a.used_max ?? 0) < 2) {
    return { text: "未启动",
             title: `窗口未启动 · 连续 ${(a.slides ?? 0) + 1} 次读数里重置时间都在跟着「现在」滑动` };
  }
  return { text: fmtEta(b.reset_at ?? undefined), title: "" };
}

/** 与 Python 侧 `quota_anchors.JITTER_SECS` 同值。 */
const AGY_ANCHOR_ID_TOL_SEC = 60;

export type AgyTone = "amber" | "red" | "muted";

/**
 * 降级态的色调。
 *
 * ★ `no_process` 给 `muted` 而不是琥珀：agy **不常驻**，没在跑是**常态**不是故障。
 * 把常态染成警告色，就是又造一盏长亮的灯 —— 本仓判过死刑的形态。
 */
export function agyReasonTone(s: AgySnapshot): AgyTone {
  switch (s.reason) {
    case "not_installed":
    case "no_process": return "muted";
    case "bad_payload": return "red";   // 接口变了，要人去看
    default: return "amber";            // 会自愈的
  }
}

/**
 * 降级文案的**唯一出处**（同 `grok.ts` 的 `grokReasonNote` 纪律）。
 *
 * 每条都必须做到两件事：
 * ① **明说这不是「额度耗尽」** —— 满格与读不到在这条链路上只隔一个默认值，
 *    用户没有别的办法分辨；
 * ② **给出下一步动作，且那个动作要真能修** —— 反例是 erp-v3 那条让用户"重试"的提示，
 *    而重试根本修不了它指的那个状态。所以 `no_process` 这条写的是"起一次 agy"，
 *    `not_ready` 写的是"等几秒"，两者不能都写成"稍后重试"。
 */
export function agyReasonNote(s: AgySnapshot): string {
  switch (s.reason) {
    case "not_installed":
      return `本机没有 agy。装了 Antigravity CLI 之后才有额度可读。`;
    case "no_process":
      return `agy 现在没在运行。额度服务随 agy 进程存在，所以这**不是「额度耗尽」**——`
        + `在终端起一次 agy（或跑一次 omc ask antigravity）就能读到。`;
    case "not_ready":
      // ★ 这条是实测出来的,不是猜的:同一个进程 0s 返 500、10s 返 200。
      //   我曾经因为在端口刚出现时就调,把这个预热窗口误判成"结构性拿不到"。
      return `agy 刚起来，额度服务还在预热（实测约 10 秒）。这不是「额度耗尽」，`
        + `过几秒再刷新就有了。`;
    case "no_ports":
      return `agy 在运行，但还没开监听端口。这不是「额度耗尽」，下次刷新会自动重试。`;
    case "bad_payload":
      return `agy 返回了 200，但响应里没有额度字段（接口可能改了）。这不是「额度耗尽」。`;
    case "rpc_error":
      return `agy 的额度接口返回错误${s.detail ? `（${s.detail.slice(0, 60)}）` : ""}。`
        + `这不是「额度耗尽」，下次刷新会自动重试。`;
    case "csrf_required":
      // ★ 这一种**重试修不好**，所以不能说"下次会自动重试"（那句在别的 case 里是真话）。
      return `agy 1.2 起本机额度接口需要它内部的 token，这里读不到。`
        + `这不是「额度耗尽」：各号额度改由云端读数提供（每 10 分钟自动刷新，↻ 可立即刷新）。`;
    case "network_error":
      return `连不上 agy 的本地端口${s.detail ? `（${s.detail.slice(0, 60)}）` : ""}。`
        + `这不是「额度耗尽」，下次刷新会自动重试。`;
    default:
      return `额度暂时读不到。这不是「额度耗尽」，下次刷新会自动重试。`;
  }
}

/**
 * 这台机器上**该不该显示 agy 额度**。总览卡与菜单栏行必须用同一个判据。
 *
 * 只有两种情况不画：
 * ① 用户在设置页停用了 agy（复用既有的平台开关，不新造第二套）；
 * ② `not_installed` —— **确定的否定**，隐藏是诚实的。
 *
 * ★★ `no_process` **要画**。它和 `not_installed` 的区别就是这个函数存在的理由：
 * agy 不常驻，"没在跑"是常态；此时卡上还能显示上次读数（`last_good`），
 * 那是关于一份真实额度的真实数字。把它一起藏掉，等于让用户永远看不见 agy 的额度。
 *
 * ★ `snap == null`（还没取过）返回 false：宁可晚 1 秒出现，也不要让没装 agy 的人
 * 先闪一下「未探测」再消失。
 */
export function agyQuotaVisible(
  snap: AgySnapshot | null | undefined,
  opts: { disabled?: boolean } = {},
): boolean {
  if (opts.disabled) return false;
  if (!snap) return false;
  return snap.reason !== "not_installed";
}
