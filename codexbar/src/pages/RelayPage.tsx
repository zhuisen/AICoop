import React, { useEffect, useMemo, useState } from "react";
import type { Theme } from "../theme";
import RelayUsage from "../components/RelayUsage";
import GhostButton from "../components/GhostButton";
import Toast from "../components/Toast";
import { IcRefresh } from "../components/CardIcons";
import RouteMap, { type EntryInfo } from "../components/relay/RouteMap";
import PoolDetail from "../components/relay/PoolDetail";
import RelayDetail from "../components/relay/RelayDetail";
import { RelayForm } from "../components/relay/RelayBits";
import { ConfirmDelete } from "../components/ov/OvLayers";
import { ovVars } from "../components/ov/ovVars";
import { useRelayUsage } from "../hooks/useRelayUsage";
import { useRelayConfig } from "../hooks/useRelayConfig";
import { useIntegration } from "../hooks/useIntegration";
import { useRotationBoard } from "../hooks/useRotationBoard";
import { useReqLedger } from "../hooks/useReqLedger";
import { invalidateSidecar } from "../hooks/useQuotaSidecar";
import { useStore } from "../hooks/useStore";
import { relayRouteNote, type RelayRow } from "../relay";
import { costOf } from "../rates";
import { agoText, groupRelays, hm, int } from "../relayView";
import { titleSize } from "../tokenView";
import { MONO, tkPal } from "../components/tk/tkPal";
import { useWidth, useWinDensity } from "./TrafficPage";
import "../components/relay/relay.css";

/**
 * 中转站 · AICoop P8（阶段 5）1:1 复刻 `~/Downloads/AICoop_handoff/boards/08_relay/P8_RB`。
 * 规格摘录 `scratch/aicoop_20261021/P7P8_extract.md` P8-*；偏离逐条在 `PLAN.md` 第 42 条（P8-*）。
 *
 * 结构：标题行 → 路由图（入口 · 本地代理 · 两个出口，当前出口实线流动）→ 两个出口各一块明细 → 可折叠的「用量」趋势块。
 * 这一页仍是全 app 唯一会**改变钱去哪儿**的地方：切到中转站 = 之后每次 codex 都扣余额。
 *
 * ## ★★ 底层是「一个 provider，两种上游」
 * codex 永远只看见 `rotateproxy` 一个 `model_provider`，账号池 ↔ 中转站的切换发生在**代理内部**
 * （`proxy.py::_relay_upstream`），所以 `codex resume` 的会话列表不会分裂。出口单选（账号池与各中转站账户互斥）。
 *
 * ## 演进留档
 * ① 拆进总览 + 用量两页 → 用户否；② 单页平铺 → 用户否（「两个版块切换」）；③ 账号 | 用量两块 Seg；
 * ④ 2026-10-22 P8：一页（路由图 + 明细），用量趋势收进页底可折叠块（偏离 P8-9，稿要求「趋势去 Token 消耗看」，
 *    在那边接入之前不删）。
 */
export default function RelayPage({ t, onOpenOverview }: { t: Theme; onOpenOverview?: () => void }): React.ReactElement {
  const p = tkPal(t);
  const { L, W } = useWinDensity();
  const [host, cw] = useWidth<HTMLDivElement>();
  const { cfg, note, setNote, acting, act } = useRelayConfig();
  const { snap, busy: usageBusy, refresh: refreshUsage } = useRelayUsage();
  const store = useStore();
  const { integration } = useIntegration();
  const { board } = useRotationBoard(true);
  const { rows: reqs, ok: reqOk } = useReqLedger();
  const [editing, setEditing] = useState<Partial<RelayRow> | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [delAsk, setDelAsk] = useState<RelayRow | null>(null);
  const [usageOpen, setUsageOpen] = useState(false);

  useEffect(() => {
    if (!toast) return;
    const h = setTimeout(() => setToast(null), 1800);
    return () => clearTimeout(h);
  }, [toast]);

  const relays = cfg?.relays ?? [];
  const route = cfg?.route;
  const exitId = route?.state === "relay" ? (route.profile ?? null) : null;
  const usage = snap?.relays ?? [];
  const groups = useMemo(() => groupRelays(relays), [relays]);

  /** ★★ 改完配置**立刻**让用量重取。不然「已停用」与 KPI 里还加着它的余额最长 5 分钟同时挂在屏幕上。 */
  const afterConfigChange = (msg: string): void => {
    setToast(msg);
    invalidateSidecar("run_relay_usage");
  };
  const pick = async (target: string, msg: string): Promise<void> => {
    const d = await act("route", target);
    // ★★ 失败的原因藏在 `route.detail` 里（`cmd_route` 的 payload 顶层没有 detail）。
    if (d && d.ok === false) {
      const rt = d.route as { detail?: string } | undefined;
      setNote("✗ " + (d.detail || rt?.detail || d.state || "未知错误"));
      return;
    }
    if (d) afterConfigChange(msg);
  };
  const toPool = () => void pick("pool", "已切换到账号池 · 逐请求轮换");
  const toRelay = (id: string) => {
    const r = relays.find((x) => x.id === id);
    if (!r) return;
    if (!r.enabled) { setToast(`${r.label} 已停用，请先启用`); return; }
    void pick(id, `已切换到中转站 · ${r.label}`);
  };

  // ── 今天（本机自然日）的账本：每入口次数、账号池今日请求 / token / 等效牌价 ──────────────
  const today = useMemo(() => {
    const mid = new Date(); mid.setHours(0, 0, 0, 0);
    const t0 = mid.getTime() / 1000;
    const pool = new Set(store.accounts.map((a) => a.node));
    const cx = reqs.filter((r) => r.platform === "codex" && r.t_end >= t0);
    const viaPool = cx.filter((r) => r.account != null && pool.has(r.account));
    let cost = 0, tokN = 0;
    for (const r of viaPool) {
      const inp = r.input ?? 0, cached = r.cached ?? 0, out = r.output ?? 0;
      tokN += inp + out;
      cost += costOf({ uncached_in: Math.max(0, inp - cached), cache_read: cached, cache_write: 0, output: out }, r.model ?? "", "codex");
    }
    // ★ 出口是中转站时，代理不给这些响应写账号归属（`affinity` 只记池子里的号），账本把它们记成「直连」——
    //   与真直连分不开（评审 gemini 阶段 5）。所以那时按来源整数、直连写「—」，不拿一个混了中转站的数冒充。
    const relayOn = exitId != null;
    return {
      inter: cx.filter((r) => r.source === "交互" && (relayOn || r.account !== "直连")).length,
      exec: cx.filter((r) => r.source === "exec" && (relayOn || r.account !== "直连")).length,
      direct: relayOn ? null : cx.filter((r) => r.source === "交互" && r.account === "直连").length,
      pool: { requests: reqOk ? viaPool.length : null, tokens: reqOk ? tokN : null, cost: reqOk ? cost : null },
    };
  }, [reqs, reqOk, store.accounts, exitId]);

  const exitRow = exitId ? relays.find((r) => r.id === exitId) : null;
  const exitName = exitRow ? exitRow.label : "账号池";
  const activeLabel = store.accounts.find((a) => a.aid === store.state?.active)?.node ?? "—";
  const n = (x: number | null) => (reqOk && x != null ? `${x} 次` : "—");
  // ★ 入口（偏离 P8-3）：`\codex` 走代理（PATH wrapper 统一注入 `--profile rotateproxy`）；VS Code 不经过代理。
  //   `cxp exec` 与 `omc ask codex` 在账本里分不开（originator 都是 codex_cli_rs）⇒ 合成一行。
  const entries: EntryInfo[] = [
    { cmd: "codex", tag: "走代理", direct: false,
      rows: [{ k: "走向", v: "代理 · 自动轮换", c: "acc" }, { k: "今日", v: n(today.inter) }, { k: "出口", v: exitName }] },
    { cmd: "cxp exec · omc", tag: "走代理", direct: false,
      rows: [{ k: "走向", v: "代理 · 非交互", c: "acc" }, { k: "今日", v: n(today.exec) },
             { k: "含", v: "omc ask codex（分不开）", c: "muted" }, { k: "出口", v: exitName }] },
    { cmd: "\\codex", tag: "走代理", direct: false,
      rows: [{ k: "走向", v: "代理 · 跳过别名", c: "acc" }, { k: "今日", v: "计入 codex", c: "muted" }, { k: "出口", v: exitName }] },
    { cmd: "cxd", tag: "单号直连", direct: true,
      rows: [{ k: "走向", v: "单号直连", c: "warn" }, { k: "常用于", v: "/usage · 重置卡" },
             { k: "用哪个号", v: `auth.json · ${activeLabel}` }, { k: "今日直连", v: n(today.direct) }] },
    { cmd: "VS Code", tag: "不经过代理", direct: true,
      rows: [{ k: "走向", v: "原生 · 不经过代理", c: "warn" }, { k: "原因", v: "自带二进制、不走 PATH" },
             { k: "轮换", v: "不参与", c: "muted" }, { k: "扣的是", v: "订阅额度（当前号）" }] },
  ];

  const listening = integration?.checks.find((c) => c.id === "listening")?.state ?? "unknown";
  const port = integration?.port || 8011;
  const proxyText = `127.0.0.1:${port} · ${listening === "ok" ? "运行中" : listening === "bad" ? "没在听" : "判定不了"}`;
  const exitEntry = exitId ? usage.find((u) => u.id === exitId) : null;
  const flowN = exitId ? exitEntry?.data?.today?.requests ?? null : today.pool.requests;
  const flowText = `今日 ${int(flowN)} 请求`;
  const burst = board?.burst?.now_min ?? null;
  const poolSub = `${store.counts.total} 个号 · 全池续航 ${hm(burst)}`;

  // 新鲜度：最近一次成功取余额的时刻；有任一家取数失败（stale）⇒ 琥珀「⚠ N 前 · 取数失败」。
  const stale = usage.find((u) => u.stale);
  const fetchedAt = usage.map((u) => u.data?.fetched_at).filter((x): x is number => x != null).reduce((a, b) => Math.max(a, b), 0) || null;
  const nowSec = Date.now() / 1000;
  const fresh = stale ? `⚠ ${agoText(stale.stale_since ?? fetchedAt, nowSec)} · 取数失败` : fetchedAt ? `余额 ${agoText(fetchedAt, nowSec)}` : "余额未取过";

  // ★★★ 路由异常态必须在这里出声（稿没画）：`orphan` / `relay_disabled` / `route_corrupt` 下代理会退回账号池，
  //   `profile_missing` 下 codex 不报错、直接退回 base 配置。健康两态不显示（常亮告警会被训练成噪音）。
  const n0 = route ? relayRouteNote(route) : null;
  const rnote = route && route.state !== "pool" && route.state !== "relay" ? n0 : null;

  return (
    <div data-page-body="relay" data-relay-page data-section="relay" ref={host}
         style={{ height: "100%", overflowY: "auto", display: "flex", flexDirection: "column", gap: 12,
                  padding: `0 ${L < 2 ? 6 : 0}px 12px`, whiteSpace: "nowrap" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, height: 34, flexShrink: 0, minWidth: 0 }}>
        {/* ★ 标题字号随宽度 26 / 24 / 22，与 P7 同族（稿 P8 三档都是 26，稿内不一致，偏离 P8-1）。 */}
        <h1 style={{ margin: 0, fontSize: titleSize(W), fontWeight: 700, flexShrink: 0 }}>中转站</h1>
        {L < 2 && (
          <span style={{ fontSize: 12.5, color: p.label, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
            出口二选一：账号池 / 中转站 · 点右侧节点切换
          </span>
        )}
        <span style={{ flex: 1 }} />
        {L < 2 && (
          <span data-act="relay-refresh" role="button" onClick={() => { if (!usageBusy) void refreshUsage(); }}
                title="点击重取余额与用量（只读账单，不计费）"
                style={{ fontSize: 12, fontFamily: MONO, color: stale ? (t.isDark ? "#fbbf24" : "#9a6512") : p.label, cursor: "pointer", flexShrink: 0 }}>
            {fresh}
          </span>
        )}
        {/* ★★ 「刷新余额」按钮保留（用户 2026-09-21：「没看到刷新，或者刷新不显眼」）—— 与总览「刷新全池」同一个 GhostButton。 */}
        <span data-act="relay-refresh-header" style={{ flexShrink: 0 }}>
          <GhostButton t={t} onClick={() => void refreshUsage()} loading={usageBusy} loadingText="取余额中…">
            <IcRefresh size={13} spin={usageBusy} />刷新余额
          </GhostButton>
        </span>
        <button type="button" data-act="add" onClick={() => setEditing({})}
                style={{ height: 30, padding: "0 12px", borderRadius: 8, border: "1px solid rgba(45,212,191,.5)", background: "transparent",
                         display: "inline-flex", alignItems: "center",
                         color: t.isDark ? "#5eead4" : "#0e7a6e", fontSize: 13, cursor: "pointer", flexShrink: 0, fontFamily: "inherit" }}>
          + 新增中转站
        </button>
      </div>

      {note && <div data-card="note" style={{ fontSize: 12, color: p.down, flexShrink: 0, whiteSpace: "normal" }}>{note}</div>}
      {/* ★ 读失败与「没配过」必须分开。后者是一句关于事实的假陈述。 */}
      {cfg === null && (
        <div data-card="cfgerr" style={{ fontSize: 12.5, color: t.isDark ? "#fbbf24" : "#9a6512", flexShrink: 0 }}>
          读不到中转站配置 —— <b>这不等于你没配过</b>。上面的红字是原因。
        </div>
      )}
      {rnote && (
        <div data-route-state={route?.state}
             style={{ fontSize: 12, lineHeight: 1.6, fontFamily: MONO, whiteSpace: "normal", flexShrink: 0,
                      color: rnote.tone === "warn" ? (t.isDark ? "#fbbf24" : "#9a6512") : p.down }}>
          <b>{rnote.title}</b> —— {rnote.body}
        </div>
      )}

      {cw > 0 && (
        <RouteMap t={t} entries={entries} exitId={exitId} poolSub={poolSub} groups={groups}
                  relays={relays} usage={usage} proxyText={proxyText} proxyTone={listening} flowText={flowText}
                  onPool={toPool} onRelay={toRelay} />
      )}
      {/* 生效范围（P8 把它画进了入口列表；这一行把「不生效」的那一半明说出来 —— 稿 Before 02 自己点名的问题）。 */}
      <div data-route-scope style={{ fontSize: 11.5, color: p.label, fontFamily: MONO, flexShrink: 0, whiteSpace: "normal", lineHeight: 1.6 }}>
        生效范围：codex / cxp exec / omc ask codex / \codex 走本地代理 ·
        <b style={{ color: t.isDark ? "#fbbf24" : "#9a6512" }}> 不生效：VS Code</b>（自带二进制、不走 PATH）· 单号直连用 cxd，不受此影响
      </div>

      <div style={{ display: "grid", gap: 12, alignItems: "stretch", flexShrink: 0,
                    gridTemplateColumns: W >= 1000 ? "minmax(0,1fr) minmax(0,1.25fr)" : "minmax(0,1fr)" }}>
        <PoolDetail t={t} isExit={exitId === null} accounts={store.accounts} inUse={store.inUseNode ?? store.currentNode ?? null}
                    next={board?.next?.label ?? null} burstMin={burst} today={today.pool} onOpenOverview={() => onOpenOverview?.()} />
        <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
          {cfg !== null && relays.length === 0 && !editing && (
            <div data-card="empty" style={{ borderRadius: 12, background: p.panel, border: `1px solid ${p.border}`, padding: "14px 16px",
                                            fontSize: 12.5, color: p.label, whiteSpace: "normal" }}>
              还没有中转站。点「+ 新增中转站」加一个 —— 加完它会作为一个出口出现在上面的路由图里。
            </div>
          )}
          {groups.map((g) => (
            <RelayDetail key={g.key} t={t} g={g} rows={relays} usage={usage} exitId={exitId} usageBusy={usageBusy}
                         onRefreshUsage={() => void refreshUsage()} onExit={toRelay} onPool={toPool} testing={acting}
                         onTest={(id) => void act("test", id).then((d) => {
                           if (d) setToast(d.ok ? `${relays.find((r) => r.id === id)?.label ?? id} 连接正常` : `✗ ${String(d.detail ?? d.state ?? "连接失败")}`);
                         })}
                         onEdit={(r) => setEditing({ ...r, key: "" } as Partial<RelayRow>)}
                         onToggle={(r) => {
                           // ★ 停用 / 启用走 CLI：真源是 relays.local.json，代理在 app 没开时也要读它。
                           void act("set", undefined, { ...r, key: "", enabled: !r.enabled }).then((d) => {
                             // ★ `ok:false` 是正常返回不是异常：写盘失败时不能说「已停用 · 出口回落到账号池」（评审 gemini 阶段 5）。
                             if (!d?.ok) return;
                             afterConfigChange(`${r.label} ${r.enabled ? "已停用" : "已启用"}` +
                               (r.enabled && exitId === r.id ? " · 出口回落到账号池" : ""));
                           });
                         }}
                         onRemove={(r) => setDelAsk(r)} />
          ))}
        </div>
      </div>

      {editing && (
        <RelayForm t={t} editing={editing} setEditing={setEditing} groups={groups.map((g) => g.name)}
                   onSave={(payload) => act("set", undefined, payload).then((d) => {
                     if (d?.ok) afterConfigChange("已保存");
                     return d;
                   })}
                   acting={acting === "set"} />
      )}

      {/* 用量趋势（偏离 P8-9）：稿说「趋势去 Token 消耗看」，那边还没有中转站来源 ⇒ 先折叠在这里，不删。
          ★★ 折叠用 CSS 可见性，不用条件渲染（§5c：`RelayUsage` 的档位是本地 state，`--dump-dom` 的闸要看得到它）。 */}
      <section style={{ borderRadius: 12, background: p.panel, border: `1px solid ${p.border}`, padding: "10px 16px", flexShrink: 0 }}>
        <div data-relay-tabs style={{ display: "flex", alignItems: "center", gap: 10, height: 26 }}>
          <span role="button" data-act="relay-usage-toggle" aria-expanded={usageOpen} onClick={() => setUsageOpen((o) => !o)}
                style={{ fontSize: 14, fontWeight: 600, cursor: "pointer" }}>用量</span>
          <span style={{ fontSize: 12, color: p.label }}>按天趋势 · 按模型 · 实扣口径</span>
          <span style={{ flex: 1 }} />
          <span role="button" onClick={() => setUsageOpen((o) => !o)} style={{ fontSize: 12, color: p.label, cursor: "pointer" }}>
            {usageOpen ? "收起 ▴" : "展开 ▾"}
          </span>
        </div>
        <div style={{ display: usageOpen ? "block" : "none", marginTop: 10, whiteSpace: "normal" }}>
          <RelayUsage t={t} />
        </div>
      </section>

      {delAsk && (
        <div style={ovVars(t.isDark) as React.CSSProperties}>
          {/* ★ 删除 = 确认框，默认焦点在「取消」（ui.md「以后任何不可逆的确认」）。删掉的中转站要重新填 key 才能回来。 */}
          <ConfirmDelete title={`删除 ${delAsk.label}？`}
                         body={<>这把 key 会从本机登记表里删除{exitId === delAsk.id ? "，出口回落到账号池" : ""}。要再用得重新填 endpoint 与 key。</>}
                         onCancel={() => setDelAsk(null)}
                         onConfirm={() => {
                           const r = delAsk;
                           setDelAsk(null);
                           void act("remove", r.id).then((d) => { if (d?.ok) afterConfigChange(`已删除 ${r.label}`); });
                         }} />
        </div>
      )}
      {toast && <Toast msg={toast} t={t} />}
    </div>
  );
}
