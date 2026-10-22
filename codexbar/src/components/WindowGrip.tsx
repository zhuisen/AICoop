import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { ovCols } from "../overview";

/**
 * 主窗口右下角的缩放抓手（用户 2026-10-22 从 demo v2 选 G3 + S3 + S4 + M）。
 * - G3：沿窗口圆角的一段弧。平时不画，光标进窗口才淡出（`App.css` `.cb-root:hover`）。
 * - S4：悬停 / 拖动时抓手变青并带一点微光，不画任何边线。
 * - M：光标进入抓手 56 px 内，抓手朝光标偏 ≤ 5 px，再弹回（Animate UI `Magnetic` 的参数，手写、不装依赖）。
 * - S3：按下后尺寸由 Rust 跟光标改（`win_chrome::grip_start`，macOS 没有原生的缩放拖动），
 *   每次变化发 `grip-size`；这里在抓手左上画胶囊「W × H · 总览 N 列 · 吸住 · 档名」，吸住时轻跳一下。
 * 「总览 N 列」= 停稳后那一刻的总览列数：Rust 给预测的倍率，内容区宽 = 窗口 ÷ 倍率 − 侧栏与边距（按下时量）。
 */
interface GripSize { w: number; h: number; label: string | null; zoom: number }

const OVERHEAD_KEY = "codexbar_ov_overhead";
const RANGE = 56, MAX_OFF = 5, PULL = 0.3;

function measureOverhead(): number | null {
  const ov = document.querySelector<HTMLElement>(".ov-root");
  if (ov && ov.clientWidth > 0) {
    const o = window.innerWidth - ov.clientWidth;
    try { localStorage.setItem(OVERHEAD_KEY, String(o)); } catch { /* 存不下就只用这一次 */ }
    return o;
  }
  const v = Number(localStorage.getItem(OVERHEAD_KEY));
  return Number.isFinite(v) && v > 0 ? v : null;
}

export default function WindowGrip() {
  const [size, setSize] = useState<GripSize | null>(null);
  const [bump, setBump] = useState(0);
  const lastLabel = useRef<string | null>(null);
  const overhead = useRef<number | null>(null);
  const el = useRef<HTMLDivElement>(null);
  const mg = useRef({ x: 0, y: 0, vx: 0, vy: 0, tx: 0, ty: 0, raf: 0 });
  const dragging = size !== null;

  useEffect(() => {
    const un = listen<GripSize | null>("grip-size", (e) => {
      const p = e.payload;
      if (p && overhead.current == null) overhead.current = measureOverhead();
      if (!p) overhead.current = null;
      setSize(p);
      const lb = p?.label ?? null;
      if (lb && lb !== lastLabel.current) setBump((n) => n + 1);
      lastLabel.current = lb;
    });
    return () => { void un.then((f) => f()); };
  }, []);

  // M：只在需要时跑弹簧（靠近 / 回弹中），不常驻 rAF
  useEffect(() => {
    const m = mg.current;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const tick = () => {
      const K = 200, C = 20, dt = 1 / 60;
      m.vx += (K * (m.tx - m.x) - C * m.vx) * dt; m.x += m.vx * dt;
      m.vy += (K * (m.ty - m.y) - C * m.vy) * dt; m.y += m.vy * dt;
      if (el.current) el.current.style.transform = `translate(${m.x.toFixed(2)}px, ${m.y.toFixed(2)}px)`;
      const still = Math.abs(m.tx - m.x) < 0.05 && Math.abs(m.ty - m.y) < 0.05 && Math.abs(m.vx) < 0.05 && Math.abs(m.vy) < 0.05;
      m.raf = still ? 0 : requestAnimationFrame(tick);
    };
    const onMove = (e: MouseEvent) => {
      if (reduce) return;
      const dx = e.clientX - (window.innerWidth - 12), dy = e.clientY - (window.innerHeight - 12);
      const near = Math.hypot(dx, dy) < RANGE;
      const tx = near ? Math.max(-MAX_OFF, Math.min(MAX_OFF, dx * PULL)) : 0;
      const ty = near ? Math.max(-MAX_OFF, Math.min(MAX_OFF, dy * PULL)) : 0;
      if (tx === m.tx && ty === m.ty) return;
      m.tx = tx; m.ty = ty;
      if (!m.raf) m.raf = requestAnimationFrame(tick);
    };
    window.addEventListener("mousemove", onMove);
    return () => { window.removeEventListener("mousemove", onMove); if (m.raf) cancelAnimationFrame(m.raf); };
  }, []);

  const start = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    overhead.current = measureOverhead();
    mg.current.tx = mg.current.ty = 0;
    invoke("grip_resize_start").catch(() => {});
  };

  const cols = size && overhead.current != null ? ovCols(size.w / (size.zoom || 1) - overhead.current) : null;
  return (
    <>
      <div ref={el} className={`win-grip${dragging ? " hot" : ""}`} data-win-grip onPointerDown={start} aria-hidden="true">
        <svg width="22" height="22" viewBox="0 0 22 22">
          <path d="M19.5 4 L19.5 6 A13.5 13.5 0 0 1 6 19.5 L4 19.5" strokeWidth="2" strokeLinecap="round" fill="none" />
        </svg>
      </div>
      <div key={bump} className={`win-pill${size?.label ? " snapped" : ""}${bump && size?.label ? " bump" : ""}`}
           data-win-pill style={{ display: size ? "block" : "none" }}>
        {size && <>
          <b>{Math.round(size.w)} × {Math.round(size.h)}</b>
          <span className="lb">{cols != null ? `总览 ${cols} 列` : ""}{size.label ? `${cols != null ? " · " : ""}吸住 · ${size.label}` : ""}</span>
        </>}
      </div>
    </>
  );
}
