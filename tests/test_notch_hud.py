"""刘海额度条（`codexbar/src-tauri/src/notch.rs` + `codexbar/src/NotchHud.tsx`）的静态闸。

守的都是「错了不报错、只是看着怪」的那一类：
  · 尺寸常量分在 Rust / TSX / CSS 三处，对不上时面板被裁或偏到一边；
  · 少了 fullScreenAuxiliary，切到全屏应用就不见了 —— 2026-10-17 用户实测确认过要的就是全屏可见；
  · 新窗口没进 capabilities，invoke/listen 全部静默失败，刘海上永远是一条空槽；
  · 默认关是用户定的（2026-10-17），被顺手改成默认开会让所有人的刘海上多出一条东西。

纯文本解析，不 import 任何模块、不碰凭证。
"""
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "codexbar"
RS = APP / "src-tauri" / "src" / "notch.rs"
LIB = APP / "src-tauri" / "src" / "lib.rs"
TSX = APP / "src" / "NotchHud.tsx"
CSS = APP / "src" / "notch.css"
SETTINGS = APP / "src" / "pages" / "SettingsPage.tsx"
APP_TSX = APP / "src" / "App.tsx"


def _one(path, pattern, what):
    hits = re.findall(pattern, path.read_text(encoding="utf-8"), re.M)
    assert len(hits) == 1, f"{path.name} 里 {what} 命中 {len(hits)} 次，应为 1"
    return hits[0]


class SizesAgree(unittest.TestCase):
    def test_panel_width_is_the_same_in_three_places(self):
        rs = float(_one(RS, r"^pub const PANEL_W: f64 = (\d+(?:\.\d+)?);", "PANEL_W"))
        tsx = float(_one(TSX, r"^const PANEL_W = (\d+);", "PANEL_W"))
        css = float(_one(CSS, r"--pw: (\d+)px", "--pw"))
        self.assertEqual(rs, tsx, "notch.rs 与 NotchHud.tsx 的面板宽不一致 ⇒ 面板被裁或偏到一边")
        self.assertEqual(rs, css, "notch.rs 与 notch.css 的 --pw 不一致")

    def test_flare_and_lip_match_the_css(self):
        for name, var in (("FLARE", "--flare"), ("LIP", "--lip")):
            rs = float(_one(RS, rf"^const {name}: f64 = (\d+(?:\.\d+)?);", name))
            css = float(_one(CSS, rf"{var}: (\d+)px", var))
            self.assertEqual(rs, css, f"notch.rs 的 {name} 与 notch.css 的 {var} 不一致")


class WindowBehaviour(unittest.TestCase):
    def test_sits_above_the_menubar(self):
        self.assertEqual(_one(RS, r"setLevel: (\d+)isize", "setLevel"), "26",
                         "层级必须是 NSStatusWindowLevel+1，低了会被菜单栏盖住")

    def test_visible_over_full_screen_apps(self):
        line = _one(RS, r"let behavior: usize = (.+);", "collectionBehavior")
        self.assertIn("1 << 8", line, "少了 fullScreenAuxiliary(1<<8)，全屏应用里就看不到了")
        self.assertIn("1 << 0", line, "少了 canJoinAllSpaces(1<<0)，切桌面就不见了")

    def test_turning_off_destroys_the_window(self):
        src = RS.read_text(encoding="utf-8")
        body = src[src.index("pub fn set_enabled"):]
        off = body[:body.index("return Ok(());")]
        self.assertIn(".destroy()", off, "关掉时要销毁窗口，隐藏的 WKWebView 仍常驻两个系统进程")

    def test_commands_are_registered(self):
        lib = LIB.read_text(encoding="utf-8")
        block = re.search(r"generate_handler!\[(.*?)\]\)", lib, re.S)
        self.assertIsNotNone(block, "找不到 invoke_handler 的 generate_handler![...]")
        for cmd in ("set_notch_hud", "notch_geometry", "notch_panel_height"):
            self.assertRegex(block.group(1), rf"\b{cmd}\b", f"{cmd} 没注册进 invoke_handler")

    def test_window_has_capabilities(self):
        caps = json.loads((APP / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8"))
        self.assertIn("notch", caps["windows"], "notch 窗口不在 capabilities 里 ⇒ invoke/listen 全部静默失败")

    def test_page_is_built(self):
        self.assertIn("notch.html", (APP / "vite.config.ts").read_text(encoding="utf-8"),
                      "vite 没把 notch.html 打进包，窗口会是空白")


class DefaultsAndColour(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(_one(SETTINGS, r"^\s*notchHud: (\w+),", "notchHud 默认值"), "false")

    def test_startup_only_turns_it_on_when_enabled(self):
        app = APP_TSX.read_text(encoding="utf-8")
        self.assertRegex(app, r"if \(st\.notchHud\) invoke\(\"set_notch_hud\"",
                         "启动时只在开着的情况下调用；无条件调用会让关着的用户也建一次窗口")

    def test_uses_the_tray_colour_rule(self):
        """刘海条和托盘标题是同一类"瞄一眼"的指示，必须同一套颜色（ui.md「额度色阈值只有一条规则」）。"""
        tsx = TSX.read_text(encoding="utf-8")
        # 打在代码形态上，不打在词上 —— 注释里正写着 quotaColor（verification.md 形态⑫）
        self.assertRegex(tsx, r"const segColor = \(pct: number\) => \(pct <= 0 \? RED : quotaColor\(pct\)\);",
                         "颜色要走 quotaColor（<50 琥珀），0 额外标红 —— 与托盘标题同一条")
        self.assertNotIn("quotaLevel", tsx, "别换成卡片那套 ≤10 红 —— 会和托盘标题说法不一")


if __name__ == "__main__":
    unittest.main()
