// 悬停面板（托盘胶囊悬停 200 ms 后弹出）的入口。窗口与进出判定在 Rust `tps_hover.rs`。
import { createRoot } from "react-dom/client";
import TpsHover from "./TpsHover";
// 减弱动态效果：只放行颜色 / 透明度类过渡（关键帧的同名版本在各自 CSS 文件末尾，见该文件注释）
import "./reducedMotion.css"
createRoot(document.getElementById("root")!).render(<TpsHover />);
