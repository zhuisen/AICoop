import { useLayoutEffect, useRef, useState } from "react";
import type { Theme } from "../theme";

export interface Kpi {
  k: string;
  v: string;
  /**
   * 原始数值 + 格式化函数。**两个都给了这一格才滚**，否则原样显示 `v`。
   * 像「Claude 73.6%」「—」这类不是纯数的格子不给 —— 把一个占位符从 0 滚上来只会让人以为在加载。
   */
  n?: number;
  fmt?: (x: number) => string;
  /** 主数值颜色,缺省用正文色 */
  c?: string;
  /** 数值下方的小字 */
  sub?: string;
  /** 小字颜色(环比涨绿跌红),缺省 `t.text2` */
  subC?: string;
  /** 放不下时**先整格让出去**（在缩数字之前）。只给页面别处已有同一信息的格子用
   *  —— 「最大占比」= 平台列表第一行的占比（用户 2026-10-14：最小尺寸下去掉它）。 */
  optional?: boolean;
}

/** 环比 / 涨跌的固定语义色。绿=上涨、红=下跌,与全局设计规范一致。 */
export const UP = "#27B26B";
export const DOWN = "#E0524D";

/**
 * 顶部 KPI 条。**总览页和平台详情页共用这一份。**
 *
 * ★ 抽出来的原因是它已经漂过两次:两页各写一份渲染,总览把「合计 token」改成「总 token」时详情页
 * 没跟上;总览加了「环比」「缓存已省」子行、改成均分居中之后,详情页仍是左侧紧排且没有子行
 * (用户 2026-08-10 实测截图)。同一条 UI 两个实现,迟早在边界上分叉 —— 这里只留一个。
 *
 * 布局用 `space-evenly` 而不是 `justifyContent:center`:后者只是把空白从右边挪成左右各一半,
 * 条目仍然挤在中间。每格文字居中,配合均分才读得整齐。
 */
const VALUE_PX = 29;
const VALUE_MIN_PX = 20;
const GAP = 18;
const GAP_MIN = 10;
const PAD_X = 18;

interface Fit { px: number; gap: number; wrap: boolean; drop: boolean }
const FULL: Fit = { px: VALUE_PX, gap: GAP, wrap: false, drop: false };

/**
 * ★★ 一行放不下时**只缩 hero 数字**（29 → 最小 20px），标签 12.5 / 小字 11 不动（用户 2026-10-14：
 *   「最小的画面都能标题一行处理完」）。那两档是 D 档定稿、小字 9px 时用户报过「没看到」，
 *   所以能让的只有本来就最大的那一个。20px 仍放不下才退回旧行为：换行，**绝不裁**。
 * 判据按**终值**算：值宽 ∝ 字号，`.cb-kpi-v::after` 用 `data-v` 撑住终值宽度（入场滚动的中途值更短，
 *   拿它算会在滚完后溢出）。伪元素不进 textContent，`--dump-dom` 的断言看不见它。
 * 幂等：每格的「单位字号宽」不随当前字号变，同一宽度反复算出同一个结果 —— 不会自己抖。
 */
function fitFor(avail: number, all: { fixed: number; perPx: number; optional: boolean }[]): Fit {
  const need = (cells: typeof all, px: number, gap: number) =>
    cells.reduce((s, c) => s + Math.max(c.fixed, c.perPx * px) + 1, 0) + gap * (cells.length - 1);
  if (need(all, VALUE_PX, GAP) <= avail) return FULL;
  // 让位顺序：先整格让出可选格（数字保持原字号）→ 再收间距 → 再缩数字 → 最后换行
  const kept = all.filter((c) => !c.optional);
  const drop = kept.length < all.length;
  if (drop && need(kept, VALUE_PX, GAP) <= avail) return { ...FULL, drop };
  for (let px = VALUE_PX; px >= VALUE_MIN_PX; px -= 0.5) {
    if (need(kept, px, GAP_MIN) <= avail) return { px, gap: GAP_MIN, wrap: false, drop };
  }
  return { ...FULL, wrap: true, drop };
}

export default function KpiStrip({ t, items, intro = 1 }: {
  t: Theme; items: Kpi[];
  /** 入场进度 0→1（见 `useIntro`）。缺省 1 = 不动画，老调用点不用改。 */
  intro?: number;
}): React.ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState<Fit>(FULL);
  const sig = items.map((i) => `${i.k}\u0000${i.v}\u0000${i.sub ?? ""}`).join("\u0001");
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // ★ 每格的「固定宽 / 单位字号宽」只随**内容和字体**变，不随容器宽变（`fitFor` 的幂等就靠它）。
    //   所以只在内容变 / 字体到齐时量一次；拖窗口时 RO 只读容器宽 —— 原来每帧对每格
    //   `getComputedStyle` + `offsetWidth`，是强制同步布局（2026-10-15 三方评审）。
    let cells: { fixed: number; perPx: number; optional: boolean }[] = [];
    const measureCells = () => {
      // ★ 让出去的格子是 `visibility:hidden` + 绝对定位（不是 display:none / 不渲染），
      //   所以仍量得到自然宽 —— 量成 0 的话下一轮会判「放得下」又把它请回来，来回抖。
      cells = (Array.from(el.children) as HTMLElement[]).map((cell) => {
        const [lab, val, sub] = Array.from(cell.children) as HTMLElement[];
        const px = parseFloat(getComputedStyle(val).fontSize) || VALUE_PX;
        return { fixed: Math.max(lab.offsetWidth, sub?.offsetWidth ?? 0), perPx: val.offsetWidth / px,
                 optional: cell.dataset.kpiOptional != null };
      });
    };
    const refit = () => {
      const next = fitFor(el.clientWidth - 2 * PAD_X, cells);
      setFit((cur) => (cur.px === next.px && cur.gap === next.gap && cur.wrap === next.wrap
                       && cur.drop === next.drop ? cur : next));
    };
    measureCells();
    refit();
    const ro = new ResizeObserver(refit);
    ro.observe(el);
    // 字体晚到会改宽度（Space Grotesk 是 webfont），到齐后重量一次
    let live = true;
    document.fonts?.ready.then(() => { if (live) { measureCells(); refit(); } }).catch(() => undefined);
    return () => { live = false; ro.disconnect(); };
  }, [sig]);

  return (
    <div ref={ref} data-kpi-fit={fit.wrap ? "wrap" : String(fit.px)}
         style={{ position: "relative", display: "flex", justifyContent: "space-evenly", alignItems: "flex-start", gap: fit.gap,
                  // ★★ **数字被裁比排版难看严重得多** —— 900px 实测「9.76B」的格子渲染宽 68px、
                  //   自然宽 80px,右边直接切掉,读出来就是另一个数。缩到下限仍放不下就换行,绝不裁。
                  flexWrap: fit.wrap ? "wrap" : "nowrap", rowGap: 14,
                  padding: `10px ${PAD_X}px`, marginBottom: 9, borderRadius: 12,
                  background: t.isDark ? "#0e1319" : t.cardBg, border: `1px solid ${t.cardBorder}` }}>
      {items.map(({ k, v, c, sub, subC, n, fmt, optional }) => (
        <div key={k} data-kpi-optional={optional ? "" : undefined}
             data-kpi-dropped={optional && fit.drop ? "" : undefined}
             style={{ display: "flex", flexDirection: "column", alignItems: "center",
                      textAlign: "center", flexShrink: 0,
                      ...(optional && fit.drop
                        ? { position: "absolute", left: 0, top: 0, visibility: "hidden", pointerEvents: "none" }
                        : null) }}>
          {/* 标签 12.5px:从 11 / 12 / 12.5 / 13.5 四档里选的(用户 2026-08-10)。13.5 开始和 29px 的
              数值抢主次,11 又偏小。四档在 1000px 默认窗宽下都不溢出(最大需 701px / 可用 886px)。 */}
          <div style={{ fontSize: 12.5, color: "#10E0E0", fontFamily: "'JetBrains Mono'",
                        letterSpacing: ".04em", whiteSpace: "nowrap" }}>{k}</div>
          {/* ★ hero 数字用 **Space Grotesk**(比例字体),是对「一切数字用等宽」的**知情例外**。
              理由:那条规则的目的是"数字右对齐成列时能对齐",而这一格是**居中的单个数字**,不在列里。
              用户 2026-08-10 从 6 个 demo 里选的 D 档(11 / 29 / 11)。
              `tabular-nums` 仍然保留 —— 这个数每 2 分钟自动刷新,等宽数位能防止 9.85B → 10.1B 时宽度跳动。
              **仅限这一处**:模型行、费率卡那些真正成列的数字仍必须用 JetBrains Mono。 */}
          <div className="cb-kpi-v" data-v={v}
               style={{ fontSize: fit.px, fontWeight: 700, marginTop: 2, whiteSpace: "nowrap",
                        fontFamily: "'Space Grotesk'", fontVariantNumeric: "tabular-nums",
                        letterSpacing: "-.01em", color: c ?? t.text }}>
            {/* ★ 第二道防线:进度必须落在 [0,1) 才用它算 —— 上游钳过一次了，但这一格是
                **用户唯一会盯着看的数字**，画错一次的代价远大于这行判断。 */}
            {n != null && fmt && intro >= 0 && intro < 1 ? fmt(n * intro) : v}
          </div>
          {/* 曾是 9px + `t.faint`(#454d57,实算 2.2:1),用户实测「没看到」。字号定在 11px;
              颜色那一半已由 2026-08-23 的三级灰阶统一解决(`t.muted` 现为 4.55:1),
              闸在 tests/test_theme_contrast.py */}
          {sub && (
            <div style={{ fontSize: 11, color: subC ?? t.text2, fontFamily: "'JetBrains Mono'",
                          marginTop: 3, whiteSpace: "nowrap" }}>{sub}</div>
          )}
        </div>
      ))}
    </div>
  );
}
