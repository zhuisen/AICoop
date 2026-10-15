import { invoke } from "@tauri-apps/api/core";
import type { Theme } from "../theme";
import type { AgyAction } from "../agy";

const MONO = "'JetBrains Mono'";

/**
 * agy 取额度被 Google 拒绝时的**下一步动作**（「需验证 →」）。总览卡与菜单栏行共用。
 *
 * ★ 有链接才可点；没有链接只说原因（不造一个点了没反应的按钮）。
 * ★ 外链走本仓的 `open_url`（只放 http(s)，见 `lib.rs`）；后端已把链接收窄到 `*.google.com`。
 * ★ `stopPropagation`：卡片/行本身可点（进总览/详情），点这里不能顺带触发它。
 */
export default function AgyActionLink({ t, action, fontSize }: {
  t: Theme; action: AgyAction; fontSize: number;
}) {
  const color = "#E0901C";
  const url = action.url;
  return (
    <span data-agy-action={action.label} title={action.note}
          onClick={url ? (e) => { e.stopPropagation(); void invoke("open_url", { url }); } : undefined}
          style={{ fontSize, fontWeight: 700, fontFamily: MONO, whiteSpace: "nowrap",
                   color: url ? color : t.muted, cursor: url ? "pointer" : "default",
                   textDecoration: url ? "underline" : "none", textUnderlineOffset: 2 }}>
      {action.label}{url ? " →" : ""}
    </span>
  );
}
