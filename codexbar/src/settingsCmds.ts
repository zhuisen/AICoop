/**
 * 设置页「指令与规则」的静态表（AICoop P9 S1，四签）。★ 零 import —— 测试用 node 直接加载。
 * ★ 每条子命令都对过现行 CLI（`codex-rotate` / `agy-rotate` 的 `CMDS` 表、`cx`、`relay-ctl`），
 *   与稿对不上的以 CLI 为准（PLAN 第 43 条）：codex 的置顶是 `pin --add`（没有 `--toggle`）；
 *   `refresh` 跳过当前在用的号；`probe` 是计费的。闸 `tests/test_settings_p9.py` 逐条核对子命令存在。
 *   稿里的 `cx / cx next`（老启动器）不列：INSTALL.md 不给它建软链，用户敲了是 command not found（闸 `test_path_entrypoints`）。
 * ⚠ 行（codex login / logout）不给复制钮。
 */

export interface CmdRow { cmd: string; desc: string; warn?: boolean }
export interface CmdTab { k: "entry" | "codex" | "agy" | "other"; name: string; note: string; rows: CmdRow[] }

const LOGIN_WARN: CmdRow = { cmd: "⚠ codex login / logout", desc: "别直接跑：会吊销当前号；加号用 codex-rotate login", warn: true };

export const CMD_TABS: readonly CmdTab[] = [
  { k: "entry", name: "入口", note: "日常怎么跑 Codex（装了 alias codex=cxp 后，codex 就是 cxp）", rows: [
    { cmd: "cxp", desc: "经代理多号透明轮换 · 日常入口" },
    { cmd: "cxp exec '…'", desc: "非交互，同样走轮换" },
    { cmd: "cxd", desc: "单号直连，绕过代理 · 看 /usage、重置卡用它" },
    { cmd: "\\codex", desc: "原生 codex，也经 PATH wrapper 走代理" },
    LOGIN_WARN,
  ] },
  { k: "codex", name: "Codex", note: "Codex 账号池", rows: [
    { cmd: "codex-rotate login", desc: "加号 / 重登（唯一入口）" },
    { cmd: "codex-rotate list", desc: "每个号的状态与用量" },
    { cmd: "codex-rotate next", desc: "下一个请求用谁 · 全池续航" },
    { cmd: "codex-rotate switch <号>", desc: "手动切直连号" },
    { cmd: "codex-rotate pin --add <号>", desc: "置顶，优先用（--remove 取消）" },
    { cmd: "codex-rotate rotate <号> --off", desc: "退出自动轮换（--on 放回）" },
    { cmd: "codex-rotate borrow --off", desc: "池子空时不借停用的号" },
    { cmd: "codex-rotate health", desc: "只读验凭证与额度（不刷 token）" },
    { cmd: "codex-rotate refresh <号|all>", desc: "手动刷新 token（跳过当前在用的号）" },
    { cmd: "codex-rotate probe <号>", desc: "真跑一次（计费）" },
    { cmd: "codex-rotate use-credit <号>", desc: "用重置卡（不可逆）" },
    LOGIN_WARN,
  ] },
  { k: "agy", name: "Gemini · agy", note: "Gemini（Antigravity · agy）账号池", rows: [
    { cmd: "agy-rotate login [号]", desc: "加号：保住当前号，登新号后自动收编" },
    { cmd: "agy-rotate list", desc: "池总览 + 每号额度" },
    { cmd: "agy-rotate live", desc: "现读钥匙串：此刻到底登录的是谁" },
    { cmd: "agy-rotate switch <号>", desc: "换号 · 只对下一次启动的 agy 生效" },
    { cmd: "agy-rotate quota", desc: "逐号刷云端额度（零消耗）" },
    { cmd: "agy-rotate health", desc: "逐号验凭证（零消耗）" },
    { cmd: "agy-rotate probe <号>", desc: "真跑一句（计费，约 15k token）" },
    { cmd: "agy-rotate rotate <号> --off", desc: "退出自动轮换（--on 放回）" },
    { cmd: "agy-rotate auto-switch --off", desc: "关掉全局自动切号" },
  ] },
  { k: "other", name: "其他", note: "其他", rows: [
    { cmd: "relay-ctl", desc: "中转站唯一 CLI · key 走 stdin，不进命令行" },
    { cmd: "grok-quota", desc: "只读抓 Grok 周额度，不刷 token" },
  ] },
];

/** 复制的内容 = 指令去掉「 / …」后面的变体（稿 P9.1「复制内容」）。⚠ 行不复制 ⇒ null。 */
export function copyOf(r: CmdRow): string | null {
  if (r.warn) return null;
  return r.cmd.split(" / ")[0].trim();
}
