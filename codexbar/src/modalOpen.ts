/** 主窗口里有没有开着的弹层（确认删除 / ⌘K / 侧滑详情 / 用重置卡 / 定时探针浮层）。开着时全局快捷键不许穿透
 *  （2026-10-22 评审：确认框开着按 ⌘2 会切号、按 ⌘K 会在确认框上面再开一层命令面板）。 */
const SEL: Record<string, string> = {
  confirm: "[data-ov-confirm]",
  cmdk: "[data-ov-cmdk]",
  sheet: "[data-ov-sheet][data-open]",
  credit: "[data-use-credit-dialog][data-open]",
  dawn: "[data-dawn-pop]",
};

export function modalOpen(except?: keyof typeof SEL): boolean {
  return Object.entries(SEL).some(([k, sel]) => k !== except && !!document.querySelector(sel));
}
