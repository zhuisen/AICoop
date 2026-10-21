/**
 * Token 消耗页（AICoop R2）的纯逻辑：密度档、数字写法、布局公式、形变插值。
 *
 * ★ **零 import**：`tests/test_token_page.py` 用 `node --experimental-strip-types` 直接跑这个真文件
 *   （CI 没有 node_modules，见 CLAUDE.md §4「pure TS under node」）。
 * 数值全部照稿 `boards/06_token/R2_*.dc.html` 的 `renderVals()`；改过的地方逐条写了理由
 * （稿件缺陷 F1 / F2 / F4，见 `scratch/aicoop_20261021/R2_extract.md` §2.10）。
 */

/** 密度档：0 = 1200，1 = 1000，2 = 860。判据是**主内容宽**（窗口宽 − 侧栏 64），不是窗口宽。 */
export type Density = 0 | 1 | 2;
export function densityOf(winW: number): Density {
  return winW <= 860 ? 2 : winW <= 1000 ? 1 : 0;
}

/** 标题字号 26 / 24 / 22：`round(22 + clamp((W−860)/340, 0, 1)·4)`。 */
export function titleSize(winW: number): number {
  return Math.round(22 + Math.max(0, Math.min(1, (winW - 860) / 340)) * 4);
}

export function fmtTokL(n: number, L: Density): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(L === 0 ? 2 : 1)}B`;
  if (n >= 1e6) return `${n >= 1e7 ? Math.round(n / 1e6) : (n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}k`;
  return String(Math.round(n));
}

/**
 * ★ 稿件缺陷 F2：稿里 860 档一律 `toFixed(1)`，把 `$0.11` 写成 `$0.1`、`$0.045` 写成 `$0.0`。
 *   亚美元值抹一位小数就是改数，所以 < $10 时三档都保留两位。
 */
export function fmtUsdL(n: number, L: Density): string {
  if (n >= 1e3) return `$${(n / 1e3).toFixed(L === 0 ? 2 : 1)}K`;
  if (L >= 1 && n >= 100) return `$${Math.round(n)}`;
  if (L === 2 && n >= 10) return `$${n.toFixed(1)}`;
  return `$${n.toFixed(2)}`;
}

export function fmtIntL(n: number, L: Density): string {
  if (L === 2 && n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return Math.round(n).toLocaleString("en-US");
}

/**
 * 涨跌。★ 稿件缺陷 F1：稿里 `sgn(0)` 输出 `↓0.0%`，把持平写成下跌。
 * 这里一位小数取整后为 0 ⇒ 不带箭头。没有上期 ⇒ `—`。
 */
export function sgn(c: number | null): string {
  if (c == null || !Number.isFinite(c)) return "—";
  const a = Math.abs(c).toFixed(1);
  if (a === "0.0") return "0.0%";
  return `${c > 0 ? "↑" : "↓"}${a}%`;
}
export type Trend = "up" | "down" | "flat" | "none";
export function trendOf(c: number | null): Trend {
  if (c == null || !Number.isFinite(c)) return "none";
  return Math.abs(c).toFixed(1) === "0.0" ? "flat" : c > 0 ? "up" : "down";
}
/** 环比百分比；上期为 0 或拿不到 ⇒ null（显示 `—`，不当 0）。 */
export function changePct(now: number, base: number | null | undefined): number | null {
  if (base == null || !(base > 0)) return null;
  return ((now - base) / base) * 100;
}

/** 时间范围分段按钮宽：码点 > 0x2E80 记 13，否则 7.8；两侧各 13（860 为 9）。 */
export function segWidth(label: string, L: Density): number {
  let w = 0;
  for (const ch of label) w += (ch.codePointAt(0) ?? 0) > 0x2e80 ? 13 : 7.8;
  return Math.round(w) + 2 * (L === 2 ? 9 : 13);
}

/** 两列平台行：先排满左列再排右列；区块高 168，行高 = 168 ÷ 每列行数（最小 32）。 */
export function twoCol(n: number): { perCol: number; rowH: number; h: number } {
  const perCol = Math.max(1, Math.ceil(n / 2));
  const rowH = Math.max(32, Math.floor(168 / perCol));
  return { perCol, rowH, h: Math.max(168, rowH * perCol) };
}

/**
 * 横轴标哪几个点：间距 ≥ 64 px，不够就隔点标。
 * ★ **从末尾锚定**（全局 `ui-design.md`；稿从索引 0 起，偏离 S11）：最后一个点（今天）恒有标签。
 */
export function axisIdx(n: number, plotW: number, minStep = 1): number[] {
  if (n <= 0) return [];
  if (n === 1) return [0];
  const every = Math.max(minStep, Math.ceil(64 / (plotW / (n - 1))));
  const out: number[] = [];
  for (let i = n - 1; i >= 0; i -= every) out.unshift(i);
  return out;
}

/** 560 ms 临界阻尼（稿 `w = 7.5`，无回弹）。 */
export function critEase(t: number): number {
  const w = 7.5;
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  return Math.min(1, (1 - (1 + w * t) * Math.exp(-w * t)) / (1 - (1 + w) * Math.exp(-w)));
}

/** 把旧数组线性重采样到新长度（形变时新旧档位桶数不同）。 */
export function resample(a: readonly number[], n: number): number[] {
  if (n <= 0) return [];
  if (!a.length) return new Array(n).fill(0);
  if (a.length === n) return [...a];
  if (a.length === 1) return new Array(n).fill(a[0]);
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    const x = n === 1 ? 0 : (i / (n - 1)) * (a.length - 1);
    const lo = Math.floor(x), hi = Math.min(a.length - 1, lo + 1);
    out.push(a[lo] + (a[hi] - a[lo]) * (x - lo));
  }
  return out;
}

export function lerpArr(from: readonly number[], to: readonly number[], e: number): number[] {
  const f = resample(from, to.length);
  return to.map((v, i) => f[i] + (v - f[i]) * e);
}

/**
 * 缓存命中 = 缓存读 ÷（缓存读 + 输入），按 token 加权。
 * ★ 「输入」含**缓存写**（偏离 R2-8）：缓存写是首次发送、顺带写进缓存的输入，不算进分母会让
 *   Claude 这种有缓存写的平台命中率虚高。没有输入 ⇒ null（显示 `—`）。
 */
export function hitRate(cacheRead: number, uncachedIn: number, cacheWrite: number): number | null {
  const d = cacheRead + uncachedIn + cacheWrite;
  return d > 0 ? (cacheRead / d) * 100 : null;
}

/** 峰值与它的下标（全 0 ⇒ null）。 */
export function peakOf(values: readonly number[]): { i: number; v: number } | null {
  let best = -1, bi = -1;
  values.forEach((v, i) => { if (v > best) { best = v; bi = i; } });
  return best > 0 ? { i: bi, v: best } : null;
}

/** 4 个纵轴刻度：0、⅓、⅔、1 × max（max 已含 1.08 余量）。 */
export function yTicks(maxV: number): number[] {
  return [0, 1 / 3, 2 / 3, 1].map((f) => maxV * f);
}

/**
 * 桶标签 → 峰值日期。小时桶 `YYYY-MM-DDTHH`、日桶 `YYYY-MM-DD`、周桶同日桶、月桶 `YYYY-MM`。
 * ★ 稿件缺陷 F4：稿里 `replace(/^2026-/)` 写死年份。这里只去掉**当年**，跨年保留。
 */
export function shortDate(l: string, thisYear: string): string {
  const d = l.length > 10 ? l.slice(0, 10) : l;
  return d.startsWith(`${thisYear}-`) ? d.slice(5) : d;
}

/** Gemini 显示名（稿 §7：显示名统一 Gemini，agy 作来源小字）。用户改过名 ⇒ 用户的名字优先。 */
export function displayName(key: string, scanName: string): { name: string; src: string | null } {
  if (key === "agy") return { name: scanName === "Antigravity" ? "Gemini" : scanName, src: "agy" };
  return { name: scanName, src: null };
}

/** 模型名：Claude 去掉 `claude-` 前缀（稿 §6）。 */
export function modelLabel(m: string): string {
  return m.replace(/^claude-/, "");
}

/** 模型缓存命中低于平台均值 1.5 pt 标橙。 */
export function lowHit(model: number | null, avg: number | null): boolean {
  return model != null && avg != null && model < avg - 1.5;
}

/**
 * 单调三次插值（Fritsch–Carlson）。★ 稿用中点贝塞尔；token 量不能为负，单调插值保证区间内不越过
 * 两端点（全局 `ui-design.md`；与 `StackedArea` 同一个实现）。
 */
export function monotonePath(pts: [number, number][]): string {
  const n = pts.length;
  if (n === 0) return "";
  if (n === 1) return `M ${pts[0][0]} ${pts[0][1]}`;
  if (n === 2) return `M ${pts[0][0]} ${pts[0][1]} L ${pts[1][0]} ${pts[1][1]}`;
  const dx: number[] = [], d: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(pts[i + 1][0] - pts[i][0]);
    d.push((pts[i + 1][1] - pts[i][1]) / (dx[i] || 1));
  }
  const m: number[] = [d[0]];
  for (let i = 1; i < n - 1; i++) m.push(d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2);
  m.push(d[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
    const a = m[i] / d[i], b = m[i + 1] / d[i], s = a * a + b * b;
    if (s > 9) { const tau = 3 / Math.sqrt(s); m[i] = tau * a * d[i]; m[i + 1] = tau * b * d[i]; }
  }
  let path = `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    path += ` C ${(pts[i][0] + h).toFixed(2)} ${(pts[i][1] + m[i] * h).toFixed(2)}`
          + ` ${(pts[i + 1][0] - h).toFixed(2)} ${(pts[i + 1][1] - m[i + 1] * h).toFixed(2)}`
          + ` ${pts[i + 1][0].toFixed(2)} ${pts[i + 1][1].toFixed(2)}`;
  }
  return path;
}

/** 真带：上边 = 本层累计线，下边 = 前一层累计线倒序回来闭合。单点 ⇒ 宽 `colW` 的柱。 */
export function bandPath(top: [number, number][], base: [number, number][], colW: number): string {
  if (!top.length || !base.length) return "";
  if (top.length === 1 && base.length === 1) {
    const x0 = (top[0][0] - colW / 2).toFixed(1), x1 = (top[0][0] + colW / 2).toFixed(1);
    return `M${x0} ${base[0][1].toFixed(1)} L${x0} ${top[0][1].toFixed(1)} L${x1} ${top[0][1].toFixed(1)} L${x1} ${base[0][1].toFixed(1)} Z`;
  }
  return `${monotonePath(top)} L ${monotonePath([...base].reverse()).slice(2)} Z`;
}

/** 堆叠：`layers[j][i]` → 每层上沿累计值（自下而上）。 */
export function stackTops(layers: readonly (readonly number[])[]): number[][] {
  const out: number[][] = [];
  layers.forEach((vs, j) => out.push(vs.map((v, i) => v + (j ? out[j - 1][i] : 0))));
  return out;
}

/**
 * 读写比的回本线：写一份缓存多付 `(写价 − 输入价)`，每被读一次省 `(输入价 − 读价)`。
 * ★ 稿件缺陷 S5：稿里写死「回本 1.4×」，按牌价算 Claude 5m 档只要 ≈ 0.28 次。这里按该平台最大模型的牌价现算。
 * 写价不高于输入价（自动缓存平台）或读不省钱 ⇒ null（不画回本线）。
 */
export function breakevenReads(inP: number, readP: number, writeP: number | undefined): number | null {
  const prem = (writeP ?? inP) - inP, save = inP - readP;
  return prem > 0 && save > 0 ? prem / save : null;
}

/**
 * 写价按 5m / 1h 两档加权（阶段 4 评审：只用 5m 价时 Claude 1h 档的回本线被算成 0.28×，实际 1.11×）。
 * `h1Share` = 1h 档占全部缓存写的比例；1h 档 = 2 × 输入价（Anthropic 规则，同 `rates.ts::costOf`）。
 */
export function blendWritePrice(inP: number, write5m: number | undefined, h1Share: number): number {
  const h = Math.min(1, Math.max(0, Number.isFinite(h1Share) ? h1Share : 0));
  return (1 - h) * (write5m ?? inP) + h * inP * 2;
}

/**
 * 点图层下钻：按**真实横坐标**插值出各层上沿再找纵值落在哪一层（阶段 4 评审：原来取最近的采样点，
 * 曲线中段会点错层）。零厚度的层不可点（选中单平台时其余层全 0，点底边会跳进别的平台）。
 * `fx` = 浮点下标（0…n−1），`v` = 点击处的纵值。点在 0 以下或全部之上 ⇒ -1。
 */
export function layerAt(tops: readonly (readonly number[])[], fx: number, v: number): number {
  if (!(v > 0) || !tops.length) return -1;
  const n = tops[0].length;
  if (!n) return -1;
  const x = Math.max(0, Math.min(n - 1, fx));
  const i0 = Math.floor(x), i1 = Math.min(n - 1, i0 + 1), f = x - i0;
  const at = (j: number) => (j < 0 ? 0 : (tops[j][i0] ?? 0) * (1 - f) + (tops[j][i1] ?? 0) * f);
  for (let j = 0; j < tops.length; j++) {
    const lo = at(j - 1), hi = at(j);
    if (hi > lo && v <= hi) return j;
  }
  return -1;
}

/** 迷你趋势按连续非空段切开（`null` = 这个桶没有分母）。每段 = `[下标, 值][]`。 */
export function nonNullRuns(vals: readonly (number | null)[]): [number, number][][] {
  const out: [number, number][][] = [];
  let cur: [number, number][] = [];
  vals.forEach((v, i) => {
    if (v == null || !Number.isFinite(v)) { if (cur.length) out.push(cur); cur = []; }
    else cur.push([i, v]);
  });
  if (cur.length) out.push(cur);
  return out;
}

/** 百分点差。四舍五入成 0.0 时不带方向、不染色（同 `sgn` 的 F1 修正）。 */
export function fmtPt(d: number | null): { text: string; trend: Trend } {
  if (d == null || !Number.isFinite(d)) return { text: "", trend: "none" };
  const a = Math.abs(d).toFixed(1);
  if (a === "0.0") return { text: "0.0 pt", trend: "flat" };
  return { text: `${d > 0 ? "+" : "-"}${a} pt`, trend: d > 0 ? "up" : "down" };
}
