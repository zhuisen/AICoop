import { useEffect, useRef, useState, type ReactNode } from "react";
import { MONO } from "./ovVars";
import { cmdkFilter, cmdkMove } from "../../cmdk";

/**
 * 总览的三层浮层（交接包 P5 §5.2 / §5.3 / §8）：详情 Sheet · 删除确认 · ⌘K 命令面板。
 * 都挂在总览根上（`position:fixed` 盖住整个主窗口），**不离开总览页**。
 */

export interface SheetRow { k: string; v: ReactNode; color?: string; mono?: boolean; title?: string }

/** 右侧滑出的详情 Sheet（宽 320）。`open=false` 时仍渲染一会儿以播完收起动画（由调用方延迟卸载）。 */
export function DetailSheet({ open, title, email, rows, name, onRename, extra, foot, onClose }: {
  open: boolean; title: string; email?: string; rows: SheetRow[];
  /** 名字一行（就地编辑 = 改名；稿里这一行是「备注」，本仓没有备注字段，改名是真有的能力）。 */
  name: string; onRename?: (next: string) => Promise<boolean>;
  /** 行之后的补充块（Codex 的 token 指纹等技术信息 —— 原「账号详情」弹窗里的每一项都还在）。 */
  extra?: ReactNode; foot?: ReactNode; onClose: () => void;
}) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    // 先挂上再滑入：同一帧里从 104% 到 0 不会有过渡
    const id = window.requestAnimationFrame(() => setShown(open));
    return () => window.cancelAnimationFrame(id);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape" && !(e.target as HTMLElement)?.closest?.("[data-sheet-edit]")) onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open, onClose]);
  const all: SheetRow[] = rows;
  const d = (j: number) => (shown
    ? { opacity: 1, transform: "none",
        transition: `opacity .25s ease-out ${0.12 + j * 0.035}s, transform .32s cubic-bezier(.32,.72,0,1) ${0.12 + j * 0.035}s` }
    : { opacity: 0, transform: "translateX(16px)", transition: "opacity .12s, transform .12s" });
  return (
    <div data-ov-sheet="" data-open={shown ? "" : undefined} style={{ position: "fixed", inset: 0, zIndex: 35, pointerEvents: open ? "auto" : "none" }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "rgba(5,8,12,.5)", opacity: shown ? 1 : 0,
                                      transition: "opacity .25s ease-out" }} />
      <div className="ov-sheet" role="dialog" aria-label={title}
           style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: 320, zIndex: 36, padding: 18, boxSizing: "border-box",
                    background: "var(--ovMenu)", borderLeft: "1px solid var(--line2)", boxShadow: "-20px 0 44px rgba(0,0,0,.45)",
                    display: "flex", flexDirection: "column", gap: 10, overflowY: "auto",
                    transform: `translate3d(${shown ? "0" : "104%"}, 0, 0)`, transition: "transform .38s cubic-bezier(.32,.72,0,1)" }}>
        <div style={{ display: "flex", alignItems: "center", height: 28, flexShrink: 0 }}>
          <b style={{ fontSize: 15 }}>{title}</b>
          <span style={{ flex: 1 }} />
          <span className="ov-ib" role="button" tabIndex={0} aria-label="关闭" data-sheet-close="" onClick={onClose}
                style={{ width: 26, height: 26 }}>×</span>
        </div>
        {email && <div style={{ fontFamily: MONO, fontSize: 11.5, color: "var(--tx3)", overflow: "hidden", textOverflow: "ellipsis" }}>{email}</div>}
        <div style={{ display: "flex", flexDirection: "column" }}>
          {all.map((r, j) => (
            <div key={r.k} data-sheet-row={r.k} title={r.title}
                 style={{ display: "flex", alignItems: "center", height: 30, borderBottom: "1px solid rgba(127,127,127,.12)", fontSize: 12.5,
                          gap: 10, ...d(j) }}>
              <span style={{ color: "var(--tx3)", flexShrink: 0 }}>{r.k}</span>
              <span style={{ flex: 1 }} />
              <span style={{ fontFamily: r.mono === false ? undefined : MONO, fontVariantNumeric: "tabular-nums", color: r.color ?? "var(--tx)",
                             overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>{r.v}</span>
            </div>
          ))}
          <NameRow name={name} onRename={onRename} style={d(all.length)} open={open} />
        </div>
        {extra && <div style={{ ...d(all.length + 1) }}>{extra}</div>}
        {foot && <div style={{ ...d(all.length + 2), marginTop: "auto" }}>{foot}</div>}
      </div>
    </div>
  );
}

function NameRow({ name, onRename, style, open }: { name: string; onRename?: (n: string) => Promise<boolean>; style: object; open: boolean }) {
  const [edit, setEdit] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (!open) { setEdit(null); setSaved(false); } }, [open]);
  const save = () => {
    const v = (edit ?? "").trim();
    // 「已保存」等 CLI 回话再说：被拒（重名 / 含空格）时不能同时挂着「已保存」和 ✗（评审 Opus L7）
    if (v && v !== name) void onRename?.(v).then((ok) => setSaved(ok));
    setEdit(null);
  };
  return (
    <div data-sheet-row="名字" style={{ display: "flex", alignItems: "center", height: 34, gap: 10, fontSize: 12.5, ...style }}>
      <span style={{ color: "var(--tx3)", width: 34, flexShrink: 0 }}>名字</span>
      {edit !== null ? (
        <span data-sheet-edit="" className="ov-pop" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <input autoFocus value={edit} data-ov-rename="" onChange={(e) => setEdit(e.target.value)}
                 onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Enter") save(); if (e.key === "Escape") setEdit(null); }}
                 style={{ width: 150, height: 26, padding: "0 8px", boxSizing: "border-box", borderRadius: 6, border: "1px solid rgba(45,212,191,.55)",
                          background: "var(--ovCard)", color: "var(--tx)", fontSize: 12.5, outline: 0, fontFamily: "inherit" }} />
          <span className="ov-dbtn ov-dbtn-pri" role="button" tabIndex={0} style={{ height: 26, padding: "0 8px" }} onClick={save}>✓</span>
          <span className="ov-dbtn" role="button" tabIndex={0} style={{ height: 26, padding: "0 8px", border: 0 }} onClick={() => setEdit(null)}>esc</span>
        </span>
      ) : (
        <>
          <span role="button" tabIndex={0} data-sheet-name="" title={onRename ? "点击改名（只改昵称，不影响凭证 / 轮换）" : undefined}
                onClick={() => { if (onRename) { setSaved(false); setEdit(name); } }}
                style={{ height: 26, display: "inline-flex", alignItems: "center", gap: 6, padding: "0 8px", borderRadius: 6, boxSizing: "border-box",
                         cursor: onRename ? "text" : "default", background: "rgba(127,127,127,.06)", border: "1px dashed rgba(127,127,127,.28)" }}>
            {name}{onRename && <span style={{ fontSize: 11, color: "var(--tx3)" }}>✎</span>}
          </span>
          {saved && <span className="ov-pop" style={{ fontSize: 11, color: "var(--ovNum)" }}>已保存</span>}
        </>
      )}
    </div>
  );
}

/** 删除确认（Alert Dialog，宽 340）。★ 默认焦点在「取消」；Esc / 点背板 = 取消。 */
export function ConfirmDelete({ title, body, onCancel, onConfirm }: { title: string; body: ReactNode; onCancel: () => void; onConfirm: () => void }) {
  const cancel = useRef<HTMLSpanElement>(null);
  // 回调走 ref：父组件每次渲染都给新函数，挂进依赖会让焦点一次次被抢回「取消」（评审 Opus L10）
  const onCancelRef = useRef(onCancel); onCancelRef.current = onCancel;
  useEffect(() => {
    cancel.current?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onCancelRef.current(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  return (
    <div data-ov-confirm="" style={{ position: "fixed", inset: 0, zIndex: 45 }}>
      <div onClick={onCancel} style={{ position: "absolute", inset: 0, background: "rgba(5,8,12,.6)" }} />
      <div role="alertdialog" aria-label={title} className="ov-dlg"
           style={{ position: "absolute", left: "50%", top: "42%", width: 340, zIndex: 46, padding: "16px 18px", boxSizing: "border-box",
                    borderRadius: 14, background: "var(--ovMenu)", border: "1px solid var(--line2)", boxShadow: "0 24px 60px rgba(0,0,0,.6)",
                    display: "flex", flexDirection: "column", gap: 10, transform: "translate(-50%,-50%)", whiteSpace: "normal" }}>
        <b style={{ fontSize: 15 }}>{title}</b>
        <span style={{ fontSize: 12.5, color: "var(--tx2)", lineHeight: 1.6 }}>{body}</span>
        <span style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <span ref={cancel} className="ov-dbtn" role="button" tabIndex={0} data-confirm-cancel="" onClick={onCancel}
                onKeyDown={(e) => { if (e.key === "Enter") onCancel(); }}>取消</span>
          <span className="ov-dbtn ov-dbtn-red" role="button" tabIndex={0} data-confirm-delete="" onClick={onConfirm}
                onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !e.repeat) { e.preventDefault(); onConfirm(); } }}>删除</span>
        </span>
      </div>
    </div>
  );
}

export interface CmdItem { key: string; icon: string; color: string; label: string; hint: string; run: () => void }

/** ⌘K 命令面板（宽 440，top 70）。↑/↓ 移动、Enter 执行、Esc 关闭；鼠标悬停改高亮、按下即执行。 */
export function CmdK({ items, onClose }: { items: CmdItem[]; onClose: () => void }) {
  const [q, setQ] = useState("");
  // 高亮按**项的 key** 记，不按序号：数据刷新让列表变了，回车不能落到另一项（比如计费探针）上（评审 Opus L9）
  const [hk, setHk] = useState<string | null>(null);
  const [moved, setMoved] = useState(false);
  const shown = cmdkFilter(items, q);
  const kh = Math.max(0, shown.findIndex((x) => x.key === hk));
  const setKh = (i: number) => setHk(shown[i]?.key ?? null);
  const go = (it: CmdItem | undefined) => { if (!it) return; onClose(); it.run(); };
  return (
    <div data-ov-cmdk="" style={{ position: "fixed", inset: 0, zIndex: 47 }}>
      <div onClick={onClose} style={{ position: "absolute", inset: 0, background: "rgba(5,8,12,.5)" }} />
      <div className="ov-kpal" role="dialog" aria-label="快速操作"
           style={{ position: "absolute", left: "50%", top: 70, width: 440, zIndex: 48, borderRadius: 12, background: "var(--ovMenu)",
                    border: "1px solid var(--line2)", boxShadow: "0 24px 60px rgba(0,0,0,.6)", overflow: "hidden", transform: "translate3d(-50%,0,0)" }}>
        <div style={{ height: 42, padding: "0 12px", display: "flex", alignItems: "center", gap: 8, borderBottom: "1px solid var(--line)" }}>
          <span style={{ color: "var(--tx3)" }}>⌕</span>
          <input autoFocus value={q} placeholder="切号、跳页、刷新、探针…" data-cmdk-input=""
                 onChange={(e) => { setQ(e.target.value); setHk(null); setMoved(false); }}
                 onKeyDown={(e) => {
                   e.stopPropagation();
                   if (e.key === "Escape") { e.preventDefault(); onClose(); }
                   else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); setMoved(true); setKh(cmdkMove(kh, e.key === "ArrowDown" ? 1 : -1, shown.length)); }
                   else if (e.key === "Enter") { e.preventDefault(); go(shown[kh]); }
                 }}
                 style={{ flex: 1, minWidth: 0, background: "transparent", border: 0, outline: 0, color: "var(--tx)", fontSize: 13, fontFamily: "inherit" }} />
          <span style={{ fontFamily: MONO, fontSize: 10.5, color: "var(--tx3)" }}>esc</span>
        </div>
        <div style={{ position: "relative", padding: 4 }}>
          {shown.length > 0 && (
            <i style={{ position: "absolute", left: 4, right: 4, top: 4, height: 32, borderRadius: 7, background: "rgba(45,212,191,.12)",
                        transform: `translate3d(0, ${kh * 32}px, 0)`, transition: moved ? "transform .1s cubic-bezier(.2,.9,.3,1)" : "none",
                        pointerEvents: "none" }} />
          )}
          {shown.map((it, i) => (
            <div key={it.key} data-cmdk-item={it.key} data-active={i === kh ? "" : undefined}
                 onMouseEnter={() => { if (i !== kh) { setMoved(true); setKh(i); } }}
                 onMouseDown={(e) => { e.preventDefault(); go(it); }}
                 style={{ position: "relative", height: 32, padding: "0 10px", display: "flex", alignItems: "center", gap: 10, fontSize: 12.5,
                          cursor: "pointer", color: "var(--tx)" }}>
              <span style={{ width: 16, textAlign: "center", color: it.color, flexShrink: 0 }}>{it.icon}</span>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{it.label}</span>
              <span style={{ flex: 1 }} />
              <span style={{ fontFamily: MONO, fontSize: 10.5, color: "var(--tx3)" }}>{it.hint}</span>
            </div>
          ))}
          {shown.length === 0 && (
            <div style={{ height: 32, display: "flex", alignItems: "center", padding: "0 10px", fontSize: 12, color: "var(--tx3)" }}>没有匹配的操作</div>
          )}
        </div>
      </div>
    </div>
  );
}
