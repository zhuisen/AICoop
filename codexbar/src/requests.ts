/**
 * 「请求」页的纯逻辑（交接包 2026-10-19 page3）。
 *
 * ★ **零 import**：`tests/test_requests_page.py` 用 `node --experimental-strip-types` 直接跑这个真文件，
 *   CI 没有 node_modules —— 顶层只要有一个 npm import，测试就只在 CI 上红（CLAUDE.md §4）。
 *
 * 数据契约 = `traffic/requests.py --json`（PLAN §2.1）。这里只做三件事：
 *   ① 在边界上校验 payload（形状不对就抛，不猜）；② 按天 / 平台筛选与指标；③ 把数字写成界面文字。
 *
 * 口径（交接包 README「计数口径」+ page3 §2）：
 * - 读不到一律写 `—`，**不写 0**；t/s 不加「≈」「估」。
 * - 速度只在单条请求上显示，本页**没有任何跨 AI 的合计 t/s**（右上「均速」是逐条实测 t/s 的中位数，
 *   不是 t/s 之和）。
 * - 首字 > 30 s 用琥珀色。没有「慢请求」筛选（定稿取消）。
 */

export type ReqPlatform = "codex" | "claude" | "agy" | "grok";
export type ReqFilter = "all" | ReqPlatform;
export type ReqDay = "today" | "yest";

/** 固定顺序 Codex → Claude → Gemini → Grok（交接包 README，不随数据变）。 */
export const PLATFORM_ORDER: readonly ReqPlatform[] = ["codex", "claude", "agy", "grok"];
/** 显示名。★ agy 显示为 **Gemini**，`agy` 只作来源小字；grok 照画板写小写。 */
export const PLATFORM_NAME: Record<ReqPlatform, string> = {
  codex: "Codex", claude: "Claude", agy: "Gemini", grok: "grok",
};

export interface ReqRow {
  key: string;
  platform: ReqPlatform;
  t_start: number | null;
  t_end: number;
  model: string | null;
  source: string | null;
  session: string | null;
  session_title: string | null;
  account: string | null;
  input: number | null;
  cached: number | null;
  output: number | null;
  reasoning: number | null;
  ttft_ms: number | null;
  gen_ms: number | null;
  total_ms: number | null;
  tool_ms: number | null;
  tps: number | null;
  est: boolean;
  session_req_n: number | null;
}

export interface DayInfo { date: string | null }

export interface ReqPayload {
  ok: boolean;
  error: string | null;
  stale_since: number | null;
  /** 读失败的是哪几家（`"*"` = 全部 / 账本本身）。只有这几家的行降透明度，别家照常。 */
  failed: string[];
  generated_at: number | null;
  requests: ReqRow[];
  days: { today: DayInfo; yesterday: DayInfo };
  /** 账本窗口的起点（秒）。比它旧的行已滑出窗口。null = 老后端没给。 */
  window_start: number | null;
  /** true = 这份只是 `since` 之后的一段（增量），要与手里的合并；false = 全部。 */
  partial: boolean;
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v !== "" ? v : null);
const isPlatform = (v: unknown): v is ReqPlatform => typeof v === "string" && (PLATFORM_ORDER as readonly string[]).includes(v);
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * 时间戳统一成毫秒。契约里 `t_start`/`t_end` 没写单位；`*_ms` 字段才明说是毫秒。
 * ★ 两种假说（秒 / 毫秒）都要成立：小于 1e12 的当秒（1e12 ms = 2001 年，秒值要到 33658 年才过线）。
 */
export function toMs(t: number): number {
  return t < 1e12 ? t * 1000 : t;
}

function parseRow(v: unknown): ReqRow | null {
  if (!isObj(v)) return null;
  const key = str(v.key), tEnd = num(v.t_end);
  if (!key || tEnd == null || !isPlatform(v.platform)) return null;
  return {
    key, platform: v.platform, t_start: num(v.t_start), t_end: tEnd,
    model: str(v.model), source: str(v.source), session: str(v.session),
    session_title: str(v.session_title), account: str(v.account),
    input: num(v.input), cached: num(v.cached), output: num(v.output), reasoning: num(v.reasoning),
    ttft_ms: num(v.ttft_ms), gen_ms: num(v.gen_ms), total_ms: num(v.total_ms), tool_ms: num(v.tool_ms),
    tps: num(v.tps), est: v.est === true, session_req_n: num(v.session_req_n),
  };
}

function parseDay(v: unknown): DayInfo {
  const d = isObj(v) ? str(v.date) : null;
  return { date: d && DATE_RE.test(d) ? d : null };
}

/**
 * 边界校验。★ 顶层形状不对就**抛**（交给 hook 当「读失败」处理、保留上次列表）；
 * 单行缺 key / 平台不认识 / 没有完成时刻 → 丢掉这一行（一条坏行不该让整页变成读失败）。
 */
export function parsePayload(raw: unknown): ReqPayload {
  const v: unknown = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (!isObj(v)) throw new Error("请求账本输出不是 JSON 对象");
  if (!Array.isArray(v.requests)) throw new Error("请求账本输出缺少 requests 列表");
  const rows: ReqRow[] = [];
  for (const r of v.requests) {
    const p = parseRow(r);
    if (p) rows.push(p);
  }
  const days = isObj(v.days) ? v.days : {};
  return {
    ok: v.ok !== false,
    error: str(v.error),
    stale_since: num(v.stale_since),
    failed: Array.isArray(v.failed) ? v.failed.filter((x): x is string => typeof x === "string")
      : v.ok === false ? ["*"] : [],
    generated_at: num(v.generated_at),
    requests: rows,
    days: { today: parseDay(days.today), yesterday: parseDay(days.yesterday) },
    window_start: num(v.window_start),
    partial: v.partial === true,
  };
}

/**
 * 增量合并（用户 2026-10-23「增量显示，而不是再全量加载」）：把 `next` 这一段并进 `prev`。
 * - `next` 是全部（`partial` 为假）或手里还没有东西 ⇒ 直接用 `next`。
 * - 否则按 `key` 合并，新值覆盖旧值（行写完后还会被补：Claude span 晚到、估值换实测）；
 *   比 `window_start` 旧的行剪掉（滑出窗口）；按 `t_end` 倒序。`days` 等汇总一律取 `next` 的（后端按全量算）。
 * - ★ 读失败（`ok` 为假）且这一段一行都没有 ⇒ 手里的行原样保留（「这次拿到空」≠「确实没有」，§7.0b）。
 */
export function mergePayload(prev: ReqPayload | null, next: ReqPayload): ReqPayload {
  if (!prev || !next.partial) return next;
  const cut = next.window_start;
  const byKey = new Map<string, ReqRow>();
  for (const r of prev.requests) if (cut == null || toMs(r.t_end) >= toMs(cut)) byKey.set(r.key, r);
  for (const r of next.requests) byKey.set(r.key, r);
  const rows = [...byKey.values()].sort((a, b) => toMs(b.t_end) - toMs(a.t_end));
  return { ...next, requests: rows, partial: false };
}

/** 下一次增量从哪儿读，**单位秒**（后端 `--since` 按秒）。null = 手里没有 ⇒ 读全部。
 *  ★ 用后端上次给的 `generated_at`（「我上次读到这一刻为止的改动」），不用手里最新一行的 `t_end`（samchen #4 ⑥）：
 *    后端按每行最后写进账本的时刻筛，迟到的行（`t_end` 更早）也能进增量。老后端没给 `generated_at` 才退回 `t_end`。 */
export function sinceOf(p: ReqPayload | null): number | null {
  if (!p || p.requests.length === 0) return null;
  if (p.generated_at != null && p.generated_at > 0) return p.generated_at;
  let m = 0;
  for (const r of p.requests) m = Math.max(m, toMs(r.t_end));
  return m > 0 ? m / 1000 : null;
}

/** 本地今天零点（秒）：今日用的几处只要今天的行，`since` 给零点就不必整读两天的账本（samchen #4 ⑧）。 */
export function todayStartSec(nowMs: number): number {
  const d = new Date(nowMs); d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000;
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/** 本地自然日 `YYYY-MM-DD`（按运行环境的时区；时间为本地，见页脚）。 */
export function localDateKey(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/**
 * 今天 / 昨天是哪两个日期。★ 优先用后端算好的 `days.*.date`：日界由后端划，前端照用，
 * 两边才不会在午夜前后各说各的。后端没给（或格式不对）才按本机时钟自己算。
 */
export function dayKeys(p: Pick<ReqPayload, "days"> | null, nowMs: number): { today: string; yest: string } {
  const today = p?.days.today.date ?? localDateKey(nowMs);
  let yest = p?.days.yesterday.date ?? null;
  if (!yest) {
    const [y, m, d] = today.split("-").map(Number);
    yest = localDateKey(new Date(y, m - 1, d - 1, 12).getTime());
  }
  return { today, yest };
}

/** 某一天的请求，按完成时刻倒序（交接包：按完成时刻倒序）。 */
export function rowsForDay(rows: readonly ReqRow[], dateKey: string): ReqRow[] {
  return rows.filter((r) => localDateKey(toMs(r.t_end)) === dateKey).sort((a, b) => b.t_end - a.t_end);
}

export function filterPlatform(rows: readonly ReqRow[], f: ReqFilter): ReqRow[] {
  return f === "all" ? rows.slice() : rows.filter((r) => r.platform === f);
}

/** 中位数（偶数取中间两个的平均，与 python `statistics.median` 一致）。空 ⇒ null。 */
export function median(xs: readonly number[]): number | null {
  if (!xs.length) return null;
  const v = [...xs].sort((a, b) => a - b), h = Math.floor(v.length / 2);
  return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2;
}

/**
 * 保留 1 位小数，**与 Python `round(x, 1)` 同值**（后端 `_day_stats` 用它；托盘 / 刘海的「均」读后端）。
 * 只有恰好落在 .x5 的二进制精确值上两者才分叉：Python 取偶，`toFixed` 进位（评审 P6-codex-3：
 * `[1, 10.2, 10.3, 100]` 中位 10.25，前端原来写 10.3、后端 10.2）。只用于非负数。
 */
export function pyRound1(x: number): number {
  const s = x.toFixed(100), i = s.indexOf(".");
  if (/^50*$/.test(s.slice(i + 2))) {
    const d = Number(s[i + 1]);
    return d % 2 === 0 ? Number(s.slice(0, i + 2)) : Number((x + 0.05).toFixed(1));
  }
  return Number(x.toFixed(1));
}

export interface DayMetrics { n: number; avgTps: number | null; ttftMedianS: number | null }

/**
 * 右上三项指标。★ **跟着筛选走**（用户 2026-10-22「同步左侧的按钮，选全部就全部信息，选 Codex 就只有 Codex」；
 * 原来照画板按整天、不跟筛选，选了一家右上仍是全部）。「全部」时均速 / 首字是四家实测行合在一起的中位数。
 * - 均速 = 有 t/s 的**实测**请求（`est=false`）的**中位数**；没有实测行 → null（界面写 `—`）。
 *   估值行照常显示自己的数字，但不进均速（用户 2026-10-22 定；估值分母含首字等待，是下限）。
 *   ★ 中位数不是算术平均（AICoop P3，阶段 6）：后端 `_day_stats.avg_tps` 一直是中位数（`traffic.md`：重尾分布下
 *   一条短响应就能把均值拉偏几倍），托盘 / 刘海的「均」读的是后端那个数。前端原来写算术平均 ⇒ 同一个「均速」两处两个数。
 *   画板写的是算术平均（示意数据下两者相同），按本仓口径取中位。
 * - 首字中位 = 有首字的请求的中位数（偶数取中间两个的平均，与 python `statistics.median` 一致）。
 *   ⚠️ 画板里写的是 `sorted[floor(n/2)]`（偶数取上中位）——那是示意数据的写法，这里取标准中位数，
 *   为的是与后端 `days.*.ttft_median_s` 在偶数条时不分叉。
 */
export function dayMetrics(rows: readonly ReqRow[]): DayMetrics {
  const tps = rows.filter((r) => !r.est).map((r) => r.tps).filter((x): x is number => x != null);
  // ★ 首字中位只取实测行（2026-10-22，与后端 `_day_stats` 同）：整包行的生成时间全在 ttft 里。
  const ttft = rows.filter((r) => !r.est).map((r) => r.ttft_ms).filter((x): x is number => x != null);
  const t = median(ttft);
  const a = median(tps);
  return { n: rows.length, avgTps: a == null ? null : pyRound1(a), ttftMedianS: t == null ? null : t / 1000 };
}

export const DASH = "—";

/** 输入 token：≥1M 写 `1.2M`，≥1000 写 `108.5k`，否则原数。读不到写 `—`。 */
export function fmtTokens(v: number | null): string {
  if (v == null) return DASH;
  if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (v >= 1000) return (v / 1000).toFixed(1) + "k";
  return String(Math.round(v));
}

/** 输出 token：千分位 `1,685`（画板 `toLocaleString('en-US')`；这里手写，不依赖运行环境的 locale）。 */
export function fmtInt(v: number | null): string {
  if (v == null) return DASH;
  const s = String(Math.round(Math.abs(v)));
  return (v < 0 ? "-" : "") + s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** 毫秒 → `4.2 s`；读不到写 `—`。 */
export function fmtSecs(ms: number | null): string {
  return ms == null ? DASH : (ms / 1000).toFixed(1) + " s";
}

/** t/s 数字（不带单位，单位是另一段小字）。读不到写 `—`；不加任何「≈」「估」。 */
export function fmtTps(v: number | null): string {
  return v == null ? DASH : v.toFixed(1);
}

export function fmtHHMM(ms: number): string {
  const d = new Date(ms);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/** 详情栏顶行 `10/18 14:26 SGT`。 */
export function fmtWhen(ms: number, tz: string): string {
  const d = new Date(ms);
  return `${pad2(d.getMonth() + 1)}/${pad2(d.getDate())} ${fmtHHMM(ms)}${tz ? " " + tz : ""}`;
}

/**
 * 时区小字。`Intl` 对新加坡给的是 `GMT+8`，而交接包写的是 `SGT`（用户在新加坡）。
 * 认得的 IANA 名用常见缩写，其余照 `Intl` 的短名。
 */
export function tzLabel(ianaZone: string, intlShort: string): string {
  const KNOWN: Record<string, string> = {
    "Asia/Singapore": "SGT", "Asia/Shanghai": "CST", "Asia/Hong_Kong": "HKT", "Asia/Tokyo": "JST",
    "UTC": "UTC", "Etc/UTC": "UTC",
  };
  return KNOWN[ianaZone] ?? intlShort;
}

/** 模型名：Claude 去掉 `claude-` 前缀（`claude-opus-5.5` → `opus-5.5`）。 */
export function modelName(model: string | null): string {
  if (!model) return DASH;
  return model.startsWith("claude-") ? model.slice(7) : model;
}

/** 来源列：codex 的 `交互` / `exec` 补上平台名（画板：`codex · 交互`、`codex exec`），其余原样。 */
export function sourceLabel(platform: ReqPlatform, source: string | null): string {
  if (!source) return DASH;
  if (platform === "codex") {
    if (source === "交互") return "codex · 交互";
    if (source === "exec") return "codex exec";
  }
  return source;
}

/** 这几个是**说明性的固定词**，不是账号身份 —— 打码模式下也照常显示。 */
export const ACCOUNT_WORDS: readonly string[] = ["直连", "本机", "单号"];

/**
 * 账号列。读不到写 `—`；打码模式只遮真正的账号名（`mask` 由调用方传入 app 现有的 `maskId`，
 * 本模块零 import）。
 */
export function accountLabel(account: string | null, privacy: boolean, mask: (s: string) => string): string {
  if (!account) return DASH;
  if (!privacy || ACCOUNT_WORDS.includes(account)) return account;
  return mask(account);
}

export const SLOW_TTFT_MS = 30_000;
/** 慢请求的第二档：**实测**速度低于它（画板 `renderVals`）。估值行不判 —— 估值分母含首字等待，是下限，判了会误报。 */
export const SLOW_TPS = 10;
export type Tone = "normal" | "muted" | "amber";

/** 首字的文字色档：读不到 → muted；> 30 s → amber；否则 normal。 */
export function ttftTone(ms: number | null): Tone {
  if (ms == null) return "muted";
  return ms > SLOW_TTFT_MS ? "amber" : "normal";
}

/** 右侧「今天总计」（用户 2026-10-22：选了 Claude，右侧除了单条，还要今天总请求的总结）。只算一家，不跨 AI。 */
export interface DaySummary {
  n: number; input: number; cached: number; output: number; cacheRate: number | null;
  avgTps: number | null; ttftMedianS: number | null;
  /** 有实测速度的条数（均速只取它们） */
  measured: number;
}

export function daySummary(rows: readonly ReqRow[]): DaySummary {
  const m = dayMetrics(rows);
  const sum = (k: "input" | "cached" | "output") => rows.reduce((a, r) => a + (r[k] ?? 0), 0);
  const input = sum("input"), cached = sum("cached");
  return { n: rows.length, input, cached, output: sum("output"), cacheRate: cacheRate(input, cached),
           avgTps: m.avgTps, ttftMedianS: m.ttftMedianS,
           measured: rows.filter((r) => !r.est && r.tps != null).length };
}

/** 缓存命中率（%，整数）。★ `input` 按含缓存的总输入算（契约口径：输入含缓存命中）。 */
export function cacheRate(input: number | null, cached: number | null): number | null {
  if (input == null || cached == null || input <= 0) return null;
  return Math.round(Math.min(1, Math.max(0, cached / input)) * 100);
}

export type TimeSplit =
  | { kind: "split"; ttftMs: number; genMs: number }
  | { kind: "none"; why: string };

/**
 * 耗时构成条（首字 / 生成）。拿不到首字 → 斜纹 + 说明（交接包），**不拿 0 去画一段**。
 * 生成段优先用后端的 `gen_ms`，没有才用 总耗时 − 首字。
 */
export function timeSplit(r: Pick<ReqRow, "ttft_ms" | "gen_ms" | "total_ms">): TimeSplit {
  if (r.ttft_ms == null) return { kind: "none", why: "这家拿不到首字时间，耗时不拆分" };
  const gen = r.gen_ms ?? (r.total_ms != null ? r.total_ms - r.ttft_ms : null);
  if (gen == null || gen < 0) return { kind: "none", why: "拿不到总耗时，耗时不拆分" };
  return { kind: "split", ttftMs: r.ttft_ms, genMs: gen };
}

/**
 * 慢请求的原因，两档（交接包「首字过长时给原因」+ 画板 `renderVals`）：
 * ① 首字 > 30 s（附缓存命中率），优先；② 实测速度 < 10 t/s —— 估值行不判（估值是下限，判了会误报）。
 */
export function slowWhy(r: Pick<ReqRow, "ttft_ms" | "input" | "cached" | "tps" | "est">): string | null {
  if (r.ttft_ms != null && r.ttft_ms > SLOW_TTFT_MS) {
    const rate = cacheRate(r.input, r.cached);
    return `慢请求：首字等了 ${(r.ttft_ms / 1000).toFixed(1)} s，超过 30 s。`
      + (rate == null ? "缓存命中读不到。" : `缓存命中 ${rate} %。`);
  }
  if (!r.est && r.tps != null && r.tps < SLOW_TPS) return `慢请求：速度 ${r.tps.toFixed(1)} t/s，低于 ${SLOW_TPS} t/s。`;
  return null;
}

/** 空列表文案（交接包 3c）。 */
export function emptyCopy(dayCount: number, day: ReqDay): { title: string; sub: string } {
  if (dayCount === 0) {
    return day === "today"
      ? { title: "今天还没有请求", sub: "有 AI 写完一条响应后会出现在这里；切到「昨天」可以看前一天" }
      : { title: "昨天没有请求", sub: "有 AI 写完一条响应后会出现在这里；只保留最近 2 天" };
  }
  return { title: "这个筛选下没有请求", sub: "换一个筛选看看" };
}

export function footerText(day: ReqDay, n: number, tz: string): string {
  return `${day === "today" ? "今天" : "昨天"} · ${n} 条 · 按完成时刻倒序 · 时间为本地 ${tz} · 列表可滚动`;
}

/** 数据来源小字（详情栏底部）。★ 按**实际**数据源写（PLAN §1），不照抄画板的示意来源。 */
export function sourceNote(r: Pick<ReqRow, "platform" | "est">): string {
  switch (r.platform) {
    case "codex": return "来源：Codex rollout 会话文件每条响应的 usage 与时间（response_id）；账号来自代理日志，对不上 = 直连";
    case "claude": return r.est
      ? "来源：~/.claude/projects 会话 jsonl，同 requestId 最后一行；速度含首字等待"
      : "来源：Claude Code 的 OpenTelemetry 账本（首字、耗时为实测）";
    case "agy": return "来源：agy 会话库（conversations/*.db）的生成元数据";
    case "grok": return "来源：grok 会话文件 turn_completed（一条 = 一轮，含多次模型调用）+ events.jsonl 的首字";
  }
}

/** 选中行：按 key 记，数据刷新后仍停在同一条；它不在当前列表里就落到第一条。 */
export function selectedIndex(list: readonly ReqRow[], selKey: string | null): number {
  if (!list.length) return -1;
  const i = selKey == null ? -1 : list.findIndex((r) => r.key === selKey);
  return i >= 0 ? i : 0;
}

/** 这一行要不要按「读失败」降透明度：只看这一行所属的那一家（全方面评审 §5：一家报错，四家整表一起变灰）。 */
export function rowStale(failed: readonly string[] | null, platform: string): boolean {
  return !!failed && (failed.includes("*") || failed.includes(platform));
}
