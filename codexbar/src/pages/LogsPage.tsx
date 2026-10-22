import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { Theme } from "../theme";
import { introEnabled } from "../hooks/useIntro";
import { fmtTokL, titleSize } from "../tokenView";
import { type Rec, median, mins, recsOf, rotLayout } from "../rotationView";
import { useReqLedger } from "../hooks/useReqLedger";
import { KpiGrid, PLogo, RefreshAgo, type TkKpi } from "../components/tk/TkParts";
import { MONO, numColor, tkPal } from "../components/tk/tkPal";
import RotTimeline, { BAD, WARN, type Lane } from "../components/rot/RotTimeline";
import RotTod from "../components/rot/RotTod";
import RotRecords from "../components/rot/RotRecords";
import type { Rotation, SvcLine } from "../components/rot/rotTypes";
import { useWinDensity } from "./TrafficPage";
import "../components/tk/tk.css";

/**
 * 代理轮换 · AICoop P7（阶段 5）1:1 复刻 `~/Downloads/AICoop_handoff/boards/07_rotation/P7_A*` / `P7_Long*`。
 * 规格摘录 `scratch/aicoop_20261021/P7P8_extract.md`；偏离逐条在 `PLAN.md` 第 41 条（P7-*）。
 *
 * 结构：顶栏（标题 · 平台胶囊 · 刷新 · 时间档）→ 7 个指标 → 在岗视图（1h/6h/24h 时间线；7d+ 账号 × 时段）→ 轮换记录。
 * 回答四个问题：**什么时间 · 哪个号在岗 · 烧了多少 token · 为什么切换**。
 *
 * ★ 段比稿碎得多：稿图 24h 约 30 段 / 每段 18–55 分钟；真机代理是**逐请求**挑号，24h 常见几十段、平均几分钟。
 *   「太短」预警因此几乎常亮 —— 那是数据的真相，不调阈值让它消失（P7-7 第 8 条）。
 * ★ 合计是**下界**：只有走过代理的响应能归属，直连 codex 的请求永远进不来（`covNote` 挂在 Token 格上）。
 */

/**
 * ★ 2026-09-21 加了 14d / 30d（用户：界面最长只能看 7 天，而日志里有 44 天）。
 *   上界实测：30d 读 ~4MB / 约 5s，在 `TAIL_BYTES`(6MB) 之内；**60d 会撞上限并截断**，所以刻意停在 30d。
 */
const WINDOWS = [1, 6, 24, 168, 336, 720] as const;
type WinH = (typeof WINDOWS)[number];
/** ★ `24` 仍写作 `24h`（既有标签）；只有 ≥7 天的档位用 `Nd`。 */
const winLabel = (h: WinH): string => (h >= 168 ? `${h / 24}d` : `${h}h`);

/** 时间窗选择要**记住**（用户 2026-09-07：「我选 6h，下次打开也是 6h」）。
 *  ★ 读回来要**校验在合法集合里**：手改过或旧版本留下的值会变成一个谁都不匹配的窗口。 */
const WIN_KEY = "codexbar_rot_win";
/** 代理轮换看的是哪个平台（Codex / Gemini）。 */
const PLAT_KEY = "codexbar_rot_plat";
function loadWin(): WinH {
  try {
    const n = Number(localStorage.getItem(WIN_KEY));
    if ((WINDOWS as readonly number[]).includes(n)) return n as WinH;
  } catch { /* 无痕模式：本次用默认值 */ }
  return 24;
}

/** `[<源> …]` 行首的三种形态。`dawnprobe` 那份**一个时间戳都没有**。 */
const RE_DATED = /^\[(\w[\w-]*) (\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\]/;   // [proxy 09-14 13:48:20]
const RE_CLOCK = /^\[(\w[\w-]*) (\d{2}):(\d{2}):(\d{2})\]/;                   // [quotad 19:26:47]

/**
 * 把 `read_logs` 的扁平文本解析成带来源与时间的行。
 *
 * ★★★ **`quotad.log` 只有 `HH:MM:SS`，没有日期。** `read_logs` 每个源给的是**倒序**（最新在前），
 *   所以沿着它往下走，**时间一旦变大就说明跨了一天**，把日期往前推一天。这样得到的时间是**推断**，
 *   逐行标 `inferred`，界面上给 `~` 前缀 —— 推断不许伪装成实测。
 * ★ `proxy` 的行**跳过**：`rot.log` 已经是它，而且带完整日期、按窗口过滤过。
 */
function parseServiceLogs(raw: string, now: Date): SvcLine[] {
  const out: SvcLine[] = [];
  // ★ 来源由 Rust 侧以 `<job>\t` 前缀给出，**不在这里猜**。
  const bySrc = new Map<string, string[]>();
  for (const raw1 of raw.split("\n")) {
    if (!raw1.trim()) continue;
    const tab = raw1.indexOf("\t");
    if (tab < 0) continue;                       // 没有来源前缀 = 契约没对上，宁可不画
    const src = raw1.slice(0, tab);
    if (src === "proxy") continue;
    const arr = bySrc.get(src) ?? [];
    arr.push(raw1.slice(tab + 1));
    bySrc.set(src, arr);
  }
  for (const [src, lines] of bySrc) {
    let cursor = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    let prevSecs = Infinity;
    for (const text of lines) {
      const d = RE_DATED.exec(text);
      if (d) {
        // ★ 跨年时 `09-14` 可能属于去年 —— 比今天晚超过 1 天就退一年。
        let dt = new Date(now.getFullYear(), +d[2] - 1, +d[3], +d[4], +d[5], +d[6]);
        if (dt.getTime() - now.getTime() > 86400_000) dt = new Date(dt.setFullYear(dt.getFullYear() - 1));
        out.push({ src, t: Math.floor(dt.getTime() / 1000), inferred: false, text: text.slice(d[0].length).trim() });
        continue;
      }
      const c = RE_CLOCK.exec(text);
      if (!c) {
        out.push({ src, t: null, inferred: false, text });   // ★ 真的没有时间。写 `null`，不编一个。
        continue;
      }
      const secs = +c[2] * 3600 + +c[3] * 60 + +c[4];
      if (secs > prevSecs) cursor = new Date(cursor.getTime() - 86400_000);   // 时间倒退 ⇒ 跨日
      prevSecs = secs;
      const dt = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate(), +c[2], +c[3], +c[4]);
      out.push({ src, t: Math.floor(dt.getTime() / 1000), inferred: true, text: text.slice(c[0].length).trim() });
    }
  }
  return out;
}

const fmtTok = (n: number): string => fmtTokL(n, 1);
const plain = (s: string | undefined): string | undefined => s?.replace(/\*\*/g, "");

const PLATS = [
  { k: "codex" as const, name: "Codex", logo: "codex", color: "#2dd4bf" },
  { k: "agy" as const, name: "Gemini", logo: "agy", color: "#4d9fff" },
];

export default function LogsPage({ t, pools }: {
  t: Theme;
  /** 池里的号（池顺序）。泳道顺序固定 = 池顺序（稿「顺序固定」），不在池里的退役名按字母排在后面。 */
  pools?: { codex: string[]; agy: string[] };
}): React.ReactElement {
  const p = tkPal(t);
  const { L, W } = useWinDensity();
  const lay = rotLayout(W);
  const [intro] = useState(() => introEnabled());
  const [rot, setRot] = useState<Rotation | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [win, setWinState] = useState<WinH>(loadWin);
  const setWin = useCallback((h: WinH) => {
    setWinState(h);
    try { localStorage.setItem(WIN_KEY, String(h)); } catch { /* 无痕模式：本次不记住 */ }
  }, []);
  /** 后台正在重扫（快照已经画出来了，这只是个不打断阅读的小标记）。 */
  const [busy, setBusy] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  /** ★ 2026-09-24 用户：「代理轮换改成 codex 和 gemini 两个版块」。Gemini 那一版来自 `traffic/agy_rotation.py`：
   *  agy 没有代理，泳道 = agy **以这个号的身份在运行**的时段，事件 = `agy.log` 的换号记录。 */
  const [plat, setPlatState] = useState<"codex" | "agy">(() => {
    try { return localStorage.getItem(PLAT_KEY) === "agy" ? "agy" : "codex"; } catch { return "codex"; }
  });
  const setPlat = useCallback((v: "codex" | "agy") => {
    setPlatState(v);
    try { localStorage.setItem(PLAT_KEY, v); } catch { /* 无痕模式：本次不记住 */ }
  }, []);
  const isAgy = plat === "agy";
  const pc = PLATS.find((x) => x.k === plat) ?? PLATS[0];
  const num = numColor(t, pc.logo, pc.color);
  const long = win >= 168;

  // ★ 每次取数一个序号：换平台 / 换窗口后，上一次（可能是冷扫 30d）晚回来的结果不许盖掉当前视图，
  //   它的 finally 也不许提前熄灭当前这次的「刷新中」（评审 gemini 阶段 5）。
  const seqRef = useRef(0);
  /** 屏上 `rot` 属于哪一份数据（`平台:窗口`）。★ 同一份的重扫失败 ⇒ 留着旧数、标「刷新失败」（§7.0b）；
   *  换了窗口 / 平台 ⇒ 旧数一律不许挂在新标签下面（全方面评审 §3：原来两种情形走同一条清空路径，
   *  而换窗口没快照时又先挂着旧窗口的数）。 */
  const rotKey = useRef<string | null>(null);
  const load = useCallback(async (hours: WinH) => {
    const seq = ++seqRef.current;
    const cur = () => seq === seqRef.current;
    const key = `${plat}:${hours}`;
    const adopt = (r: Rotation) => { rotKey.current = key; setRot(r); setErr(null); };
    const fail = (why: string) => {
      if (rotKey.current !== key) { rotKey.current = null; setRot(null); }
      setErr(why);
    };
    // ★ 换了平台 / 窗口：旧数据与旧错误都不许挂在新标签下（阶段 C 评审 gemini：只清 rot 会残留「✗ 读取失败」）
    if (rotKey.current !== key) { rotKey.current = null; setRot(null); setErr(null); }
    if (plat === "codex") {
      // ★★ 两段式：先把**成品快照**画出来（读盘 ~1ms），再后台重扫。Gemini 没有快照（冷路径实测 0.2s，不值得多一份缓存文件）。
      try {
        const snap = await invoke<Rotation | null>("read_rotation_snapshot", { hours });
        if (cur() && snap && snap.ok && rotKey.current !== key) adopt(snap);
      } catch { /* 没有快照是首次运行的正常状态，不是故障 */ }
      if (!cur()) return;
    }
    setBusy(true);
    try {
      const r = await invoke<Rotation>(plat === "agy" ? "read_agy_rotation" : "read_proxy_rotation", { hours });
      if (!cur()) return;
      if (r.ok) adopt(r);
      else fail(r.detail ?? (plat === "agy" ? "读不到 agy 日志" : "读不到 proxy/proxy.log"));
    } catch (e: unknown) {
      if (!cur()) return;
      fail(String(e));
    } finally {
      // ★ 必须在 `finally`：失败时不熄灯，「刷新中」会一直亮着。只熄自己这一次的。
      if (cur()) setBusy(false);
    }
  }, [plat]);

  // ★ 换版块 / 换窗口先清聚焦：不许把另一个数据集的状态留在新标签下面。
  useEffect(() => { rotKey.current = null; setRot(null); setErr(null); setFocus(null); }, [plat]);

  /** 服务日志（quotad / agy / dawnprobe / autosync …）—— 原始日志与展开日志的另一半来源。
   *  ⚠️ 其中 **dawnprobe 是全仓唯一会自动花钱的任务**，它的成败要看得见。
   *  ★ 跟 30 s 刷新与 ↻ 一起读（全方面评审 §3：原来只在换窗口时读一次）。 */
  const [svc, setSvc] = useState<SvcLine[]>([]);
  const loadSvc = useCallback(() => {
    invoke<string>("read_logs")
      .then((raw) => { setSvc(parseServiceLogs(raw || "", new Date())); })
      .catch(() => { /* 服务日志读不到不影响本页其余部分；留着上次读到的 */ });
  }, []);
  const refreshAll = useCallback((h: WinH) => { void load(h); loadSvc(); }, [load, loadSvc]);

  useEffect(() => {
    refreshAll(win);
    const id = setInterval(() => { refreshAll(win); }, 30_000);
    return () => clearInterval(id);
  }, [refreshAll, win]);

  /** 每号实测 t/s（请求账本，与「请求」页同口径：只取 `est=false`、中位数）。账本只留近 2 天。 */
  const { rows: reqs, ok: reqOk } = useReqLedger();

  const logs = useMemo(() => {
    // ★ Gemini 版的 `rot.log` 就是 `agy.log` 的换号行，而服务日志里 `agy` 那一源**已经整份**含着它们 —— 不并第二次。
    const proxy = isAgy ? [] : (rot?.log ?? []).map(
      (l): SvcLine => ({ src: "proxy", t: l.t, inferred: false, text: l.text }));
    // ★ 有时间的按时间倒序；**没有时间的排在最后**，不许给它们编一个时间去参与排序。
    const merged = [...proxy, ...svc];
    const dated = merged.filter((l) => l.t !== null).sort((a, b) => (b.t as number) - (a.t as number));
    const undated = merged.filter((l) => l.t === null);
    return [...dated, ...undated];
  }, [rot, svc, isAgy]);

  const cov = rot?.coverage;
  /**
   * 窗口完整性的一句话。★★ **三态各说各的，不许共用一句**（2026-09-21）：
   *   完整 → 不说 · 上限切进窗口 → 换短窗口可补救 · 日志没那么早 → 数据从哪天开始才有。
   */
  const windowNote = (c: NonNullable<typeof cov>): string => {
    if (c.window_covered) return "";
    if (c.tail_truncated) {
      return ` ⚠️ 这个窗口超出了日志读取上限（本次读了 ${(c.tail_bytes / 1e6).toFixed(1)}MB）`
        + `，更早的部分没统计进来 —— 换一个更短的窗口可以看到完整数据。`;
    }
    if (c.log_begins_at) {
      const d = new Date(c.log_begins_at * 1000);
      return ` 日志从 ${d.getMonth() + 1}-${String(d.getDate()).padStart(2, "0")} 才开始记录，`
        + `更早的时间段**确实没有数据**（不是没统计）。`;
    }
    // ★ `log_begins_at` 为空还要分两种：读不到 vs 那段行本来就没时间戳。
    return c.log_begins_reason === "unreadable"
      ? " ⚠️ 读不到日志头部，窗口是否完整**无法判断** —— 这不等于数据完整。"
      : " 日志最早那批行是旧格式、没有时间戳，所以更早的时间段无法定位。";
  };
  /** ★ Gemini 的按号 token：后端按**会话 id** 精确归属；只有后端真做过归属（`attributed_pct` 非 null）才显示数字。 */
  const agyTok = !isAgy || rot?.coverage.attributed_pct != null;
  /**
   * 覆盖率说明（挂在 Token 格的悬停提示上）。★ 未归属的那部分**多数是流式中断**：流断了 codex 就不写 usage，
   * 而这部分**已经计费**（2026-09-21 实测：缺的 57 个 response_id 57/57 在 rollout 里没有记录，与 stream err 率 r=0.98）。
   */
  const covNote = isAgy
    ? "Gemini 按**会话**统计：agy 没有代理，看不到逐请求记录。泳道是 agy 以这个号的身份在运行的时段"
      + "（取自 agy 自己日志里的 `applyAuthResult`），不是「在消耗」。"
      + (cov && cov.attributed_pct != null
        ? `token 按**会话 id** 归属（id 写在哪份 agy 日志里、那份日志登录的是谁），`
          + `已归属 ${cov.responses_with_tokens}/${cov.responses_seen} 次生成`
          + `（${Math.round(cov.attributed_pct * 100)}%）。对不上的不按时间猜、不计入，所以合计是**下界**。`
        : "窗口内没有可归属的生成记录。")
      + (cov && cov.responses_unplaced > 0 ? ` 另有 ${cov.responses_unplaced} 场会话认不出身份、未计入。` : "")
      + (cov && ((cov.logs_unreadable ?? 0) + (cov.dbs_unreadable ?? 0)) > 0
        ? ` ⚠️ 读不了 ${cov.logs_unreadable ?? 0} 份 agy 日志、${cov.dbs_unreadable ?? 0} 个会话库 —— 那部分**没看到**，不是没运行。` : "")
    : cov
    ? `已归属 ${cov.responses_with_tokens}/${cov.responses_seen} 次响应`
      + `（${cov.attributed_pct === null ? "—" : Math.round(cov.attributed_pct * 100) + "%"}）。`
      + (cov.responses_seen > cov.responses_with_tokens
        ? `未归属的 ${cov.responses_seen - cov.responses_with_tokens} 次里多数是**流式中断**：`
          + `流断了 codex 就不写用量记录，而这部分**已经计费** —— 花了钱但看不到明细。`
        : "")
      + `另外，直连 codex 的请求不经过代理、连分母都不在，所以合计是**下界**不是总量。`
      + ((cov.rollouts_unreadable ?? 0) > 0 ? ` ⚠️ 有 ${cov.rollouts_unreadable} 个会话文件读不了 / 解压不了，那部分 token **没看到**。` : "")
      + (cov.state_error ? ` ⚠️ 读不到 state.json（${cov.state_error}），套餐 / 额度 / 「已移除」都无法判断。` : "")
      + (cov.undated_lines > 0 ? ` 另有 ${cov.undated_lines} 行旧格式日志无时间戳、未计入。` : "")
      + windowNote(cov)
    : undefined;

  /** 泳道（池顺序固定；退役名按字母排在后面）。 */
  const lanes: Lane[] = useMemo(() => {
    if (!rot) return [];
    const order = (isAgy ? pools?.agy : pools?.codex) ?? [];
    const rank = (a: string) => { const i = order.indexOf(a); return i < 0 ? 1e6 : i; };
    const now = rot.generated_at;
    return [...rot.accounts]
      .sort((a, b) => rank(a.acc) - rank(b.acc) || a.acc.localeCompare(b.acc))
      .map((a) => {
        const segs = rot.segments.filter((s) => s.acc === a.acc);
        return { ...a, segs, current: segs.some((s) => s.current),
                 cooling: a.cooling_until != null && a.cooling_until > now };
      });
  }, [rot, pools, isAgy]);

  const tps = useMemo(() => {
    const m = new Map<string, number | null>();
    const start = rot?.window.start ?? Infinity;
    for (const l of lanes) {
      // ★ 账本过期（>10 分钟没读成功 / 跨了自然日）⇒ 写 —，不拿旧账本算现在的速度（全方面评审 §3）
      m.set(l.acc, reqOk ? median(reqs.filter((r) => r.platform === plat && r.account === l.acc && !r.est && r.t_end >= start)
                                   .map((r) => r.tps)) : null);
    }
    return m;
  }, [lanes, reqs, reqOk, plat, rot]);

  const recs: Rec[] = useMemo(() => {
    if (!rot) return [];
    const all = recsOf(rot.events, rot.window.end);
    // 长周期：KPI 按所选周期，记录只列最近 24h（稿 §4）。
    const cut = long ? rot.window.end - 86400 : -Infinity;
    return all.filter((r) => r.t >= cut && (!focus || r.accs.includes(focus)));
  }, [rot, focus, long]);

  // ★ agy 池只在总览 Gemini 档读（`useAgyPool` 读池会起子进程现读钥匙串）⇒ 这里拿到空表 = 「没读」不是「0 个号」。
  const poolN = (isAgy ? pools?.agy : pools?.codex)?.length || null;
  const k = rot?.kpi;
  const n860 = L === 2;
  const onDuty = lanes.filter((l) => l.segs.length > 0).length;
  const noProxy = "agy 没有代理，没有 429 / 断流事件";
  const kpis: TkKpi[] = [
    { label: "Token", value: rot && agyTok ? fmtTokL(k!.tokens, L) : "—", full: rot && agyTok ? fmtTokL(k!.tokens, 0) : isAgy ? "agy 不上报 token" : undefined,
      sub: !rot ? "读取中" : isAgy ? (agyTok ? "按会话归属" : n860 ? "不上报" : "agy 不上报") : n860 ? "代理" : "经代理",
      tip: plain(covNote) },
    { label: isAgy ? "会话" : "请求", value: rot ? String(k!.requests) : "—", full: rot ? String(k!.requests) : undefined,
      sub: !rot ? "读取中" : isAgy ? "" : `均 ${fmtTokL(k!.avg_tokens, L)}/次` },
    { label: "换号", value: rot ? String(k!.rotations) : "—", sub: !rot ? "读取中" : n860 ? "含故障转移" : "自动 + 故障转移",
      tip: "账号**变了**才算一次；同号空闲后重新上岗不算".replace(/\*\*/g, "") },
    { label: n860 ? "在岗" : "平均在岗", value: rot ? mins(k!.avg_dwell) : "—", full: rot ? `平均每次上号 ${mins(k!.avg_dwell)}` : undefined,
      sub: !rot ? "读取中" : "每次上号" },
    { label: n860 ? "账号" : "在岗账号", value: rot ? `${onDuty}/${poolN ?? lanes.length}` : "—",
      sub: !rot ? "读取中" : n860 ? "上过号" : "本期上过号" },
    // ★ 429 / 断流是代理才有的事件：Gemini 写「—」，不写 0（0 = 说它确实没发生过）。
    { label: "429", value: !rot ? "—" : isAgy ? "—" : String(k!.cool_429), color: !isAgy && k && k.cool_429 > 0 ? BAD : undefined,
      sub: !rot ? "读取中" : n860 ? "限流" : "被限流冷却", tip: isAgy ? noProxy : undefined },
    { label: "断流", value: !rot ? "—" : isAgy ? "—" : String(k!.stream_err), color: !isAgy && k && k.stream_err > 0 ? WARN : undefined,
      sub: !rot ? "读取中" : n860 ? "未必换号" : "流中断（未必换号）", tip: isAgy ? noProxy : undefined },
  ];

  /**
   * 「每号 · 每天在岗」浮层（用户 2026-09-21 选的口径：**优先级到底生效没**）。落点：泳道表头「账号」旁（同日用户定）。
   * ★★★ 它回答的问题与账号 × 时段不同（那张答「几点」，这张答「哪天、优先级有没有被执行」），所以保留（偏离 P7-9）。
   * ★★ 每格三态绝不合并：数字=这天用了它 · `—`=这天没选中它 · `?`=这天我们没读到。
   * ★ 末行「中转站」：实测某天 40 次 POST 里 39 次走了中转站 —— 没有这一行，整列 `—` 会被读成「这天没用 codex」。
   */
  const dailyPop = rot?.daily && rot.daily.rows.length > 0 ? (
        <div data-daily className="cb-hoverwrap" style={{ marginLeft: 6 }}>
          <span data-daily-badge
                style={{ display: "inline-flex", alignItems: "center", gap: 3,
                         padding: "1px 6px", borderRadius: 6, cursor: "help", userSelect: "none",
                         fontSize: 10.5, letterSpacing: 0, textTransform: "none",
                         border: `1px solid ${t.ghostBorder}`, color: t.muted }}>
            ⓘ<span style={{ fontWeight: 600 }}>{n860 ? "每天" : "每天在岗"}</span>
          </span>
          {/* ★★ 浮层内容仍在 DOM 里，靠 CSS 控制可见性（`.cb-hoverpop`）—— 条件渲染会让 `--dump-dom` 的闸静默失效（§5c）。
              ★★ `textTransform` / `letterSpacing` 在浮层上重置：继承来的样式缺陷在源码里看不出来。 */}
          <div className="cb-hoverpop"
               style={{ maxWidth: "min(1100px, 92vw)", padding: "11px 13px", borderRadius: 10,
                        background: t.cardBg, border: `1px solid ${t.cardBorder}`,
                        boxShadow: t.shadow, textTransform: "none", letterSpacing: 0,
                        color: t.text, zIndex: 20 }}>
            <div style={{ fontSize: 10.5, color: t.muted, marginBottom: 7 }}>
              左列 <span style={{ fontFamily: MONO }}>#N</span> 是你在总览拖出来的轮换优先级 ——
              这张表是它有没有被执行的证据
            </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", fontSize: 10.5, whiteSpace: "nowrap" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "3px 8px 5px 0", color: t.muted, fontWeight: 600 }}>号</th>
                  {rot.daily.days.map((d) => (
                    <th key={d} style={{ padding: "3px 7px 5px", color: t.muted, fontWeight: 600,
                                         fontFamily: MONO, fontVariantNumeric: "tabular-nums" }}>{d}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rot.daily.rows.map((r) => (
                  <tr key={r.acc} style={{ borderTop: `1px solid ${t.divider}` }}>
                    <td style={{ padding: "4px 8px 4px 0", display: "flex", alignItems: "center", gap: 5 }}>
                      <span style={{ fontFamily: MONO, fontSize: 9.5, color: t.muted, minWidth: 18 }}>
                        {r.rank ? `#${r.rank}` : ""}
                      </span>
                      <span style={{ color: t.text, fontWeight: 600 }}>{r.acc}</span>
                      {r.rotate_off && (
                        <span style={{ color: "#E0901C", fontWeight: 700 }}>⊘</span>
                      )}
                    </td>
                    {r.cells.map((c, i) => (
                      <td key={i} style={{ padding: "4px 7px", textAlign: "right", fontFamily: MONO,
                                           fontVariantNumeric: "tabular-nums",
                                           color: c === "unknown" ? "#E0901C"
                                             : c === null ? t.muted : t.text }}>
                        {c === "unknown"
                          ? "?"
                          : c === null
                            ? "—"
                            : <span title={`${c.requests} 次请求 · ${fmtTok(c.tokens)} token`}>
                                {(c.secs / 3600).toFixed(1)}h
                              </span>}
                      </td>
                    ))}
                  </tr>
                ))}
                {rot.daily.relay.some((n) => n > 0) && (
                  <tr style={{ borderTop: `1px solid ${t.divider}` }}>
                    <td style={{ padding: "4px 8px 4px 0", color: t.muted }}>
                      中转站
                      <span title="走第三方中转站的请求不进账号池，所以泳道与上面的格子里都看不到它们"
                            style={{ marginLeft: 4, color: t.accent, cursor: "help" }}>ⓘ</span>
                    </td>
                    {rot.daily.relay.map((n, i) => (
                      <td key={i} style={{ padding: "4px 7px", textAlign: "right", fontFamily: MONO,
                                           fontVariantNumeric: "tabular-nums",
                                           color: n ? t.text2 : t.muted }}>{n || "—"}</td>
                    ))}
                  </tr>
                )}
              </tbody>
            </table>
          </div>
            <div style={{ fontSize: 9.5, color: t.muted, marginTop: 7, lineHeight: 1.6 }}>
              <span style={{ fontFamily: MONO }}>—</span> 这天没被选中 ·{" "}
              <span style={{ fontFamily: MONO, color: "#E0901C" }}>?</span> 这天的日志没读到（不是没用过） ·{" "}
              <span style={{ color: "#E0901C" }}>⊘</span> 已停用自动轮换，优先级对它无效
            </div>
          </div>
        </div>
  ) : null;

  // ★ 三种「没数字」必须说三句不同的话 —— 合成「暂无数据」就是把「我们没看到」伪装成「确实没有」。
  const empty = err ? (isAgy ? `读不到 agy 日志（${err}）` : `读不到 proxy/proxy.log（${err}）`)
    : !rot ? "读取中"
      : (cov?.in_window_lines ?? 0) === 0 ? (isAgy ? `最近 ${winLabel(win)} agy 没有运行过` : `最近 ${winLabel(win)} 代理没有处理过请求`)
        : "窗口内有日志，但没有可归属到账号的计费请求";

  return (
    // 页面根不滚（一屏规则）：记录卡在自己的容器里滚。
    <div data-rot-page className={intro ? "tk-intro" : undefined}
         style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0, gap: 12, whiteSpace: "nowrap",
                  padding: `0 ${L < 2 ? 6 : 0}px 0` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, height: 34, flexShrink: 0, minWidth: 0 }}>
        <h1 style={{ margin: 0, fontSize: titleSize(W), fontWeight: 700, flexShrink: 0 }}>代理轮换</h1>
        <div data-rot-plat role="group" aria-label="平台" style={{ display: "flex", gap: 4, flexShrink: 0 }}>
          {PLATS.map((x) => {
            const on = plat === x.k;
            const n = (x.k === "agy" ? pools?.agy.length : pools?.codex.length) || null;
            const showName = !n860 || on;
            return (
              <button key={x.k} type="button" data-rot-plat-chip={x.k} aria-pressed={on} title={x.name}
                      onMouseDown={(e) => { if (e.button === 0 && !on) setPlat(x.k); }}
                      onClick={(e) => { if (e.detail === 0 && !on) setPlat(x.k); }}
                      style={{ height: 26, padding: "0 10px", boxSizing: "border-box", borderRadius: 13,
                               border: `1px solid ${on ? `${x.color}99` : p.idleBorder}`, background: on ? `${x.color}24` : "transparent",
                               color: on ? p.text : p.text2, fontSize: 12.5, fontWeight: 500, fontFamily: "inherit",
                               display: "inline-flex", alignItems: "center", gap: 5, cursor: "pointer",
                               transition: "background .2s ease-out, border-color .2s ease-out, color .2s ease-out" }}>
                <PLogo k={x.logo} color={x.color} size={14} isDark={t.isDark} />
                {showName && <span>{x.name}</span>}
                {n != null && <span style={{ fontFamily: MONO, fontSize: 11, color: p.label }}>{n}</span>}
              </button>
            );
          })}
        </div>
        <span style={{ flex: 1 }} />
        {err && rot == null && <span title={err} style={{ fontSize: 12, color: p.down, flexShrink: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>✗ 读取失败</span>}
        {err && rot != null && <span data-rot-stale="" title={`下面是上次读到的结果；这次刷新失败：${err}`}
                                     style={{ fontSize: 12, color: WARN, flexShrink: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>⚠ 刷新失败 · 显示上次结果</span>}
        <RefreshAgo t={t} generatedAt={rot?.generated_at ?? null} L={L} busy={busy} onRefresh={() => { refreshAll(win); }}
                    hint={isAgy ? "点击重读 agy 日志（只读本地文件）" : "点击重新扫描 proxy.log（只读本地文件，不消耗额度）"} />
        <div data-rot-win role="group" aria-label="时间范围"
             style={{ display: "inline-flex", padding: 3, borderRadius: 10, gap: 2, flexShrink: 0,
                      border: `1px solid ${t.isDark ? "rgba(255,255,255,.12)" : "rgba(0,0,0,.12)"}`, background: p.panel }}>
          {WINDOWS.map((h) => {
            const on = win === h;
            return (
              <button key={h} type="button" data-win={h} aria-pressed={on}
                      onMouseDown={(e) => { if (e.button === 0 && !on) setWin(h); }}
                      onClick={(e) => { if (e.detail === 0 && !on) setWin(h); }}
                      style={{ height: 28, padding: `0 ${lay.segPad}px`, borderRadius: 7, border: 0, fontSize: 13, cursor: "pointer",
                               fontFamily: "inherit", background: on ? p.accent : "transparent", color: on ? p.accentOn : p.text2 }}>
                {winLabel(h)}
              </button>
            );
          })}
        </div>
      </div>

      {/* ★ 7 格任何宽度都是一行（稿 §1.3）；原来的单行汇总条 `Stat` 与「整条下移」机制随之删除（不是删功能）。 */}
      <div data-rot-stats style={{ flexShrink: 0 }}>
        <KpiGrid t={t} items={kpis} borderColor={p.border} />
      </div>

      {long
        ? <RotTod key={`${plat}:${win}`} t={t} rot={rot} lanes={lanes} lay={lay} color={pc.color} num={num}
                  focus={focus} onFocus={setFocus} acctExtra={dailyPop} empty={empty} isAgy={isAgy} />
        : <RotTimeline t={t} rot={rot} lanes={lanes} lay={lay} hours={win} color={pc.color} num={num}
                       agyTok={agyTok} isAgy={isAgy} tps={tps} focus={focus} onFocus={setFocus}
                       onZoom={(h) => setWin(h as WinH)} empty={empty} acctExtra={dailyPop} />}

      <RotRecords key={`${plat}:${win}:${focus ?? ""}`} t={t} recs={recs} logs={logs} lay={lay} num={num} isAgy={isAgy}
                  focus={focus} long={long} />
    </div>
  );
}
