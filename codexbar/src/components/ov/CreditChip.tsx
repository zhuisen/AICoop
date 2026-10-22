import { useEffect, useRef, useState } from "react";
import type { Account } from "../../helpers";
import { cardLeftText } from "../../helpers";
import { isCardExpiring } from "../CardBadge";
import { IcCard } from "./OvCard";

/**
 * 重置卡 chip + 「用一张重置卡？」单选弹层（交接包 P5 §3.2 / §6）。
 *
 * ★ chip 在底栏最右、**悬停也不让位**：悬停时只缩成 `×N`（右对齐 ⇒ 位置不变），所以鼠标够得着它。
 * ★ 弹层挂在底栏里（`position:absolute`，相对的是底栏 —— 这个组件自己**不能**是定位元素），
 *   卡片水平居中、向上弹；上面放不下（第一排卡片、被卡片区的滚动框裁掉）时朝下开。
 * ★ 防误触（用卡**不可逆**，用户 2026-10-01 实测很容易误触）沿用旧确认弹窗的做法：
 *   默认选**最先过期**那张；**Enter 不确认**（连按回车不能花掉一张卡），只能点「确认使用」；Esc / 点外面 = 取消。
 *   确认时把**选中那张的 id** 传给 CLI（`--card`）—— 用户看到的就是将被用掉的。
 */
export default function CreditChip({ a, busy, open, onOpenChange, onConfirm }: {
  a: Account; busy: boolean; open: boolean; onOpenChange: (o: boolean) => void; onConfirm: (cardId: string) => void;
}) {
  const n = a.cards > 0 ? a.cards : 0;
  const warn = n > 0 && isCardExpiring(a);
  // ★ 记选中那张的 **id**，不记下标：弹层开着时列表变了（取到新明细），下标会指到另一张（不可逆，2026-10-22 评审）
  const [pickId, setPickId] = useState<string | null>(null);
  const [down, setDown] = useState(false);
  // 同一次打开只确认一次：连点「确认使用」在父组件的 busy 回来之前也只发一张（评审 agy#2；父层另有按号在途锁）
  const sent = useRef(false);
  const box = useRef<HTMLSpanElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const list = a.cardList;
  const usable = list.length > 0;
  const pick = list.findIndex((c) => c.id === pickId);
  const picked = pick >= 0 ? list[pick] : null;

  const toggle = () => {
    if (!usable || busy) return;
    if (!open && box.current) {
      const r = box.current.getBoundingClientRect();
      const sc = box.current.closest("[data-ov-scroll]")?.getBoundingClientRect();
      const need = 110 + 40 * list.length;
      // 上面放不下就看哪边空间大（两边都放不下时朝大的那边开，再滚进可见区 —— 评审 Opus M4：
      //   原来两边都不够时恒朝上，第一排卡的标题和「用掉不能撤回」被滚动框裁掉，「确认使用」却点得到）
      const up = sc ? r.top - sc.top : Infinity, dn = sc ? sc.bottom - r.bottom : 0;
      setDown(up < need && dn > up);
    }
    sent.current = false;
    setPickId(list[0]?.id ?? null);
    onOpenChange(!open);
  };
  useEffect(() => {
    if (open) pop.current?.scrollIntoView({ block: "nearest" });
  }, [open, down]);
  useEffect(() => {
    if (!open) return;
    const md = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) onOpenChange(false); };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onOpenChange(false); return; }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const k = Math.max(0, list.findIndex((c) => c.id === pickId));
        const nk = e.key === "ArrowDown" ? Math.min(list.length - 1, k + 1) : Math.max(0, k - 1);
        setPickId(list[nk]?.id ?? null);
      }
    };
    document.addEventListener("mousedown", md);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", md); document.removeEventListener("keydown", key); };
  }, [open, onOpenChange, list, pickId]);

  const tone = open ? "open" : n === 0 ? "none" : warn ? "warn" : "ok";
  // ★ 剩不到一天时写「23小时」比「1天」长两格 ⇒ 1200 宽四列（内容宽 237）也放不下，阈值放宽到 250（`ov-chip-hrs`）。
  //   2026-10-22 全量测试随时钟走过「剩 1天 → 23小时」变红抓到的。
  // ★ 窄卡（内容宽 < 226，即 860 宽三列）里「重置卡」三个字由 CSS 容器查询藏掉 —— 否则带「· 剩 1天」时
  //   左边的「到期 MM-DD」被挤成省略号（用户 2026-10-21「到期日期挡住了」，有渲染闸）。
  const long = busy ? "使用中…" : n === 0 ? "无重置卡"
    : <><span className="ov-chip-word">重置卡 </span>×{n}{warn ? ` · 剩 ${cardLeftText(a.cardDays ?? 0)}` : ""}</>;
  const unknown = Math.max(0, n - list.length);
  const title = n === 0 ? "没有可用的重置卡"
    : usable ? `点击使用重置卡（会先确认）\n共 ${n} 张 · 最早一张到期 ${a.cardExp ?? "—"}${a.cardsExpiring ? ` · ${a.cardsExpiring} 张快作废` : ""}`
             + (warn ? "\n也可以在终端用：codex → 输入 /usage → Redeem usage limit reset" : "")
    : `共 ${n} 张 · 到期未知（运行 codex-rotate credits 取明细后才能选用）`;
  return (
    <span ref={box} style={{ display: "inline-flex", flexShrink: 0 }} onClick={(e) => e.stopPropagation()}>
      <span className={`ov-chip ov-chip-${tone}${warn && (a.cardDays ?? 0) < 1 ? " ov-chip-hrs" : ""}`} role="button" tabIndex={0} data-card-badge="" data-card-chip={n}
            aria-expanded={open} title={open ? undefined : title}
            onClick={toggle} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}>
        <IcCard /><span className="ov-chip-long">{long}</span><span className="ov-chip-short">×{n}</span>
      </span>
      <div ref={pop} className={down ? "ov-credit ov-credit-down" : "ov-credit"} data-use-credit-dialog="" data-open={open ? "" : undefined}
           role="dialog" aria-label={`给 ${a.node} 用一张重置卡`}>
        <b style={{ fontSize: 13.5, fontWeight: 600, color: "var(--tx)" }}>给 {a.node} 用一张重置卡？</b>
        <span style={{ fontSize: 12, color: "var(--tx2)" }}>5h 和周窗口立刻回满 · <span style={{ color: "var(--ovAmb)" }}>用掉不能撤回</span></span>
        <div role="radiogroup" data-use-credit-list="" style={{ position: "relative", display: "flex", flexDirection: "column", gap: 8 }}>
          <i className="ov-credit-sel" style={{ transform: `translate3d(0, ${Math.max(0, pick) * 40}px, 0)`, opacity: picked ? 1 : 0 }} />
          {list.map((c, i) => (
            <button key={c.id} type="button" role="radio" aria-checked={i === pick} data-use-credit-row={c.id}
                    data-selected={i === pick ? "" : undefined} data-left={cardLeftText(c.days)} title={`还剩 ${cardLeftText(c.days)}`}
                    onMouseDown={() => setPickId(c.id)} onClick={() => setPickId(c.id)}
                    className="ov-credit-row">
              <span className="ov-radio" data-on={i === pick ? "" : undefined}><i /></span>
              <span>重置卡 {i + 1}{i === 0 ? " · 最先过期" : ""}</span>
              <span style={{ marginLeft: "auto", fontFamily: "'JetBrains Mono', monospace", fontVariantNumeric: "tabular-nums", fontSize: 11.5,
                             color: i === 0 ? "var(--ovAmb)" : "var(--tx3)" }}>到期 {c.expiresAt.slice(5, 10)}</span>
            </button>
          ))}
        </div>
        {open && !picked && <span data-use-credit-gone="" style={{ fontSize: 11, color: "var(--ovAmb)" }}>选中的那张已不在列表里 —— 重新选一张</span>}
        {unknown > 0 && <span data-use-credit-unknown="" style={{ fontSize: 11, color: "var(--tx3)" }}>另有 {unknown} 张还没取到到期日，暂不能选</span>}
        <span style={{ display: "flex", justifyContent: "flex-end", gap: 6, marginTop: 2 }}>
          <span className="ov-dbtn" role="button" tabIndex={0} data-use-credit-cancel="" onClick={() => onOpenChange(false)}>取消</span>
          <span className="ov-dbtn ov-dbtn-amber" role="button" tabIndex={0} data-use-credit-confirm="" aria-disabled={!picked}
                style={picked ? undefined : { opacity: .45, cursor: "not-allowed" }}
                onClick={() => { if (picked && !busy && !sent.current) { sent.current = true; onOpenChange(false); onConfirm(picked.id); } }}>确认使用</span>
        </span>
      </div>
    </span>
  );
}
