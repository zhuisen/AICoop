import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { Theme } from "../../theme";
import type { Account, AppState } from "../../helpers";
import { agyPoolFreshness, freshnessLine, maskId, winSlot } from "../../helpers";
import type { Board } from "../../hooks/useRotationBoard";
import type { AgyPoolAccount, useAgyPool } from "../../hooks/useAgyPool";
import type { AgySnapshot } from "../../agy";
import { agyAction, agyProbeToast, agyShown, agyTightest, agyWinRows } from "../../agy";
import type { GrokSnapshot } from "../../grok";
import { grokLastGoodRemPct, grokRefreshToast, grokRemPct } from "../../grok";
import type { ClaudeQuota } from "../../mbLogic";
import { SUB_WARN_DAYS, expiryWarnings } from "../../mbLogic";
import { getSettings } from "../../pages/SettingsPage";
import { CARD_WARN_DAYS } from "../../helpers";
import type { LiveSnapshot } from "../../live";
import type { Integration } from "../../hooks/useIntegration";
import type { CardDragWiring } from "../../hooks/useCardDrag";
import { applyOrder, undoPinStep } from "../../cardOrder";
import type { OvState } from "../../overview";
import { dayStart, lastUseByAcct, ovCounts, ovIsLow, OV_BP_WIDE, ovBand, ovLayout, ovSort, ovState, stableOrder, todaySwitches } from "../../overview";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { POOL_PLATFORMS, type PoolKey } from "../../platforms";
import AccountCard from "../AccountCard";
import AgyCard from "../AgyCard";
import GrokCard from "../GrokCard";
import IntegrationBanner from "../IntegrationBanner";
import DawnChip from "../DawnChip";
import ClaudeCard from "./ClaudeCard";
import { ClaudeHero, GrokHero } from "./OvHeroRO";
import { HeroShell, PoolHero, type PlatColors } from "./OvHero";
import { AutoSwitchItem, GroupDivider, HeadMore, OvTabs, ProbeHead, RefreshBtn, ToggleGroup, type OvTab } from "./OvHeader";
import { OvStrip } from "./OvStrip";
import { CmdK, ConfirmDelete, DetailSheet, type CmdItem, type SheetRow } from "./OvLayers";
import { TechRows, type AccountDetail } from "../AccountTech";
import { useFlip } from "../../hooks/useFlip";
import { isCmdK } from "../../cmdk";
import { modalOpen } from "../../modalOpen";
import { TOAST_BAD, TOAST_MS, TOAST_MUTED, TOAST_OK, TOAST_WARN, type RunOpts, type ToastOpts } from "../../hooks/useStore";
import ExpiryStack from "./ExpiryStack";
import { useRotationDay } from "./useRotationDay";
import { ovVars, MONO } from "./ovVars";
import "../../menubar.css";
import "./overview.css";

/**
 * 工作台 · 总览（交接包 2026-10-19 page5 · 5b 卡片版）。
 *
 * 一句话：总览回答三件事 —— 现在用的是谁、还能连续用多久、今天怎么切过；下面是等高的账号卡片网格。
 *
 * ★ 页根不滚动；卡片网格在自己的盒子里滚（`data-ov-scroll`）—— 头部与顶部三栏永远在眼前。
 * ★ 一种间距：12（卡片之间、模块之间）。不做列表视图。所有文字 nowrap，放不下先藏次要字再省略号。
 * ★ 数据全部来自调用方（`App.tsx` 持有各个 hook，按页面 / 档位开关）—— 这里只做映射与排版，
 *   所以「在哪一档才去读哪一家」的那几条纪律（探针扣哪家的钱、grok 只在总览联网）不会被这个组件改掉。
 */

type Run = (actionId: string, args: string[], msg: string, opts?: RunOpts) => Promise<boolean>;

export type AgyPoolApi = ReturnType<typeof useAgyPool>;

export interface OverviewProps {
  t: Theme; isDark: boolean; privacy: boolean;
  /** 四家的识别色，App 用 `colorOf(traffic, key)` 算（带用户偏好）。 */
  colors: PlatColors;
  provider: PoolKey; setProvider: (k: PoolKey) => void;
  state: AppState; accounts: Account[]; inUseNode: string | undefined; currentNode: string | undefined;
  lastRefreshAt: number | undefined; freshness: { fresh: number; stale: number; unknown: number };
  loadingAction: string | null; run: Run; showToast: (m: string, ms?: number, o?: ToastOpts) => number;
  /** 撤销窗口里的删除（`useStore.deferDelete`）：键带平台前缀 `codex:<aid>` / `agy:<sub>`。 */
  pendingDel: ReadonlySet<string>; deferDelete: (key: string, label: string, commit: () => Promise<boolean>) => void;
  integration: Integration | null; onConnect: () => void;
  board: Board | null; boardErr: string | null;
  agyPool: AgyPoolApi; agyBoard: Board | null; agyBoardErr: string | null;
  agySnap: AgySnapshot | null; agyBusy: boolean; agyErr: string | null; refreshAgy: () => void;
  grokSnap: GrokSnapshot | null; grokBusy: boolean; grokErr: string | null; refreshGrok: () => Promise<boolean>;
  /** 最近一次取回的 grok 快照（刷新后 toast 按它说原因）。缺省 = 当前 `grokSnap`。 */
  grokLast?: () => GrokSnapshot | null;
  claudeQuota: ClaudeQuota | null; claudeErr: string | null; refreshClaude: () => Promise<boolean | null>;
  live: LiveSnapshot | null; liveErr: string | null;
  autoSwitch: boolean; toggleAutoSwitch: () => void;
  agyOrder: string[] | undefined; setAgyOrder: (ids: string[]) => void;
  preview: string[] | null;
  makeDrag: (aid: string, baseIds: string[], hint: string, commit: (next: string[]) => void | Promise<unknown>) => CardDragWiring;
  platOff: { agy: boolean; grok: boolean };
  /** Codex 详情 Sheet 下半的技术信息（`read_account_detail`）；读不到给 null。 */
  loadDetail: (aid: string) => Promise<AccountDetail | null>;
  /** ⌘K 的「打开 Token 消耗 / 中转站 / 设置」。 */
  onNav: (page: "traffic" | "relay" | "settings") => void;
  onOpenUsage: (pk: string) => void; onLogs: () => void;
}

/** 排序模式（每档一份）：`auto` = 在用 → 可用度 → 需处理；`custom` = 用户拖出来的顺序。 */
const SORT_KEY = "codexbar_ov_sort";
type SortMode = "auto" | "custom";
function loadSort(): Record<string, SortMode> {
  try {
    const o = JSON.parse(localStorage.getItem(SORT_KEY) ?? "{}") as unknown;
    return o && typeof o === "object" ? (o as Record<string, SortMode>) : {};
  } catch { return {}; }
}
/** harness 专用（`?ovhover=` / `?ovoff=1`，由 `make_harness.py` 写进 localStorage）。生产里恒为空。 */
const HARNESS = (() => {
  try { return { hover: localStorage.getItem("codexbar_ov_hover"), open: localStorage.getItem("codexbar_ov_stripopen") === "1",
                 cmdk: localStorage.getItem("codexbar_ov_cmdk") === "1" }; }
  catch { return { hover: null, open: false, cmdk: false }; }
})();

const TAB_ORDER: PoolKey[] = POOL_PLATFORMS.map((p) => p.key);

export default function Overview(p: OverviewProps) {
  // ★ grok 的三个刷新入口（头部 / 卡片 / ⌘K）共用：结果出来就说一句（2026-10-23「点刷新没有 UI 反应」）
  const grokRefresh = (): void => {
    void p.refreshGrok().then((ok) => p.showToast(grokRefreshToast(ok, (p.grokLast?.() ?? p.grokSnap)?.accounts?.[0])));
  };
  const rootRef = useRef<HTMLDivElement>(null);
  const [cw, setCw] = useState(OV_BP_WIDE);
  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setCw(ovBand(el.clientWidth)));
    ro.observe(el);
    setCw(ovBand(el.clientWidth));
    return () => ro.disconnect();
  }, []);
  const layout = ovLayout(cw);
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => { const id = window.setInterval(() => setNowMs(Date.now()), 30_000); return () => window.clearInterval(id); }, []);
  const [sort, setSort] = useState<Record<string, SortMode>>(loadSort);
  // ★ 用户自己换排序 = 要立刻按新规则排：清掉「打开期间顺序不动」记下的顺序（`frozen` 在下面定义，调用时已存在）。
  const setSortFor = (k: string, m: SortMode) => { frozen.current = {}; setSortState(k, m); };
  const setSortState = (k: string, m: SortMode) => setSort((cur) => {
    const next = { ...cur, [k]: m };
    try { localStorage.setItem(SORT_KEY, JSON.stringify(next)); } catch { /* 无痕：本次生效 */ }
    return next;
  });
  const [stripOpen, setStripOpen] = useState<Record<string, boolean>>(() => (HARNESS.open ? { off: true, dead: true } : {}) as Record<string, boolean>);
  const toggleStrip = (k: string) => setStripOpen((c) => ({ ...c, [k]: !c[k] }));

  const prov = p.provider;
  // ── 打开期间顺序不动（用户 2026-10-23）：「其余 · 按可用度」在窗口开着时只更新数字、不换位置。
  //   重置（按新数字重排）的时机：切档、重新进总览（组件重挂）、窗口失焦 ≥ 60 s 后再回来（= 「下次打开」）。
  //   只管自动排序；「我拖的顺序」本来就固定。置顶区按置顶先后，是用户的操作，照常即时生效。
  const frozen = useRef<Record<string, string[]>>({});
  const frozenProv = useRef(prov);
  if (frozenProv.current !== prov) { frozenProv.current = prov; frozen.current = {}; }
  const [, setFreezeEpoch] = useState(0);
  useEffect(() => {
    let blurAt = 0;
    const un = getCurrentWindow().onFocusChanged(({ payload: focused }) => {
      if (!focused) { blurAt = Date.now(); return; }
      if (blurAt && Date.now() - blurAt >= 60_000) { frozen.current = {}; setFreezeEpoch((e) => e + 1); }
      blurAt = 0;
    });
    return () => { void un.then((f) => f()).catch(() => {}); };
  }, []);
  const freeze = <T,>(key: string, list: T[], id: (x: T) => string): T[] => {
    const out = stableOrder(frozen.current[key], list, id);
    frozen.current[key] = out.map(id);
    return out;
  };
  const codexOn = prov === "codex", agyOn = prov === "gemini";
  const { rot: codexRot } = useRotationDay("codex", codexOn);
  const { rot: agyRot } = useRotationDay("agy", agyOn);
  const day0 = dayStart(nowMs);
  const codexSw = useMemo(() => codexRot ? todaySwitches(codexRot.events, day0) : null, [codexRot, day0]);
  const agySw = useMemo(() => agyRot ? todaySwitches(agyRot.events, day0) : null, [agyRot, day0]);
  const codexLast = useMemo(() => lastUseByAcct(codexRot?.segments ?? [], day0), [codexRot, day0]);
  const agyLast = useMemo(() => lastUseByAcct(agyRot?.segments ?? [], day0), [agyRot, day0]);
  const liveOf = (k: "codex" | "agy" | "claude" | "grok") => p.live?.platforms?.[k] ?? null;
  const liveLine = (k: "codex" | "agy") => {
    const l = liveOf(k);
    return l && l.running ? { tps: l.tps, sessions: l.n_sessions, today: l.tokens_today } : null;
  };

  // ── 删除：先藏起来，撤销窗口（toast 3.2 s）过去才真删 ——「已删除 号X · 撤销」得真能撤销（P5 §5.3 / §7） ──
  const hidden = p.pendingDel;
  /** ★ 花钱动作的在途锁（四方评审 2026-10-22 codex#3 / Opus M1）：卡片 ⚡、⋯ 里的探针、⌘K、头部「探针 全池」、用卡
   *  都走这一处，**同步**占位（ref，不等 re-render），同号重复、全池与单号重叠一律挡掉。`billedOn` 只是给转圈用的镜像。
   *  键：`codex:<aid>` / `codex:*`（全池）/ `agy:<label>` / `agy:*` / `credit:<aid>`。 */
  const billed = useRef(new Set<string>());
  const [billedOn, setBilledOn] = useState<ReadonlySet<string>>(() => new Set());
  const billedBusy = (key: string) => {
    const [plat, who] = key.split(/:(.*)/s);
    if (billed.current.has(key)) return true;
    if (plat === "credit") return false;
    return who === "*" ? [...billed.current].some((k) => k.startsWith(`${plat}:`)) : billed.current.has(`${plat}:*`);
  };
  const withBilled = (key: string, go: () => Promise<unknown>) => {
    if (billedBusy(key)) { p.showToast("上一次还没回来 · 这次没发（计费）", TOAST_MS, { color: TOAST_WARN }); return; }
    billed.current.add(key); setBilledOn(new Set(billed.current));
    void go().finally(() => { billed.current.delete(key); setBilledOn(new Set(billed.current)); });
  };
  const [confirmDel, setConfirmDel] = useState<{ id: string; label: string; cli: string; go: () => void } | null>(null);
  /** 用卡成功的扫光（每张卡一个计数，+1 重播一次）。 */
  const [shine, setShine] = useState<Record<string, number>>({});

  // ── Codex 档 ──
  // ★ 停了自动轮换的号**留在主网格**，只多一枚「不轮换」标签 + 62% 透明度（P5 §4.1 号L）；状态（边框 / 环 / 排序）照原样算。
  const cState = (a: Account): OvState => ovState({
    inUse: a.aid === p.inUseNode, next: p.board?.next?.aid === a.aid, dead: a.status === "dead", off: false,
    coolSec: a.cooldownSec, tightest: a.windows.length ? a.tightest : null });
  const cMain = p.accounts.filter((a) => a.status !== "dead" && !hidden.has(`codex:${a.aid}`));
  const cDead = p.accounts.filter((a) => a.status === "dead" && !hidden.has(`codex:${a.aid}`));
  const savedCodex = p.state.card_order ?? p.state.pick_order ?? null;
  const codexMode: SortMode = sort.codex ?? (savedCodex?.length ? "custom" : "auto");
  const codexSorted = ovSort(cMain, (a) => ({ id: a.aid, state: cState(a), tightest: a.windows.length ? a.tightest : null, name: a.node }),
                             codexMode === "custom" ? savedCodex : null);
  const codexShown = p.preview ? applyOrder(codexSorted, p.preview, (a) => a.aid) : codexSorted;
  // 置顶区（P5 §1.2）：按置顶先后；「其余」按排序。拖拽只排「其余」。
  const codexPinned = codexShown.filter((a) => a.pinRank !== null).sort((x, y) => (x.pinRank ?? 0) - (y.pinRank ?? 0));
  const codexRest0 = codexShown.filter((a) => a.pinRank === null);
  const codexRest = codexMode === "auto" && !p.preview ? freeze("codex", codexRest0, (a) => a.aid) : codexRest0;
  const cBest = cMain.filter((a) => a.rotates && a.cooldownSec <= 0 && a.windows.length).reduce<number | null>((m, a) => (m == null || a.tightest > m ? a.tightest : m), null);

  // ── Gemini 档 ──
  const agyEnt = new Map([...(p.agyBoard?.queue ?? []), ...(p.agyBoard?.rest ?? [])].map((e) => [e.aid, e] as const));
  const gTight = (a: AgyPoolAccount) => agyTightest(agyShown(p.agyPool.snapshotOf(a, p.agySnap))?.quota)?.b.remaining_percent ?? null;
  const gState = (a: AgyPoolAccount): OvState => ovState({
    inUse: a.sub === p.agyPool.liveSub, next: p.agyBoard?.next?.aid === a.sub, dead: !!agyEnt.get(a.sub)?.dead,
    off: false, coolSec: (agyEnt.get(a.sub)?.cool_min ?? 0) * 60, tightest: gTight(a) });
  const gMain = p.agyPool.accounts.filter((a) => !hidden.has(`agy:${a.sub}`));
  const agyMode: SortMode = sort.gemini ?? (p.agyOrder?.length ? "custom" : "auto");
  const agySorted = ovSort(gMain, (a) => ({ id: a.sub, state: gState(a), tightest: gTight(a), name: a.label }),
                           agyMode === "custom" ? p.agyOrder : null);
  const agyShownList = p.preview ? applyOrder(agySorted, p.preview, (a) => a.sub) : agySorted;
  const gPin = (a: AgyPoolAccount) => { const e = agyEnt.get(a.sub); return e?.pin == null ? null : e.pin - 1; };
  const agyPinned = agyShownList.filter((a) => gPin(a) !== null).sort((x, y) => (gPin(x) ?? 0) - (gPin(y) ?? 0));
  const agyRest0 = agyShownList.filter((a) => gPin(a) === null);
  const agyRest = agyMode === "auto" && !p.preview ? freeze("gemini", agyRest0, (a) => a.sub) : agyRest0;
  // 失效号的读数是作废前的旧值，不能当「最好的余量」（2026-10-22 评审核实：gMain 只滤用户藏起来的）
  const gBest = gMain.filter((a) => !a.rotate_off && gState(a) !== "cool" && gState(a) !== "dead").reduce<number | null>((m, a) => { const v = gTight(a); return v == null ? m : m == null || v > m ? v : m; }, null);

  // ── Claude / Grok ──
  const cq = p.claudeQuota;
  const claudePct = cq?.fiveH == null && cq?.week == null ? null : Math.min(cq?.fiveH?.rem ?? 100, cq?.week?.rem ?? 100);
  const ga = p.grokSnap?.accounts?.[0] ?? null;
  const grokRem = ga && !ga.available ? grokLastGoodRemPct(ga) : grokRemPct(ga);

  // ── 平台档：号数 + 红点 ──
  const lowCodex = cMain.some((a) => a.windows.length > 0 && a.cooldownSec <= 0 && ovIsLow(a.tightest));
  const lowAgy = gMain.some((a) => gState(a) !== "dead" && ovIsLow(gTight(a)));
  const tabs: OvTab[] = TAB_ORDER.map((k): OvTab => ({ ...tabOf(k), note: POOL_PLATFORMS.find((x) => x.key === k)?.note }));
  function tabOf(k: PoolKey): OvTab {
    if (k === "codex") {
      const stranded = !!p.board && p.board.queue.length === 0;
      const warn = p.integration?.level === "warn";
      return { key: k, name: "Codex", count: cMain.length, color: p.colors.codex, alert: stranded || lowCodex || warn,
               alertWhy: stranded ? "池子见底" : warn ? "没接上轮换" : "有号额度低于 10%" };
    }
    if (k === "gemini") {
      const stranded = !!p.agyBoard && p.agyPool.accounts.length > 0 && p.agyBoard.queue.length === 0;
      return { key: k, name: "Gemini", count: Math.max(1, gMain.length), color: p.colors.gemini,
               alert: stranded || lowAgy || p.agyPool.drifted,
               alertWhy: stranded ? "池子见底" : p.agyPool.drifted ? "钥匙串被别的 agy 写回" : "有号额度低于 10%" };
    }
    if (k === "claude") return { key: k, name: "Claude", count: 1, color: p.colors.claude, alert: ovIsLow(claudePct), alertWhy: "额度低于 10%" };
    return { key: k, name: "Grok", count: 1, color: p.colors.grok, alert: ovIsLow(grokRem), alertWhy: "周额度低于 10%" };
  }

  // ── 头部动作（每档只放这一档真有的） ──
  const codexFresh = freshnessLine(p.lastRefreshAt, p.freshness);
  const agyFresh = p.agyPool.accounts.length ? freshnessLine(agyPoolFreshness(p.agyPool.accounts).lastAt, agyPoolFreshness(p.agyPool.accounts)) : "";
  const addHint = POOL_PLATFORMS.find((x) => x.key === prov)?.addHint ?? "";
  let actions: ReactNode;
  if (codexOn) {
    actions = (<>
      <RefreshBtn labels={layout.labels} busy={p.loadingAction === "refresh-all"} title={`刷新全池（零消耗）· ${codexFresh}`}
                  onClick={() => void p.run("refresh-all", ["refresh-all", "--notify"], `已刷新全池 · ${p.accounts.length} 个号`)} />
      <ProbeHead loading={billedOn.has("codex:*")} onFire={() => cx.probeAll()}
                 hint={`对 ${p.accounts.length} 个号各发一次真实补全(问 hi 要求答 ok),证明"真的还能干活"。⚠️ 计费：消耗周额度(实测单次 <1%),约 ${p.accounts.length * 7}s`} />
      <ToggleGroup>
        <DawnChip key="codex" t={p.t} kind="codex" active={codexOn} look="switch" showLabel={layout.labels} />
        <GroupDivider />
        <AutoSwitchItem on={p.autoSwitch} labels={layout.labels} onToggle={p.toggleAutoSwitch}
                        title={p.autoSwitch ? "自动切号开着：直连号额度见底时自动换一个" : "自动切号已关"} />
      </ToggleGroup>
      <HeadMore items={[
        { key: "health", label: "检查各号 token（零消耗）", onClick: () => void p.run("health", ["health"], "已检查各号 token") },
        { key: "add", label: "加号…", onClick: () => p.showToast(addHint) },
        { key: "fresh", label: codexFresh, info: true },
      ]} />
    </>);
  } else if (agyOn) {
    actions = (<>
      <RefreshBtn labels={layout.labels} busy={p.agyPool.busy} title={`刷新全池（agy-rotate quota，零消耗）${agyFresh ? ` · ${agyFresh}` : ""}`}
                  onClick={() => { void p.agyPool.refresh().then((ok) => p.showToast(ok === null ? "Gemini 正在刷新" : ok ? `已刷新 Gemini · ${p.agyPool.accounts.length} 个号` : "✗ Gemini 刷新失败")); }} />
      <ProbeHead loading={billedOn.has("agy:*")} onFire={() => gx.probeAll()}
                 hint={`对 ${p.agyPool.accounts.length} 个号各起一次 agy 真跑一句（问 hi 要求答 ok）。⚠️ 计费：花的是 agy 自己的额度（实测单次约 15k token），每号约 30s`} />
      <ToggleGroup>
        <DawnChip key="agy" t={p.t} kind="agy" active={agyOn} look="switch" showLabel={layout.labels} />
        <GroupDivider />
        <AutoSwitchItem on={p.agyPool.autoOn} labels={layout.labels} onToggle={() => { void p.agyPool.setAuto(!(p.agyPool.autoOn ?? true)).then((ok) => {
                          if (!ok) p.showToast("✗ 自动切号没改成，已拨回原位", TOAST_MS, { color: TOAST_WARN });
                        }); }}
                        title={p.agyPool.autoOn
                          ? "自动切号开着：下次启动 agy 时，额度低于阈值会自动换一个号（由 `bin/agy` wrapper 在拉起真身前决定）"
                          : "自动切号已关：wrapper 不再替你换号，`agy` 一律用当前登录的那个"} />
      </ToggleGroup>
      <HeadMore items={[
        { key: "health", label: "检查各号 token（零消耗）", onClick: () => p.agyPool.health() },
        { key: "add", label: "加号…", onClick: () => p.showToast(addHint) },
        ...(agyFresh ? [{ key: "fresh", label: agyFresh, info: true }] : []),
      ]} />
    </>);
  } else if (prov === "claude") {
    actions = (<>
      <RefreshBtn labels={layout.labels} busy={false} text="刷新" title="重读一次状态栏转写的额度（读本机文件，零消耗）" onClick={() => { void p.refreshClaude(); }} />
      <HeadMore items={[
        { key: "why", label: "本机只有 1 个 Claude 号：不切号、不探针", info: true,
          title: "仓库没有 Claude 账号池后端（切号要写 Claude Code 凭证，已定不碰）" },
        { key: "add", label: "加号…", onClick: () => p.showToast(addHint) },
      ]} />
    </>);
  } else {
    actions = (<>
      <RefreshBtn labels={layout.labels} busy={p.grokBusy} text="刷新" title="重新取一次 grok 周额度（一次 GET，不计费）" onClick={grokRefresh} />
      <HeadMore items={[{ key: "why", label: "grok 单号：只有周额度，不切号", info: true }]} />
    </>);
  }

  // ── 顶部三栏 ──
  const pending = (pc: string, err: string | null) => (
    <HeroShell pc={pc} layout={layout}>
      <div data-runway-err={err ? "" : undefined} style={{ gridColumn: "1 / -1", height: 78, display: "flex", alignItems: "center", gap: 8,
                                                            fontFamily: MONO, fontSize: 11.5, color: err ? "var(--ovWarnTx)" : "var(--tx3)" }}>
        {err ? <><b>⚠️ 续航数据没读到</b><span style={{ color: "var(--tx2)", overflow: "hidden", textOverflow: "ellipsis" }}>{err}</span></> : "正在读轮换板…"}
      </div>
    </HeroShell>
  );
  const errLine = (err: string | null, has: boolean) => err && has ? (
    <div data-runway-err="" style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 11, color: "var(--ovWarnTx)",
                                     flexShrink: 0, overflow: "hidden" }}>
      <b>⚠️ 续航数据没读到</b><span style={{ color: "var(--tx2)", overflow: "hidden", textOverflow: "ellipsis" }}>上面这条是上次读到的 · {err}</span>
    </div>
  ) : null;
  const hero = codexOn
    ? (p.board ? <PoolHero source="codex" pc={p.colors.codex} board={p.board} layout={layout} privacy={p.privacy} live={liveOf("codex")} liveErr={!!p.liveErr}
                           switches={codexSw} onLogs={p.onLogs} nowMs={nowMs} /> : pending(p.colors.codex, p.boardErr))
    : agyOn
      ? (p.agyBoard ? <PoolHero source="agy" pc={p.colors.gemini} board={p.agyBoard} layout={layout} privacy={p.privacy} live={liveOf("agy")} liveErr={!!p.liveErr}
                                switches={agySw} onLogs={p.onLogs} nowMs={nowMs} /> : pending(p.colors.gemini, p.agyBoardErr))
      : prov === "claude"
        ? <ClaudeHero pc={p.colors.claude} quota={p.claudeQuota} layout={layout} live={liveOf("claude")} liveErr={!!p.liveErr} onLogs={p.onLogs} nowMs={nowMs} />
        : <GrokHero pc={p.colors.grok} snap={p.grokSnap} layout={layout} err={p.grokErr} />;

  // ── 账号区 ──
  const hoverIdx = HARNESS.hover;
  const isHov = (id: string, i: number) => hoverIdx != null && (hoverIdx === id || hoverIdx === String(i));
  const bump = (id: string) => setShine((m) => ({ ...m, [id]: (m[id] ?? 0) + 1 }));

  // Codex 的写操作 —— 每条 toast 的文案 / 颜色 / 撤销照 P5 §7 那张表；撤销只撤自己那一步。
  const codexPinOrder = p.accounts.filter((a) => a.pinRank !== null).sort((x, y) => (x.pinRank ?? 0) - (y.pinRank ?? 0)).map((a) => a.node);
  // 撤销作用在**撤销那一刻**的顺序上（`undoPinStep`），所以要读最新的，不是闭包里那份
  const codexPinNow = useRef(codexPinOrder); codexPinNow.current = codexPinOrder;
  const cx = {
    pin: (a: Account) => {
      const was = codexPinOrder, at = a.pinRank === null ? null : was.indexOf(a.node);
      const undo = () => { const next = undoPinStep(codexPinNow.current, a.node, at);
        void p.run(`pin-${a.aid}`, next.length ? ["pin", ...next] : ["pin", "--clear"], "撤销置顶", { quiet: true }); };
      if (a.pinRank === null) void p.run(`pin-${a.aid}`, ["pin", "--add", a.node], `置顶 ${a.node}`,
        { done: `已置顶 ${a.node} · 第 ${was.length + 1} 个用`, color: TOAST_OK, undo });
      else void p.run(`pin-${a.aid}`, ["pin", "--remove", a.node], `取消置顶 ${a.node}`, { done: `已取消置顶 ${a.node}`, color: TOAST_MUTED, undo });
    },
    rotate: (a: Account, on: boolean) => void p.run(`rotate-${a.aid}`, ["rotate", a.aid, on ? "--on" : "--off"], on ? `恢复轮换 ${a.node}` : `停轮换 ${a.node}`,
      { done: on ? `${a.node} 回到自动轮换` : `${a.node} 已停轮换 · codex-rotate rotate ${a.node} --off`, color: on ? TOAST_OK : TOAST_WARN,
        undo: () => void p.run(`rotate-${a.aid}`, ["rotate", a.aid, on ? "--off" : "--on"], "撤销", { quiet: true }) }),
    switch: (a: Account) => void p.run(`switch-${a.aid}`, ["switch", a.node], `切到 ${a.node}`, { done: `已切到 ${a.node}`, color: TOAST_OK }),
    probe: (a: Account) => withBilled(`codex:${a.aid}`, () =>
      p.run(`probe-${a.aid}`, ["probe", a.node], `探针已发出 · ${a.node} · 计费`, { resultToast: true, ms: 8000, color: TOAST_WARN })),
    probeAll: () => withBilled("codex:*", () => p.run("probe-all", ["probe", "--all"], "探针 全池")),
    credit: (a: Account, cardId: string) => withBilled(`credit:${a.aid}`, () =>
      p.run(`usecredit-${a.aid}`, ["use-credit", a.node, "--card", cardId], `用重置卡 ${a.node}`,
        { resultToast: true, ms: 6000, color: TOAST_WARN }).then((ok) => { if (ok) bump(a.aid); })),
    // 到期才发的命令用**确认那一刻**的稳定身份（aid）：撤销窗口里改名 / 名字被复用都不会删错号（评审 codex#5）
    // ★ auth.json 里那个号 CLI 拒删（`cmd_remove`）⇒ 同 Gemini 先说清楚，不弹确认、不先假删 3.2 s 再弹回（阶段 A 评审）
    remove: (a: Account) => a.aid === p.currentNode
      ? p.showToast(`${a.node} 正在 auth.json 里（直连）· 先切到别的号再删`, TOAST_MS, { color: TOAST_WARN })
      : setConfirmDel({ id: a.aid, label: a.node, cli: "codex-rotate login",
          go: () => p.deferDelete(`codex:${a.aid}`, a.node, () => p.run(`remove-${a.aid}`, ["remove", a.aid], `删除 ${a.node}`, { quiet: true })) }),
  };
  // Gemini 的写操作（`agy-rotate`；切号只对**下一次启动的** agy 生效）
  const agyPinOrder = [...p.agyPool.accounts].filter((a) => gPin(a) !== null).sort((x, y) => (gPin(x) ?? 0) - (gPin(y) ?? 0)).map((a) => a.label);
  const agyPinNow = useRef(agyPinOrder); agyPinNow.current = agyPinOrder;
  /** Gemini 的撤销本身失败也要说（codex 那边 `p.run` 会弹 ✗；评审 Opus L8）。 */
  const agyUndo = (go: Promise<boolean>, label: string) => void go.then((ok) => { if (!ok) p.showToast(`✗ 撤销失败：${label}`); });
  const gx = {
    pin: (a: AgyPoolAccount) => {
      const was = agyPinOrder, pinned = gPin(a) !== null, at = pinned ? was.indexOf(a.label) : null;
      void p.agyPool.togglePin(a.label).then((ok) => p.showToast(
        !ok ? `✗ 置顶失败：${a.label}` : pinned ? `已取消置顶 ${a.label}` : `已置顶 ${a.label} · 第 ${was.length + 1} 个用`, TOAST_MS,
        ok ? { color: pinned ? TOAST_MUTED : TOAST_OK,
               undo: () => agyUndo(p.agyPool.setPins(undoPinStep(agyPinNow.current, a.label, at)), a.label) } : undefined));
    },
    rotate: (a: AgyPoolAccount, on: boolean) => void p.agyPool.setRotate(a.label, on).then((ok) => p.showToast(
      !ok ? `✗ 失败：${a.label}` : on ? `${a.label} 回到自动轮换` : `${a.label} 已停轮换 · agy-rotate rotate ${a.label} --off`, TOAST_MS,
      ok ? { color: on ? TOAST_OK : TOAST_WARN, undo: () => agyUndo(p.agyPool.setRotate(a.label, !on), a.label) } : undefined)),
    switch: (a: AgyPoolAccount) => void p.agyPool.switchTo(a.label).then((ok) =>
      p.showToast(ok ? `已换到 ${a.label} · 下一次启动 agy 生效` : `✗ 换号失败：${a.label}`)),
    probe: (a: AgyPoolAccount) => withBilled(`agy:${a.label}`, () => {
      const id = p.showToast(`探针已发出 · ${a.label} · 计费`, 120_000, { color: TOAST_WARN });
      return p.agyPool.probe(a.label).then((r) => p.showToast(r ? agyProbeToast(r) : `✗ 探针没回来：${a.label}`, 8000, { replace: id }));
    }),
    probeAll: () => withBilled("agy:*", () => {
      p.showToast("探针 全池…");
      return p.agyPool.probe().then((r) => { if (r) p.showToast(agyProbeToast(r), 8000); });
    }),
    // ★ 当前登录的号 agy-rotate 拒删（`agy-rotate:684`）⇒ 先说清楚，不弹一个注定失败的确认（评审 Opus M3）
    remove: (a: AgyPoolAccount) => a.sub === p.agyPool.liveSub
      ? p.showToast(`${a.label} 是当前登录的号 · 先切到别的号再删`, TOAST_MS, { color: TOAST_WARN })
      : setConfirmDel({ id: a.sub, label: a.label, cli: "agy-rotate login",
          go: () => p.deferDelete(`agy:${a.sub}`, a.label, () => p.agyPool.removeIt(a.sub).then((ok) => {
            if (!ok) p.showToast(`✗ 删除失败，已放回 ${a.label}${p.agyPool.err ? ` · ${p.agyPool.err}` : ""}`);
            return ok;
          })) }),
  };

  const codexCard = (a: Account, i: number, inGrid: boolean) => (
    <AccountCard key={a.aid} a={a} t={p.t} state={cState(a)} isDirect={a.aid === p.currentNode} borrowOff={!!p.state.borrow_off}
      bestPct={cBest} privacy={p.privacy} hov={isHov(a.aid, i)} live={liveLine("codex")}
      lastUse={codexLast.get(a.node) ?? null} rotLoaded={!!codexRot}
      probing={billedOn.has(`codex:${a.aid}`) || billedOn.has("codex:*")} usingCredit={billedOn.has(`credit:${a.aid}`)} shine={shine[a.aid]}
      drag={inGrid && a.pinRank === null ? p.makeDrag(a.aid, codexRest.map((x) => x.aid),
        "按住拖动排序 —— **只影响卡片摆放**，不影响轮换。要优先用某个号，点名字旁的图钉「置顶」。",
        (next) => {
          setSortFor("codex", "custom");
          const byAid = new Map(cMain.map((x) => [x.aid, x.node]));
          // 置顶号不在拖拽里（它们的顺序 = 置顶先后），接在后面保住它们在摆放顺序里的位置
          return p.run("priority", ["priority", "--set", ...[...next, ...codexPinned.map((x) => x.aid)].map((id) => byAid.get(id) as string)], "已更新卡片顺序",
                       { done: "已更新卡片顺序" });
        }) : undefined}
      onSwitch={() => cx.switch(a)} onProbe={() => cx.probe(a)} onShowDetail={() => openSheet("codex", a.aid)}
      onRemove={() => cx.remove(a)} onUseCredit={(id) => cx.credit(a, id)}
      onToggleRotate={(on) => cx.rotate(a, on)} onTogglePin={() => cx.pin(a)} />
  );
  const agyCard = (a: AgyPoolAccount, i: number, inGrid: boolean) => {
    const e = agyEnt.get(a.sub);
    return (
      <AgyCard key={a.sub} t={p.t} color={p.colors.gemini} aid={a.sub} snap={p.agyPool.snapshotOf(a, p.agySnap)} state={gState(a)} hov={isHov(a.sub, i)}
        action={agyAction(a.quota_err_reason, a.quota_err_url)} plan={a.plan} label={a.label} email={a.email ?? undefined}
        bestPct={gBest} privacy={p.privacy} live={liveLine("agy")} lastUse={agyLast.get(a.label) ?? null} rotLoaded={!!agyRot}
        coolMin={e?.cool_min} pinRank={gPin(a)} rotates={!a.rotate_off}
        disabled={p.platOff.agy} busy={p.agyPool.busy} err={p.agyPool.err}
        drag={inGrid && gPin(a) === null ? p.makeDrag(a.sub, agyRest.map((x) => x.sub), "按住拖动调整摆放顺序。只影响显示，不影响切号策略。",
                                  (next) => { setSortFor("gemini", "custom"); p.setAgyOrder([...next, ...agyPinned.map((x) => x.sub)]); }) : undefined}
        onSwitch={() => gx.switch(a)} switching={p.agyPool.switching === a.label}
        onProbe={() => gx.probe(a)} probing={billedOn.has(`agy:${a.label}`) || billedOn.has("agy:*")}
        onRefresh={p.agyPool.refresh} onTogglePin={() => gx.pin(a)}
        onToggleRotate={(on) => gx.rotate(a, on)} onRemove={() => gx.remove(a)} onShowDetail={() => openSheet("agy", a.sub)} />
    );
  };

  // ── 详情 Sheet（P5 §5.2）：开着时数据每次渲染现取；关的时候留 400 ms 播完收起 ──
  const [sheet, setSheet] = useState<{ kind: "codex" | "agy"; id: string } | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  /** null = 还在读；"fail" = 读不到（「读不到」不能永远停在「正在读…」）。 */
  const [tech, setTech] = useState<AccountDetail | null | "fail">(null);
  const sheetTok = useRef(0);
  function openSheet(kind: "codex" | "agy", id: string) {
    const tok = ++sheetTok.current;
    setSheet({ kind, id }); setSheetOpen(true); setTech(null);
    if (kind === "codex") void p.loadDetail(id).then((d) => { if (sheetTok.current === tok) setTech(d ?? "fail"); });
  }
  const closeSheet = useCallback(() => {
    setSheetOpen(false);
    const tok = sheetTok.current;
    window.setTimeout(() => { if (sheetTok.current === tok) setSheet(null); }, 400);
  }, []);
  const STATE_TEXT: Record<string, string> = { inuse: "在用", next: "下一个", cool: "冷却中", unprobed: "未探测", low: "额度低", dead: "失效", readonly: "只读" };
  const pctTxt = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v)}%`);
  let sheetEl: ReactNode = null;
  if (sheet?.kind === "codex") {
    const a = p.accounts.find((x) => x.aid === sheet.id);
    if (a) {
      const five = a.windows.find((w) => winSlot(w.mins) === "5h"), week = a.windows.find((w) => winSlot(w.mins) === "w");
      const rows: SheetRow[] = [
        { k: "状态", v: !a.rotates && a.status !== "dead" ? "不轮换" : STATE_TEXT[cState(a)] ?? "可用", mono: false },
        { k: "5h / 周", v: `${pctTxt(five?.pct)} · ${pctTxt(week?.pct)}` },
        { k: "订阅", v: `订阅到期 ${a.exp}${a.expStale ? " *" : ""}`, mono: false,
          title: a.expStale ? "OpenAI 上次复核订阅早于这个日期，「已过期」是拿陈旧快照下的结论" : undefined },
        { k: "置顶", v: a.pinRank !== null ? `第 ${a.pinRank + 1} 个` : "—", mono: false },
        { k: "轮换", v: a.rotates ? "参与中" : "已停", color: a.rotates ? undefined : "var(--ovAmb)", mono: false },
        { k: "重置卡", v: `×${a.cards > 0 ? a.cards : 0}`, color: "var(--ovNum)" },
        ...(a.aid === p.currentNode ? [{ k: "直连", v: "auth.json 里是它", mono: false } as SheetRow] : []),
      ];
      sheetEl = (
        <DetailSheet open={sheetOpen} title={`${a.node} · 详情`} email={maskId(a.email, p.privacy) || undefined} rows={rows} name={a.node}
          onRename={(next) => p.run(`rename-${a.aid}`, ["rename", a.aid, next], `改名 ${a.node}`, { done: `已改名 ${a.node} → ${next}` })}
          extra={tech && tech !== "fail" ? <TechRows detail={tech} privacy={p.privacy} />
            : <span data-account-tech-state={tech ?? "loading"} style={{ fontSize: 11, color: tech === "fail" ? "var(--ovWarnTx)" : "var(--tx3)" }}>
                {tech === "fail" ? "技术信息读不到（read_account_detail 失败）—— 关掉重开再试一次" : "正在读技术信息…"}</span>}
          onClose={closeSheet} />
      );
    }
  } else if (sheet?.kind === "agy") {
    const a = p.agyPool.accounts.find((x) => x.sub === sheet.id);
    if (a) {
      const q = agyWinRows(agyShown(p.agyPool.snapshotOf(a, p.agySnap))?.quota);
      const rows: SheetRow[] = [
        { k: "状态", v: a.rotate_off ? "不轮换" : STATE_TEXT[gState(a)] ?? "可用", mono: false },
        { k: "5h / 周", v: `${pctTxt(q.find((r) => r.label === "5h")?.remaining)} · ${pctTxt(q.find((r) => r.label === "周")?.remaining)}` },
        { k: "订阅", v: a.plan === "ultra" ? "Google AI Ultra" : a.plan === "pro" ? "Google AI Pro" : "—", mono: false },
        { k: "置顶", v: gPin(a) !== null ? `第 ${(gPin(a) ?? 0) + 1} 个` : "—", mono: false },
        { k: "轮换", v: a.rotate_off ? "已停" : "参与中", color: a.rotate_off ? "var(--ovAmb)" : undefined, mono: false },
        { k: "重置卡", v: "—" },
      ];
      sheetEl = (
        <DetailSheet open={sheetOpen} title={`${a.label} · 详情`} email={a.email ? maskId(a.email, p.privacy) : undefined} rows={rows} name={a.label}
          onRename={(next) => p.agyPool.renameTo(a.label, next).then((ok) => { p.showToast(ok ? `已改名 ${a.label} → ${next}` : `✗ 改名失败：${a.label}`, undefined, ok ? undefined : { color: TOAST_BAD }); return ok; })}
          foot={<span role="button" tabIndex={0} data-sheet-usage="" onClick={() => { closeSheet(); p.onOpenUsage("agy"); }}
                      style={{ fontSize: 12, color: "var(--ovNum)", cursor: "pointer" }}>查看用量 →</span>}
          onClose={closeSheet} />
      );
    }
  }

  // ── ⌘K（P5 §8）：只在总览页上挂监听 ──
  const [kOpen, setKOpen] = useState(() => HARNESS.cmdk);
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (isCmdK(e) && !modalOpen("cmdk")) { e.preventDefault(); setKOpen((o) => !o); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  const platName = prov === "codex" ? "Codex" : prov === "gemini" ? "Gemini" : prov === "claude" ? "Claude" : "Grok";
  const cmds: CmdItem[] = [
    ...(codexOn ? codexShown.filter((a) => a.aid !== p.inUseNode && a.aid !== p.currentNode).slice(0, 3)
      .map((a): CmdItem => ({ key: `sw-${a.aid}`, icon: "⇄", color: "var(--ovNum)", label: `切到 ${a.node}`, hint: platName, run: () => cx.switch(a) })) : []),
    ...(agyOn ? agyShownList.filter((a) => a.sub !== p.agyPool.liveSub).slice(0, 3)
      .map((a): CmdItem => ({ key: `sw-${a.sub}`, icon: "⇄", color: "var(--ovNum)", label: `切到 ${a.label}`, hint: platName, run: () => gx.switch(a) })) : []),
    { key: "refresh", icon: "↻", color: "var(--tx3)", label: codexOn || agyOn ? "刷新全池" : "刷新", hint: "免费",
      run: () => {
        if (codexOn) void p.run("refresh-all", ["refresh-all", "--notify"], "刷新全池", { done: "已刷新全池 · 免费" });
        else if (agyOn) { void p.agyPool.refresh().then((ok) => p.showToast(ok === null ? "Gemini 正在刷新" : ok ? "已刷新全池 · 免费" : "✗ Gemini 刷新失败")); }
        else if (prov === "claude") void p.refreshClaude().then((ok) => p.showToast(ok === null ? "Claude 正在重读" : ok ? "已重读 Claude 额度 · 本机" : "✗ Claude 额度读不到"));
        else grokRefresh();
      } },
    ...(() => {
      const nc = codexOn && p.board?.next ? p.accounts.find((a) => a.aid === p.board?.next?.aid) : undefined;
      const ng = agyOn && p.agyBoard?.next ? p.agyPool.accounts.find((a) => a.sub === p.agyBoard?.next?.aid) : undefined;
      return nc ? [{ key: "probe", icon: "⚡", color: "var(--ovAmb)", label: `探针 · 下一个号（${nc.node}）`, hint: "计费", run: () => cx.probe(nc) }]
        : ng ? [{ key: "probe", icon: "⚡", color: "var(--ovAmb)", label: `探针 · 下一个号（${ng.label}）`, hint: "计费", run: () => gx.probe(ng) }] : [];
    })(),
    { key: "traffic", icon: "◔", color: "var(--tx3)", label: "打开 Token 消耗", hint: "", run: () => p.onNav("traffic") },
    { key: "relay", icon: "⇢", color: "var(--tx3)", label: "打开 中转站", hint: "", run: () => p.onNav("relay") },
    { key: "settings", icon: "⚙", color: "var(--tx3)", label: "打开 设置", hint: "⌘,", run: () => p.onNav("settings") },
  ];

  // ── 网格：置顶区 + 其余（P5 §1.2，只在有置顶时出两个标题）；换位置走 FLIP ──
  const gridRef = useRef<HTMLDivElement>(null);
  let title: ReactNode, grid: ReactNode, below: ReactNode = null, flipSig = prov;
  const grid0 = (children: ReactNode) => (
    <div ref={gridRef} data-cards-grid="" data-ov-cols={layout.cols}
         style={{ position: "relative", display: "grid", gridTemplateColumns: `repeat(${layout.cols}, minmax(0, 1fr))`, gap: 12, alignContent: "start" }}>
      {children}
    </div>
  );
  const sections = <T,>(pinned: T[], rest: T[], card: (x: T, i: number) => ReactNode) => pinned.length ? (<>
    <div className="ov-sec" data-flip={`§pin:${prov}`} data-ov-sec="pin" style={{ color: "var(--ovNum)" }}>置顶 · 先置顶先用</div>
    {pinned.map((x, i) => card(x, i))}
    <div className="ov-sec ov-sec-rest" data-flip={`§rest:${prov}`} data-ov-sec="rest" style={{ color: "var(--tx3)" }}>其余 · 按可用度</div>
    {rest.map((x, i) => card(x, pinned.length + i))}
  </>) : rest.map((x, i) => card(x, i));
  if (codexOn) {
    const c = ovCounts([...cMain.map(cState), ...cDead.map(() => "dead" as const)]);
    const offN = cMain.filter((a) => !a.rotates).length;
    // 快到期（重置卡 / 订阅）：与菜单栏通知条同一套判据；失效号不算（卡与订阅对它已无意义）
    // 订阅到期提醒天数跟设置页走（2026-10-22 评审：原来写死 7，设置页那一项只对系统通知生效）
    const warns = expiryWarnings(p.accounts.filter((a) => a.status !== "dead"), nowMs, CARD_WARN_DAYS, getSettings().subExpiryWarnDays ?? SUB_WARN_DAYS);
    title = <AccountsTitle name="Codex" c={c} offN={offN} mode={codexMode} canCustom={!!savedCodex?.length} onMode={(m) => setSortFor("codex", m)}
                           warn={<ExpiryStack items={warns} />} />;
    grid = grid0(sections(codexPinned, codexRest, (a, i) => codexCard(a, i, true)));
    flipSig = [...codexPinned, ...codexRest].map((a) => a.aid).join() + `|${codexPinned.length}`;
    below = cDead.length > 0 ? (
      <OvStrip kind="dead" count={cDead.length} names={cDead.map((a) => a.node)} cols={layout.cols}
               note="凭证失效 · 重登用 codex-rotate login" open={!!stripOpen.dead} onToggle={() => toggleStrip("dead")}>
        {cDead.map((a, i) => codexCard(a, 200 + i, false))}
      </OvStrip>
    ) : null;
  } else if (agyOn) {
    const c = ovCounts(gMain.map(gState));
    title = <AccountsTitle name="Gemini" c={c} offN={gMain.filter((a) => !!a.rotate_off).length} mode={agyMode} canCustom={!!p.agyOrder?.length}
                           onMode={(m) => setSortFor("gemini", m)} />;
    // ★ 「还没建池」看的是池本身，不是筛过的 gMain —— 全部号都在撤销窗口里（先隐藏、未真删）时不能退回只读卡。
    grid = grid0(p.agyPool.accounts.length > 0
      ? sections(agyPinned, agyRest, (a, i) => agyCard(a, i, true))
      : <AgyCard t={p.t} color={p.colors.gemini} snap={p.agySnap} state="readonly" privacy={p.privacy} disabled={p.platOff.agy} busy={p.agyBusy} err={p.agyErr}
                 onRefresh={p.refreshAgy} hov={isHov("agy", 0)} />);
    flipSig = [...agyPinned, ...agyRest].map((a) => a.sub).join() + `|${agyPinned.length}`;
    below = p.agyPool.drifted ? (
      <div data-agy-drift="" style={{ fontSize: 11.5, fontFamily: MONO, color: "var(--ovWarnTx)", overflow: "hidden", textOverflow: "ellipsis" }}
           title="钥匙串是一个槽，本机常有多个长期存活的 agy 进程，各自在 token 到期时把自己的身份写回去。">
        ⚠️ 当前登录的号与你上次切换的不一致 —— 某个仍在跑的 agy 把凭证写回了钥匙串。要让切换生效：先退出那些旧的 agy 会话，再切换，然后开新的 agy。
      </div>
    ) : null;
  } else if (prov === "claude") {
    title = <AccountsTitle name="Claude" c={ovCounts([claudePct == null ? "unprobed" : "inuse"])} />;
    grid = grid0(<ClaudeCard t={p.t} color={p.colors.claude} quota={p.claudeQuota} err={p.claudeErr} live={liveOf("claude")} onRefresh={p.refreshClaude}
                             nowMs={nowMs} hov={isHov("claude-local", 0)} />);
  } else {
    const ga = p.grokSnap?.accounts?.[0] ?? null;
    const gRem = ga ? (ga.available ? grokRemPct(ga) : grokLastGoodRemPct(ga)) : null;
    title = <AccountsTitle name="Grok" c={ovCounts([gRem == null ? "unprobed" : ovIsLow(gRem) ? "low" : "inuse"])} />;
    grid = grid0(<GrokCard t={p.t} color={p.colors.grok} snap={p.grokSnap} privacy={p.privacy} busy={p.grokBusy} err={p.grokErr} disabled={p.platOff.grok}
                           hov={isHov("grok", 0)} onOpen={() => p.onOpenUsage("grok")} onRefresh={grokRefresh} />);
  }
  useFlip(gridRef, flipSig, p.preview);

  return (
    <div ref={rootRef} className="ov-root" data-ov-layout={layout.cols}
         style={{ ...ovVars(p.isDark), flex: 1, minHeight: 0, minWidth: 0, display: "flex", flexDirection: "column", gap: 12 } as CSSProperties}>
      <div data-overview-head="" style={{ display: "flex", alignItems: "center", gap: 8, height: 32, flexShrink: 0, minWidth: 0 }}>
        <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-.01em", flexShrink: 0, marginRight: 2 }}>总览</span>
        <span className="ov-kchip" role="button" tabIndex={0} data-ov-kchip="" title="快速操作" onClick={() => { if (!modalOpen("cmdk")) setKOpen(true); }}
              onKeyDown={(e) => { if (e.key === "Enter" && !modalOpen("cmdk")) setKOpen(true); }}>⌘K</span>
        <OvTabs tabs={tabs} cur={prov} onPick={p.setProvider} isDark={p.isDark} layout={layout} />
        <span style={{ flex: 1, minWidth: 0 }} />
        {actions}
      </div>
      <div key={prov} className="ov-pg" data-ov-page={prov}
           style={{ display: "flex", flexDirection: "column", gap: 12, flex: 1, minHeight: 0 }}>
        {codexOn && <IntegrationBanner t={p.t} integration={p.integration} onConnect={p.onConnect} />}
        {hero}
        {codexOn && errLine(p.boardErr, !!p.board)}
        {agyOn && errLine(p.agyBoardErr, !!p.agyBoard)}
        {title}
        <div data-ov-scroll="" style={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", display: "flex",
                                         flexDirection: "column", gap: 12, paddingBottom: 4 }}>
          {grid}
          {below}
        </div>
      </div>
      {sheetEl}
      {confirmDel && (
        <ConfirmDelete title={`删除 ${confirmDel.label}？`}
                       body={<>会删掉本机保存的 token，用 <code style={{ fontFamily: MONO }}>{confirmDel.cli}</code> 可以重新加回来。</>}
                       onCancel={() => setConfirmDel(null)}
                       onConfirm={() => { const c = confirmDel; setConfirmDel(null); c.go(); }} />
      )}
      {kOpen && <CmdK items={cmds} onClose={() => setKOpen(false)} />}
    </div>
  );
}

const Chev = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/** 账号区标题行：`Codex 账号 · 5 可用 · 1 冷却中 · 1 需处理 · 3 已停用`，右侧排序。0 的项不写。 */
function AccountsTitle({ name, c, offN = 0, mode, canCustom, onMode, warn }: {
  name: string; c?: ReturnType<typeof ovCounts>; offN?: number; mode?: SortMode; canCustom?: boolean; onMode?: (m: SortMode) => void;
  /** 计数后面的「快到期」堆叠警告（只有 Codex 有）。 */
  warn?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", down);
    return () => document.removeEventListener("mousedown", down);
  }, [open]);
  const item = (n: number, label: string, color: string) => n > 0 && (
    <span key={label} data-ov-count={label}><b style={{ color }}>{n}</b> {label}</span>
  );
  return (
    <div data-ov-acct-title="" style={{ display: "flex", alignItems: "center", gap: 14, height: 20, minWidth: 0, flexShrink: 0 }}>
      <b style={{ fontSize: 14 }}>{name} 账号</b>
      <span style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 11.5, color: "var(--tx2)", overflow: "hidden", minWidth: 0 }}>
        {c && (<>
          {item(c.ok, "可用", "var(--tx)")}
          {item(c.cool, "冷却中", "var(--ovWarnTx)")}
          {item(c.low, "额度低", "var(--badTx)")}
          {item(c.bad, "需处理", "var(--badTx)")}
          {item(offN, "不轮换", "var(--tx3)")}
        </>)}
      </span>
      {warn}
      {onMode && (
        <span ref={box} style={{ marginLeft: "auto", position: "relative", display: "inline-flex", flexShrink: 0 }}>
          <span data-ov-sort={mode} role="button" tabIndex={0} onClick={() => setOpen((o) => !o)}
                onKeyDown={(e) => { if (e.key === "Enter") setOpen((o) => !o); }}
                title="排序只影响卡片摆放，不影响轮换（轮换看置顶与容量）"
                style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11.5, color: "var(--tx2)", cursor: "pointer" }}>
            排序：{mode === "custom" ? "我拖的顺序" : "在用 → 可用度 → 需处理"}<Chev />
          </span>
          {(
            <div className="ov-menu ov-menu-down" data-open={open ? "" : undefined} style={{ minWidth: 200 }}>
              <div className="ov-mi" data-ov-mi="sort-auto" onClick={() => { onMode("auto"); setOpen(false); }}>
                {mode === "auto" ? "✓ " : ""}在用 → 可用度 → 需处理
              </div>
              <div className="ov-mi" data-ov-mi="sort-custom" title={canCustom ? undefined : "还没拖过 —— 按住卡片右上角 ⠿ 拖动即可"}
                   onClick={() => { if (canCustom) { onMode("custom"); setOpen(false); } }}
                   style={canCustom ? undefined : { color: "var(--tx3)", cursor: "default" }}>
                {mode === "custom" ? "✓ " : ""}我拖的顺序{canCustom ? "" : "（还没拖过）"}
              </div>
            </div>
          )}
        </span>
      )}
    </div>
  );
}
