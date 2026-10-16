/**
 * 扫描源的健康状态 → 给人看的一句话（B85 · 四方评审 P1）。
 *
 * ★★ 本仓「读不到 ≠ 没有」在用量页的最后一跳：`scan.py` 早就知道「根目录不存在 / 有文件没解析 /
 *   读失败」，但 TS 契约把这些字段全丢了，于是页面上它们与「这家没用过」长得一模一样。
 *
 * ★ **零 import**：测试用 `node --experimental-strip-types` 直接跑这个文件（CI 不装 node_modules）。
 * ★ 两级：`warn` = 少算了（有文件却没计入）；`info` = 没找到 / 是空的 —— 没装那个 CLI 是常态，
 *   绝不能染成告警（一盏永远亮着又消不掉的灯，本仓判过死刑）。
 */
export type SourceState = "ok" | "empty" | "not_found" | "partial" | "read_failed" | "disabled";

export interface SourceStatus {
  state: SourceState;
  root: string;
  name: string;
  files?: number;
  read_failed?: number;
  /** 读失败里「这台机器没有解压器」的那部分（不是文件坏了）。 */
  no_decoder?: number;
  /** 压缩过却没被解析的文件数，按后缀。 */
  unparsed?: Record<string, number>;
}

export interface SourceNote {
  key: string;
  level: "warn" | "info";
  text: string;
}

export function sourceNotes(sources: Record<string, SourceStatus> | undefined): SourceNote[] {
  const out: SourceNote[] = [];
  for (const [key, s] of Object.entries(sources ?? {})) {
    const nd = s.no_decoder ?? 0;
    const rf = (s.read_failed ?? 0) - nd;
    if (nd > 0)
      out.push({ key, level: "warn", text: `${s.name}：未计入 ${nd} 个压缩会话（没有 zstd 解压器，装一个：brew install zstd）` });
    if (rf > 0)
      out.push({ key, level: "warn", text: `${s.name}：${rf} 个文件读失败，下次刷新会重试` });
    for (const [suf, n] of Object.entries(s.unparsed ?? {}))
      if (n > 0) out.push({ key, level: "warn", text: `${s.name}：未计入 ${n} 个 ${suf} 文件（还不支持这种压缩格式）` });
    if (s.state === "not_found")
      out.push({ key, level: "info", text: `${s.name}：未找到 ${s.root}` });
    else if (s.state === "empty")
      out.push({ key, level: "info", text: `${s.name}：${s.root} 下没有会话文件` });
  }
  // 告警排前面：它们是「少算了」，info 只是「没装 / 没用」。
  return out.sort((a, b) => (a.level === b.level ? 0 : a.level === "warn" ? -1 : 1));
}

/** 某一家的告警（只取 `warn`）—— 用量卡副标题那一档 demo 用。没有问题返回空数组。 */
export function warnNotesFor(sources: Record<string, SourceStatus> | undefined, key: string): SourceNote[] {
  return sourceNotes(sources).filter((n) => n.key === key && n.level === "warn");
}
