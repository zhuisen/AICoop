import { useRef } from "react";
import { probeShouldFire } from "../../mbLogic";

const Bolt = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block", flexShrink: 0 }}>
    <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" fill="currentColor" />
  </svg>
);

/**
 * 菜单栏的计费探针（尺寸 / 颜色照抄 `P4PopRows.html` 底栏第二格）。
 *
 * ★ **点一下就执行**（用户 2026-10-21「探针的功能 修改点击即可」），取代交接包 4f 的「按住 0.6 s」。
 *   与免费按钮的区分靠外观（琥珀 + ⚡ +「计费」），不靠确认动作。
 * ★ 连点只算一次：判据在 `mbLogic.ts::probeShouldFire`（零 import，有行为闸）。
 */
export default function ProbeBtn({ onFire, loading, hint }: { onFire: () => void; loading: boolean; hint: string }) {
  const last = useRef<number | null>(null);
  const fire = () => {
    const now = performance.now();
    if (!probeShouldFire(last.current, now, loading)) return;
    last.current = now;
    onFire();
  };
  return (
    <span className="mb-foot-btn" role="button" tabIndex={0} data-mb-probe={loading ? "loading" : "idle"}
          title={`${hint}\n\n点一下就执行（计费）。`}
          onClick={(e) => { e.stopPropagation(); fire(); }}
          onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !e.repeat) { e.preventDefault(); fire(); } }}
          style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                   borderRadius: 9, border: "1px solid var(--warnLine)", color: "var(--warn)", fontSize: 13, fontWeight: 600,
                   overflow: "hidden", cursor: loading ? "default" : "pointer", userSelect: "none",
                   opacity: loading ? .6 : 1 }}>
      <span style={{ position: "relative", display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
        {loading ? <><span className="mb-spinner" />探测中…</> : <>
          <Bolt />探针
          <span style={{ fontSize: 10.5, padding: "0 5px", borderRadius: 4, border: "1px solid var(--warnLine)" }}>计费</span>
        </>}
      </span>
    </span>
  );
}
