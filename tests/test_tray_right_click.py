"""右键托盘图标 = 打开工作台总览（用户 2026-10-24「双击打开工作台，更改为鼠标右键」，取代 10-23 的双击）。

左键照旧只开 / 收菜单栏弹窗。真实点击 harness 做不到（托盘不在 webview 里），这里守 `lib.rs` 的接线。
"""
import unittest
from pathlib import Path

LIB = (Path(__file__).resolve().parents[1] / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")


def _fn(name):
    i = LIB.index("fn %s(" % name)
    return LIB[i:LIB.index("\n}\n", i)]


class RightClickOpensTheOverview(unittest.TestCase):
    def ev(self):
        i = LIB.index(".on_tray_icon_event(")
        return LIB[i:LIB.index(".build(app)?;", i)]

    def test_right_opens_the_overview_left_toggles_the_popover(self):
        ev = self.ev()
        self.assertIn("if button == MouseButton::Right {\n                                on_tray_right_click(tray.app_handle());\n"
                      "                            } else {\n                                toggle_menubar(tray.app_handle(), Some(rect));", ev)
        self.assertIn("matches!(button, MouseButton::Left | MouseButton::Right)", ev, "两个键都要接")
        self.assertIn("tps_hover::on_click(tray.app_handle());", ev, "点哪个键都先收起悬停面板")

    def test_the_right_click_hides_the_popover_then_opens_the_overview(self):
        f = _fn("on_tray_right_click")
        self.assertIn('app.emit("open-main-page", serde_json::json!({ "page": "overview", "platform": "codex" }))', f,
                      "★ 走与菜单栏 / 刘海同一条跳转，且固定落在 Codex 档（用户 2026-10-24），不停在上次那一档")
        self.assertLess(f.index('get_webview_window("menubar")'), f.index('app.emit("open-main-page"'), "弹窗开着先收起")

    def test_the_double_click_judge_is_gone(self):
        self.assertNotIn("LAST_TRAY_CLICK", LIB, "★ 双击判定已被右键取代，别留两套")
        self.assertNotIn("on_tray_left_click", LIB)


if __name__ == "__main__":
    unittest.main()
