import { maskId } from "../helpers";

export interface AccountDetail {
  account_id?: string; email?: string; label?: string; plan?: string; sub_until?: string;
  /** OpenAI 上次向计费系统复核订阅的时刻;到期日只是那次复核的快照 */
  sub_checked?: string;
  last_refresh?: string; auth_dead?: boolean; file?: string;
  access_token_tail?: string; access_token_len?: number; access_exp?: number; access_iat?: number;
  refresh_token_tail?: string; refresh_token_len?: number; id_token_len?: number;
  quota_source?: string; quota_captured_at?: number;
}

/**
 * 账号的技术信息（token 指纹、签发 / 过期、订阅复核、快照来源）—— 原「账号详情」弹窗里的每一行，
 * 现在放在总览详情 Sheet 的下半（交接包 P5 §5.2；CLAUDE.md §6 不随手删功能）。
 * ★ 打码：account_id / email / token 尾巴和邮箱一样能认人，截图时一并遮。
 */
export function TechRows({ detail, privacy }: { detail: AccountDetail; privacy: boolean }) {
  const fmtTs = (ts?: number) => ts ? new Date(ts * 1000).toLocaleString("zh-CN", { timeZone: "Asia/Singapore" }) : "—";
  const rows: [string, string, string?][] = [
    ["account_id", maskId(detail.account_id, privacy, 8) || (detail.account_id ?? "—")],
    // 文件名就是 `<account_id>.json` ⇒ 打码时同样遮（评审 Opus L5）
    ["文件", `auth/${privacy ? maskId(detail.file, true, 8) : detail.file}`],
    ["access_token", `…${privacy ? "••••••••" : detail.access_token_tail}  (${detail.access_token_len} chars)`],
    ["access 签发", fmtTs(detail.access_iat)],
    ["access 过期", fmtTs(detail.access_exp), detail.access_exp && detail.access_exp < Date.now() / 1000 ? "#E0524D" : undefined],
    ["refresh_token", `…${privacy ? "••••••••" : detail.refresh_token_tail}  (${detail.refresh_token_len} chars)`],
    ["last_refresh", detail.last_refresh?.slice(0, 19) ?? "—"],
    ["plan", detail.plan || "—"],
    ["订阅至", detail.sub_until?.slice(0, 10) ?? "—",
      // 复核早于到期日 ⇒ 这个「已过期」是拿陈旧快照下的结论,标琥珀而不是当事实
      detail.sub_until && detail.sub_checked && Date.parse(detail.sub_checked) < Date.parse(detail.sub_until)
        && Date.parse(detail.sub_until) < Date.now() ? "var(--ovWarnTx)" : undefined],
    ["订阅复核于", detail.sub_checked?.slice(0, 19) ?? "—"],
    ["quota 来源", String(detail.quota_source ?? "—")],
    ["快照时间", fmtTs(detail.quota_captured_at)],
  ];
  return (
    <div data-account-tech="" style={{ display: "flex", flexDirection: "column", userSelect: "text" }}>
      <div style={{ fontSize: 11, color: "var(--tx3)", margin: "6px 0 2px" }}>技术信息 · 完整 token 不显示（仅指纹）</div>
      {rows.map(([k, v, color]) => (
        <div key={k} style={{ display: "flex", gap: 10, padding: "4px 0", borderBottom: "1px solid rgba(127,127,127,.1)",
                              fontFamily: "'JetBrains Mono', monospace", fontSize: 10.5 }}>
          <span style={{ color: "var(--tx3)", width: 86, flexShrink: 0 }}>{k}</span>
          <span style={{ color: color ?? "var(--tx)", whiteSpace: "normal", wordBreak: "break-all", cursor: "text" }}>{v}</span>
        </div>
      ))}
    </div>
  );
}
