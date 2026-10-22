/**
 * 「检查更新」的版本比较（零 import，测试用 node 直接跑）。
 * ★ 按数值比，不按字符串（0.10.0 > 0.9.0）。
 * ★ 带预发布段（`-beta.1`）的版本**小于**同号正式版（SemVer §11）：原来 `parseInt("0-beta")` 得 0、
 *   预发布段被丢掉，beta 用户在正式版发布后被判成「已是最新」（全方面评审 §6）。
 * ★ `+B`（本地构建号）不参与比较。
 */
function parts(v: string): { core: number[]; pre: string[] } {
  const s = v.trim().replace(/^v/, "").split("+")[0];
  const i = s.indexOf("-");
  const core = (i < 0 ? s : s.slice(0, i)).split(".").map((x) => parseInt(x, 10) || 0);
  while (core.length < 3) core.push(0);
  return { core, pre: i < 0 ? [] : s.slice(i + 1).split(".") };
}

/** a 比 b 新 ⇒ >0；同 ⇒ 0；旧 ⇒ <0。 */
export function cmpVersion(a: string, b: string): number {
  const x = parts(a), y = parts(b);
  for (let k = 0; k < 3; k++) if (x.core[k] !== y.core[k]) return x.core[k] - y.core[k];
  if (!x.pre.length || !y.pre.length) return (x.pre.length ? -1 : 0) + (y.pre.length ? 1 : 0);
  for (let k = 0; k < Math.max(x.pre.length, y.pre.length); k++) {
    const p = x.pre[k], q = y.pre[k];
    if (p === undefined) return -1;
    if (q === undefined) return 1;
    const pn = /^\d+$/.test(p), qn = /^\d+$/.test(q);
    if (pn && qn) { if (+p !== +q) return +p - +q; continue; }
    if (pn !== qn) return pn ? -1 : 1;
    if (p !== q) return p < q ? -1 : 1;
  }
  return 0;
}

export function isNewer(remote: string, current: string): boolean {
  return cmpVersion(remote, current) > 0;
}
