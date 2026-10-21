import { useLayoutEffect, useRef, useState } from "react";
import type { Theme } from "../theme";

/**
 * 主导航（AICoop 交接包 2026-10-21 · `10_brand/P10_Nav` 方案 A「线性」，1:1）。
 *
 * 栏宽 64 · 按钮 40×40 圆角 10 · 间距 8 · 上下内边距 16 · 图标 20 · 描边 1.75。
 * 选中块与悬停高亮都是**一个**绝对定位的块，按 `translate3d` 滑到目标按钮上（只动 transform）。
 * 按下（mousedown）即切换，click 只做幂等兜底。提示在热身后（正在悬停另一项，或离开不足 300 ms）
 * 直接切换、不重播入场动画。
 *
 * ★ 每个按钮保留 `data-page`：harness 与测试按身份点导航项，不按位置（插一页就会点错，且看不出来）。
 * ★ 稿子没有「展开侧栏 / 版本号」两项：版本号在标题栏；页面名由右侧提示给出。
 */
export type NavPage = "overview" | "traffic" | "logs" | "relay" | "requests" | "settings";

interface Item { id: NavPage; name: string; icon: React.ReactNode }

const SVG = (children: React.ReactNode) => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);

const MAIN: Item[] = [
  { id: "overview", name: "总览", icon: SVG(<g className="a-dash"><rect x="3.5" y="3.5" width="7" height="8.5" rx="1.8" /><rect className="dr2" x="13.5" y="3.5" width="7" height="5" rx="1.8" /><rect x="13.5" y="11.5" width="7" height="9" rx="1.8" /><rect x="3.5" y="15.5" width="7" height="5" rx="1.8" /></g>) },
  { id: "traffic", name: "Token 消耗", icon: SVG(<><path d="M3.5 3.5v17h17" /><g className="a-bars"><path d="M8.5 16.5v-4.5" /><path d="M13 16.5v-9" /><path d="M17.5 16.5v-6" /></g></>) },
  { id: "logs", name: "代理轮换", icon: SVG(<g className="a-rot"><path d="M20 11.5a8 8 0 0 0-14.3-4.9L4 8.5" /><path d="M4 3.8v4.7h4.7" /><path d="M4 12.5a8 8 0 0 0 14.3 4.9L20 15.5" /><path d="M20 20.2v-4.7h-4.7" /></g>) },
  { id: "relay", name: "中转站", icon: SVG(<><path d="M8.6 18.5H16a3.3 3.3 0 0 0 0-6.6H8a3.3 3.3 0 0 1 0-6.6h7.4" /><g className="a-dots"><circle cx="6" cy="18.5" r="2.3" /><circle cx="18" cy="5.3" r="2.3" /></g></>) },
  { id: "requests", name: "请求", icon: SVG(<><g className="a-lines"><path className="l1" d="M9 6.5h11" /><path className="l2" d="M9 12h11" /><path className="l3" d="M9 17.5h7" /></g><circle cx="4.8" cy="6.5" r=".9" /><circle cx="4.8" cy="12" r=".9" /><circle cx="4.8" cy="17.5" r=".9" /></>) },
];
const SETTINGS: Item = { id: "settings", name: "设置", icon: SVG(<g className="a-gear"><path d="M10.3 3.2h3.4l.5 2.4 1.7.9 2.3-.9 1.7 2.9-1.8 1.6v1.8l1.8 1.6-1.7 2.9-2.3-.9-1.7.9-.5 2.4h-3.4l-.5-2.4-1.7-.9-2.3.9-1.7-2.9 1.8-1.6v-1.8L4.1 8.5l1.7-2.9 2.3.9 1.7-.9z" /><circle cx="12" cy="12" r="2.6" /></g>) };

export const NAV_ORDER: NavPage[] = [...MAIN.map((i) => i.id), SETTINGS.id];

/** 稿子的 `yOf`：前 5 项是常量；设置贴底（随栏高变）⇒ 用 CSS 锚定，不测量。 */
const topOf = (id: NavPage): string => {
  const i = MAIN.findIndex((m) => m.id === id);
  return i >= 0 ? `${16 + i * 48}px` : "calc(100% - 56px)";
};

/** 动效关着吗：系统「减弱动态效果」，或 harness 的 `?notrans=1`（WAAPI 不吃 CSS 的 `transition: none`）。 */
const motionOff = (): boolean =>
  !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.notrans === "1";

/**
 * FLIP：位置由 `top` 定（窗口缩放时直接到位），移动时只用 transform 补一段滑动。
 * `fromTop` 是**视觉**起点（含正在跑的动画）。★ 先取消正在跑的那段再量终点 —— 不取消的话量到的是
 * 动画中途的位置，快速连点或鼠标快速扫过时块会跳一下（四方评审 Opus M2）。
 */
function slide(el: HTMLElement | null, fromTop: number | null, ms: number): void {
  if (!el || typeof el.animate !== "function") return;
  el.getAnimations().forEach((a) => a.cancel());
  if (fromTop === null || motionOff()) return;
  const dy = fromTop - el.getBoundingClientRect().top;
  if (Math.abs(dy) < 0.5) return;
  el.animate([{ transform: `translate3d(0, ${dy}px, 0)` }, { transform: "translate3d(0, 0, 0)" }],
             { duration: ms, easing: "cubic-bezier(.2,.9,.3,1)" });
}

export function NavRail({ t, page, onPage }: { t: Theme; page: NavPage; onPage: (p: NavPage) => void }) {
  const [hover, setHover] = useState<NavPage | null>(null);
  /** 悬停块离开时原地淡出：记住最后悬停的那项，块停在那里（不跳回选中项再淡出）。 */
  const [lastHover, setLastHover] = useState<NavPage | null>(null);
  const [instant, setInstant] = useState(false);   // 提示不重播入场（热身）
  const leftAt = useRef(0);
  const selRef = useRef<HTMLElement | null>(null);
  const hovRef = useRef<HTMLElement | null>(null);
  const selFrom = useRef<number | null>(null);
  const hovFrom = useRef<number | null>(null);
  const shownPage = useRef<NavPage>(page);

  // ★ 任何换页都滑（⌘, / 菜单栏 / 刘海 / 悬停面板跳过来），不只是点导航：起点 = 选中块此刻的视觉位置
  useLayoutEffect(() => {
    if (shownPage.current === page) return;
    shownPage.current = page;
    slide(selRef.current, selFrom.current, 200);
    selFrom.current = null;
  }, [page]);
  useLayoutEffect(() => { slide(hovRef.current, hovFrom.current, 120); hovFrom.current = null; }, [hover]);

  const leave = () => { if (hover !== null) { leftAt.current = Date.now(); setHover(null); } };
  const enter = (id: NavPage) => {
    if (hover === id) return;
    setInstant(hover !== null || Date.now() - leftAt.current < 300);
    // 只有从另一项滑过来才动；从栏外进来是原地淡入（稿子 `hT`）。
    hovFrom.current = hover !== null ? hovRef.current?.getBoundingClientRect().top ?? null : null;
    setHover(id);
    setLastHover(id);
  };
  const press = (id: NavPage) => {
    if (id === page) return;
    selFrom.current = selRef.current?.getBoundingClientRect().top ?? null;
    onPage(id);
  };
  // 换页之前记下选中块的视觉位置（外部换页走不到 `press`）
  if (shownPage.current !== page && selFrom.current === null && selRef.current) {
    selFrom.current = selRef.current.getBoundingClientRect().top;
  }

  const button = (it: Item) => {
    const on = page === it.id;
    return (
      <button key={it.id} type="button" data-page={it.id} aria-label={it.name} aria-current={on ? "page" : undefined}
              className="cb-nv" onMouseDown={(e) => { if (e.button === 0) press(it.id); }} onClick={() => press(it.id)}
              onMouseEnter={() => enter(it.id)}
              style={{ color: on ? t.navOn : hover === it.id ? t.navHover : t.navOff }}>
        <span className="cb-nv-ic">{it.icon}</span>
        {hover === it.id && (
          <span className="cb-nv-tip" style={{ animation: instant ? "none" : undefined, background: t.navTipBg, color: t.navTipFg }}>
            {it.name}
          </span>
        )}
      </button>
    );
  };

  const block = { position: "absolute", left: 12, width: 40, height: 40, borderRadius: 10 } as const;
  return (
    // 按钮之间的 8 px 缝和左右内边距直接落在 nav 上：光标停在那里也算离开（悬停块与提示不停在上一项上）
    <nav className="cb-rail" onMouseLeave={leave} onMouseOver={(e) => { if (e.target === e.currentTarget) leave(); }}
         style={{ position: "relative", width: 64, flexShrink: 0, boxSizing: "border-box", padding: "16px 12px",
                  borderRight: `1px solid ${t.navBorder}`, background: t.railBg,
                  display: "flex", flexDirection: "column", alignItems: "center", transition: "background-color .35s ease" }}>
      <i ref={selRef} aria-hidden="true" data-nav-sel={page}
         style={{ ...block, top: topOf(page), background: t.accent, willChange: "transform", pointerEvents: "none" }} />
      <i ref={hovRef} aria-hidden="true" data-nav-hover={hover ?? ""}
         style={{ ...block, top: topOf(hover ?? lastHover ?? page), background: t.navHoverBg, pointerEvents: "none",
                  opacity: hover && hover !== page ? 1 : 0, transition: "opacity .1s" }} />
      {MAIN.map(button)}
      {/* 最后一项与设置之间的大空白、分隔线同样算离开 */}
      <span style={{ flex: 1, alignSelf: "stretch" }} onMouseEnter={leave} />
      <i onMouseEnter={leave} style={{ display: "block", width: 28, height: 1, background: t.navDivider, margin: "0 auto 8px" }} />
      {button(SETTINGS)}
    </nav>
  );
}
