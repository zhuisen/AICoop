/**
 * D3（用户 2026-10-22 从 demo v2 选）：内容区顶上一条带里，**点在空白处**就拖窗口，双击 = 缩放。
 * 不再用一条盖在内容上的 12 px 透明条 —— 盖得越高，压住的标题行控件越多。这里反过来：
 * 从点中的元素往上找，碰到任何可点的东西（按钮 / 输入框 / 有交互 role / 指针不是默认箭头）就不拖。
 * 判据与 Tauri 自带 `drag.js` 的 `isClickableElement` 同一套，多加「光标不是默认」——
 * 本仓很多可点的是带 onClick 的 div / span，它们都设了 `cursor: pointer`。
 */
export const HEADER_BAND = 60;

const CLICKABLE = new Set(["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA", "LABEL", "SUMMARY"]);
const ROLES = new Set(["button", "link", "menuitem", "tab", "checkbox", "radio", "switch", "option", "slider"]);

export function isBlankHeader(target: EventTarget | null, root: HTMLElement, clientY: number): boolean {
  if (clientY - root.getBoundingClientRect().top > HEADER_BAND) return false;
  for (let el = target instanceof Element ? target : null; el; el = el.parentElement) {
    if (el instanceof HTMLElement) {
      if (CLICKABLE.has(el.tagName) || el.isContentEditable || ROLES.has(el.getAttribute("role") ?? "")) return false;
      if (el.hasAttribute("tabindex") && el.tabIndex >= 0) return false;
      if (el.hasAttribute("data-no-drag")) return false;
      const cur = getComputedStyle(el).cursor;
      if (cur !== "auto" && cur !== "default") return false;
    }
    if (el === root) return true;
  }
  return false;
}
