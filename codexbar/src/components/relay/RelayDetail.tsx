import { useState } from "react";
import type { Theme } from "../../theme";
import { MONO, tkPal } from "../tk/tkPal";
import { money, type RelayEntry, type RelayRow } from "../../relay";
import { type Banner, type Group, agoText, bannerOf, groupPerActiveDay, int, monthSum, runDays, saveRatio, sumOf, todayModels, tok } from "../../relayView";

/**
 * 中转站明细（P8-1.4），一个平台一块。账户表 → 视角（合计 / 各账户）→ 余额 + 还能撑 → 今日实扣 / 本月实扣 / 今日请求 → 今日按模型。
 * ★ 口径：实扣 `actual_cost` 是主数字；牌价 `cost` 只做灰色参考，两者永不相加、永不互相替代。
 * ★ 保留（偏离 P8-*）：余额旁的旧读数 `*`（title 带原因）· 就近 ↻ · `···` 菜单（测试连接 / 编辑 / 停用·启用 / 删除）·
 *   停用徽章与变淡 · 多币种不可相加。账户表整行**不**可点，只有「设为出口」可点（防误触开始花钱）。
 */
export default function RelayDetail({ t, g, rows, usage, exitId, usageBusy, onRefreshUsage, onExit, onPool,
                                     onTest, onEdit, onToggle, onRemove, testing }: {
  t: Theme; g: Group; rows: RelayRow[]; usage: RelayEntry[]; exitId: string | null;
  usageBusy: boolean; onRefreshUsage: () => void; onExit: (id: string) => void; onPool: () => void;
  onTest: (id: string) => void; onEdit: (r: RelayRow) => void; onToggle: (r: RelayRow) => void; onRemove: (r: RelayRow) => void;
  testing: string | null;
}) {
  const p = tkPal(t);
  const dark = t.isDark;
  const acc = dark ? "#5eead4" : "#0e7a6e";
  const amb = dark ? "#fbbf24" : "#9a6512";
  const bad = dark ? "#FF8A73" : "#c23f3a";
  const muted = "#6b7480";
  const inner = dark ? "#0e1319" : "#f6f8fb";
  const mine = g.ids.map((id) => rows.find((r) => r.id === id)).filter((r): r is RelayRow => !!r);
  const ent = (id: string) => usage.find((u) => u.id === id);
  const isExit = !!exitId && g.ids.includes(exitId);
  const [view, setView] = useState<string>("");
  const [menu, setMenu] = useState<string | null>(null);
  const v = view && (view === "sum" || g.ids.includes(view)) ? view : isExit && exitId ? exitId : mine.length > 1 ? "sum" : mine[0]?.id ?? "sum";
  const now = new Date();
  const ids = v === "sum" ? mine.map((r) => r.id) : [v];
  const ds = ids.map((id) => ent(id)?.data);
  const units = ds.map((d) => d?.unit);
  const bal = sumOf(ds.map((d) => d?.balance), units);
  const perDay0 = sumOf(ds.map((d) => d?.runway?.per_active_day), units);
  // 组合计：按日期合并后的日均（`groupPerActiveDay`），不是各账户日均之和。
  // ★ 币种按「有数据的账户」判，不借 `perDay0`（阶段 C 评审：各账户自己的日均都读不到时它没有币种、也判不出混币种）
  const cur = sumOf(ds.map((d) => (d ? 0 : null)), units);
  const perDay = ids.length === 1 ? perDay0
    : { v: cur.mixed || cur.v == null ? null : groupPerActiveDay(ds), unit: cur.unit, mixed: cur.mixed };
  const days = ids.length === 1 ? runDays(ds[0]?.balance, ds[0]?.runway?.days)
    : bal.v === 0 ? 0 : bal.v != null && perDay.v ? Math.floor(bal.v / perDay.v) : null;
  const reason = ids.length === 1 ? ds[0]?.runway?.reason ?? null : null;
  const tAct = sumOf(ds.map((d) => d?.today?.actual_cost), units);
  const tCost = sumOf(ds.map((d) => d?.today?.cost), units);
  const tReq = ds.every((d) => d?.today?.requests != null) ? ds.reduce((s, d) => s + (d?.today?.requests ?? 0), 0) : null;
  const tTok = ds.every((d) => d?.today?.total_tokens != null) ? ds.reduce((s, d) => s + (d?.today?.total_tokens ?? 0), 0) : null;
  const mA = ds.map((d) => monthSum(d?.daily, now, "actual_cost", d?.covered));
  const mC = ds.map((d) => monthSum(d?.daily, now, "cost", d?.covered));
  const mAct = sumOf(mA.map((x) => x.v), units), mCost = sumOf(mC.map((x) => x.v), units);
  const mFull = mA.every((x) => x.complete);
  const save = saveRatio(tCost.v, tAct.v);
  const tm = todayModels(ds, now);
  const models = tm.rows;
  const banner: Banner | null = bannerOf(mine, usage, exitId);
  const stale = banner?.kind === "stale";
  const dim = stale ? 0.55 : 1;
  const runC = days === 0 ? bad : p.text2;
  const balC = bal.v === 0 ? bad : bal.v == null ? muted : p.text;
  const nm = (id: string) => mine.find((r) => r.id === id)?.label ?? id;

  const bannerEl = banner && (() => {
    const tone = banner.kind === "zero" ? { bg: "rgba(224,82,77,.1)", bd: "rgba(224,82,77,.4)", c: bad }
      : banner.kind === "stale" || banner.kind === "error" ? { bg: "rgba(251,191,36,.08)", bd: "rgba(251,191,36,.35)", c: amb }
        : { bg: dark ? "rgba(255,255,255,.04)" : "rgba(0,0,0,.03)", bd: dark ? "rgba(255,255,255,.12)" : "rgba(0,0,0,.12)", c: p.text2 };
    const txt = banner.kind === "zero"
      ? (banner.isExit ? `${banner.acc} 余额为 0：走它的请求会失败` : `${banner.acc} 余额为 0 · 当前出口不受影响`)
      : banner.kind === "nobal" ? `${banner.acc} 余额读不到（接口没返回）· 不等于 0，不报警；合计也只能显示「—」`
        : banner.kind === "error" ? `${banner.acc} 从未取到数据：${banner.why ?? "原因未知"} · 下次刷新自动重试`
        : `数据过期：最近一次取数失败，下面是 ${agoText(banner.since, Date.now() / 1000)}的快照`;
    return (
      <div data-relay-banner={banner.kind} style={{ display: "flex", gap: 10, alignItems: "center", padding: "8px 12px", borderRadius: 8,
                                                    background: tone.bg, border: `1px solid ${tone.bd}`, color: tone.c, fontSize: 12.5 }}>
        <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{txt}</span>
        <span style={{ flex: 1 }} />
        {banner.kind === "zero" && banner.isExit && (
          <button type="button" data-act="banner-switch"
                  onClick={() => (banner.alt ? onExit(banner.alt.id) : onPool())}
                  style={{ height: 24, padding: "0 10px", borderRadius: 6, border: 0, background: "#2dd4bf", color: "#062b27",
                           fontSize: 12, fontWeight: 600, cursor: "pointer", flexShrink: 0, fontFamily: "inherit" }}>
            {banner.alt ? `切到 ${banner.alt.label}（${money(banner.alt.balance, banner.alt.unit)}）` : "切回账号池"}
          </button>
        )}
      </div>
    );
  })();

  const tcols = "minmax(64px,auto) minmax(0,1fr) 76px 64px 72px 92px";
  const kpi = (label: string, val: string, sub: string, attr?: Record<string, string>) => (
    <div {...attr} title={sub} style={{ padding: "8px 10px", borderRadius: 8, background: inner, display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
      <span style={{ fontSize: 11.5, color: p.label }}>{label}</span>
      <span style={{ fontFamily: MONO, fontSize: 16, fontWeight: 700 }}>{val}</span>
      <span style={{ fontFamily: MONO, fontSize: 11, color: muted, overflow: "hidden", textOverflow: "ellipsis" }}>{sub}</span>
    </div>
  );

  return (
    <section data-relay-detail={g.name} style={{ position: "relative", borderRadius: 12, background: p.panel,
                                                 border: `1px solid ${isExit ? "rgba(45,212,191,.5)" : p.border}`,
                                                 padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <i style={{ width: 8, height: 8, borderRadius: 4, background: isExit ? "#2dd4bf" : muted, flexShrink: 0 }} />
        <span style={{ fontSize: 15, fontWeight: 600, flexShrink: 0 }}>{g.name}</span>
        <span style={{ fontSize: 11, padding: "1px 6px", borderRadius: 5, background: "rgba(251,191,36,.12)", color: amb, flexShrink: 0 }}>按量 · 扣余额</span>
        <span style={{ fontFamily: MONO, fontSize: 11, color: muted, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
          {g.host} · {mine.length} 个账户
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: isExit ? acc : p.label, flexShrink: 0 }}>
          {isExit && exitId ? `出口 · ${nm(exitId)}` : "空闲 · 不扣钱"}
        </span>
      </div>
      {bannerEl}

      <div style={{ display: "flex", flexDirection: "column", opacity: dim }}>
        <div style={{ display: "grid", gridTemplateColumns: tcols, gap: 8, fontSize: 11, color: muted, padding: "0 8px 4px" }}>
          <span>账户</span><span>key</span><span style={{ textAlign: "right" }}>余额</span><span style={{ textAlign: "right" }}>还能撑</span>
          <span style={{ textAlign: "right" }}>今日实扣</span><span style={{ textAlign: "right" }}>出口</span>
        </div>
        {mine.map((r) => {
          const e = ent(r.id), d = e?.data;
          const me = exitId === r.id;
          const dd = runDays(d?.balance, d?.runway?.days);
          const off = !r.enabled;
          return (
            <div key={r.id} data-relay={r.id} data-relay-current={me ? "1" : undefined}
                 style={{ position: "relative", display: "grid", gridTemplateColumns: tcols, gap: 8, alignItems: "center", height: 32,
                          padding: "0 8px", borderRadius: 7, fontFamily: MONO, fontSize: 12, opacity: off ? 0.45 : 1,
                          background: me ? "rgba(45,212,191,.07)" : "transparent" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                <span style={{ fontFamily: "inherit", fontWeight: 600, fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis" }}>{r.label}</span>
                {off && <span data-relay-off style={{ fontSize: 10, color: p.label, border: `1px solid ${p.idleBorder}`, padding: "0 5px", borderRadius: 4, flexShrink: 0 }}>停用</span>}
              </span>
              {/* ★ 只出指纹的可读前缀，sha256 前 12 位放 title（`store.fingerprint` 刻意不出 key 尾巴；稿画了明文尾巴，不照抄）。 */}
              <span title={`${r.base_url} · ${r.key_fp}`} style={{ color: muted, overflow: "hidden", textOverflow: "ellipsis" }}>
                <span data-key-fp>{(r.key_fp ?? "").split(" (")[0]}</span>
              </span>
              <span style={{ textAlign: "right", fontWeight: 700, color: d?.balance === 0 ? bad : d?.balance == null ? muted : p.text }}>
                {money(d?.balance ?? null, d?.unit)}
                {/* ★★★ 余额是钱，「这是什么时候读的」必须跟着它走：取数失败时保留旧值并标 `*`。 */}
                {e?.stale && (
                  <span data-relay-balance-stale title={`这次没取到，显示的是上一次的读数${e.detail ? ` —— ${e.detail}` : ""}`}
                        style={{ color: amb, marginLeft: 2, cursor: "help" }}>*</span>
                )}
                {e?.ok === false && !e.data && !off && (
                  <span data-relay-balance-never title={`还没取到过：${e.detail ?? "原因未知"}`}
                        style={{ color: amb, marginLeft: 2, cursor: "help" }}>!</span>
                )}
              </span>
              <span title={dd == null ? (d?.runway?.reason ?? "样本不足") : undefined}
                    style={{ textAlign: "right", color: dd === 0 ? bad : p.text2 }}>{dd == null ? "—" : `${dd} 天`}</span>
              <span style={{ textAlign: "right" }}>{money(d?.today?.actual_cost ?? null, d?.unit)}</span>
              <span style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 4 }}>
                {me ? <span style={{ fontSize: 11.5, color: acc }}>● 出口</span>
                  : (
                    <button type="button" data-act={`set-exit:${r.id}`} disabled={off}
                            title={off ? `${r.label} 已停用，请先启用` : "之后每次 codex 请求都从这个账户扣余额"}
                            onClick={() => onExit(r.id)}
                            style={{ height: 22, padding: "0 8px", borderRadius: 6, border: `1px solid ${p.idleBorder}`, background: "transparent",
                                     color: p.text2, fontSize: 11.5, cursor: off ? "default" : "pointer", fontFamily: "inherit" }}>设为出口</button>
                  )}
                <span data-act={`menu:${r.id}`} role="button" title="更多"
                      onClick={() => setMenu((m) => (m === r.id ? null : r.id))}
                      style={{ width: 22, height: 22, borderRadius: 6, display: "grid", placeItems: "center", cursor: "pointer",
                               color: p.label, border: `1px solid ${p.idleBorder}`, fontSize: 11 }}>···</span>
              </span>
              {menu === r.id && (
                <div data-relay-menu={r.id} style={{ position: "absolute", right: 8, top: 30, zIndex: 10, width: 150, padding: 4, borderRadius: 9,
                                                     background: dark ? "#1b2330" : "#fff", border: `1px solid ${p.tipBorder}`,
                                                     boxShadow: dark ? "0 12px 30px rgba(0,0,0,.5)" : "0 12px 28px rgba(0,0,0,.14)",
                                                     fontFamily: "inherit" }}>
                  {[
                    { k: `test:${r.id}`, s: testing === `test:${r.id}` ? "测试中…" : "测试连接（免费）", f: () => onTest(r.id) },
                    { k: `edit:${r.id}`, s: "编辑", f: () => onEdit(r) },
                    { k: `toggle:${r.id}`, s: r.enabled ? "停用" : "启用", f: () => onToggle(r) },
                    { k: `del:${r.id}`, s: "删除", f: () => onRemove(r), red: true },
                  ].map((x) => (
                    <div key={x.k} data-act={x.k} role="button" onClick={() => { setMenu(null); x.f(); }}
                         style={{ padding: "7px 10px", borderRadius: 6, fontSize: 12, cursor: "pointer", color: x.red ? bad : p.text2 }}>{x.s}</div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {mine.length > 1 && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: p.label }}>看</span>
          <div role="group" aria-label="视角" style={{ display: "inline-flex", padding: 2, borderRadius: 8, gap: 2,
                                                       border: `1px solid ${dark ? "rgba(255,255,255,.12)" : "rgba(0,0,0,.12)"}`,
                                                       background: dark ? "#0e1117" : "#eef1f5" }}>
            {[{ k: "sum", s: "合计" }, ...mine.map((r) => ({ k: r.id, s: r.label }))].map((x) => (
              <button key={x.k} type="button" data-relay-view={x.k} aria-pressed={v === x.k} onClick={() => setView(x.k)}
                      style={{ height: 24, padding: "0 10px", borderRadius: 6, border: 0, fontSize: 12, cursor: "pointer", fontFamily: "inherit",
                               background: v === x.k ? p.accent : "transparent", color: v === x.k ? p.accentOn : p.text2 }}>{x.s}</button>
            ))}
          </div>
          <span style={{ fontSize: 11.5, color: muted, overflow: "hidden", textOverflow: "ellipsis" }}>
            {v === "sum" ? (bal.mixed ? "多币种，不可相加" : "各账户相加（同一平台、同一币种，实扣可以相加）")
              : v === exitId ? "当前出口账户" : "非出口账户 · 只读历史"}
          </span>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "210px minmax(0,1fr)", gap: 16, alignItems: "end", opacity: dim }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontSize: 12, color: p.label, display: "flex", alignItems: "center", gap: 6 }}>
            {v === "sum" ? "合计余额" : `${nm(v)} 余额`}
            {/* ★ 刷新放在余额旁边（就近可点）；与页头 ↻ 同一个 `useRelayUsage`。`/usage` 只读账单、不计费。 */}
            <span data-act="relay-balance-refresh" role="button"
                  onClick={(e) => { e.stopPropagation(); if (!usageBusy) onRefreshUsage(); }}
                  title={usageBusy ? "正在重取…" : "重新取一次余额与用量（只读账单，不计费）"}
                  style={{ fontFamily: MONO, fontSize: 11, color: usageBusy ? muted : p.label, cursor: usageBusy ? "default" : "pointer" }}>↻</span>
          </span>
          <span data-relay-balance style={{ fontFamily: MONO, fontSize: 32, fontWeight: 700, lineHeight: 1.1, color: balC }}>
            {bal.mixed ? "—" : money(bal.v, bal.unit)}
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
          <span style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
            <span style={{ fontSize: 12, color: p.label, flexShrink: 0 }}>还能撑</span>
            <span style={{ fontFamily: MONO, fontSize: 18, fontWeight: 700, color: runC, flexShrink: 0 }}>{days == null ? "—" : `${days} 天`}</span>
            <span style={{ fontSize: 11.5, color: muted, overflow: "hidden", textOverflow: "ellipsis" }}>
              {days == null ? (bal.mixed ? "多币种，不能合计" : bal.v == null ? "有账户余额读不到，没法估算" : reason ?? "活跃日样本不足")
                : `近 7 个活跃日日均实扣 ${money(perDay.v, perDay.unit)}`}
            </span>
          </span>
          <i style={{ height: 5, borderRadius: 3, background: p.track, overflow: "hidden", display: "block" }}>
            <i style={{ display: "block", height: "100%", borderRadius: 3, background: days === 0 ? bad : "#2dd4bf",
                        width: `${days ? Math.min(100, days * 2) : 0}%` }} />
          </i>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 8, opacity: dim }}>
        {kpi("今日实扣", money(tAct.v, tAct.unit), `牌价 ${money(tCost.v, tCost.unit)}${save ? ` · 省 ${save.toFixed(2)}×` : ""}`, { "data-kpi": "今日实扣" })}
        {kpi("本月实扣", mAct.v == null ? "—" : `${mFull ? "" : "≥ "}${money(mAct.v, mAct.unit)}`,
             mFull ? `牌价 ${money(mCost.v, mCost.unit)}` : "快照晚于月初，本月前几天没取到", { "data-kpi": "本月实扣" })}
        {kpi("今日请求", int(tReq), tTok == null ? "—" : `${tok(tTok)} token`, { "data-kpi": "今日请求" })}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4, opacity: dim }}>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 56px 64px 64px 64px", gap: 8, fontSize: 11, color: muted }}>
          <span>今日按模型</span><span style={{ textAlign: "right" }}>请求</span><span style={{ textAlign: "right" }}>token</span>
          <span style={{ textAlign: "right" }}>实扣</span><span style={{ textAlign: "right" }}>牌价</span>
        </div>
        {models == null && <span data-relay-models-none={tm.why ?? ""} style={{ fontSize: 12, color: p.label }}>
          {tm.why === "mixed" ? "多币种，按模型的金额不可相加 —— 切到单个账户看" : "今天的按模型明细没取到（不是今天没用过）"}</span>}
        {models != null && models.length === 0 && <span style={{ fontSize: 12, color: p.label }}>今天还没有请求</span>}
        {models?.map((m) => (
          <div key={m.model} data-relay-model={m.model}
               style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 56px 64px 64px 64px", gap: 8, height: 22, alignItems: "center",
                        fontFamily: MONO, fontSize: 12 }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{m.model}</span>
            <span style={{ textAlign: "right", color: p.text2 }}>{m.requests}</span>
            <span style={{ textAlign: "right", color: p.text2 }}>{tok(m.total_tokens)}</span>
            <span style={{ textAlign: "right", fontWeight: 700 }}>{money(m.actual_cost, bal.unit)}</span>
            <span style={{ textAlign: "right", color: muted }}>{money(m.cost, bal.unit)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
