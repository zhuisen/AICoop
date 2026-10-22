import { createRoot } from "react-dom/client";
import NotchHud from "./NotchHud";
// 减弱动态效果：只放行颜色 / 透明度类过渡（关键帧的同名版本在各自 CSS 文件末尾，见该文件注释）
import "./reducedMotion.css"
createRoot(document.getElementById("root")!).render(<NotchHud />);
