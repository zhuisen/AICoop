import type React from "react";

/**
 * 共用的图标与图标按钮：刷新图标（总览四家卡 / 头部、中转站页）· `IconBtn`（中转站表）。
 * ★ 2026-10-19 总览照交接包 page5 重做，旧动作条（`CardActionBar`）删除，它独用的
 *   轮换 / 置顶 / 钥匙 / 笔 / 信息 / 垃圾桶六个图标随之删除（要恢复从 git 历史取）。
 *
 * ★★ 抽出来的理由与 `KpiStrip` / `PageSub` 一字不差：两张卡各写一份图标与按钮，
 *   下次调尺寸/配色必然只改一边，而那**不会报任何错** —— 本仓已经因此漂过两次。
 *   2026-09-13 用户要求「gemini 的功能 1:1 同步上 codex」时，这份就是第一个要共用的东西。
 *
 * ★ **不用 emoji**（全局 `ui-design.md` 的「禁忌」明写）：emoji 在不同系统/字体下
 *   会变彩色、变宽窄，与等宽仪表风格直接冲突。这里是单色描边 SVG，与侧栏图标同族。
 */
/**
 * 刷新。★ **搬到这里是为了不抄第二份** —— 它原来是 `App.tsx` 里的模块局部 `IconRefresh`，
 * 而中转站页也要一个长得一模一样的「↻ 刷新余额」。两处各写一份 SVG，下次调尺寸/线宽
 * 必然只改一边，而那**不会报任何错**（本仓已因此漂过两次，正是这个文件头上写的理由）。
 * ⚠️ `App.tsx` 不能反过来 import 页面里的东西（它 import 了 `RelayPage`，会成环），
 *   所以公共件只能落在这种两边都依赖的叶子模块里。
 */
export const IcRefresh = ({ size = 12, spin }: { size?: number; spin?: boolean }): React.ReactElement => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"
       style={{ display: "block", flexShrink: 0, animation: spin ? "cbSpin .9s linear infinite" : undefined }}>
    <path d="M20 12a8 8 0 1 1-2.4-5.7M20 4v4.5h-4.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
/** 动作条上的图标按钮。**全名只在 `title` 里** —— 用户 2026-09-07:「精简成一两个字符,
 *  鼠标悬浮才展示完整的名字」。★ 一律 34×26 定宽:图标宽度不一时按钮会参差,
 *  而参差的按钮行看着就像没对齐。 */
export function IconBtn({ title, onClick, color, border, bg, children }: {
  title: string; onClick: () => void; color: string; border: string; bg?: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <span onClick={onClick} title={title} aria-label={title}
          /* ★★ 2026-09-21：从 `width:34 + flexShrink:0` 改成**可收缩**。
             固定宽 + 不收缩 = 空间不够时只能折行，而用户明确要「不换行、一起压缩」。
             28 是实测下限：再窄图标（13px）两侧就只剩 7px，按钮看着像被裁了。 */
          style={{ width: 34, minWidth: 28, flexShrink: 1, height: 26, display: "grid", placeItems: "center",
                   borderRadius: 6, cursor: "pointer", color,
                   border: `1px solid ${border}`, background: bg ?? "transparent",
                   transition: "background .15s, color .15s" }}>{children}</span>
  );
}
