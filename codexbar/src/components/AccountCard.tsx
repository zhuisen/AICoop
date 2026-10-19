import { useState } from "react";
import type { Account } from "../helpers";
import { CARD_WARN_DAYS, QUOTA_STALE_SEC, cardLeftText, fmtAgeSec, maskId } from "../helpers";
import type { Theme } from "../theme";
import type { OvState } from "../overview";
import { deltaText, fmtClock, fmtDur } from "../overview";
import { fmtTokens, fmtTps } from "../live";
import type { DragWiring } from "./DragHandle";
import StaleMark from "./StaleMark";
import { isCardExpiring } from "./CardBadge";
import { Ab, DynText, HoldAb, IcRefresh, IcSwap, IcTicket, OvCard, OvMenu, OvTag, type OvWin } from "./ov/OvCard";

/**
 * Codex 账号卡（交接包 page5「账号卡」，5 行槽位 + 底栏，固定 148 高）。外壳在 `ov/OvCard.tsx`，
 * 这里只把 `Account` 映射进槽位、把每个原有操作接到底栏 / ⋯ 菜单上。
 *
 * ★★ CLAUDE.md §6「不要随手简化掉已有功能」—— 旧动作条（`CardActionBar`）上的每一项都还在：
 *   | 原来                         | 现在                                   |
 *   |------------------------------|----------------------------------------|
 *   | 切换                         | 底栏主按钮「切换」（在用号不出）           |
 *   | 探针（两段确认）              | 底栏「探针」，按住 0.6 s（与菜单栏同一状态机）|
 *   | 置顶 / 轮换开关 / 改名 / 详情 / 删除（两段）| ⋯ 菜单                         |
 *   | 页脚重置卡角标 → 确认弹窗     | 页脚角标原样可点（`data-card-badge-use`）+ ⋯「使用重置卡」|
 *   | 拖拽手柄                      | 右上角，悬停出现                          |
 *   ⚠️ 新增的「刷新」：codex 没有单号刷新命令，它跑的就是「刷新全池」（`refresh-all`），title 写明。
 */
export interface LiveLine { tps: number | null; sessions: number; today: number }

export default function AccountCard({ a, t, state, isDirect, borrowOff, bestPct, privacy, hov, drag, live, lastUse, rotLoaded,
  probing, usingCredit, refreshing,
  onSwitch, onProbe, onRefresh, onShowDetail, onRemove, onUseCredit, onRename, onToggleRotate, onTogglePin }: {
  a: Account; t: Theme; state: OvState;
  /** auth.json 里是它（不走代理直接跑 codex 时用的号）。 */
  isDirect: boolean;
  /** `state.borrow_off`：池子见底时**不许**借用停用号（缺省允许）。只影响停用卡上的说法。 */
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
  probing: boolean; usingCredit: boolean; refreshing: boolean;
  onSwitch: () => void;
  onProbe: () => void;
  onRefresh: () => void;
  onShowDetail: () => void;
  onRemove: () => void;
  onUseCredit: () => void;
  onRename: (next: string) => void;
  onToggleRotate: (on: boolean) => void;
  onTogglePin: () => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const pct = a.windows.length ? a.tightest : null;
  const five = a.windows.find((w) => w.mins > 0 && w.mins < 1000) ?? null;
  const week = a.windows.find((w) => w.mins >= 10000) ?? null;
  const toWin = (w: Account["windows"][number] | null, kind: "5h" | "w"): OvWin => {
    const label = kind === "5h" ? "5h" : "周";
    if (!w) return { label, pct: null, reset: "", kind, absent: true,
                     title: kind === "5h" && week ? "这个号没有 5h 窗口（Pro 只有周额度）" : undefined };
    const anchored = w.anchorState === "anchored";
    return { label, pct: w.pct, kind, reset: anchored ? w.reset : "", note: anchored ? undefined : w.reset, title: w.resetAt };
  };

  const tag = state === "inuse" ? { text: "在用", kind: "inuse" as const }
    : state === "next" ? { text: "下一个", kind: "next" as const }
    : state === "cool" ? { text: "冷却中", kind: "cool" as const }
    : state === "unprobed" ? { text: "未探测", kind: "unprobed" as const }
    : state === "low" ? { text: "额度低", kind: "low" as const }
    : state === "off" ? { text: "已停用", kind: "off" as const }
    : state === "dead" ? { text: "失效", kind: "dead" as const }
    : null;
  const delta = state === "ok" || state === "next" || state === "low" ? deltaText(pct, bestPct) : "";

  const head = (
    <>
      {editing !== null ? (
        <input autoFocus value={editing} data-ov-rename=""
               onClick={(e) => e.stopPropagation()}
               onChange={(e) => setEditing(e.target.value)}
               onKeyDown={(e) => {
                 e.stopPropagation();
                 if (e.key === "Enter" && editing.trim()) { onRename(editing.trim()); setEditing(null); }
                 if (e.key === "Escape") setEditing(null);
               }}
               onBlur={() => setEditing(null)}
               style={{ fontSize: 14, fontWeight: 700, color: "var(--tx)", minWidth: 0, width: 110, background: "transparent",
                        border: "1px solid var(--accLine)", borderRadius: 5, padding: "0 4px", fontFamily: "inherit", height: 20 }} />
      ) : (
        <b data-card-name="" style={{ fontSize: 15, minWidth: 24, overflow: "hidden", textOverflow: "ellipsis" }}>{a.node}</b>
      )}
      {a.pinRank !== null && (
        <span data-pin-badge="" title={`已置顶（第 ${a.pinRank + 1} 位）—— 优先用它，撞限冷却时自动换下一个`}
              style={{ fontSize: 10.5, fontWeight: 700, color: "var(--acc)", flexShrink: 0 }}>▲{a.pinRank + 1}</span>
      )}
      {tag && <OvTag tag={tag} title={state === "next" ? "代理下一个请求会挑这个号（与顶部续航条同一个真源：codex-rotate next）"
                                     : state === "off" ? "已停用自动轮换 —— 代理不会挑它（池子见底且允许借用时除外）" : undefined} />}
      {/* 在用但停了轮换（被借用 / 手动直连）：「在用」压过了「已停用」，这枚补上另一半事实。 */}
      {!a.rotates && state === "inuse" && <OvTag tag={{ text: "已停用", kind: "off" }} title="这个号停了自动轮换，此刻是被借用 / 直连在用" />}
      {a.plan && a.plan !== "plus" && a.plan !== "free" && <OvTag tag={{ text: a.plan.toUpperCase(), kind: "ultra" }} title={`套餐：${a.plan}`} />}
      {a.quotaStale && a.quotaAgeSec != null && (
        <StaleMark t={t} tone="muted" size={10}
                   note={`这个号的额度快照是 ${fmtAgeSec(a.quotaAgeSec)}前读到的（超过 ${Math.round(QUOTA_STALE_SEC / 60)} 分钟）。`
                         + "条和百分比画的是那一刻的值，不是现在的值。这不代表额度有问题——只代表我们有一阵子没读到它了。"} />
      )}
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
  ) : state === "off" ? (
    <DynText tone="muted" title={lastLine}>{borrowOff ? "已停用 · 借用已关闭（池子见底也不会用它）" : "池子见底时可临时借用"}</DynText>
  ) : (
    <DynText tone="muted">{lastLine}</DynText>
  );

  const expiring = isCardExpiring(a);
  const some = expiring && a.cardsExpiring > 0 && a.cardsExpiring < a.cards;
  const canUse = !!a.cardExp;
  const cardTitle = (a.cardExp
    ? `共 ${a.cards} 张 · 最早一张到期 ${a.cardExp}${a.cardsExpiring ? ` · ${a.cardsExpiring} 张在 ${CARD_WARN_DAYS} 天内作废` : ""}`
    : `共 ${a.cards} 张 · 到期未知(运行 codex-rotate credits 取明细)`)
    + (canUse ? `\n用卡：⋯ →「使用重置卡」，弹窗确认后用掉所选的那张（默认最近到期 ${a.cardExp}）。⚠️ 不可逆。额度没见底也能用（用户实测）` : "")
    // 「怎么用卡」（2026-09-18 从菜单栏横幅搬来，横幅可关 ⇒ 这里是它的常驻归宿）：只在快到期时缀上。
    + (expiring ? "\n也可以在终端用：codex → 输入 /usage → Redeem usage limit reset" : "");
  // 停用的号：有重置卡就照样画角标（卡会过期，停不停用都一样）；「可借用 / 不借用」第 ③ 槽已经写了，
  //   没卡时才放到这里（交接包 12 的样子）。
  const footRight = state === "off" && !(a.cards > 0) ? (
    <span style={{ color: "var(--tx2)", flexShrink: 0 }} title={borrowOff ? "借用已关闭" : "池子见底时代理会临时借用它"}>{borrowOff ? "不借用" : "可借用"}</span>
  ) : a.cards > 0 ? (
    // ★ 只是显示：交接包 page5 的卡片悬停时底栏**整条**换成操作，角标在鼠标够得着之前就让位了，
    //   点它的入口改在 ⋯「使用重置卡」（同一个确认弹窗，PLAN §4）。留着 onClick 就是一个够不着的按钮。
    <span data-card-badge="" title={cardTitle}
          style={{ display: "flex", alignItems: "center", gap: 4, fontFamily: "'JetBrains Mono', monospace",
                   fontVariantNumeric: "tabular-nums", color: expiring ? "var(--ovWarnTx)" : "var(--ovNum)",
                   flexShrink: 0 }}>
      <IcTicket />{usingCredit ? "使用中…" : `重置卡 ×${a.cards}${expiring ? ` · ${some ? `${a.cardsExpiring}张` : ""}剩 ${cardLeftText(a.cardDays ?? 0)}` : ""}`}
    </span>
  ) : <span style={{ color: "var(--ovPh)", fontFamily: "'JetBrains Mono', monospace", flexShrink: 0 }}>无重置卡</span>;

  const canSwitch = state !== "inuse" && state !== "dead" && !isDirect;
  const actions = state === "dead" ? (
    <>
      <Ab onClick={onShowDetail} data="detail">详情</Ab>
      <OvMenu onOpenChange={setMenuOpen} items={[
        { key: "rename", label: "重命名", onClick: () => setEditing(a.node) },
        { key: "remove", label: "删除这个号", bad: true, confirm: "再点一次确认删除", onClick: onRemove },
      ]} />
    </>
  ) : (
    <>
      {canSwitch && (
        <Ab primary onClick={onSwitch} data="switch"
            title={state === "off"
              ? `借用：把直连号（auth.json）切成 ${a.node}。不恢复它的自动轮换 —— 要恢复在 ⋯ 里打开`
              : `把直连号（auth.json）切成 ${a.node}。走代理时每个请求仍由代理挑号`}>
          <IcSwap />{state === "off" ? "借用" : "切换"}
        </Ab>
      )}
      {state !== "off" && (
        <HoldAb loading={probing} onFire={onProbe}
                hint={`对 ${a.node} 发一次真实补全（问 hi 要求答 ok），证明"真的还能干活"。⚠️ 计费：消耗周额度（实测单次 <1%）`} />
      )}
      <Ab onClick={onRefresh} disabled={refreshing} data="refresh"
          title="刷新额度 —— codex 没有单号刷新命令，这里跑的是「刷新全池」（零消耗）">
        <IcRefresh spin={refreshing} />刷新
      </Ab>
      <OvMenu onOpenChange={setMenuOpen} items={[
        { key: "direct", label: "✓ 直连号（auth.json 里是它）", info: true, hidden: !isDirect,
          title: "不走代理直接跑 codex 时用的就是这个号。走代理时每个请求都可能换号，以顶部「正在使用」为准。" },
        { key: "pin", label: a.pinRank !== null ? `取消置顶（第 ${a.pinRank + 1} 位）` : "置顶 —— 优先用它", onClick: onTogglePin },
        { key: "rotate", label: a.rotates ? "停用自动轮换" : "恢复自动轮换", onClick: () => onToggleRotate(!a.rotates),
          title: a.rotates ? "移出轮换池 —— 代理不再挑它（关掉最后一个会被 CLI 拒绝）" : "放回轮换池" },
        { key: "rename", label: "重命名", onClick: () => setEditing(a.node) },
        { key: "detail", label: "详情", onClick: onShowDetail },
        { key: "credit", label: `使用重置卡（${a.cards} 张）`, hidden: !(a.cards > 0 && canUse), onClick: onUseCredit },
        { key: "remove", label: "删除这个号", bad: true, confirm: "再点一次确认删除", onClick: onRemove },
      ]} />
    </>
  );

  return (
    <OvCard id={a.aid} t={t} state={state} ringPct={pct} head={head} right={right}
            email={maskId(a.email, privacy) || "—"} dyn={dyn} w5={toWin(five, "5h")} ww={toWin(week, "w")}
            footLeft={<span title={a.expStale ? "OpenAI 上次复核订阅早于这个日期,所以「已过期」是拿陈旧快照下的结论 —— 续费不在它视野里。" : "订阅到期日"}>
              到期 {a.exp}{a.expStale && <span style={{ color: "var(--ovWarnTx)" }}>*</span>}{isDirect && <span title="auth.json 里是它（直连时用的号）"> · 直连</span>}
            </span>}
            footRight={footRight} actions={actions} hov={hov} menuOpen={menuOpen} drag={drag} />
  );
}
