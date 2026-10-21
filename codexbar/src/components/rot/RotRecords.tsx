import { useState } from "react";
import type { Theme } from "../../theme";
import { type Rec, type RecFilter, type RecKind, type RotLayout, clockOf, logLevel, logsAround, mins, recCounts, recMatches } from "../../rotationView";
import { MONO, tkPal } from "../tk/tkPal";
import { BAD, WARN } from "./RotTimeline";
import type { SvcLine } from "./rotTypes";

/**
 * 记录类型 → 标签（稿 §1.6）。★ 状态色用全局语义色（偏离 P7-3）。
 * ★★ 三类失败的计费含义完全不同，颜色必须一眼分得开（`CLAUDE.md` §8「计费相位分界」）：
 *   断流 = 已计费（琥珀）· **计费未知 = 可能已计费（红，唯一的危险级）** · 安全换号 = 没计费（中性）。
 * ★ 「Pro 保底」用紫色（与 PRO 同系），不用红 —— 它是**按设计工作**，染红会训练用户忽略真告警。
 */
export const EV_STYLE: Record<RecKind, { label: string; color: string; bg: string; ring?: string }> = {
  err: { label: "轮换", color: WARN, bg: "rgba(224,144,28,.14)" },
  fail: { label: "故障转移", color: BAD, bg: "transparent", ring: "inset 0 0 0 1px rgba(224,82,77,.6)" },
  switch: { label: "切换", color: "#aab3c0", bg: "rgba(255,255,255,.07)" },
  pro: { label: "Pro 保底", color: "#8b7cf6", bg: "rgba(139,124,246,.16)" },
  "429": { label: "429 冷却", color: BAD, bg: "rgba(224,82,77,.14)" },
  stream: { label: "断流", color: WARN, bg: "rgba(224,144,28,.14)" },
  billed: { label: "计费未知", color: BAD, bg: "rgba(224,82,77,.14)" },
  safe: { label: "安全换号", color: "#8a93a0", bg: "rgba(255,255,255,.06)" },
  probe: { label: "探活", color: "#8a93a0", bg: "rgba(255,255,255,.06)" },
};

const FILTERS: { k: RecFilter; name: string }[] = [
  { k: "all", name: "全部" }, { k: "switch", name: "切换" }, { k: "fail", name: "故障转移" },
  { k: "429", name: "429" }, { k: "err", name: "断流" },
];
const RAW_FILTERS = ["all", "refresh", "switch", "cool"] as const;

/**
 * 轮换记录（单栏，稿 §1.6）：时间 · 类型 · 「A → B · 原因」· 上号时长；点一条展开该时刻前后 90 s 的原始日志。
 * 「原始日志」开关打开后**替换**记录列表（内容同源），并保留旧运行日志的 refresh / switch / cool 筛选（偏离 P7-14）。
 */
export default function RotRecords({ t, recs, logs, lay, num, isAgy, focus, long }: {
  t: Theme; recs: Rec[]; logs: SvcLine[]; lay: RotLayout; num: string; isAgy: boolean;
  focus: string | null; long: boolean;
}) {
  const p = tkPal(t);
  const [filter, setFilter] = useState<RecFilter>("all");
  const [open, setOpen] = useState<string>("first");
  const [raw, setRaw] = useState(false);
  const [rawF, setRawF] = useState<(typeof RAW_FILTERS)[number]>("all");
  const counts = recCounts(recs);
  // ★ Gemini 没有代理，没有 429 / 断流事件 ⇒ 那两个 chip 不画（画成「0」= 说它确实没发生过）。
  const base = isAgy ? FILTERS.filter((f) => f.k !== "429" && f.k !== "err") : FILTERS;
  const filters = counts.billed > 0 ? [...base, { k: "billed" as RecFilter, name: "计费未知" }] : base;
  // ★ 选中的 chip 被藏起来（换到 Gemini / 计费未知归零）⇒ 回到「全部」，不许留一个看不见的筛选把列表筛空（评审 gemini 阶段 5）。
  const fk = filters.some((f) => f.k === filter) ? filter : "all";
  const shown = recs.filter((r) => recMatches(r.kind, fk));
  const openKey = open === "first" ? shown[0]?.key ?? "" : open;
  const lv = (text: string) => {
    if (text.includes("✗")) return p.down;
    const k = logLevel(text);
    return k === "bad" ? p.down : k === "warn" ? (t.isDark ? "#f5b544" : "#9a6512") : k === "ok" ? num : p.text2;
  };
  const rawRows = rawF === "all" ? logs : logs.filter((l) => l.text.toLowerCase().includes(rawF));
  const timeOf = (l: SvcLine) => (l.t === null ? "—" : (l.inferred ? "~" : "") + clockOf(l.t, true));
  const timeTitle = (l: SvcLine) => (l.t === null ? "这一行日志没有时间戳"
    : l.inferred ? "该源的日志只有时分秒、没有日期，这个日期是按「时间倒退＝跨日」推出来的" : undefined);

  return (
    <section data-rot-records style={{ borderRadius: 12, background: p.panel, border: `1px solid ${p.border}`,
                                       padding: "12px 16px", display: "flex", flexDirection: "column", gap: 6,
                                       flex: "1 1 0", minHeight: 120 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, height: 28, flexShrink: 0, minWidth: 0 }}>
        <span style={{ fontSize: 14, fontWeight: 600, flexShrink: 0 }}>{raw ? "原始日志" : "轮换记录"}</span>
        <span style={{ fontSize: 12, fontFamily: MONO, color: p.label, flexShrink: 0 }}>
          {raw ? `${rawRows.length} 条` : `${shown.length} 条${long ? " · 最近 24h" : ""}`}{focus && !raw ? ` · 仅 ${focus}` : ""}
        </span>
        <span style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: 6, minWidth: 0, overflowX: "auto", scrollbarWidth: "none" }}>
          {!raw && filters.map((f) => {
            const on = fk === f.k, red = f.k === "billed";
            return (
              <button key={f.k} type="button" data-rec-filter={f.k} aria-pressed={on}
                      onClick={() => { setFilter(f.k); setOpen("first"); }}
                      style={{ height: 24, padding: "0 10px", borderRadius: 12, fontSize: 12, fontFamily: "inherit", cursor: "pointer",
                               flexShrink: 0, border: `1px solid ${red ? "rgba(224,82,77,.6)" : on ? p.selAllBorder : p.idleBorder}`,
                               background: on ? p.selAll : "transparent", color: red ? BAD : on ? p.text : p.text2 }}>
                {f.name} {counts[f.k]}
              </button>
            );
          })}
          {raw && RAW_FILTERS.map((f) => {
            const on = rawF === f;
            return (
              <button key={f} type="button" data-raw-filter={f} aria-pressed={on} onClick={() => setRawF(f)}
                      style={{ height: 24, padding: "0 10px", borderRadius: 12, fontSize: 12, fontFamily: MONO, cursor: "pointer",
                               flexShrink: 0, border: `1px solid ${on ? p.selAllBorder : p.idleBorder}`,
                               background: on ? p.selAll : "transparent", color: on ? p.text : p.text2 }}>
                {f === "all" ? "全部" : f}
              </button>
            );
          })}
        </div>
        <button type="button" data-raw-toggle aria-pressed={raw} onClick={() => setRaw((x) => !x)}
                style={{ height: 24, padding: "0 10px", borderRadius: 6, marginLeft: 6, flexShrink: 0, cursor: "pointer",
                         border: `1px solid ${t.isDark ? "rgba(255,255,255,.12)" : "rgba(0,0,0,.12)"}`,
                         background: raw ? p.selAll : "transparent", color: p.text2, fontFamily: MONO, fontSize: 11.5 }}>
          原始日志
        </button>
      </div>

      <div data-rec-list style={{ flex: "1 1 0", minHeight: 0, overflowY: "auto" }}>
        {!raw && shown.length === 0 && <div style={{ fontSize: 12, color: p.text2, padding: "12px 0" }}>无轮换记录</div>}
        {!raw && shown.map((r) => {
          const st0 = EV_STYLE[r.kind];
          // 中性三类（切换 / 安全换号 / 探活）在浅色主题上走主题中性色，白底上的白 7% 底色看不见。
          const neutral = st0.color === "#aab3c0" || st0.color === "#8a93a0";
          const st = neutral ? { ...st0, color: p.text2, bg: p.selAll } : st0;
          const isOpen = r.key === openKey;
          const around = isOpen ? logsAround(logs, r.t) : null;
          return (
            <div key={r.key}>
              <div data-rec={r.kind} role="button" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? "" : r.key)}
                   style={{ display: "grid", gridTemplateColumns: "14px 52px 76px minmax(0,1fr) auto", columnGap: 12, alignItems: "center",
                            height: 32, borderTop: `1px solid ${p.hair}`, cursor: "pointer",
                            background: isOpen ? (t.isDark ? "rgba(255,255,255,.03)" : "rgba(0,0,0,.025)") : "transparent" }}>
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
                     style={{ transform: `rotate(${isOpen ? 90 : 0}deg)`, transition: "transform .18s ease-out" }}>
                  <path d="M3.5 2l3 3-3 3" stroke={p.label} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span style={{ fontFamily: MONO, fontSize: 12.5, color: p.label }}>{clockOf(r.t)}</span>
                <span style={{ justifySelf: "start", fontSize: 11.5, padding: "2px 8px", borderRadius: 6, color: st.color,
                               background: st.bg, boxShadow: st.ring ?? "none", whiteSpace: "nowrap" }}>{st.label}</span>
                <span title={r.head} style={{ fontSize: 13, color: p.text, overflow: "hidden", textOverflow: "ellipsis" }}>{r.head}</span>
                {lay.showMeta && !isAgy && r.onDuty != null
                  ? <span style={{ fontFamily: MONO, fontSize: 12, color: p.label }}>上号 {mins(r.onDuty)}</span> : <span />}
              </div>
              {isOpen && (
                <div data-rec-open style={{ margin: "0 0 6px 26px", padding: "6px 10px", borderRadius: 8,
                                            background: t.isDark ? "#0e1117" : "rgba(0,0,0,.03)",
                                            border: `1px solid ${p.hair}`, display: "flex", flexDirection: "column" }}>
                  {/* ★ 原文案后半「上号 4m / 0.0M / 26 次」说的是**上一个号**这一段；稿的 meta 改成了接班号的时长，
                      这句挪到这里（信息不丢）。 */}
                  {r.prevStats && (
                    <div style={{ fontSize: 11.5, fontFamily: MONO, color: p.text2, height: 22, display: "flex", alignItems: "center" }}>
                      {r.from ?? "上一个号"} 这一段：{r.prevStats.replace(/^上号 /, "")}
                    </div>
                  )}
                  {around && around.rows.length === 0 && (
                    <div style={{ fontSize: 11.5, fontFamily: MONO, color: p.label, height: 22, display: "flex", alignItems: "center" }}>
                      {isAgy ? "前后 90 秒没有日志行" : "前后 90 秒没有日志行（代理只写失败与冷却，不写「换号」这一行）"}
                    </div>
                  )}
                  {around?.rows.map((l, i) => (
                    <div key={i} style={{ display: "grid", gridTemplateColumns: "64px 52px minmax(0,1fr)", columnGap: 10, height: 22,
                                          alignItems: "center", fontFamily: MONO, fontSize: 11.5 }}>
                      <span title={timeTitle(l)} style={{ color: i === around.mark ? num : p.label }}>{timeOf(l)}</span>
                      <span style={{ color: p.label, overflow: "hidden" }}>{l.src}</span>
                      <span title={l.text} style={{ color: lv(l.text), overflow: "hidden", textOverflow: "ellipsis" }}>{l.text}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {raw && rawRows.length === 0 && <div style={{ fontSize: 12, color: p.text2, padding: "12px 0" }}>无匹配日志</div>}
        {raw && rawRows.map((l, i) => (
          <div key={i} data-raw-line style={{ display: "grid", gridTemplateColumns: "64px 60px minmax(0,1fr)", columnGap: 12,
                                              height: 28, alignItems: "center", borderTop: `1px solid ${p.hair}`, fontFamily: MONO, fontSize: 12 }}>
            {/* ★ `~` = 时间是推出来的（该源只有 HH:MM:SS）；`—` = 这一行真的没有时间（dawnprobe.log）。 */}
            <span title={timeTitle(l)} style={{ color: p.label }}>{timeOf(l)}</span>
            {/* ★ 来源：多源合流之后，不标来源就分不出「代理没换号」和「quotad 没扫到」。 */}
            <span title={`来源：${l.src}`} style={{ color: p.label, overflow: "hidden", textOverflow: "ellipsis" }}>{l.src}</span>
            {/* ★ `✗` 是 agy 那侧统一的失败标记；失败行和成功行同色，等于把「成功与否」藏起来。 */}
            <span title={l.text} style={{ color: l.text.includes("✗") ? p.down : lv(l.text), overflow: "hidden", textOverflow: "ellipsis" }}>{l.text}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
