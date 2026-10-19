import StaleMark from "./StaleMark";
import AgyActionLink from "./AgyActionLink";
import QuotaRow, { type WinCell } from "./mb/QuotaRow";
import type { Theme } from "../theme";
import type { AgySnapshot } from "../agy";
import {
  AGY_EXPIRED_TITLE, AGY_UNKNOWN_TITLE, type AgyAction, agyBadgePlan, agyShown, agyTightest, agyQuotaVisible, agyReasonNote, agyReasonTone, agyResetText, agyWinRows,
} from "../agy";
import { fmtAgo } from "../helpers";

/**
 * 行上固定画这两格。★★ **写成固定槽位而不是"有什么画什么"** ——
 * 非当值号读不到周窗口（云端按账号那条只给 5h），"有什么画什么"会让那些行少一格、
 * 比旁边的行矮一截，而那个矮**没有任何地方解释**。固定槽位下缺的那格显式画 `—`。
 */
const MB_WIN_SLOTS = ["5h", "周"] as const;

/**
 * 菜单栏里的 Gemini（agy）账号行（交接包 2026-10-19 · 4f）。外形在 `mb/QuotaRow`，这里只翻译数据。
 *
 * ★★ **走完全独立的数据通路** —— 数据**绝不**混进 `accounts` / `alive` / `aliveByLabel`：
 *   那几个数组同时驱动计数徽章、探针全池的号数、自动切号。混进去自动切号就可能"切"到一个
 *   根本切不了的东西上，**而且不报错**。闸在 `tests/test_agy_not_in_pool_ui.py`。
 * ★ 小字三态（与总览 AgyCard 同一套语义，别合并）：当值 →「在用」· 在池里 → 可切 · 不在池里 →「只读」。
 * ★ 「没在跑」不染警告色：agy 不常驻，那是常态。
 * ★ 切号**只对下一次启动的 agy 生效**（agy 只在启动时读凭证），toast 由调用方说清楚。
 */
export default function AgyRow({ t, snap, busy, disabled, onOpen,
                                 label, isCurrent, onSwitch, switching, isBest, action, plan }: {
  /** 档位，只有 ULTRA 画出来（`agyBadgePlan`，与总览卡同一口径）。 */
  plan?: string | null;
  /** 取额度被 Google 拒绝时的下一步动作（`agyAction`）。null = 没有可说的。 */
  action?: AgyAction | null;
  /** 「下一个」—— 下次启动 agy 会装进这个号（`agy/pool.py::pick`，与总览同源）。 */
  isBest?: boolean;
  t: Theme;
  snap: AgySnapshot | null;
  busy?: boolean;
  /** 用户在设置页停用了 agy。停用 = 一个像素都不画。 */
  disabled?: boolean;
  /** 点行内容 = 跳工作台总览的 Gemini 档。 */
  onOpen?: () => void;
  /** 池里的显示名。池还没建起来时缺省「当前号」。 */
  label?: string;
  /** 这个号是不是 agy **当前**的登录态（现读钥匙串，不是我们写进去的值）。 */
  isCurrent?: boolean;
  /** 切到这个号（下次启动 agy 生效）。不传 = 不出「切换」。 */
  onSwitch?: () => void;
  switching?: boolean;
}) {
  // ★ 与总览卡**共用同一个判据** —— 两边各写一份迟早出现「主窗有、菜单栏没有」。
  if (!agyQuotaVisible(snap, { disabled })) return null;

  const shown = agyShown(snap);
  const tight = agyTightest(shown?.quota);
  const rows = agyWinRows(shown?.quota);
  const degraded = !!snap && !snap.available;
  const tone = snap ? agyReasonTone(snap) : "muted";
  const name = label ?? "当前号";
  const inPool = !!onSwitch || !!isCurrent;
  const ultra = agyBadgePlan(plan);

  const mark = degraded && snap
    ? <StaleMark t={t} note={action ? action.note : agyReasonNote(snap)} tone={tone} size={10} />
    : null;
  const sub = (
    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
      {isCurrent ? <span style={{ color: "var(--acc)" }} title="agy 当前就登录着这个号（现读钥匙串）">✓ 在用</span>
        : isBest ? <span style={{ color: "var(--acc)" }} title="下次启动 agy 会装进这个号">下一个</span>
        : !inPool ? <span style={{ color: "var(--tx3)" }}
                          title="这个号不在轮换池里，只显示额度（`agy-rotate login --current` 可收编）">只读</span>
        // ★ 小字只放**一个**词（号名列只有 46 宽，两个词会被切成「在用 ult」）：档位排在状态之后。
        : ultra ? <span style={{ color: "var(--gr)", fontWeight: 700 }} title={`档位 ${ultra}`}>{ultra}</span>
        : null}
      {mark}
    </span>
  );

  // 一个数都没有 ——— ★ 绝不画 0%：`0` 和"额度用光了"长得一模一样，而这里的真相是"读不到"。
  // 同理也绝不画满格（上游缺省值就是满格）。
  if (!tight) {
    const note = action && !busy ? <AgyActionLink t={t} action={action} fontSize={10.5} />
      : busy ? "正在取额度…" : snap?.reason === "no_process" ? "agy 没在运行 · 下次启动后显示额度"
      : "未探测 · 刷新一次后显示额度";
    return (
      <QuotaRow platform="agy" isDark={t.isDark} name={name} sub={sub} note={note}
                readOnly={!onSwitch} onSwitch={onSwitch} switching={switching}
                switchTitle={`切到 ${name} —— 只对下一次启动的 agy 生效`}
                onOpen={onOpen} opacity={switching ? .55 : 1} data={{ "data-mb-agy": name }} />
    );
  }

  // ★★ **每个窗口一格**（5h + 周）。缺的那一格**补 `—` 不留空**：非当值号读不到周窗口（云端只给 5h），
  //   空着会把「读不到」伪装成「没有这个窗口」，两者的下一步动作完全相反。
  const wins = MB_WIN_SLOTS.map((slot): WinCell => {
    const row = rows.find(r => r.label === slot);
    const rr = row?.remaining;
    if (row == null || rr == null) {
      return { label: slot, pct: null, refill: "—",
               title: row ? (row.seen_at ? AGY_EXPIRED_TITLE : AGY_UNKNOWN_TITLE)
                 : `${slot} 窗口这次没读到 —— 云端偶尔不返回这一格，下次刷新会补上` };
    }
    // ★★ 沿用的旧读数（`seen_at`）与 AgyCard 同一画法：降不透明度 + 标龄。
    const rt = agyResetText(row);
    return { label: slot, pct: rr, refill: rt.text, refillTitle: rt.title || undefined, dim: !!row.seen_at,
             title: row.seen_at ? `这是 ${fmtAgo(row.seen_at)}的读数：最近一次云端没返回这一组，沿用上次的数` : undefined };
  }) as [WinCell, WinCell];

  return (
    <QuotaRow platform="agy" isDark={t.isDark} name={name} sub={sub} wins={wins}
              readOnly={!onSwitch} onSwitch={onSwitch} switching={switching}
              switchTitle={`切到 ${name} —— 只对下一次启动的 agy 生效`}
              title={tight.group ? `${tight.group} 最紧` : undefined}
              onOpen={onOpen} opacity={switching ? .55 : 1} data={{ "data-mb-agy": name }} />
  );
}
