import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useStore } from "./hooks/useStore";
import { useAgyQuota } from "./hooks/useAgyQuota";
import { usePlatformPrefs } from "./hooks/usePlatformPrefs";
import { usePrivacy } from "./hooks/usePrivacy";
import { agyShown, agyWinRows, agyResetText } from "./agy";
import { quotaColor, maskId } from "./helpers";
import "./notch.css";

/** 与 `notch.rs` 的 `PANEL_W`、`notch.css` 的 `--pw` 同值。闸在 `tests/test_notch_hud.py`。 */
const PANEL_W = 312;
const RED = "#E0524D";

/**
 * 刘海额度条（用户 2026-10-17 从 demo 里选定：收起 = 刘海下沿分段细线，悬停 = 额度环面板；
 * 只显示 Codex 与 Antigravity；默认关）。窗口、层级、悬停判定全在 `notch.rs`，这里只画。
 *
 * ★ 颜色走**托盘那一条**规则（`quotaColor`：<50 琥珀、否则绿；0 额外标红）——
 *   刘海条和托盘标题是同一类"瞄一眼"的指示，两处说法必须一致（ui.md「额度色阈值只有一条规则」）。
 * ★ 读不到就是空槽 + `—`，**不编数**：Codex 的 `windows` 已经把读不到的窗口剔掉
 *   （`buildWindow` 返回 null），agy 的 `remaining == null` 原样当未知。
 */
interface Seg {
  key: string;
  name: string;
  /** null = 读不到 */
  pct: number | null;
  reset: string;
  /** agy 的上次读数（`agyShown().stale`）—— 照画但降亮度，与菜单栏行同口径 */
  stale?: boolean;
}

const segColor = (pct: number) => (pct <= 0 ? RED : quotaColor(pct));

function Ring({ s }: { s: Seg }) {
  const r = 18, c = 2 * Math.PI * r;
  const col = s.pct == null ? "#8a929c" : segColor(s.pct);
  const d = s.pct == null ? 0 : (Math.max(0, Math.min(100, s.pct)) / 100) * c;
  return (
    <svg width="46" height="46" viewBox="0 0 46 46" aria-hidden="true">
      <circle cx="23" cy="23" r={r} fill="none" stroke="rgba(255,255,255,.14)" strokeWidth="4" />
      {s.pct != null && (
        <circle cx="23" cy="23" r={r} fill="none" stroke={col} strokeWidth="4" strokeLinecap="round"
                strokeDasharray={`${d.toFixed(2)} ${c.toFixed(2)}`} transform="rotate(-90 23 23)" />
      )}
      <text x="23" y="27" textAnchor="middle" fontFamily="'JetBrains Mono', ui-monospace, Menlo, monospace"
            fontSize="11" fontWeight="600" fill={col}>{s.pct == null ? "—" : Math.round(s.pct)}</text>
    </svg>
  );
}

export default function NotchHud() {
  const { accounts, inUseNode, counts } = useStore();
  const { snap: agySnap } = useAgyQuota();
  const { prefs } = usePlatformPrefs();
  const { privacy } = usePrivacy();
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const un = listen<boolean>("notch-open", (e) => setOpen(!!e.payload));
    invoke<{ width: number; height: number } | null>("notch_geometry").then((g) => {
      if (!g) return;
      document.documentElement.style.setProperty("--nw", `${g.width}px`);
      document.documentElement.style.setProperty("--nh", `${g.height}px`);
    }).catch(() => {});
    return () => { void un.then((f) => f()); };
  }, []);

  const inUse = accounts.find((a) => a.aid === inUseNode);
  const segs = useMemo<Seg[]>(() => {
    const out: Seg[] = [];
    if (inUse && !prefs.by?.codex?.off) {
      if (inUse.status === "dead") out.push({ key: "codex-dead", name: "Codex", pct: null, reset: "失效" });
      else if (inUse.windows.length === 0) out.push({ key: "codex-unknown", name: "Codex", pct: null, reset: "待刷新" });
      else for (const w of inUse.windows) out.push({ key: `codex-${w.label}`, name: `Codex ${w.label}`, pct: w.pct, reset: w.reset });
    }
    const shown = agyShown(agySnap);
    if (shown && !prefs.by?.agy?.off) {
      for (const r of agyWinRows(shown.quota)) {
        out.push({ key: `agy-${r.label}`, name: `agy ${r.label}`, pct: r.remaining,
                   reset: agyResetText(r).text, stale: shown.stale || r.seen_at != null });
      }
    }
    return out;
  }, [inUse, agySnap, prefs]);

  // 面板自然高度随窗口个数变 → 报给 Rust，展开时按它定窗口高
  useEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const report = () => { invoke("notch_panel_height", { h: el.scrollHeight }).catch(() => {}); };
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const node = inUse ? maskId(inUse.node, privacy) : null;
  return (
    <div className={open ? "nh-open" : undefined} style={{ ["--pw" as string]: `${PANEL_W}px` }}>
      <div className="nh-panel" ref={panelRef}
           onClick={() => { invoke("set_main_visible", { show: true }).catch(() => {}); }}>
        <div className="nh-head"><b>额度剩余 %</b><span>{node ? `Codex 在用 ${node}` : ""}</span></div>
        <div className="nh-rings" style={{ gridTemplateColumns: `repeat(${Math.max(1, segs.length)}, 1fr)` }}>
          {segs.map((s) => (
            <div key={s.key} className={`nh-ring${s.stale ? " stale" : ""}`}
                 title={s.stale ? "上次读到的数，agy 现在没在跑" : undefined}>
              <Ring s={s} />
              <span className="nm">{s.name}</span>
              <span className="rs">{s.reset}</span>
            </div>
          ))}
        </div>
        <div className="nh-foot">账号池 <b>{counts.live}</b> 个号可用 · 点这里打开 CodexBar</div>
      </div>
      <div className="nh-island">
        <div className="nh-bars">
          {segs.map((s) => (
            <span key={s.key} className={s.stale ? "stale" : undefined}>
              {s.pct != null && <i style={{ width: `${Math.max(0, Math.min(100, s.pct))}%`, background: segColor(s.pct) }} />}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
