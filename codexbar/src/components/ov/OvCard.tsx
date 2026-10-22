import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { OvState } from "../../overview";
import { ovIsLow } from "../../overview";
import { probeShouldFire } from "../../mbLogic";
import DragHandle, { type DragWiring } from "../DragHandle";
import type { Theme } from "../../theme";
import { MONO } from "./ovVars";
import { IcRefresh } from "../CardIcons";

/**
 * 总览账号卡的**外壳**（交接包 page5「账号卡（固定 148 高，5 行槽位 + 底栏）」）。
 *
 * ★★ 高度由构造保证，不由内容决定：5 个槽位各有固定高（22/18/18/18/18）、底栏 28，
 *   外框 `height: 148` + `justify-content: space-between`。状态再多也只换**槽位里的内容**，
 *   不加行、不减行 —— 未探测 / 只读 / 已停用 / 只有周额度，一律用占位填满（README §5 第一条）。
 * ★★ 悬停时**底栏原位换成操作**（`.ov-fdef` ↔ `.ov-fact` 叠在同一个 28 高的盒子里），
 *   卡片尺寸不变、不弹浮层盖数据 —— 它取代了 v1.6 起的「点开卡片 → 半透明动作条浮层 + 5 秒自动收回」
 *   （`CardActionBar` 已整体删除，ui.md §5c「删组件连同本体」）。
 * ★ 键盘：卡片 `tabIndex=0`，`:focus-within` 与悬停同一套样式 —— 键盘用户也拿得到操作
 *   （此前 0 个 `<button>` / 0 个 `:focus` 样式，memory.md §1b 记过）。
 */

export interface OvWin {
  label: string;
  /** 剩余 %；`null` = 读不到（画「—」）。 */
  pct: number | null;
  /** ↻ 后面的文字（`3h34m` / `6d6h`）；空 = 不画 ↻。 */
  reset: string;
  /** 不带 ↻ 的说法（`未启动` / `待确认`）。 */
  note?: string;
  title?: string;
  kind: "5h" | "w";
  /** 读数是沿用的旧值（agy `seen_at`）⇒ 整行降不透明度。 */
  dim?: boolean;
  /** 这一格整个不存在（只有周额度的平台的 5h）⇒ 空槽 + 「—」。 */
  absent?: boolean;
}

export interface OvTagSpec { text: string; kind: OvState | "ultra" | "best" }

const Check = () => (
  <svg width="10" height="10" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M5 12.5 10 17 19 7" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const IcBolt = ({ size = 12 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" fill="currentColor" />
  </svg>
);
/** 刷新图标只有一份（`CardIcons`，中转站页也用它）—— 两份 SVG 会漂且不报错。 */
export { IcRefresh };
export const IcMore = ({ size = 13 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <circle cx="5" cy="12" r="1.7" fill="currentColor" /><circle cx="12" cy="12" r="1.7" fill="currentColor" />
    <circle cx="19" cy="12" r="1.7" fill="currentColor" />
  </svg>
);
export const IcTicket = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M3 8a2 2 0 0 0 2-2h14a2 2 0 0 0 2 2v8a2 2 0 0 0-2 2H5a2 2 0 0 0-2-2Z" fill="currentColor" />
  </svg>
);

/** 环（原型：卡片 44 / r20 / 描边 4；正在使用 54 / r24.5 / 5）。`pct=null` ⇒ 空轨 + 顶上一个红点（未探测）。 */
export function OvRing({ size, r, sw, pct, color, numSize, dot }: {
  size: number; r: number; sw: number; pct: number | null; color: string; numSize: number;
  /** 未探测：不画弧，只在 12 点钟方向画一个红点（原型 `circle cy=2 r=2.2`）。 */
  dot?: boolean;
}) {
  const c = size / 2, circ = 2 * Math.PI * r;
  const p = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <span data-ov-ring={pct == null ? "—" : String(Math.round(p))}
          style={{ position: "relative", display: "block", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" style={{ display: "block" }}>
        <circle cx={c} cy={c} r={r} fill="none" stroke="var(--track)" strokeWidth={sw} />
        {pct != null && (
          <circle cx={c} cy={c} r={r} fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round"
                  strokeDasharray={`${((p / 100) * circ).toFixed(2)} ${circ.toFixed(2)}`}
                  transform={`rotate(-90 ${c} ${c})`} style={{ transition: "stroke-dasharray .5s cubic-bezier(.2,.9,.25,1)" }} />
        )}
        {pct == null && dot && <circle cx={c} cy={c - r} r={2.2} fill="var(--bad)" />}
      </svg>
      <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
                     fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: numSize, fontWeight: 600, color: "var(--tx)" }}>
        {pct == null ? "—" : Math.round(p)}
      </span>
    </span>
  );
}

/**
 * 环的颜色：停用灰 · 失效 / 额度低红 · 冷却琥珀 · 其余 = **平台识别色**
 * （交接截图 13/14/15：Gemini 蓝、Claude 橙、Grok 紫；Codex 的识别色恰好就是品牌青）。
 */
export function ringColor(state: OvState, pct: number | null, platColor?: string): string {
  if (state === "off") return "var(--tx3)";
  if (state === "dead" || ovIsLow(pct)) return "var(--bad)";
  if (state === "cool") return "var(--warn)";
  return platColor ?? "var(--acc)";
}
function borderOf(state: OvState, pct: number | null): string {
  if (state === "inuse") return "1px solid var(--ovBdIn)";
  if (state === "cool") return "1px solid var(--ovBdCool)";
  if (state === "unprobed" || state === "dead" || state === "low" || ovIsLow(pct)) return "1px solid var(--ovBdBad)";
  if (state === "off") return "1px dashed var(--line2)";
  return "1px solid var(--line)";
}

const TAG_STYLE: Record<string, { color: string; bg: string }> = {
  inuse: { color: "var(--acc)", bg: "var(--ovTagIn)" },
  next: { color: "var(--ovNextTx)", bg: "var(--acc)" },
  cool: { color: "var(--ovWarnTx)", bg: "var(--ovTagWarn)" },
  unprobed: { color: "var(--badTx)", bg: "var(--badBg)" },
  low: { color: "var(--badTx)", bg: "var(--badBg)" },
  dead: { color: "var(--badTx)", bg: "var(--badBg)" },
  off: { color: "var(--tx2)", bg: "var(--ovTagOff)" },
  readonly: { color: "var(--tx2)", bg: "var(--ovTagOff)" },
  best: { color: "var(--ovNum)", bg: "var(--ovTagBest)" },
};

/**
 * 状态标签。★ 文字变了（停轮换 ↔ 恢复、在用 ↔ 下一个）走 Swapping Text：旧字向上滑出、新字从下滑入，
 * 宽度与底色同步过渡（交接包 P5 §9：swOut .2s / swIn .26s，420 ms 后清掉旧字）。中文标签按「字数 × 11 + 14」定宽，
 * 宽度才过渡得起来；拉丁字（PRO / ULTRA）不定宽。
 */
export function OvTag({ tag, title }: { tag: OvTagSpec; title?: string }) {
  const last = useRef(tag);
  const [prev, setPrev] = useState<{ t: OvTagSpec; n: number } | null>(null);
  useEffect(() => {
    if (last.current.text === tag.text && last.current.kind === tag.kind) return;
    const was = last.current;
    last.current = tag;
    setPrev((p) => ({ t: was, n: (p?.n ?? 0) + 1 }));
    const id = window.setTimeout(() => setPrev(null), 420);
    return () => window.clearTimeout(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在文字 / 种类变了时换；`tag` 每次渲染都是新对象
  }, [tag.text, tag.kind]);
  if (tag.kind === "ultra") {
    return (
      <span data-ov-tag="ultra" title={title}
            style={{ fontSize: 10, fontWeight: 700, color: "#fff", background: "#8b5cf6", padding: "1px 6px",
                     borderRadius: 5, flexShrink: 0, letterSpacing: ".04em" }}>{tag.text}</span>
    );
  }
  const s = TAG_STYLE[tag.kind] ?? TAG_STYLE.off;
  // 「只读」不带锁：用户 2026-10-22 把锁读成「被锁住 / 没接通」，其实只是「单号、不换号」
  const icon = (k: string) => (k === "inuse" ? <Check /> : null);
  const cjk = /^[\u3400-\u9fff]+$/.test(tag.text);
  const width = cjk ? tag.text.length * 11 + 14 + (icon(tag.kind) ? 13 : 0) : undefined;
  const flip = prev ? (prev.n % 2 ? "a" : "b") : "";
  return (
    <span data-ov-tag={tag.kind} data-next-badge={tag.kind === "next" ? "" : undefined}
          data-rotate-off={tag.kind === "off" ? "" : undefined} title={title} className="ov-tag"
          style={{ position: "relative", display: "inline-flex", alignItems: "center", justifyContent: "center", height: 18,
                   width, padding: cjk ? 0 : "0 7px", boxSizing: "border-box", borderRadius: 6, overflow: "hidden",
                   fontSize: 11, fontWeight: 600, color: s.color, background: s.bg, flexShrink: 0 }}>
      {prev && (
        <span className={`ov-swl ov-sw-out-${flip}`} aria-hidden="true"
              style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 3,
                       color: (TAG_STYLE[prev.t.kind] ?? TAG_STYLE.off).color }}>
          {icon(prev.t.kind)}{prev.t.text}
        </span>
      )}
      <span className={prev ? `ov-swl ov-sw-in-${flip}` : "ov-swl"} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
        {icon(tag.kind)}{tag.text}
      </span>
    </span>
  );
}

/**
 * Progress 首次填充（交接包 P5 §9）：挂载 140 ms 后从 0 填到值（.7 s，周条晚 .06 s）；再过 900 ms 之后
 * 所有变化都走 `.4s ease-out`、不重播。减弱动态效果时 `.ov-bar` 的过渡被 CSS 关掉。
 */
function useFirstFill(): "wait" | "fill" | "done" {
  const [st, setSt] = useState<"wait" | "fill" | "done">("wait");
  useEffect(() => {
    const a = window.setTimeout(() => setSt("fill"), 140);
    const b = window.setTimeout(() => setSt("done"), 140 + 900);
    return () => { window.clearTimeout(a); window.clearTimeout(b); };
  }, []);
  return st;
}

/** ④ / ⑤ 槽：标签 · 4px 条 · % · ↻ 回满。 */
export function OvWinRow({ w, off }: { w: OvWin; off?: boolean }) {
  const fill = useFirstFill();
  const low = ovIsLow(w.pct);
  const bar = off ? "var(--tx3)" : low ? "var(--bad)" : w.kind === "5h" ? "var(--ovB5)" : "var(--ovBw)";
  return (
    <div data-ov-win={w.kind} data-agy-unknown={w.pct == null && !w.absent ? "" : undefined} title={w.title}
         style={{ display: "flex", alignItems: "center", gap: 8, height: 18, width: "100%", opacity: w.dim ? .62 : 1 }}>
      <span style={{ width: 14, fontSize: 11, color: "var(--tx3)", flexShrink: 0 }}>{w.label}</span>
      <span style={{ display: "block", flex: 1, minWidth: 0, height: 4, borderRadius: 4, background: "var(--track)", overflow: "hidden" }}>
        {w.pct != null && (
          <span className="ov-bar" style={{ display: "block", width: `${fill === "wait" ? 0 : Math.max(0, Math.min(100, w.pct))}%`,
                         height: "100%", borderRadius: 4, background: bar,
                         transition: fill === "done" ? "width .4s ease-out"
                           : `width .7s cubic-bezier(.22,1,.36,1)${w.kind === "w" ? " .06s" : ""}` }} />
        )}
      </span>
      <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", width: 34, textAlign: "right", fontSize: 11.5,
                     fontWeight: 600, flexShrink: 0,
                     color: w.pct == null ? "var(--ovPh)" : low ? "var(--badTx)" : "var(--tx)" }}>
        {w.pct == null ? "—" : `${Math.round(w.pct)}%`}
      </span>
      <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", width: 46, textAlign: "right", fontSize: 11, color: "var(--tx3)",
                     flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
        {w.pct == null ? (w.note ?? "") : w.reset ? `↻${w.reset}` : (w.note ?? "")}
      </span>
    </div>
  );
}

/** 一个槽位（固定高）。 */
export function Slot({ h, children, title, data }: { h: 18 | 22; children?: ReactNode; title?: string; data?: string }) {
  return (
    <div data-ov-slot={data} title={title} style={{ height: h, display: "flex", alignItems: "center", minWidth: 0 }}>{children}</div>
  );
}

/** ③ 动态行的文字（颜色按状态）。 */
export function DynText({ tone, children, title }: { tone: "live" | "muted" | "warn" | "bad"; children: ReactNode; title?: string }) {
  const color = tone === "live" ? "var(--ovNum)" : tone === "warn" ? "var(--ovWarnTx)" : tone === "bad" ? "var(--badTx)" : "var(--tx3)";
  return (
    <span data-ov-dyn={tone} title={title}
          style={{ display: "block", fontSize: 11.5, color, overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>
      {children}
    </span>
  );
}

export interface OvCardProps {
  id: string;
  state: OvState;
  ringPct: number | null;
  /** 只读平台（Grok）的环用平台色。 */
  platColor?: string;
  /** ① 名称行左侧（号名 + 状态标签）。 */
  head: ReactNode;
  /** ① 名称行右侧的角标（⊘ 停轮换 · 图钉）——排在环比之前。 */
  marks?: ReactNode;
  /** ① 右侧（环比 `-15%` / 「最优」）。★ 悬停时整个消失，给图钉让位（P5 §2.3）。 */
  right?: ReactNode;
  email: ReactNode;
  emailTitle?: string;
  dyn: ReactNode;
  w5: OvWin;
  ww: OvWin;
  footLeft: ReactNode;
  /** 默认底栏右侧（悬停时随左侧文字一起让位）。 */
  footRight?: ReactNode;
  /** 底栏最右、**悬停也不让位**的那一枚（Codex 的重置卡 chip：悬停时只缩字不挪位）。 */
  chip?: ReactNode;
  actions: ReactNode;
  /** 停了自动轮换：整卡 62%，悬停回到 1（P5 §2.1）。 */
  off?: boolean;
  /** 置顶号（`data-ov-pinned`）：拖拽排序只排「其余」区，置顶区的顺序由置顶先后决定。 */
  pinned?: boolean;
  /** 用卡成功的扫光（每次 +1 重播一次）。 */
  shine?: number;
  /** 弹层（重置卡 / ··· 菜单）打开：边框换琥珀 / 卡片抬到最上层、悬停态保持。 */
  popOpen?: boolean;
  /** harness 用：强制悬停态（`?ovhover=`）。 */
  hov?: boolean;
  menuOpen?: boolean;
  drag?: DragWiring;
  t: Theme;
  title?: string;
  onClick?: () => void;
}

export function OvCard(p: OvCardProps) {
  const cls = ["ov-card", p.hov ? "ov-hov" : "", p.menuOpen || p.popOpen ? "ov-menu-open" : "", p.drag?.isDragging ? "ov-dragging" : "",
               p.off ? "ov-off" : ""].filter(Boolean).join(" ");
  return (
    <div className={cls} data-aid={p.id} data-ov-card={p.state} data-ov-off={p.off ? "" : undefined}
         data-ov-pinned={p.pinned ? "" : undefined} data-flip={p.id} tabIndex={0} title={p.title} onClick={p.onClick}
         style={{ border: p.popOpen ? "1px solid rgba(251,191,36,.55)" : borderOf(p.state, p.ringPct),
                  ...(p.state === "off" ? { background: "var(--ovOff)", opacity: .82 } : null),
                  ...(p.drag?.isDragging ? { zIndex: 5, boxShadow: "0 8px 24px rgba(0,0,0,.45)" } : null),
                  cursor: p.onClick ? "pointer" : "default", userSelect: "none" }}>
      {p.shine ? (
        <span aria-hidden="true" style={{ position: "absolute", inset: 0, borderRadius: 12, overflow: "hidden", pointerEvents: "none" }}>
          <i key={p.shine} className={`ov-shine ov-shine-${p.shine % 2 ? "a" : "b"}`} />
        </span>
      ) : null}
      {p.drag && (
        <span className="ov-drag">
          <DragHandle t={p.t} dragging={p.drag.isDragging} hint={p.drag.hint}
                      onStart={p.drag.onStart} onMove={p.drag.onMove} onEnd={p.drag.onEnd} />
        </span>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "44px minmax(0, 1fr)", columnGap: 12, alignItems: "center" }}>
        <OvRing size={44} r={20} sw={4} pct={p.ringPct} color={ringColor(p.state, p.ringPct, p.platColor)} numSize={13}
                dot={p.state === "unprobed"} />
        <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
          <Slot h={22} data="name">
            <span style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", minWidth: 0 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, overflow: "hidden" }}>{p.head}</span>
              <span style={{ flex: 1, minWidth: 0 }} />
              {p.marks}
              {p.right && <span className="ov-delta" style={{ flexShrink: 0 }}>{p.right}</span>}
            </span>
          </Slot>
          <Slot h={18} data="email" title={p.emailTitle}>
            <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 11.5, color: "var(--tx2)",
                           overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>{p.email}</span>
          </Slot>
          <Slot h={18} data="dyn">{p.dyn}</Slot>
          <Slot h={18} data="w5"><OvWinRow w={p.w5} off={p.state === "off"} /></Slot>
          <Slot h={18} data="ww"><OvWinRow w={p.ww} off={p.state === "off"} /></Slot>
        </div>
      </div>
      <div data-ov-foot="" style={{ position: "relative", height: 28, display: "flex", alignItems: "center", gap: 5,
                                    borderTop: "1px solid var(--ovFoot)", fontSize: 11, flexShrink: 0, minWidth: 0 }}>
        {/* ★ 默认底栏与悬停底栏是**换着渲染**（CSS 切 display），不是交叉淡化；悬停那组 `inUp .16s` 入场（P5 §3.3）。
              两组都留在 DOM 里（本仓「折叠用 CSS 不用条件渲染」：行为闸读 --dump-dom）。 */}
        <span className="ov-fdef" style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, flex: "1 1 auto", overflow: "hidden" }}>
          <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", fontSize: 11.5, color: "var(--tx3)", minWidth: 0,
                         overflow: "hidden", textOverflow: "ellipsis" }}>{p.footLeft}</span>
          {p.footRight && <><span style={{ flex: 1 }} />{p.footRight}</>}
        </span>
        <span className="ov-fact" data-ov-actions="" onClick={(e) => e.stopPropagation()}>
          {p.actions}
        </span>
        {p.chip && <><span className="ov-fgap" style={{ flex: 1, minWidth: 0 }} />{p.chip}</>}
      </div>
    </div>
  );
}

/** 底栏一个有字的操作按钮（「切换」/「在用」/「刷新」）。有字就不出自定义提示（P5 §3.3「有字不出提示」）。 */
export function Ab({ children, onClick, primary, warn, bad, title, disabled, data, current }: {
  children: ReactNode; onClick?: () => void; primary?: boolean; warn?: boolean; bad?: boolean;
  title?: string; disabled?: boolean; data?: string;
  /** 「在用」：同一个位置、禁用、青字青边。 */
  current?: boolean;
}) {
  const cls = ["ov-ab", primary ? "ov-abp" : "", warn ? "ov-abw" : "", bad ? "ov-abd" : "", current ? "ov-abc" : ""].filter(Boolean).join(" ");
  return (
    <span className={cls} role="button" tabIndex={0} title={title} aria-disabled={disabled || current ? "true" : undefined}
          data-ov-ab={data}
          onClick={(e) => { e.stopPropagation(); if (!disabled && !current) onClick?.(); }}
          onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !disabled && !current) { e.preventDefault(); e.stopPropagation(); onClick?.(); } }}>
      {children}
    </span>
  );
}

/* ── 底栏按钮组 + 精简提示（P5 §3.4） ─────────────────────────────────────────────
 * ★ 提示热身：已有提示在显示、或离开按钮组不到 300 ms ⇒ 新提示不播入场动画、直接出。
 *   「离开」挂在整个按钮组上（在两个按钮之间的缝里不算离开）。··· 菜单开着时不出提示。
 * ★ 图标按钮**不带原生 `title`**：自定义提示 + 原生提示会叠两层（`test_no_double_tooltip.py`）；
 *   长说明放 `aria-label`。 */
interface TipApi { cur: string | null; inst: boolean; block: boolean; show: (k: string) => void; setBlock: (b: boolean) => void }
const TipCtx = createContext<TipApi>({ cur: null, inst: false, block: false, show: () => {}, setBlock: () => {} });

export function ActGroup({ children }: { children: ReactNode }) {
  const [cur, setCur] = useState<string | null>(null);
  const [inst, setInst] = useState(false);
  const [block, setBlockS] = useState(false);
  const lc = useRef(0);
  const api: TipApi = {
    cur, inst, block,
    show: (k) => { setInst(cur != null || Date.now() - lc.current < 300); setCur(k); },
    setBlock: (b) => { setBlockS(b); if (b) setCur(null); },
  };
  return (
    <span className="ov-acts" onMouseLeave={() => { lc.current = Date.now(); setCur(null); }}
          style={{ display: "inline-flex", alignItems: "center", gap: 5, flexShrink: 0 }}>
      <TipCtx.Provider value={api}>{children}</TipCtx.Provider>
    </span>
  );
}

export type IbTone = "plain" | "warn" | "warnOn" | "dim";
/** 24×22 的图标按钮（⚡ 探针 / ⊘ 停止轮换 / ···）。 */
export function IconBtn({ k, tip, label, tone = "plain", onClick, disabled, busy, data, className, children }: {
  k: string; tip: string; label?: string; tone?: IbTone; onClick?: () => void; disabled?: boolean; busy?: boolean;
  data?: string; className?: string; children: ReactNode;
}) {
  const c = useContext(TipCtx);
  const on = c.cur === k && !c.block;
  return (
    <span className={`ov-ib ov-ib-${tone}${className ? ` ${className}` : ""}`} role="button" tabIndex={0} data-ov-ab={data}
          aria-label={label ?? tip} aria-disabled={disabled ? "true" : undefined} data-busy={busy ? "" : undefined}
          onMouseEnter={() => c.show(k)}
          onClick={(e) => { e.stopPropagation(); if (!disabled) onClick?.(); }}
          onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !e.repeat && !disabled) { e.preventDefault(); e.stopPropagation(); onClick?.(); } }}>
      {children}
      {on && <span className={`ov-tp${c.inst ? " ov-tp-inst" : ""}`} data-ov-tip={k}>{tip}</span>}
    </span>
  );
}

/**
 * 卡片底栏的 ⚡ 探针 —— **点一下就执行**（用户 2026-10-21「探针的功能 修改点击即可」）。
 * 连点只算一次，判据只用 `mbLogic.ts::probeShouldFire` 那一份（有行为闸），与菜单栏 / 头部同一颗。
 * ★ 卡宽 < 240 时这一颗由 CSS 容器查询藏起来，换成 ··· 菜单首项（`ov-mi-narrow`，P5 §3.5）。
 */
export function useProbeFire(onFire: () => void, loading: boolean): () => void {
  const last = useRef<number | null>(null);
  return () => {
    const now = performance.now();
    if (!probeShouldFire(last.current, now, loading)) return;
    last.current = now;
    onFire();
  };
}
export function ProbeIb({ onFire, loading, hint }: { onFire: () => void; loading: boolean; hint: string }) {
  const fire = useProbeFire(onFire, loading);
  return (
    <IconBtn k="probe" tip="探针 · 计费" label={`${hint}（点一下就执行，计费）`} tone={loading ? "warnOn" : "warn"}
             busy={loading} disabled={loading} onClick={fire} data="probe" className="ov-ib-probe">
      {loading ? <i className="ov-spin" /> : <IcBolt />}
    </IconBtn>
  );
}

/** ⊘ 停止 / 恢复轮换。平台不支持时置灰 35%、提示「不支持轮换」。 */
export function RotIb({ off, onToggle, unsupported }: { off: boolean; onToggle?: (on: boolean) => void; unsupported?: boolean }) {
  return (
    <IconBtn k="rot" tip={unsupported ? "不支持轮换" : off ? "恢复轮换" : "停止轮换"} tone={unsupported ? "dim" : off ? "warnOn" : "plain"}
             disabled={unsupported} onClick={() => onToggle?.(off)} data="rotate">
      <IcBan size={12} sw={2.2} />
    </IconBtn>
  );
}

export interface CardMenuItem { key: string; label: string; icon?: ReactNode; onClick: () => void; bad?: boolean; warn?: boolean;
  /** 只在卡宽 < 240 时出现（CSS 容器查询）。 */
  narrow?: boolean;
  /** 正在跑（探针在途）⇒ 画成不可点、点了不发。 */
  disabled?: boolean }

/** 底栏最右的 ···（P5 §5.1）：只有「详情 / 删除」，卡窄时首项补「⚡ 探针 · 计费」。滑动高亮跟着鼠标走。 */
export function CardMenu({ items, onOpenChange }: { items: CardMenuItem[]; onOpenChange?: (o: boolean) => void }) {
  const c = useContext(TipCtx);
  const [open, setOpen] = useState(false);
  const [up, setUp] = useState(false);
  const [mh, setMh] = useState(-1);
  const moved = useRef(false);
  const box = useRef<HTMLSpanElement>(null);
  const setO = (o: boolean) => {
    // 往下展开会被卡片区（自己滚的那个框）的底边裁掉 ⇒ 下面放不下、上面放得下时朝上开。
    if (o && box.current) {
      const r = box.current.getBoundingClientRect();
      const sc = box.current.closest("[data-ov-scroll]")?.getBoundingClientRect();
      const need = 14 + 30 * items.length;
      setUp(!!sc && r.bottom + need > sc.bottom && r.top - need >= sc.top);
    }
    setOpen(o); setMh(-1); moved.current = false; c.setBlock(o); onOpenChange?.(o);
  };
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setO(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setO(false); };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  return (
    <span ref={box} style={{ position: "relative", display: "inline-flex" }}>
      <IconBtn k="more" tip="其他" onClick={() => setO(!open)} data="more">
        <span style={{ fontSize: 13, letterSpacing: 1, lineHeight: 1, marginTop: -4 }}>···</span>
      </IconBtn>
      <div className={up ? "ov-cmenu ov-cmenu-up" : "ov-cmenu"} data-ov-menu="" data-open={open ? "" : undefined}
           onClick={(e) => e.stopPropagation()} onMouseLeave={() => setMh(-1)}>
        <i className="ov-cm-hl" style={{ transform: `translateY(${Math.max(0, mh) * 30}px)`, opacity: mh >= 0 ? 1 : 0,
                                         transition: moved.current ? "transform .14s cubic-bezier(.2,.9,.3,1), opacity .1s" : "opacity .1s" }} />
        {items.map((it, i) => (
          <div key={it.key} className={`ov-mi${it.bad ? " ov-mi-bad" : ""}${it.warn ? " ov-mi-warn" : ""}${it.narrow ? " ov-mi-narrow" : ""}`}
               role="menuitem" tabIndex={0} data-ov-mi={it.key} aria-disabled={it.disabled ? "true" : undefined}
               style={it.disabled ? { opacity: .45, cursor: "default" } : undefined}
               onMouseEnter={() => { if (mh >= 0) moved.current = true; setMh(i); }}
               onClick={() => { setO(false); if (!it.disabled) it.onClick(); }}
               onKeyDown={(e) => { if (e.key === "Enter") (e.currentTarget as HTMLElement).click(); }}>
            <span className="ov-mi-ic">{it.icon}</span>{it.label}
          </div>
        ))}
      </div>
    </span>
  );
}

/** 名称行角标（P5 §2.3 `.mk`）：图钉 —— 已置顶常亮青 + 顺序号；未置顶只在悬停时出灰色幽灵。 */
export function PinMark({ rank, onToggle, hint }: { rank: number | null; onToggle: () => void; hint?: string }) {
  const pinned = rank != null;
  return (
    <span className={`ov-mk ${pinned ? "ov-mk-pin" : "ov-mk-ghost"}`} role="button" tabIndex={0}
          data-pin-badge={pinned ? "" : undefined} data-pin-ghost={pinned ? undefined : ""}
          title={pinned ? `已置顶 · 第 ${rank + 1} 个用 · 点击取消` : `置顶：优先用这个号${hint ? `\n${hint}` : ""}`}
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); onToggle(); } }}>
      <IcPin />{pinned && <span>{rank + 1}</span>}
    </span>
  );
}

/** ⊘ 停轮换角标：**只在已停时出现**（不出灰色幽灵），点一下放回自动轮换。 */
export function RotMark({ onRestore }: { onRestore: () => void }) {
  return (
    <span className="ov-mk ov-mk-rot" role="button" tabIndex={0} data-rot-mark="" title="已停轮换 · 点击放回自动轮换"
          onClick={(e) => { e.stopPropagation(); onRestore(); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); onRestore(); } }}>
      <IcBan size={11} sw={2.6} />
    </span>
  );
}

export const IcPin = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M15 3l6 6-3 1-4 4 1 5-2 2-4-5-5 5-1-1 5-5-5-4 2-2 5 1 4-4z" fill="currentColor" />
  </svg>
);
export const IcBan = ({ size = 12, sw = 2.2 }: { size?: number; sw?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M5.6 5.6l12.8 12.8M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round" />
  </svg>
);
export const IcCard = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <rect x="3" y="6" width="18" height="12" rx="2" fill="currentColor" />
  </svg>
);
export const IcInfo = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block" }}>
    <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.8" />
    <path d="M12 11v6M12 7.5v.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>
);
export const IcTrash = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block" }}>
    <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
