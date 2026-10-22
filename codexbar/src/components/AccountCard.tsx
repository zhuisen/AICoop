import { useState } from "react";
import type { Account } from "../helpers";
import { QUOTA_STALE_SEC, fmtAgeSec, maskId, winSlot } from "../helpers";
import type { Theme } from "../theme";
import type { OvState } from "../overview";
import { deltaText, fmtClock, fmtDur } from "../overview";
import { fmtTokens, fmtTps } from "../live";
import type { DragWiring } from "./DragHandle";
import StaleMark from "./StaleMark";
import { shortDate } from "../mbLogic";
import { ActGroup, Ab, CardMenu, DynText, IcBolt, IcInfo, IcTrash, OvCard, OvTag, PinMark, ProbeIb, RotIb, RotMark, useProbeFire,
         type OvWin } from "./ov/OvCard";
import CreditChip from "./ov/CreditChip";

/**
 * Codex 账号卡（交接包 P5「账号卡」，5 行槽位 + 底栏，固定 148 高）。外壳在 `ov/OvCard.tsx`，
 * 这里只把 `Account` 映射进槽位、把每个操作接到角标 / 底栏 / ··· 上。
 *
 * ★★ CLAUDE.md §6「不要随手简化掉已有功能」—— 旧卡上的每一项都还在，只是换了位置：
 *   | 原来（10-19 版）                 | 现在（P5 定稿）                                   |
 *   |----------------------------------|---------------------------------------------------|
 *   | 切换                             | 悬停底栏第一颗「切换」（在用号同位置是「在用」）      |
 *   | 探针                             | 悬停底栏 ⚡（卡宽 < 240 时进 ···）                  |
 *   | ⋯ 置顶 / 取消置顶                 | 名称行图钉（已置顶常亮 + 顺序号；未置顶悬停出幽灵）   |
 *   | ⋯ 停用 / 恢复自动轮换             | 悬停底栏 ⊘ + 名称行琥珀 ⊘（已停时）                  |
 *   | ⋯ 使用重置卡 → 确认弹窗           | 底栏右侧 chip → 单选弹层                           |
 *   | ⋯ 详情 / 改名                    | ···「详情」→ 右侧 Sheet（改名在 Sheet 里）           |
 *   | ⋯ 删除（两段确认）                | ···「删除」→ 确认对话框 + toast 撤销                |
 *   | 刷新（= 刷新全池）                | 头部「刷新全池」与 ⌘K（codex 没有单号刷新命令）       |
 *   | 拖拽手柄                          | 右上角，悬停出现（只排「其余」区）                   |
 */
export interface LiveLine { tps: number | null; sessions: number; today: number }

export default function AccountCard({ a, state, isDirect, borrowOff, bestPct, privacy, hov, drag, live, lastUse, rotLoaded,
  probing, usingCredit, shine, t,
  onSwitch, onProbe, onShowDetail, onRemove, onUseCredit, onToggleRotate, onTogglePin }: {
  a: Account; t: Theme; state: OvState;
  /** auth.json 里是它（不走代理直接跑 codex 时用的号）。 */
  isDirect: boolean;
  /** `state.borrow_off`：池子见底时**不许**借用停轮换的号（缺省允许）。只影响说法。 */
  borrowOff?: boolean;
  bestPct: number | null;
  privacy: boolean;
  hov?: boolean;
  drag?: DragWiring;
  /** 在用号的实时速度（`read_live` 的 codex 平台合计，与托盘 / 刘海同源）。 */
  live?: LiveLine | null;
  /** 轮换段里它最后一次在岗的时刻（秒）+ 今天经代理的 token。 */
  lastUse?: { last: number; today: number } | null;
  rotLoaded: boolean;
  probing: boolean; usingCredit: boolean;
  /** 用卡成功的扫光计数。 */
  shine?: number;
  onSwitch: () => void;
  onProbe: () => void;
  onShowDetail: () => void;
  onRemove: () => void;
  onUseCredit: (cardId: string) => void;
  onToggleRotate: (on: boolean) => void;
  onTogglePin: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [creditOpen, setCreditOpen] = useState(false);
  const off = !a.rotates && state !== "dead";
  const pct = a.windows.length ? a.tightest : null;
  const five = a.windows.find((w) => winSlot(w.mins) === "5h") ?? null;
  const week = a.windows.find((w) => winSlot(w.mins) === "w") ?? null;
  const toWin = (w: Account["windows"][number] | null, kind: "5h" | "w"): OvWin => {
    const label = kind === "5h" ? "5h" : "周";
    if (!w) return { label, pct: null, reset: "", kind, absent: true,
                     title: kind === "5h" && week ? "这个号没有 5h 窗口（Pro 只有周额度）" : undefined };
    const anchored = w.anchorState === "anchored";
    return { label, pct: w.pct, kind, reset: anchored ? w.reset : "", note: anchored ? undefined : w.reset, title: w.resetAt };
  };

  // ★ 停轮换覆盖原状态标签（P5 §2.3 `tagK = off ? 'off' : tag`）；边框 / 环仍按原状态。
  const tag = off ? { text: "不轮换", kind: "off" as const }
    : state === "inuse" ? { text: "在用", kind: "inuse" as const }
    : state === "next" ? { text: "下一个", kind: "next" as const }
    : state === "cool" ? { text: "冷却中", kind: "cool" as const }
    : state === "unprobed" ? { text: "未探测", kind: "unprobed" as const }
    : state === "low" ? { text: "额度低", kind: "low" as const }
    : state === "dead" ? { text: "失效", kind: "dead" as const }
    : null;
  const delta = state === "ok" || state === "next" || state === "low" ? deltaText(pct, bestPct) : "";

  const head = (
    <>
      <b data-card-name="" style={{ fontSize: 15, minWidth: 24, overflow: "hidden", textOverflow: "ellipsis" }}>{a.node}</b>
      {tag && <OvTag tag={tag} title={state === "next" && !off ? "代理下一个请求会挑这个号（与顶部续航条同一个真源：codex-rotate next）"
                                     : off ? `不轮换 —— 仍在池里、仍登录，只是代理自动轮换不挑它；手动可切。${borrowOff ? "借用已关闭（池子见底也不会用它）" : "池子见底时代理会临时借用它"}`
                                     : undefined} />}
      {a.plan && a.plan !== "plus" && a.plan !== "free" && <OvTag tag={{ text: a.plan.toUpperCase(), kind: "ultra" }} title={`套餐：${a.plan}`} />}
      {a.quotaStale && a.quotaAgeSec != null && (
        <StaleMark t={t} tone="muted" size={10}
                   note={`这个号的额度快照是 ${fmtAgeSec(a.quotaAgeSec)}前读到的（超过 ${Math.round(QUOTA_STALE_SEC / 60)} 分钟）。`
                         + "条和百分比画的是那一刻的值，不是现在的值。这不代表额度有问题——只代表我们有一阵子没读到它了。"} />
      )}
    </>
  );
  const marks = state === "dead" ? null : (
    <>
      {off && <RotMark onRestore={() => onToggleRotate(true)} />}
      <PinMark rank={a.pinRank} onToggle={onTogglePin} hint="先置顶先用，撞限冷却时自动换下一个" />
    </>
  );
  const right = delta === "最优" ? <OvTag tag={{ text: "最优", kind: "best" }} title="全池可用号里余量最多的" />
    : delta ? <span title={`比余量最多的号少 ${delta.slice(1)}`} style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "var(--tx3)" }}>{delta}</span>
    : null;

  const lastLine = lastUse && lastUse.last > 0
    ? `上次用 ${fmtClock(lastUse.last * 1000)} · 今日 ${lastUse.today > 0 ? fmtTokens(lastUse.today) : "0"}`
    : rotLoaded ? "24 小时内没经代理用过" : "上次用 —";
  const dyn = state === "inuse" && live && live.sessions > 0 ? (
    <DynText tone="live" title="codex 此刻在跑的会话合计（与托盘 / 刘海同源）">
      <i style={{ display: "inline-block", verticalAlign: 1, margin: "0 7px 0 3px", width: 6, height: 6, borderRadius: 3,
                  background: "var(--acc)", boxShadow: "0 0 0 3px rgba(45,212,191,.2)" }} />
      {fmtTps(live.tps)} t/s · {live.sessions} 会话 · 今日 {fmtTokens(live.today)}
    </DynText>
  ) : state === "cool" ? (
    <DynText tone="warn">429 冷却 · {fmtDur(a.cooldownSec / 60)} 后恢复</DynText>
  ) : state === "unprobed" ? (
    <DynText tone="bad">未探测 · 刷新一次后显示额度</DynText>
  ) : state === "low" ? (
    <DynText tone="bad">额度低 · {a.tightestWin?.label ?? ""} 剩 {Math.round(a.tightest)}%{a.tightestWin?.anchorState === "anchored" && a.tightestWin.reset ? ` · ↻${a.tightestWin.reset}` : ""}</DynText>
  ) : state === "dead" ? (
    <DynText tone="bad" title="token 已被服务端判死。重登只用 codex-rotate login（codex login/logout 会 revoke 别的号）">凭证失效 · 终端跑 codex-rotate login 重登</DynText>
  ) : (
    <DynText tone="muted">{lastLine}</DynText>
  );

  const probeHint = `对 ${a.node} 发一次真实补全（问 hi 要求答 ok），证明"真的还能干活"。⚠️ 计费：消耗周额度（实测单次 <1%）`;
  const fire = useProbeFire(onProbe, probing);
  const menu = (
    <CardMenu onOpenChange={setMenuOpen} items={[
      ...(state === "dead" ? [] : [{ key: "probe", label: probing ? "探针中…" : "探针 · 计费", icon: <IcBolt />, warn: true, narrow: true, disabled: probing, onClick: fire }]),
      { key: "detail", label: "详情", icon: <IcInfo />, onClick: onShowDetail },
      { key: "remove", label: "删除", icon: <IcTrash />, bad: true, onClick: onRemove },
    ]} />
  );
  const actions = (
    <ActGroup>
      {state === "dead" ? null : state === "inuse" ? (
        <Ab current data="inuse" title="当前正在用这个号（代理此刻挑的是它）">在用</Ab>
      ) : isDirect ? (
        <Ab current data="inuse" title="auth.json 里就是它（不走代理直接跑 codex 时用的号）—— 切到它是空操作">直连</Ab>
      ) : (
        <Ab primary onClick={onSwitch} data="switch"
            title={`切到这个号：把直连号（auth.json）切成 ${a.node}。走代理时每个请求仍由代理挑号${off ? "；不恢复它的自动轮换" : ""}`}>
          切换
        </Ab>
      )}
      {state !== "dead" && <ProbeIb loading={probing} onFire={onProbe} hint={probeHint} />}
      {state !== "dead" && <RotIb off={off} onToggle={(wasOff) => onToggleRotate(wasOff)} />}
      {menu}
    </ActGroup>
  );

  const chip = state === "dead" ? undefined : (
    <CreditChip a={a} busy={usingCredit} open={creditOpen} onOpenChange={setCreditOpen} onConfirm={onUseCredit} />
  );
  return (
    <OvCard id={a.aid} t={t} state={state} ringPct={pct} head={head} marks={marks} right={right} off={off}
            pinned={a.pinRank !== null} shine={shine} popOpen={creditOpen}
            email={maskId(a.email, privacy) || "—"} dyn={dyn} w5={toWin(five, "5h")} ww={toWin(week, "w")}
            footLeft={<span data-ov-exp={a.exp} title={a.expStale ? `订阅到期 ${a.exp}。OpenAI 上次复核订阅早于这个日期,所以「已过期」是拿陈旧快照下的结论 —— 续费不在它视野里。${isDirect ? " · auth.json 里是它（直连号）" : ""}` : `订阅到期 ${a.exp}${isDirect ? " · auth.json 里是它（直连号）" : ""}`}>
              到期 {shortDate(a.exp, Date.now())}{a.expStale && <span style={{ color: "var(--ovWarnTx)" }}>*</span>}{isDirect && <span className="ov-direct" title="auth.json 里是它（直连时用的号）"> · 直连</span>}
            </span>}
            chip={chip} actions={actions} hov={hov} menuOpen={menuOpen} drag={drag} />
  );
}
