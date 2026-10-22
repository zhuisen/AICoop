import { type Account, fmtAgeSec, winSlot } from "../helpers";
import { isLow, tightestOf } from "../mbLogic";
import QuotaRow, { type WinCell } from "./mb/QuotaRow";

/**
 * 菜单栏里的 Codex 账号行（交接包 2026-10-19 · 4f「账号行」）。外形在 `mb/QuotaRow`，这里只翻译数据。
 *
 * ★ 号名下一行的小字，优先级固定：在用 > 下一个 > 冷却 > 失效 / 未探测 > PRO > 与最优号的差值。
 *   「在用」= 代理最近一次真的用了它（`last_aid`），「下一个」= 真挑号器的下一个（与总览同源）。
 * ★ 邮箱 / 到期日 / 重置卡数**不再常显**（交接包 DECISIONS 4f「已定」）；重置卡与到期仍进通知条。
 * ★ 两个固定槽位 5h / 周：Pro 号只有周窗口，5h 那格画 —（不留空，留空会被读成「这一格坏了」）。
 * ★ 颜色只有一条规则：任一窗口 < 10% 整行橙红（`mbLogic.isLow`，四家共用）。最紧窗口仍取 `a.tightest`，
 *   不拿 `windows` 的第一个 —— 那会在两个窗口时显示较宽松的那个。
 */
export default function AccountRow({ a, isCurrent, isBest, bestPct, isDark, onSelect,
                                     onSwitch, switching }: {
  a: Account; isCurrent: boolean; isBest: boolean; bestPct: number; isDark: boolean;
  /** 点行内容 = 跳工作台总览的 Codex 档。 */
  onSelect: () => void;
  /** 「切换」按钮。**只在传了它时才渲染**，调用方负责判断在用 / 当前 / 失效号不给。 */
  onSwitch?: () => void;
  /** 该号正在切换中。切号要跑一次 CLI，没有这个状态按钮会看起来没反应、诱发连点。 */
  switching?: boolean;
}) {
  const isDead = a.status === "dead";
  const isCool = a.status === "cool";
  const known = a.tightest >= 0 && !isDead && a.windows.length > 0;
  const delta = known && bestPct >= 0 ? a.tightest - bestPct : null;

  // ★ 陈旧读数降不透明度 + 标龄（2026-10-22 评审：另外三家都有，codex 行几天前的数看起来和新的一样）
  const staleTitle = a.quotaStale && a.quotaAgeSec != null ? `这是 ${fmtAgeSec(a.quotaAgeSec)}前的读数 —— 之后没再读到这个号` : undefined;
  const slot = (mins: (m: number) => boolean, label: string): WinCell | null => {
    const w = a.windows.find((x) => mins(x.mins));
    return w ? { label, pct: w.pct, refill: w.reset, refillTitle: w.resetAt, dim: a.quotaStale, title: staleTitle } : null;
  };
  const wins: [WinCell | null, WinCell | null] = [
    slot((m) => winSlot(m) === "5h", "5h"),
    slot((m) => winSlot(m) === "w", "周"),
  ];
  // 一个窗口都对不上时长档（上游多出来一种窗口）：照原样按顺序放，不丢数。
  if (!wins[0] && !wins[1] && a.windows.length) {
    const [w0, w1] = a.windows;
    wins[0] = { label: "5h", pct: w0.pct, refill: w0.reset, refillTitle: w0.resetAt, dim: a.quotaStale, title: staleTitle };
    if (w1) wins[1] = { label: "周", pct: w1.pct, refill: w1.reset, refillTitle: w1.resetAt, dim: a.quotaStale, title: staleTitle };
  }
  const low = known && isLow(tightestOf(a.windows.map((w) => w.pct)));

  const sub0 = isCurrent
    ? <span style={{ display: "flex", alignItems: "center", gap: 2, color: "var(--acc)" }}
            title="代理最近一次请求用的就是这个号"><Check />在用</span>
    : isBest ? <span style={{ color: "var(--acc)" }} title="代理下一个请求会挑这个号">下一个</span>
    : isCool ? <span style={{ color: "var(--warn)" }}>冷却</span>
    : isDead ? <span style={{ color: "var(--bad)" }}>失效</span>
    : !known ? <span style={{ color: "var(--bad)" }}>未探测</span>
    : a.plan === "pro" ? <span style={{ color: "var(--gr)", fontWeight: 700 }}>PRO</span>
    : delta != null ? <span style={{ fontFamily: "'JetBrains Mono', monospace", color: low ? "var(--bad)" : "var(--tx3)" }}>
        {delta === 0 ? "最优" : `${delta}%`}</span>
    : null;
  // ★ 陈旧时号名下一行**看得见**读数年龄（同 Claude 行「N 小时前读数」）：只靠降透明度 + 悬停，
  //   不悬停看不出是几天前的数（阶段 A 评审）。
  const sub = known && a.quotaStale && a.quotaAgeSec != null
    ? <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
        {sub0}<span data-mb-acct-stale="" style={{ color: "var(--warn)" }} title={staleTitle}>
          {fmtAgeSec(a.quotaAgeSec).replace(" ", "")}前</span></span>
    : sub0;

  return (
    <QuotaRow platform="codex" isDark={isDark} name={a.node} sub={sub}
              wins={known ? wins : undefined}
              note={isDead ? "token 失效 · 需重登" : "未探测 · 刷新一次后显示额度"}
              readOnly={!onSwitch} onSwitch={onSwitch} switching={switching}
              switchTitle={`切到 ${a.node}（不打开主界面）`}
              onOpen={onSelect} opacity={isDead ? 0.6 : 1}
              data={{ "data-mb-acct": a.aid }} />
  );
}

function Check() {
  return (
    <svg width="9" height="9" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
      <path d="m5 12.5 4.5 4.5L19 7.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
