// 悬停面板（托盘胶囊悬停 200 ms 后弹出）的入口。窗口与进出判定在 Rust `tps_hover.rs`。
import { createRoot } from "react-dom/client";
import TpsHover from "./TpsHover";
createRoot(document.getElementById("root")!).render(<TpsHover />);
