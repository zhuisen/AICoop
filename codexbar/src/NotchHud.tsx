import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useStore } from "./hooks/useStore";
import { useAgyQuota } from "./hooks/useAgyQuota";
import { useAgyPool } from "./hooks/useAgyPool";
import { usePlatformPrefs } from "./hooks/usePlatformPrefs";
import { usePrivacy } from "./hooks/usePrivacy";
import { maskId } from "./helpers";
import { agySegs, codexSegs, ringNum, segColor, type NotchSeg } from "./notchSegs";
import "./notch.css";

/** 与 `notch.rs` 的 `PANEL_W`、`notch.css` 的 `--pw` 同值。闸在 `tests/test_notch_hud.py`。 */
const PANEL_W = 312;

/**
 * 刘海额度条（用户 2026-10-17 从 demo 里选定：收起 = 刘海下沿分段细线，悬停 = 额度环面板；
 * 只显示 Codex 与 Antigravity；默认关）。窗口、层级、悬停判定全在 `notch.rs`，这里只画；
 * 画什么在 `notchSegs.ts`（纯函数，有行为闸）。
 *
 * ★ 颜色走**托盘那一条**规则（`quotaColor`：<50 琥珀、否则绿；显示成 0 额外标红）——
 *   刘海条和托盘标题是同一类"瞄一眼"的指示，两处说法必须一致（ui.md「额度色阈值只有一条规则」）。
 * ★ 取数**一个子进程都不起**：`useAgyPool(false)` 只读池文件、收别的 webview 广播的现读结果；
 *   `useAgyQuota({ enabled: false })` 只收采样器推送。保鲜由菜单栏 webview 负责（它是唯一的 `background`）。
 */
type Seg = NotchSeg;

function Ring({ s }: { s: Seg }) {
  const r = 18, c = 2 * Math.PI * r;
  const col = s.pct == null ? "#8a929c" : segColor(s.pct);
  const d = s.pct == null ? 0 : (ringNum(s.pct) / 100) * c;
  return (
    <svg width="46" height="46" viewBox="0 0 46 46" aria-hidden="true">
      <circle cx="23" cy="23" r={r} fill="none" stroke="rgba(255,255,255,.14)" strokeWidth="4" />
      {s.pct != null && (
        <circle cx="23" cy="23" r={r} fill="none" stroke={col} strokeWidth="4" strokeLinecap="round"
                strokeDasharray={`${d.toFixed(2)} ${c.toFixed(2)}`} transform="rotate(-90 23 23)" />
      )}
      <text x="23" y="27" textAnchor="middle" fontFamily="'JetBrains Mono', ui-monospace, Menlo, monospace"
            fontSize="11" fontWeight="600" fill={col}>{s.pct == null ? "—" : ringNum(s.pct)}</text>
    </svg>
  );
}

export default function NotchHud() {
  const { accounts, inUseNode, counts } = useStore();
  const { snap: agySnap } = useAgyQuota({ enabled: false });
  const agyPool = useAgyPool(false);
  const { prefs } = usePlatformPrefs();
  const { privacy } = usePrivacy();
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const geom = (g: { width: number; height: number } | null | undefined) => {
      if (!g) return;
      document.documentElement.style.setProperty("--nw", `${g.width}px`);
      document.documentElement.style.setProperty("--nh", `${g.height}px`);
    };
    let dead = false;
    const uns = [
      listen<boolean>("notch-open", (e) => setOpen(!!e.payload)),
      // 改分辨率 / 换屏后刘海尺寸变了，Rust 摆完窗口再告诉这里
      listen<{ width: number; height: number }>("notch-geom", (e) => geom(e.payload)),
    ];
    // ★ 两个监听都注册好之后再问一次当前状态：窗口刚建好时光标已经停在刘海上，
    //   `notch-open` 可能早于 listen 生效 —— 不补这一句，Rust 认为展开了、这里还收着。
    void Promise.all(uns).then(() => invoke<{ width: number; height: number; open?: boolean } | null>("notch_geometry"))
      .then((g) => { if (dead || !g) return; geom(g); setOpen(!!g.open); })
      .catch(() => {});
    return () => { dead = true; for (const u of uns) void u.then((f) => f()); };
  }, []);

  const inUse = accounts.find((a) => a.aid === inUseNode);
  const agyCur = agyPool.accounts.find((a) => a.sub === agyPool.liveSub);
  const segs = useMemo<Seg[]>(() => {
    const agySnapForCur = agyCur ? agyPool.snapshotOf(agyCur, agySnap)
      // 池还没建起来 —— 退回本机那份（与菜单栏池空那一路同）
      : agyPool.accounts.length === 0 ? agySnap : null;
    return [
      ...codexSegs(inUse, !!prefs.by?.codex?.off),
      ...agySegs(agySnapForCur, !!prefs.by?.agy?.off, agyPool.accounts.length > 0 && !agyCur),
    ];
  }, [inUse, agyCur, agyPool, agySnap, prefs]);

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
        {segs.length === 0 && <div className="nh-empty">暂无可显示的额度（Codex / agy 都没开或都没读到）</div>}
        <div className="nh-rings" style={{ gridTemplateColumns: `repeat(${Math.max(1, segs.length)}, 1fr)` }}>
          {segs.map((s) => (
            <div key={s.key} className={`nh-ring${s.stale ? " stale" : ""}`} title={s.title}>
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
              {s.pct != null && <i style={{ width: `${ringNum(s.pct)}%`, background: segColor(s.pct) }} />}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
