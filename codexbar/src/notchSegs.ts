/**
 * 刘海额度条要画的那几段（纯函数，零 npm 依赖 —— `tests/test_notch_hud.py` 用 node 直接跑它）。
 *
 * ★ 读不到就是空槽 + `—`，**不编数**：Codex 的 `windows` 已经把读不到的窗口剔掉
 *   （`buildWindow` 返回 null），agy 的 `remaining == null` 原样当未知。
 * ★★ agy 的快照必须是**池里当前那个号的**（调用方用 `agyPool.snapshotOf(当前号, 本机RPC)` 算好再传进来，
 *    与菜单栏同一条）。本机 RPC 那份自 agy 1.2 起恒 `csrf_required`，只拿它就是画一个几周前的 `last_good`
 *    （2026-10-17 评审实测：本机那份停在 24.5 天前）。
 */
import { agyQuotaVisible, agyResetText, agyShown, agyWinRows, type AgySnapshot } from "./agy";
import { quotaColor, type Account } from "./helpers";

export interface NotchSeg {
  key: string;
  name: string;
  /** null = 读不到 */
  pct: number | null;
  reset: string;
  /** 旧读数 —— 照画但降亮度，与菜单栏行同口径 */
  stale?: boolean;
  /** 悬浮说明：为什么是旧的 / 为什么读不到。按原因分开写，不用一句话盖全部。 */
  title?: string;
}

export const NOTCH_RED = "#E0524D";

/** 环里显示的整数。与卡片同样四舍五入。 */
export const ringNum = (pct: number) => Math.round(Math.max(0, Math.min(100, pct)));

/**
 * 颜色走托盘那一条（`quotaColor`：<50 琥珀、否则绿），**显示成 0 的额外标红** ——
 * 判据是「显示出来的那个数」，不是原值：剩 0.3% 时环上写着 0，就必须是红的。
 */
export const segColor = (pct: number) => (ringNum(pct) <= 0 ? NOTCH_RED : quotaColor(pct));

const hhmm = (sec: number) => {
  const d = new Date(sec * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

export function codexSegs(inUse: Pick<Account, "status" | "windows"> | null | undefined, off: boolean): NotchSeg[] {
  if (!inUse || off) return [];
  if (inUse.status === "dead") return [{ key: "codex-dead", name: "Codex", pct: null, reset: "失效" }];
  if (inUse.windows.length === 0) return [{ key: "codex-unknown", name: "Codex", pct: null, reset: "待刷新" }];
  return inUse.windows.map((w) => ({ key: `codex-${w.label}`, name: `Codex ${w.label}`, pct: w.pct, reset: w.reset }));
}

/**
 * @param noCurrent 池里有号、但还不知道钥匙串里现在是谁 —— 说「当前号未知」，不随手拿一个号的数顶上。
 */
export function agySegs(snap: AgySnapshot | null | undefined, off: boolean, noCurrent = false): NotchSeg[] {
  if (noCurrent && !off) return [{ key: "agy-none", name: "agy", pct: null, reset: "当前号未知" }];
  if (!agyQuotaVisible(snap, { disabled: off })) return [];
  const shown = agyShown(snap);
  const rows = agyWinRows(shown?.quota);
  // agy 装着、但一个数都没有 ⇒ 一个灰槽说「读不到」，而不是整段消失（消失和「没装」长得一样）。
  if (!shown || rows.length === 0) {
    return [{ key: "agy-none", name: "agy", pct: null, reset: "读不到",
              title: snap?.detail ? `读不到：${snap.detail}` : "这次没读到 agy 的额度" }];
  }
  return rows.map((r) => {
    const title = shown.stale
      ? `上次读到的数${shown.at ? `（${hhmm(shown.at)}）` : ""}，这次没读到`
      : r.seen_at != null ? `这一格这次没返回，沿用 ${hhmm(r.seen_at)} 的读数` : undefined;
    return { key: `agy-${r.label}`, name: `agy ${r.label}`, pct: r.remaining,
             reset: agyResetText(r).text, stale: shown.stale || r.seen_at != null, title };
  });
}

/** `set_notch_hud` / `notch_status` 的回答（见 `notch.rs::Status`）。 */
export interface NotchStatus { active: boolean; reason?: string | null }

export const NOTCH_DESC = "选刘海屏：有 AI 在跑时刘海四周亮起它的颜色；鼠标靠近刘海展开卡片：在跑 / 今日 / 额度。菜单栏图标藏起来。只在刘海屏上显示，外接屏、合盖时菜单栏图标照常显示";

/** 设置「显示位置」的说明行（菜单栏 / 刘海屏二选一，用户 2026-10-24）。 */
export function surfaceDesc(notch: boolean): string {
  return notch ? "只在刘海显示，菜单栏图标藏起来；没有刘海屏时图标自动回来" : "AI 状态显示在菜单栏图标上";
}

/**
 * 设置页那一行的**第二行**：开关与屏幕对不上时的原因；对得上时 `null`。
 * ★ 「开关记住了」与「屏幕上真有东西」是两件事，没对上时必须说出来 ——
 * 原来没有刘海屏时开关照样变绿、屏幕上什么都没有、也没有任何原因（四方评审 2026-10-17 一致指出）。
 * `st == null` = 还没问到（或旧版本 Rust 没有这条命令）⇒ 不下结论。
 * ★ 单独一行（设置页文字一律不折行，放不下省略号）：塞进说明行末尾的话，原因会第一个被省略掉。
 */
export function notchRowWarn(on: boolean, st: NotchStatus | null, err: string | null): string | null {
  if (err) return `⚠ 没能打开：${err}`;
  if (st?.reason === "no_notch") {
    return on
      ? "⚠ 现在没有检测到刘海屏（外接屏 / 合盖），菜单栏图标照常显示；换回带刘海的屏幕后刘海自动出现。"
      : "这台 Mac 现在没有刘海屏。";
  }
  return null;
}

/** 整段说明（说明行 + 原因行），给悬浮提示与旧调用方。 */
export function notchRowDesc(on: boolean, st: NotchStatus | null, err: string | null): string {
  const w = notchRowWarn(on, st, err);
  return w ? `${NOTCH_DESC} ${w}` : NOTCH_DESC;
}
