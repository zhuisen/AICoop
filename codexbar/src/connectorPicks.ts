/** 接入面板的勾选（零 import，见 `coalesce.ts` 的说明）。 */
export interface PickStep { id: string; state: string; optional: boolean }

/**
 * 默认勾选规则：只勾没装的；`optional` 的那一步（改 `codex` 行为）**永远不默认勾**。
 *
 * ★★ `blocked` 时**一个都不勾**。像素验证抓到（2026-09-19）：这份安装缺运行时文件、
 *   红条已经说了「装不了」，可复选框仍是勾选态、按钮还写着「接入（N 项）」——
 *   一个说不能装、一个邀请你去装，用户只会相信后者。
 */
export function defaultPicks(steps: readonly PickStep[], blocked: boolean): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const s of steps) out[s.id] = !blocked && s.state === "todo" && !s.optional;
  return out;
}

/**
 * 重读计划后的勾选。★ 状态没变的步骤**保留用户的勾选**；状态变了（如刚装好）的步骤回到默认。
 * 原来每条 `state-changed` 都整份重置成默认，用户刚勾的东西一秒后就没了（全方面评审 §6）。
 */
export function mergePicks(prev: Record<string, boolean>, prevSteps: readonly PickStep[] | null,
                           steps: readonly PickStep[], blocked: boolean): Record<string, boolean> {
  const def = defaultPicks(steps, blocked);
  if (!prevSteps || blocked) return def;
  const was = new Map(prevSteps.map((s) => [s.id, s.state]));
  const out: Record<string, boolean> = {};
  for (const s of steps) out[s.id] = was.get(s.id) === s.state && s.id in prev ? prev[s.id] : def[s.id];
  return out;
}
