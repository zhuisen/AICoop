"""双击托盘图标 = 打开工作台总览（用户 2026-10-23「新增双击 AICoop 菜单栏图标就是打开工作台总览界面」）。

macOS 上 `tray-icon` 不发 `DoubleClick`（只有 Windows 实现），所以 `lib.rs` 按系统双击间隔自己判。
判定本身是纯函数，由 `cargo test --lib`（`tray_double_click_tests`）守；这里守接线。
"""
import re
import unittest
from pathlib import Path

LIB = (Path(__file__).resolve().parents[1] / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")


def _fn(name):
    i = LIB.index("fn %s(" % name)
    return LIB[i:LIB.index("\n}\n", i)]


class DoubleClickOpensTheOverview(unittest.TestCase):
    def test_left_click_goes_through_the_double_click_judge(self):
        i = LIB.index(".on_tray_icon_event(")
        ev = LIB[i:LIB.index(".build(app)?;", i)]
        self.assertIn("if button == MouseButton::Left {\n                                on_tray_left_click(tray.app_handle(), rect);", ev)
        self.assertIn("tps_hover::on_click(tray.app_handle());", ev, "单击 / 双击都先收起悬停面板")

    def test_the_second_click_hides_the_popover_and_opens_the_overview(self):
        f = _fn("on_tray_left_click")
        self.assertIn("doubleClickInterval", f, "间隔跟系统设置走，不写死")
        self.assertIn('app.emit("open-main-page", serde_json::json!({ "page": "overview" }))', f,
                      "走与菜单栏 / 刘海同一条跳转（Rust 转成只发主窗口的 main-open-page）")
        self.assertLess(f.index('get_webview_window("menubar")'), f.index('app.emit("open-main-page"'),
                        "第一下开出来的弹窗要先收起")
        self.assertRegex(f, r"if !double \{\n\s+toggle_menubar\(app, Some\(rect\)\);\n\s+return;",
                         "单击照常立刻开弹窗，不为等第二下而延迟")

    def test_a_double_click_is_judged_once(self):
        self.assertIn("*last = if d { 0.0 } else { now };", _fn("on_tray_left_click"), "判过就清零：三连击不算两次")


if __name__ == "__main__":
    unittest.main()
