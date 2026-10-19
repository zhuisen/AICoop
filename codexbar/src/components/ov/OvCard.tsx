import { useEffect, useReducer, useRef, useState, type ReactNode } from "react";
import type { OvState } from "../../overview";
import { ovIsLow } from "../../overview";
import { HOLD_IDLE, HOLD_MS, RETREAT_MS, holdFill, holdReduce } from "../../mbLogic";
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

const Lock = () => (
  <svg width="10" height="10" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <rect x="5" y="11" width="14" height="9" rx="2" fill="none" stroke="currentColor" strokeWidth="1.7" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" strokeWidth="1.7" />
  </svg>
);

export const IcSwap = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M7 7h11l-3-3M17 17H6l3 3" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
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
                  transform={`rotate(-90 ${c} ${c})`} style={{ transition: "stroke-dasharray .55s cubic-bezier(.4,0,.2,1)" }} />
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

export function OvTag({ tag, title }: { tag: OvTagSpec; title?: string }) {
  if (tag.kind === "ultra") {
    return (
      <span data-ov-tag="ultra" title={title}
            style={{ fontSize: 10, fontWeight: 700, color: "#fff", background: "#8b5cf6", padding: "1px 6px",
                     borderRadius: 5, flexShrink: 0, letterSpacing: ".04em" }}>{tag.text}</span>
    );
  }
  const s = TAG_STYLE[tag.kind] ?? TAG_STYLE.off;
  return (
    <span data-ov-tag={tag.kind} data-next-badge={tag.kind === "next" ? "" : undefined}
          data-rotate-off={tag.kind === "off" ? "" : undefined} title={title}
          style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11, fontWeight: 600, color: s.color,
                   padding: "1px 7px", borderRadius: 6, background: s.bg, border: "1px solid transparent", flexShrink: 0 }}>
      {tag.kind === "inuse" && <Check />}{tag.kind === "readonly" && <Lock />}{tag.text}
    </span>
  );
}

/** ④ / ⑤ 槽：标签 · 4px 条 · % · ↻ 回满。 */
export function OvWinRow({ w, off }: { w: OvWin; off?: boolean }) {
  const low = ovIsLow(w.pct);
  const bar = off ? "var(--tx3)" : low ? "var(--bad)" : w.kind === "5h" ? "var(--ovB5)" : "var(--ovBw)";
  return (
    <div data-ov-win={w.kind} data-agy-unknown={w.pct == null && !w.absent ? "" : undefined} title={w.title}
         style={{ display: "flex", alignItems: "center", gap: 8, height: 18, width: "100%", opacity: w.dim ? .62 : 1 }}>
      <span style={{ width: 14, fontSize: 11, color: "var(--tx3)", flexShrink: 0 }}>{w.label}</span>
      <span style={{ display: "block", flex: 1, minWidth: 0, height: 4, borderRadius: 4, background: "var(--track)", overflow: "hidden" }}>
        {w.pct != null && (
          <span style={{ display: "block", width: `${Math.max(0, Math.min(100, w.pct))}%`, height: "100%", borderRadius: 4,
                         background: bar, transition: "width .55s cubic-bezier(.4,0,.2,1)" }} />
        )}
      </span>
      <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", width: 34, textAlign: "right", fontSize: 12,
                     fontWeight: 600, flexShrink: 0,
                     color: w.pct == null ? "var(--ovPh)" : low ? "var(--badTx)" : "var(--tx)" }}>
        {w.pct == null ? "—" : `${Math.round(w.pct)}%`}
      </span>
      <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", width: 48, fontSize: 10.5, color: "var(--tx3)",
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
  /** ① 名称行左侧（号名 / 改名输入框 + 标签们）。 */
  head: ReactNode;
  /** ① 右侧（环比 `-15%` / 「最优」）。 */
  right?: ReactNode;
  email: ReactNode;
  emailTitle?: string;
  dyn: ReactNode;
  w5: OvWin;
  ww: OvWin;
  footLeft: ReactNode;
  footRight?: ReactNode;
  actions: ReactNode;
  /** harness 用：强制悬停态（`?ovhover=`）。 */
  hov?: boolean;
  menuOpen?: boolean;
  drag?: DragWiring;
  t: Theme;
  title?: string;
  onClick?: () => void;
}

export function OvCard(p: OvCardProps) {
  const cls = ["ov-card", p.hov ? "ov-hov" : "", p.menuOpen ? "ov-menu-open" : "", p.drag?.isDragging ? "ov-dragging" : ""]
    .filter(Boolean).join(" ");
  return (
    <div className={cls} data-aid={p.id} data-ov-card={p.state} tabIndex={0} title={p.title} onClick={p.onClick}
         style={{ border: borderOf(p.state, p.ringPct),
                  ...(p.state === "off" ? { background: "var(--ovOff)", opacity: .82 } : null),
                  ...(p.drag?.isDragging ? { zIndex: 5, boxShadow: "0 8px 24px rgba(0,0,0,.45)" } : null),
                  cursor: p.onClick ? "pointer" : "default", userSelect: "none" }}>
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
              {p.head}
              <span style={{ marginLeft: "auto", flexShrink: 0 }}>{p.right}</span>
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
      <div data-ov-foot="" style={{ position: "relative", height: 28, borderTop: "1px solid var(--ovFoot)", fontSize: 11, flexShrink: 0 }}>
        <div className="ov-fdef" style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center",
                                          justifyContent: "space-between", gap: 8, minWidth: 0 }}>
          <span style={{ fontFamily: MONO, fontVariantNumeric: "tabular-nums", color: "var(--tx3)", minWidth: 0,
                         overflow: "hidden", textOverflow: "ellipsis" }}>{p.footLeft}</span>
          {p.footRight}
        </div>
        <div className="ov-fact" data-ov-actions="" onClick={(e) => e.stopPropagation()}
             style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", gap: 6 }}>
          {p.actions}
        </div>
      </div>
    </div>
  );
}

/** 底栏一个操作按钮。 */
export function Ab({ children, onClick, primary, warn, bad, title, disabled, data }: {
  children: ReactNode; onClick?: () => void; primary?: boolean; warn?: boolean; bad?: boolean;
  title?: string; disabled?: boolean; data?: string;
}) {
  const cls = ["ov-ab", primary ? "ov-abp" : "", warn ? "ov-abw" : "", bad ? "ov-abd" : ""].filter(Boolean).join(" ");
  return (
    <span className={cls} role="button" tabIndex={0} title={title} aria-disabled={disabled ? "true" : undefined}
          data-ov-ab={data}
          onClick={(e) => { e.stopPropagation(); if (!disabled) onClick?.(); }}
          onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !disabled) { e.preventDefault(); e.stopPropagation(); onClick?.(); } }}>
      {children}
    </span>
  );
}

/**
 * 卡片底栏的「探针」—— **按住 0.6 s 才执行**（交接包 README §5：「菜单栏弹窗里是按住 0.6 s 确认，
 * 工作台建议同样处理」）。判据只用 `mbLogic.ts::holdReduce` 那一份（有行为闸），这里只喂指针事件。
 * ★ 它取代了主窗原来的「两段确认」（`ProbeButton`）—— 同一个花钱控件在两个界面两种确认法，
 *   用户要记两套肌肉记忆（PLAN §4）。键盘：按住空格 / 回车同样走 down → up。
 */
export function HoldAb({ onFire, loading, hint, label = "探针", data }: {
  onFire: () => void; loading: boolean; hint: string; label?: string; data?: string;
}) {
  const [s, send] = useReducer(holdReduce, HOLD_IDLE);
  const timer = useRef<number | null>(null);
  const fireRef = useRef(onFire);
  fireRef.current = onFire;
  useEffect(() => {
    if (timer.current != null) { window.clearTimeout(timer.current); timer.current = null; }
    if (s.phase === "holding") timer.current = window.setTimeout(() => send({ type: "tick", now: performance.now() }), HOLD_MS + 5);
    else if (s.phase === "retreat") timer.current = window.setTimeout(() => send({ type: "tick", now: performance.now() }), RETREAT_MS + 5);
    else if (s.phase === "fired") { fireRef.current(); send({ type: "reset" }); }
    return () => { if (timer.current != null) window.clearTimeout(timer.current); };
  }, [s]);
  const fill = holdFill(s);
  const down = () => send({ type: "down", now: performance.now(), disabled: loading });
  const up = () => send({ type: "up", now: performance.now() });
  return (
    <span className="ov-ab ov-abw" role="button" tabIndex={0} data-ov-ab={data ?? "probe"} data-hold={s.phase}
          title={`${hint}\n\n按住 0.6 秒才会执行；中途松手取消。`}
          aria-disabled={loading ? "true" : undefined}
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => { e.stopPropagation(); if (e.button === 0) down(); }}
          onMouseUp={up} onMouseLeave={() => send({ type: "leave", now: performance.now() })}
          onKeyDown={(e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); e.stopPropagation(); down(); } }}
          onKeyUp={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); up(); } }}>
      <i aria-hidden style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${fill.width}%`,
                              background: "var(--warnBg2)", transition: fill.transition }} />
      <span style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 4 }}>
        <IcBolt />{loading ? "探测中…" : s.phase === "holding" ? "按住…" : label}
      </span>
    </span>
  );
}

export interface MenuItem {
  key: string;
  label: string;
  onClick?: () => void;
  bad?: boolean;
  /** 只读的一行说明（不可点）。 */
  info?: boolean;
  /** 不可逆：第一次点只把文字换成「再点一次确认」，5 秒内第二次才执行。 */
  confirm?: string;
  title?: string;
  hidden?: boolean;
}

/** 底栏最右的「⋯」：放不进主操作的那些（置顶 / 轮换 / 改名 / 详情 / 用卡 / 删除…）。 */
export function OvMenu({ items, onOpenChange, data }: { items: MenuItem[]; onOpenChange?: (o: boolean) => void; data?: string }) {
  const [open, setOpen] = useState(false);
  const [arm, setArm] = useState<string | null>(null);
  const [up, setUp] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  const setO = (o: boolean) => {
    // 往下展开会被卡片区（自己滚的那个框）的底边裁掉 ⇒ 下面放不下、上面放得下时朝上开。
    if (o && box.current) {
      const r = box.current.getBoundingClientRect();
      const sc = box.current.closest("[data-ov-scroll]")?.getBoundingClientRect();
      const need = 30 + 27 * items.filter((i) => !i.hidden).length;
      setUp(!!sc && r.bottom + need > sc.bottom && r.top - need >= sc.top);
    }
    setOpen(o); if (!o) setArm(null); onOpenChange?.(o);
  };
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setO(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setO(false); };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
  }, [open]);
  useEffect(() => {
    if (!arm) return;
    const id = window.setTimeout(() => setArm(null), 5000);
    return () => window.clearTimeout(id);
  }, [arm]);
  const shown = items.filter((i) => !i.hidden);
  return (
    <span ref={box} style={{ marginLeft: "auto", position: "relative", display: "inline-flex" }}>
      <Ab title="更多操作" onClick={() => setO(!open)} data={data ?? "more"}><IcMore /></Ab>
      {(
        <div className={up ? "ov-menu" : "ov-menu ov-menu-down"} data-ov-menu="" data-open={open ? "" : undefined} onClick={(e) => e.stopPropagation()}>
          {shown.map((it) => it.info ? (
            <div key={it.key} className="ov-mi ov-mi-info" title={it.title}>{it.label}</div>
          ) : (
            <div key={it.key} className={`ov-mi${it.bad ? " ov-mi-bad" : ""}`} role="menuitem" tabIndex={0} title={it.title}
                 data-ov-mi={it.key} data-confirm-delete={it.confirm && arm === it.key ? "" : undefined}
                 onClick={() => {
                   if (it.confirm && arm !== it.key) { setArm(it.key); return; }
                   setO(false); it.onClick?.();
                 }}
                 onKeyDown={(e) => { if (e.key === "Enter") (e.currentTarget as HTMLElement).click(); }}>
              {it.confirm && arm === it.key ? it.confirm : it.label}
            </div>
          ))}
        </div>
      )}
    </span>
  );
}
