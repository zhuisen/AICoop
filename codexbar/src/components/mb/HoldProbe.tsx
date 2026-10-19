import { useEffect, useReducer, useRef } from "react";
import { HOLD_IDLE, HOLD_MS, RETREAT_MS, holdFill, holdReduce } from "../../mbLogic";

const Bolt = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" fill="currentColor" />
  </svg>
);

/**
 * 菜单栏的计费探针（交接包 4f：「按住 0.6 s 才执行：按钮内琥珀色进度从左填满；中途松手
 * 150 ms 退回、不执行；完成后底部提示」）。尺寸 / 颜色照抄 `P4PopRows.html` 底栏第二格。
 *
 * ★ 它取代了菜单栏里原来的「两段确认」（`ProbeButton variant="menubar"`）。主窗的探针仍是两段确认。
 * ★ 判据全在 `mbLogic.ts::holdReduce`（零 import，有行为闸）：这里只把指针事件和计时器喂给它。
 * ★ 指针移出按钮 = 松手（与画板 `onMouseLeave={{holdEnd}}` 一致），所以「按下后拖走」不会误发。
 */
export default function HoldProbe({ onFire, loading, hint, forceHolding }: {
  onFire: () => void;
  loading: boolean;
  hint: string;
  /** harness 截「按住中途」那一帧用（`?probehold=1`）。生产里恒 false。 */
  forceHolding?: boolean;
}) {
  const [s, send] = useReducer(holdReduce, HOLD_IDLE);
  const timer = useRef<number | null>(null);
  const fireRef = useRef(onFire);
  fireRef.current = onFire;

  useEffect(() => {
    if (forceHolding) send({ type: "down", now: performance.now() });
  }, [forceHolding]);

  useEffect(() => {
    if (timer.current != null) { window.clearTimeout(timer.current); timer.current = null; }
    if (forceHolding) return;
    if (s.phase === "holding") {
      timer.current = window.setTimeout(() => send({ type: "tick", now: performance.now() }), HOLD_MS + 5);
    } else if (s.phase === "retreat") {
      timer.current = window.setTimeout(() => send({ type: "tick", now: performance.now() }), RETREAT_MS + 5);
    } else if (s.phase === "fired") {
      fireRef.current();
      send({ type: "reset" });
    }
    return () => { if (timer.current != null) window.clearTimeout(timer.current); };
  }, [s, forceHolding]);

  const fill = holdFill(s);
  const up = () => send({ type: "up", now: performance.now() });
  return (
    <span className="mb-foot-btn" data-mb-probe={s.phase} title={`${hint}\n\n按住 0.6 秒才会执行；中途松手取消。`}
          onMouseDown={(e) => { if (e.button === 0) send({ type: "down", now: performance.now(), disabled: loading }); }}
          onMouseUp={up} onMouseLeave={() => send({ type: "leave", now: performance.now() })}
          style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                   borderRadius: 9, border: "1px solid var(--warnLine)", color: "var(--warn)", fontSize: 13, fontWeight: 600,
                   overflow: "hidden", cursor: loading ? "default" : "pointer", userSelect: "none",
                   opacity: loading ? .6 : 1 }}>
      <i data-mb-probe-fill="" style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${forceHolding ? 55 : fill.width}%`,
                  background: "var(--warnBg2)", transition: forceHolding ? "none" : fill.transition }} />
      <span style={{ position: "relative", display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
        {loading ? <><span className="mb-spinner" />探测中…</> : <>
          <Bolt />{s.phase === "holding" ? "按住…" : "探针"}
          <span style={{ fontSize: 10.5, padding: "0 5px", borderRadius: 4, border: "1px solid var(--warnLine)" }}>计费</span>
        </>}
      </span>
    </span>
  );
}
