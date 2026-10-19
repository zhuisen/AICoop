import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { Theme } from "../../theme";
import type { Account, AppState } from "../../helpers";
import { agyPoolFreshness, freshnessLine } from "../../helpers";
import type { Board } from "../../hooks/useRotationBoard";
import type { AgyPoolAccount, useAgyPool } from "../../hooks/useAgyPool";
import type { AgySnapshot } from "../../agy";
import { agyAction, agyProbeToast, agyShown, agyTightest } from "../../agy";
import type { GrokSnapshot } from "../../grok";
import { grokLastGoodRemPct, grokRemPct } from "../../grok";
import type { ClaudeQuota } from "../../mbLogic";
import type { LiveSnapshot } from "../../live";
import type { Integration } from "../../hooks/useIntegration";
import type { CardDragWiring } from "../../hooks/useCardDrag";
import { applyOrder } from "../../cardOrder";
import type { OvState } from "../../overview";
import { dayStart, lastUseByAcct, ovCounts, ovIsLow, OV_BP_WIDE, ovBand, ovLayout, ovSort, ovState, todaySwitches } from "../../overview";
import { POOL_PLATFORMS, type PoolKey } from "../../platforms";
import AccountCard from "../AccountCard";
import AgyCard from "../AgyCard";
import GrokCard from "../GrokCard";
import IntegrationBanner from "../IntegrationBanner";
import DawnChip from "../DawnChip";
import ClaudeCard from "./ClaudeCard";
import { ClaudeHero, GrokHero } from "./OvHeroRO";
import { HeroShell, PoolHero, type PlatColors } from "./OvHero";
import { AutoSwitchItem, GroupDivider, HeadMore, OvTabs, ProbeHold, RefreshBtn, ToggleGroup, type OvTab } from "./OvHeader";
import { OvStrip } from "./OvStrip";
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

type Run = (actionId: string, args: string[], msg: string, opts?: { resultToast?: boolean }) => Promise<unknown>;

export type AgyPoolApi = ReturnType<typeof useAgyPool>;

export interface OverviewProps {
  t: Theme; isDark: boolean; privacy: boolean;
  /** 四家的识别色，App 用 `colorOf(traffic, key)` 算（带用户偏好）。 */
  colors: PlatColors;
  provider: PoolKey; setProvider: (k: PoolKey) => void;
  state: AppState; accounts: Account[]; inUseNode: string | undefined; currentNode: string | undefined;
  lastRefreshAt: number | undefined; freshness: { fresh: number; stale: number; unknown: number };
  loadingAction: string | null; run: Run; showToast: (m: string, ms?: number) => void;
  integration: Integration | null; onConnect: () => void;
  board: Board | null; boardErr: string | null;
  agyPool: AgyPoolApi; agyBoard: Board | null; agyBoardErr: string | null;
  agySnap: AgySnapshot | null; agyBusy: boolean; agyErr: string | null; refreshAgy: () => void;
  grokSnap: GrokSnapshot | null; grokBusy: boolean; grokErr: string | null; refreshGrok: () => void;
  claudeQuota: ClaudeQuota | null; claudeErr: string | null; refreshClaude: () => void;
  live: LiveSnapshot | null; liveErr: string | null;
  autoSwitch: boolean; toggleAutoSwitch: () => void;
  agyOrder: string[] | undefined; setAgyOrder: (ids: string[]) => void;
  preview: string[] | null;
  makeDrag: (aid: string, baseIds: string[], hint: string, commit: (next: string[]) => void | Promise<unknown>) => CardDragWiring;
  platOff: { agy: boolean; grok: boolean };
  onShowDetail: (aid: string) => void; onUseCredit: (aid: string) => void;
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
  try { return { hover: localStorage.getItem("codexbar_ov_hover"), open: localStorage.getItem("codexbar_ov_stripopen") === "1" }; }
  catch { return { hover: null, open: false }; }
})();

const TAB_ORDER: PoolKey[] = POOL_PLATFORMS.map((p) => p.key);

export default function Overview(p: OverviewProps) {
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
  const setSortFor = (k: string, m: SortMode) => setSort((cur) => {
    const next = { ...cur, [k]: m };
    try { localStorage.setItem(SORT_KEY, JSON.stringify(next)); } catch { /* 无痕：本次生效 */ }
    return next;
  });
  const [stripOpen, setStripOpen] = useState<Record<string, boolean>>(() => (HARNESS.open ? { off: true, dead: true } : {}) as Record<string, boolean>);
  const toggleStrip = (k: string) => setStripOpen((c) => ({ ...c, [k]: !c[k] }));

  const prov = p.provider;
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

  // ── Codex 档 ──
  const cState = (a: Account): OvState => ovState({
    inUse: a.aid === p.inUseNode, next: p.board?.next?.aid === a.aid, dead: a.status === "dead", off: !a.rotates,
    coolSec: a.cooldownSec, tightest: a.windows.length ? a.tightest : null });
  // 当值号永远在主网格（哪怕它停用了轮换 —— 见 `ovState` 注释）。
  const cMain = p.accounts.filter((a) => a.status !== "dead" && (a.rotates || a.aid === p.inUseNode));
  const cOff = p.accounts.filter((a) => a.status !== "dead" && !a.rotates && a.aid !== p.inUseNode);
  const cDead = p.accounts.filter((a) => a.status === "dead");
  const savedCodex = p.state.card_order ?? p.state.pick_order ?? null;
  const codexMode: SortMode = sort.codex ?? (savedCodex?.length ? "custom" : "auto");
  const codexSorted = ovSort(cMain, (a) => ({ id: a.aid, state: cState(a), tightest: a.windows.length ? a.tightest : null, name: a.node }),
                             codexMode === "custom" ? savedCodex : null);
  const codexShown = p.preview ? applyOrder(codexSorted, p.preview, (a) => a.aid) : codexSorted;
  const cBest = cMain.filter((a) => a.cooldownSec <= 0 && a.windows.length).reduce<number | null>((m, a) => (m == null || a.tightest > m ? a.tightest : m), null);

  // ── Gemini 档 ──
  const agyEnt = new Map([...(p.agyBoard?.queue ?? []), ...(p.agyBoard?.rest ?? [])].map((e) => [e.aid, e] as const));
  const gTight = (a: AgyPoolAccount) => agyTightest(agyShown(p.agyPool.snapshotOf(a, p.agySnap))?.quota)?.b.remaining_percent ?? null;
  const gState = (a: AgyPoolAccount): OvState => ovState({
    inUse: a.sub === p.agyPool.liveSub, next: p.agyBoard?.next?.aid === a.sub, dead: !!agyEnt.get(a.sub)?.dead,
    off: !!a.rotate_off, coolSec: (agyEnt.get(a.sub)?.cool_min ?? 0) * 60, tightest: gTight(a) });
  const gMain = p.agyPool.accounts.filter((a) => !a.rotate_off || a.sub === p.agyPool.liveSub);
  const gOff = p.agyPool.accounts.filter((a) => !!a.rotate_off && a.sub !== p.agyPool.liveSub);
  const agyMode: SortMode = sort.gemini ?? (p.agyOrder?.length ? "custom" : "auto");
  const agySorted = ovSort(gMain, (a) => ({ id: a.sub, state: gState(a), tightest: gTight(a), name: a.label }),
                           agyMode === "custom" ? p.agyOrder : null);
  const agyShownList = p.preview ? applyOrder(agySorted, p.preview, (a) => a.sub) : agySorted;
  const gBest = gMain.filter((a) => gState(a) !== "cool").reduce<number | null>((m, a) => { const v = gTight(a); return v == null ? m : m == null || v > m ? v : m; }, null);

  // ── Claude / Grok ──
  const cq = p.claudeQuota;
  const claudePct = cq?.fiveH == null && cq?.week == null ? null : Math.min(cq?.fiveH?.rem ?? 100, cq?.week?.rem ?? 100);
  const ga = p.grokSnap?.accounts?.[0] ?? null;
  const grokRem = ga && !ga.available ? grokLastGoodRemPct(ga) : grokRemPct(ga);

  // ── 平台档：号数 + 红点 ──
  const lowCodex = cMain.some((a) => a.windows.length > 0 && a.cooldownSec <= 0 && ovIsLow(a.tightest));
  const lowAgy = gMain.some((a) => ovIsLow(gTight(a)));
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
      <ProbeHold loading={p.loadingAction === "probe-all"} onFire={() => void p.run("probe-all", ["probe", "--all"], "探针 全池")}
                 hint={`对 ${p.accounts.length} 个号各发一次真实补全(问 hi 要求答 ok),证明"真的还能干活"。⚠️ 计费：消耗周额度(实测单次 <1%),约 ${p.accounts.length * 7}s`} />
      <ToggleGroup>
        <DawnChip t={p.t} kind="codex" active={codexOn} look="switch" showLabel={layout.labels} />
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
                  onClick={() => { p.agyPool.refresh(); p.showToast(`已刷新 Gemini · ${p.agyPool.accounts.length} 个号`); }} />
      <ProbeHold loading={(p.agyPool.running ?? "").startsWith("probe:")}
                 onFire={() => { p.showToast("探针 全池…"); void p.agyPool.probe().then((r) => r && p.showToast(agyProbeToast(r), 8000)); }}
                 hint={`对 ${p.agyPool.accounts.length} 个号各起一次 agy 真跑一句（问 hi 要求答 ok）。⚠️ 计费：花的是 agy 自己的额度（实测单次约 15k token），每号约 30s`} />
      <ToggleGroup>
        <DawnChip t={p.t} kind="agy" active={agyOn} look="switch" showLabel={layout.labels} />
        <GroupDivider />
        <AutoSwitchItem on={p.agyPool.autoOn} labels={layout.labels} onToggle={() => p.agyPool.setAuto(!(p.agyPool.autoOn ?? true))}
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
      <RefreshBtn labels={layout.labels} busy={false} text="刷新" title="重读一次状态栏转写的额度（读本机文件，零消耗）" onClick={p.refreshClaude} />
      <HeadMore items={[
        { key: "why", label: "本机只有 1 个 Claude 号：不切号、不探针", info: true,
          title: "仓库没有 Claude 账号池后端（切号要写 Claude Code 凭证，已定不碰）" },
        { key: "add", label: "加号…", onClick: () => p.showToast(addHint) },
      ]} />
    </>);
  } else {
    actions = (<>
      <RefreshBtn labels={layout.labels} busy={p.grokBusy} text="刷新" title="重新取一次 grok 周额度（只读 GET，不计费）" onClick={p.refreshGrok} />
      <HeadMore items={[{ key: "why", label: "grok 单号只读：只有周额度，不切号", info: true }]} />
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
  const codexCard = (a: Account, i: number, inGrid: boolean) => (
    <AccountCard key={a.aid} a={a} t={p.t} state={cState(a)} isDirect={a.aid === p.currentNode} borrowOff={!!p.state.borrow_off}
      bestPct={cBest} privacy={p.privacy} hov={isHov(a.aid, i)} live={liveLine("codex")}
      lastUse={codexLast.get(a.node) ?? null} rotLoaded={!!codexRot}
      probing={p.loadingAction === `probe-${a.aid}`} usingCredit={p.loadingAction === `usecredit-${a.aid}`}
      refreshing={p.loadingAction === "refresh-all"}
      drag={inGrid ? p.makeDrag(a.aid, codexSorted.map((x) => x.aid),
        "按住拖动排序 —— **只影响卡片摆放**，不影响轮换。要优先用某个号，点 ⋯ 里的「置顶」。",
        (next) => {
          setSortFor("codex", "custom");
          const byAid = new Map(cMain.map((x) => [x.aid, x.node]));
          return p.run("priority", ["priority", "--set", ...next.map((id) => byAid.get(id) as string)], "已更新卡片顺序");
        }) : undefined}
      onSwitch={() => void p.run(`switch-${a.aid}`, ["switch", a.node], `直连号 → ${a.node}`)}
      onProbe={() => void p.run(`probe-${a.aid}`, ["probe", a.node], `探针 ${a.node}`)}
      onRefresh={() => void p.run("refresh-all", ["refresh-all", "--notify"], `已刷新全池 · ${p.accounts.length} 个号`)}
      onShowDetail={() => p.onShowDetail(a.aid)}
      onRemove={() => void p.run(`remove-${a.aid}`, ["remove", a.node], `已删除 ${a.node}`)}
      onUseCredit={() => p.onUseCredit(a.aid)}
      onRename={(next) => void p.run(`rename-${a.aid}`, ["rename", a.aid, next], `${a.node} → ${next}`)}
      onToggleRotate={(on) => void p.run(`rotate-${a.aid}`, ["rotate", a.aid, on ? "--on" : "--off"], on ? `${a.node} 已恢复轮换` : `${a.node} 已停用轮换`)}
      onTogglePin={() => void p.run(`pin-${a.aid}`, ["pin", "--toggle", a.node],
        a.pinRank !== null ? `${a.node} 已取消置顶 —— 回到容量最高优先` : `${a.node} 已置顶 —— 优先用它，撞限冷却时自动换下一个`)} />
  );
  const agyCard = (a: AgyPoolAccount, i: number, inGrid: boolean) => {
    const e = agyEnt.get(a.sub);
    return (
      <AgyCard key={a.sub} t={p.t} color={p.colors.gemini} aid={a.sub} snap={p.agyPool.snapshotOf(a, p.agySnap)} state={gState(a)} hov={isHov(a.sub, i)}
        action={agyAction(a.quota_err_reason, a.quota_err_url)} plan={a.plan} label={a.label} email={a.email ?? undefined}
        bestPct={gBest} privacy={p.privacy} live={liveLine("agy")} lastUse={agyLast.get(a.label) ?? null} rotLoaded={!!agyRot}
        coolMin={e?.cool_min} pinRank={e?.pin == null ? null : e.pin - 1} rotates={!a.rotate_off}
        disabled={p.platOff.agy} busy={p.agyPool.busy} err={p.agyPool.err}
        drag={inGrid ? p.makeDrag(a.sub, agySorted.map((x) => x.sub), "按住拖动调整摆放顺序。只影响显示，不影响切号策略。",
                                  (next) => { setSortFor("gemini", "custom"); p.setAgyOrder(next); }) : undefined}
        onSwitch={() => p.agyPool.switchTo(a.label)} switching={p.agyPool.switching === a.label}
        onProbe={() => { p.showToast(`探针 ${a.label}…`); void p.agyPool.probe(a.label).then((r) => r && p.showToast(agyProbeToast(r), 8000)); }}
        probing={p.agyPool.running === `probe:${a.label}`}
        onRefresh={p.agyPool.refresh} onTogglePin={() => p.agyPool.togglePin(a.label)}
        onToggleRotate={(on) => p.agyPool.setRotate(a.label, on)} onRename={(next) => p.agyPool.renameTo(a.label, next)}
        onRemove={() => p.agyPool.removeIt(a.label)} onOpen={() => p.onOpenUsage("agy")} />
    );
  };

  let title: ReactNode, grid: ReactNode, below: ReactNode = null;
  const grid0 = (children: ReactNode) => (
    <div data-cards-grid="" data-ov-cols={layout.cols}
         style={{ display: "grid", gridTemplateColumns: `repeat(${layout.cols}, minmax(0, 1fr))`, gap: 12, alignContent: "start" }}>
      {children}
    </div>
  );
  if (codexOn) {
    const c = ovCounts([...cMain.map(cState), ...cDead.map(() => "dead" as const), ...cOff.map(() => "off" as const)]);
    title = <AccountsTitle name="Codex" c={c} mode={codexMode} canCustom={!!savedCodex?.length} onMode={(m) => setSortFor("codex", m)} />;
    grid = grid0(codexShown.map((a, i) => codexCard(a, i, true)));
    below = (<>
      {cOff.length > 0 && (
        <OvStrip kind="off" count={cOff.length} names={cOff.map((a) => a.node)} cols={layout.cols}
                 note={p.state.borrow_off ? "借用已关闭" : "池子见底时可临时借用"} open={!!stripOpen.off} onToggle={() => toggleStrip("off")}>
          {cOff.map((a, i) => codexCard(a, 100 + i, false))}
        </OvStrip>
      )}
      {cDead.length > 0 && (
        <OvStrip kind="dead" count={cDead.length} names={cDead.map((a) => a.node)} cols={layout.cols}
                 note="凭证失效 · 重登用 codex-rotate login" open={!!stripOpen.dead} onToggle={() => toggleStrip("dead")}>
          {cDead.map((a, i) => codexCard(a, 200 + i, false))}
        </OvStrip>
      )}
    </>);
  } else if (agyOn) {
    const c = ovCounts([...gMain.map(gState), ...gOff.map(() => "off" as const)]);
    title = <AccountsTitle name="Gemini" c={c} mode={agyMode} canCustom={!!p.agyOrder?.length} onMode={(m) => setSortFor("gemini", m)} />;
    grid = grid0(gMain.length > 0 || gOff.length > 0
      ? agyShownList.map((a, i) => agyCard(a, i, true))
      : <AgyCard t={p.t} color={p.colors.gemini} snap={p.agySnap} state="readonly" privacy={p.privacy} disabled={p.platOff.agy} busy={p.agyBusy} err={p.agyErr}
                 onRefresh={p.refreshAgy} onOpen={() => p.onOpenUsage("agy")} hov={isHov("agy", 0)} />);
    below = (<>
      {gOff.length > 0 && (
        <OvStrip kind="off" count={gOff.length} names={gOff.map((a) => a.label)} cols={layout.cols}
                 note="池子见底时可临时借用" open={!!stripOpen.off} onToggle={() => toggleStrip("off")}>
          {gOff.map((a, i) => agyCard(a, 100 + i, false))}
        </OvStrip>
      )}
      {p.agyPool.drifted && (
        <div data-agy-drift="" style={{ fontSize: 11.5, fontFamily: MONO, color: "var(--ovWarnTx)", overflow: "hidden", textOverflow: "ellipsis" }}
             title="钥匙串是一个槽，本机常有多个长期存活的 agy 进程，各自在 token 到期时把自己的身份写回去。">
          ⚠️ 当前登录的号与你上次切换的不一致 —— 某个仍在跑的 agy 把凭证写回了钥匙串。要让切换生效：先退出那些旧的 agy 会话，再切换，然后开新的 agy。
        </div>
      )}
    </>);
  } else if (prov === "claude") {
    title = <AccountsTitle name="Claude" c={ovCounts([claudePct == null ? "unprobed" : "inuse"])} />;
    grid = grid0(<ClaudeCard t={p.t} color={p.colors.claude} quota={p.claudeQuota} err={p.claudeErr} live={liveOf("claude")} onRefresh={p.refreshClaude}
                             nowMs={nowMs} hov={isHov("claude-local", 0)} />);
  } else {
    title = <AccountsTitle name="Grok" readOnly />;
    grid = grid0(<GrokCard t={p.t} color={p.colors.grok} snap={p.grokSnap} privacy={p.privacy} busy={p.grokBusy} err={p.grokErr} disabled={p.platOff.grok}
                           hov={isHov("grok", 0)} onOpen={() => p.onOpenUsage("grok")} onRefresh={p.refreshGrok} />);
  }

  return (
    <div ref={rootRef} className="ov-root" data-ov-layout={layout.cols}
         style={{ ...ovVars(p.isDark), flex: 1, minHeight: 0, minWidth: 0, display: "flex", flexDirection: "column", gap: 12 } as CSSProperties}>
      <div data-overview-head="" style={{ display: "flex", alignItems: "center", gap: 12, height: 32, flexShrink: 0, minWidth: 0 }}>
        <span style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-.01em", flexShrink: 0 }}>总览</span>
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
    </div>
  );
}

const Chev = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

/** 账号区标题行：`Codex 账号 · 5 可用 · 1 冷却中 · 1 需处理 · 3 已停用`，右侧排序。0 的项不写。 */
function AccountsTitle({ name, c, mode, canCustom, onMode, readOnly }: {
  name: string; c?: ReturnType<typeof ovCounts>; mode?: SortMode; canCustom?: boolean; onMode?: (m: SortMode) => void; readOnly?: boolean;
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
        {readOnly ? <span><b style={{ color: "var(--tx2)" }}>1</b> 只读</span> : c && (<>
          {item(c.ok, "可用", "var(--tx)")}
          {item(c.cool, "冷却中", "var(--ovWarnTx)")}
          {item(c.low, "额度低", "var(--badTx)")}
          {item(c.bad, "需处理", "var(--badTx)")}
          {item(c.off, "已停用", "var(--tx3)")}
        </>)}
      </span>
      {readOnly ? (
        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 4, fontSize: 11.5, color: "var(--tx2)" }}>只读</span>
      ) : onMode && (
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
