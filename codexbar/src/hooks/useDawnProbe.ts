import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { dawnCatchUpDue, type DawnKind, type DawnStatus } from "../dawn";

/**
 * 每日清晨探针的**补跑**路径（用户 2026-09-06 要的「早上 6 点给 Plus 号探针，
 * 让 5h 额度走动」）。
 *
 * ## 为什么定时器之外还要这一条
 *
 * 主触发是 launchd 的 `com.doushutangmu.codex-rotate.dawnprobe`（06:00
 * `StartCalendarInterval`）。但**本项目的日历定时有前科**：keepalive / refreshquota 的
 * `StartCalendarInterval` 曾被 `install-launchd.sh` 以外的东西改写掉，`runs = 0`、
 * **从未运行过**，而没有任何一处会为此报红（改写者至今未查明，CLAUDE.md §3）。
 * 所以那个 plist **不能是唯一触发路径** —— 这里补一条不依赖 plist 的。
 *
 * ## 三条护栏（全在 CLI 侧，这里只是尽量少调它）
 *
 * ① **默认关闭**：`state.json` 的 `dawn_probe.enabled` 缺省为假。仓库已公开，
 *    一个默认开启的自动计费定时器会在别人机器上悄悄花钱。
 * ② ★★ **先占天再探**：`cmd_dawn_probe` 在**发请求之前**就把当天日期写进 state
 *    （持跨进程互斥锁）。没有它，launchd 与本补跑几乎同时触发就是**双重计费**。
 *    已用 3 进程并发实测：恰好 1 个进到探测阶段。
 * ③ **每次运行落痕**，成功失败都写，UI 读它 —— 「从未运行过」必须看得见。
 *
 * ## 只在菜单栏 webview 跑
 *
 * 两个 webview 都常驻，都跑就是每天多起一个 python（虽然被②挡住不会重复计费，
 * 但那是靠护栏兜底，不是设计）。菜单栏 webview 在 app 启动时创建且**从不卸载**，
 * 是更稳的那个宿主。
 *
 * ★ 判据是「今天的到点时刻（`due_at`）已过、而记录的日期不是今天」，**不是**「现在正好到点」——
 *   Mac 凌晨多半在睡觉，卡点判定等于永远不触发。睡醒后补跑才是真实场景。
 * ★★ 2026-10-15：时间可选 + 3 分钟内随机（`dawn_sched.py`），而且 **Gemini（agy）也有了同一套**。
 *   `due_at` 由 CLI 的 `--status` 给出（按天固定的随机偏移，launchd 与这里算出的是同一秒），
 *   这里不再写死 06:00。调 CLI 时带 `--no-wait`：没到点就退出，不在 IPC 里睡。
 */

/** 多久检查一次。只是读一次状态（一个 ~60ms 的 python），不联网。 */
const TICK_MS = 10 * 60 * 1000;

function todayLocal(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** 两家各一条：读状态走只读通道，真跑走各自的命令通道。 */
const KINDS: { kind: DawnKind; read: () => Promise<string>; run: () => Promise<unknown> }[] = [
  { kind: "codex",
    read: () => invoke<string>("read_dawn_status"),
    run: () => invoke("run_rotate", { args: ["dawn-probe", "--no-wait"] }) },
  { kind: "agy",
    read: () => invoke<string>("run_agy_rotate", { args: ["dawn-probe", "--status"] }),
    run: () => invoke("run_agy_rotate", { args: ["dawn-probe", "--no-wait"] }) },
];

export function useDawnProbe(): void {
  const running = useRef(false);

  useEffect(() => {
    let label = "";
    try { label = getCurrentWindow().label; } catch { return; }
    if (label !== "menubar") return;      // 见上：只在常驻的那个 webview 跑

    const check = async () => {
      if (running.current) return;
      running.current = true;
      try {
        for (const k of KINDS) {
          try {
            const rec = JSON.parse((await k.read()).trim().split("\n").pop() || "{}") as DawnStatus;
            // ★ 关掉了就什么都不做 —— 用户对一个**会花钱**的功能的显式选择，补跑没有资格绕过它。
            if (!dawnCatchUpDue(rec, todayLocal(), Date.now() / 1000)) continue;
            await k.run();
          } catch {
            // 读不到 / 跑失败：下个 tick 再说。★ 不弹 toast —— 后台补救失败不是用户此刻要处理的事；
            //   该看的是工具栏「定时」浮层里那条「上次运行」。
          }
        }
      } finally {
        running.current = false;
      }
    };

    void check();
    const id = setInterval(() => { void check(); }, TICK_MS);
    return () => clearInterval(id);
  }, []);
}
