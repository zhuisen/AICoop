/**
 * Shimmering Text（P99「扫描 / 加入：保留转圈，只加文字流光」）。
 * ★ 底层文字始终不透明；流光是叠在字形上的一层（`::after` + `background-clip: text`），只会**加大**对比度：
 *   `lift` = 文字比它的底色亮（深色主题的普通文字）⇒ 叠一道更亮的带；否则（浅色主题、主按钮上的深色字）叠一道更暗的带。
 *   评审 P7-codex-3：第一版用遮罩把字压到 40%，浅色琥珀字扫过时只剩 1.83:1。
 * 减弱动态效果：关键帧换成静止版本（App.css 末尾），带停在字外。
 */
export default function ShimText({ text, lift }: { text: string; lift: boolean }): React.ReactElement {
  return (
    <span className="cb-shim-text" data-t={text}
          style={{ ["--shim" as string]: lift ? "rgba(255,255,255,.6)" : "rgba(0,0,0,.45)" } as React.CSSProperties}>{text}</span>
  );
}
