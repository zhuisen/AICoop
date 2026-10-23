"""进程名统一叫 AICoop（用户 2026-10-23「原来旧进程的名字是叫 codexbar 的，能不能都统一改成 AICoop」）。

进程名 = bundle 里可执行文件的名字。2026-10-21 改名时只改了 `productName`（窗口 / .app 名），可执行文件
仍随 Cargo 包名叫 `codexbar` ⇒ 活动监视器、`ps` 里还是 codexbar。改法是 `mainBinaryName`，**不动 bundle id**：
`com.doushutangmu.codexbar` 是本机设置（localStorage）、窗口几何、单实例锁、TCC 授权的钥匙，换了全丢。
部署脚本按可执行文件路径认进程，必须跟着改 —— 否则新包装好后「启动后没看到进程」误报失败。
"""
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONF = json.loads((ROOT / "codexbar" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
DEPLOY = (ROOT / "codexbar" / "scripts" / "deploy.sh").read_text(encoding="utf-8")


class TheProcessIsCalledAICoop(unittest.TestCase):
    def test_binary_name_matches_the_product_name(self):
        self.assertEqual(CONF.get("mainBinaryName"), "AICoop")
        self.assertEqual(CONF.get("productName"), "AICoop")

    def test_bundle_id_is_unchanged(self):
        self.assertEqual(CONF.get("identifier"), "com.doushutangmu.codexbar",
                         "★ 换 bundle id = 设置、窗口几何、TCC 授权全丢；进程名只靠 mainBinaryName")

    def test_deploy_script_expects_the_new_binary(self):
        self.assertIn('!= "$APP/Contents/MacOS/AICoop"', DEPLOY, "后验比对的是新可执行文件")
        ours = next(l for l in DEPLOY.splitlines() if l.startswith("_ours()"))
        for exe in ('$APP/Contents/MacOS/AICoop', '$APP/Contents/MacOS/codexbar', '$LEGACY_APP/Contents/MacOS/codexbar'):
            self.assertIn(exe, ours, "升级那一次在跑的还是旧名，停旧实例要两个都认")
        self.assertTrue(re.search(r"_running=.*AICoop", DEPLOY))


if __name__ == "__main__":
    unittest.main()
