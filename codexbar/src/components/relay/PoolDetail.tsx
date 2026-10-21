import type { Theme } from "../../theme";
import type { Account } from "../../helpers";
import { MONO, tkPal } from "../tk/tkPal";
import { hm, int, tok } from "../../relayView";

export interface PoolToday { requests: number | null; tokens: number | null; cost: number | null }

/** 账号池明细（P8-1.3）：全池续航 + 每号 5h / 周 + 状态 + 今日请求 / token / 等效牌价（订阅内，不额外花钱）。 */
export default function PoolDetail({ t, isExit, accounts, inUse, next, burstMin, today, onOpenOverview }: {
  t: Theme; isExit: boolean; accounts: Account[]; inUse: string | null; next: string | null;
  /** 全池还能连续用（分钟，`read_rotation_board().burst.now_min`）。读不到 ⇒ null。 */
  burstMin: number | null; today: PoolToday; onOpenOverview: () => void;
}) {
  const p = tkPal(t);
  const dark = t.isDark;
  const acc = dark ? "#5eead4" : "#0e7a6e";
  const amb = dark ? "#fbbf24" : "#9a6512";
  const bad = dark ? "#FF8A73" : "#c23f3a";
  const muted = "#6b7480";
  const inner = dark ? "#0e1319" : "#f6f8fb";
  const win = (a: Account, long: boolean) => a.windows.find((w) => (long ? w.mins >= 1440 : w.mins > 0 && w.mins < 1440)) ?? null;
  const stat = (a: Account): { s: string; c: string } => {
    if (a.status === "dead") return { s: "失效", c: bad };
    if (a.node === inUse) return { s: "在用", c: acc };
    if (a.status === "cool") return { s: "冷却中", c: amb };
    if (!a.windows.length) return { s: "未探测", c: bad };
    if (!a.rotates) return { s: "不轮换", c: p.label };
    if (a.node === next) return { s: "下一个", c: p.label };
    return { s: "待命", c: p.label };
  };
  const cnt = { ok: 0, cool: 0, unk: 0 };
  for (const a of accounts) {
    if (a.status === "dead") continue;
    if (a.status === "cool") cnt.cool += 1;
    else if (!a.windows.length) cnt.unk += 1;
    else cnt.ok += 1;
  }
  const bar = (pct: number | null, c: string) => (
    <i style={{ height: 4, borderRadius: 2, background: p.track, overflow: "hidden", display: "block" }}>
      <i style={{ display: "block", height: "100%", width: `${pct ?? 0}%`, background: c }} />
    </i>
  );
  const grid = "52px minmax(0,1fr) 40px minmax(0,1fr) 40px 56px";
  const kpi = (label: string, v: string, sub: string) => (
    <div style={{ padding: "8px 10px", borderRadius: 8, background: inner, display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
      <span style={{ fontSize: 11.5, color: p.label }}>{label}</span>
      <span style={{ fontFamily: MONO, fontSize: 16, fontWeight: 700 }}>{v}</span>
      <span style={{ fontFamily: MONO, fontSize: 11, color: muted, overflow: "hidden", textOverflow: "ellipsis" }}>{sub}</span>
    </div>
  );
  return (
    <section data-pool-detail style={{ borderRadius: 12, background: p.panel, border: `1px solid ${isExit ? "rgba(45,212,191,.5)" : p.border}`,
                                       padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <i style={{ width: 8, height: 8, borderRadius: 4, background: isExit ? "#2dd4bf" : muted }} />
        <span style={{ fontSize: 15, fontWeight: 600 }}>账号池</span>
        <span style={{ fontSize: 11, padding: "1px 6px", borderRadius: 5, background: "rgba(45,212,191,.12)", color: acc }}>订阅 · 不额外花钱</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: isExit ? acc : p.label }}>{isExit ? "● 出口" : "待命"}</span>
      </div>
      <div style={{ display: "flex", gap: 18, alignItems: "baseline" }}>
        <span style={{ fontSize: 12, color: p.label }}>全池还能连续用</span>
        <span data-pool-burst title={burstMin == null ? "续航要等额度历史攒够才算得出" : undefined}
              style={{ fontFamily: MONO, fontSize: 22, fontWeight: 700 }}>{hm(burstMin)}</span>
        <span style={{ fontSize: 12, color: p.label }}>{cnt.ok} 可用 · {cnt.cool} 冷却 · {cnt.unk} 未探测</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <div style={{ display: "grid", gridTemplateColumns: grid, gap: 8, fontSize: 11, color: muted }}>
          <span>号</span><span>5h</span><span /><span>周</span><span /><span style={{ textAlign: "right" }}>状态</span>
        </div>
        {accounts.map((a) => {
          const w5 = win(a, false), ww = win(a, true);
          const low = w5 != null && Math.round(w5.pct) < 10;
          const st = stat(a);
          return (
            <div key={a.aid} data-pool-row={a.node} style={{ display: "grid", gridTemplateColumns: grid, gap: 8, alignItems: "center", height: 22,
                                                            fontFamily: MONO, fontSize: 12, opacity: a.status === "dead" ? 0.55 : 1 }}>
              <span style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>{a.node}</span>
              {bar(w5?.pct ?? null, low ? bad : "#2dd4bf")}
              <span style={{ textAlign: "right", color: low ? bad : p.text2 }}>{w5 ? `${Math.round(w5.pct)}%` : "—"}</span>
              {bar(ww?.pct ?? null, dark ? "#22c55e" : "#16a34a")}
              <span style={{ textAlign: "right", color: p.text2 }}>{ww ? `${Math.round(ww.pct)}%` : "—"}</span>
              <span style={{ textAlign: "right", fontSize: 11, fontFamily: "inherit", color: st.c }}>{st.s}</span>
            </div>
          );
        })}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 8 }}>
        {kpi("今日请求", int(today.requests), isExit ? "经代理" : "切走前")}
        {kpi("今日 token", tok(today.tokens), `${accounts.length} 个号合计`)}
        {kpi("等效牌价", today.cost == null ? "—" : `$${today.cost.toFixed(2)}`, "订阅内 · 不额外花钱")}
      </div>
      <div style={{ marginTop: "auto", display: "flex", justifyContent: "space-between", fontSize: 12, color: p.label,
                    borderTop: `1px solid ${p.hair}`, paddingTop: 8 }}>
        <span>额度按 5h / 周窗口重置，不花钱</span>
        <span role="button" data-act="open-overview" onClick={onOpenOverview} style={{ color: p.accent, cursor: "pointer" }}>打开总览 →</span>
      </div>
    </section>
  );
}
