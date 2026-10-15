"""主窗口随窗口大小整体缩放（用户 2026-10-14：「界面随窗口大小调整，字体也要调整」）。

判据：
① 走引擎级 `set_zoom`（WKWebView pageZoom），**不许**回到 CSS `zoom` —— 8-24 那次在真机把版面撑爆；
② 只缩主窗口，菜单栏（固定 352 宽、按内容量高度）不缩；
③ 窗口尺寸变化（拖动 / 换屏）都要重算，启动时也要算一次；
④ 倍率的数值行为由 Rust 单测 `zoom_tests` 守（`cargo test zoom_tests`）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RS = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")


def _code(src):
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("//"))


class TheMainWindowZoomsWithItsSize(unittest.TestCase):
    def test_set_zoom_is_called_only_by_the_main_window_helper(self):
        code = _code(RS)
        calls = [m.start() for m in re.finditer(r"\.set_zoom\(", code)]
        self.assertEqual(len(calls), 1, "★ set_zoom 应只有 apply_main_zoom 一处调用")
        i = code.index("fn apply_main_zoom(")
        self.assertTrue(i < calls[0] < code.index("\n}", i), "set_zoom 不在 apply_main_zoom 里")

    def test_resize_and_scale_change_and_startup_all_reapply(self):
        block = _code(RS[RS.index('// ---- main window: show on launch'):])[:1500]
        self.assertIn("apply_main_zoom(&w);", block, "启动时没算一次")
        self.assertIn("tauri::WindowEvent::Resized(_)", block)
        self.assertIn("tauri::WindowEvent::ScaleFactorChanged", block)
        self.assertIn("schedule_main_zoom(&handle_close);", block, "尺寸变化后没安排重算")

    def test_dragging_does_not_zoom_until_it_settles(self):
        """★★ 方案 ①（用户 2026-10-15）：拖动中每跨一档就整页 set_zoom = 字号一跳一跳。
        窗口事件里只许推迟（`schedule_main_zoom`），真正调用在去抖线程里。"""
        block = _code(RS[RS.index('// ---- main window: show on launch'):])[:1500]
        ev = block[block.index("tauri::WindowEvent::Resized(_)"):block.index("CloseRequested")]
        self.assertNotIn("apply_main_zoom(", ev, "★★ 窗口事件里直接调了 apply_main_zoom —— 拖动中又会逐档跳")
        sched = _code(RS[RS.index("fn schedule_main_zoom("):])
        sched = sched[:sched.index("\n}\n")]
        self.assertIn("apply_main_zoom(&w)", sched, "去抖线程到点后没调 apply_main_zoom")
        self.assertIn("ZOOM_SETTLE_MS", sched)

    def test_the_menubar_is_not_zoomed(self):
        i = RS.index("_menubar.on_window_event(")
        self.assertNotIn("zoom", RS[i:i + 800])

    def test_no_css_zoom_comes_back(self):
        """★★ CSS `zoom` 在 WKWebView 与 Chrome 语义不同，harness 会假绿。"""
        hits = []
        for p in (ROOT / "codexbar" / "src").rglob("*"):
            if p.suffix in (".ts", ".tsx", ".css"):
                src = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", p.read_text(encoding="utf-8"))
                if re.search(r"\bzoom\s*:", src):
                    hits.append(p.name)
        self.assertEqual(hits, [])

    def test_the_rust_unit_tests_pass(self):
        if not shutil.which("cargo"):
            self.skipTest("没有 cargo")
        # CI 的 invariants job 跑在 ubuntu 上，没装 gtk/gio 开发库 ⇒ tauri 依赖链编不过（v1.10.0 ci 实测
        # `pkg-config … gio-2.0 >= 2.70` 失败）。那不是 zoom 逻辑红；Rust 的真编译在 ci.yml 的 macOS/Windows 构建 job 里。
        if sys.platform.startswith("linux") and subprocess.run(
                ["pkg-config", "--exists", "gio-2.0"], capture_output=True).returncode != 0:
            self.skipTest("Linux 缺 gio-2.0 开发库，tauri 编不了")
        r = subprocess.run(["cargo", "test", "--lib", "zoom_tests", "--quiet"],
                           cwd=ROOT / "codexbar" / "src-tauri", capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
