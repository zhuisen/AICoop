"""「检查更新」（samchen #5 补充）。

原来只走 `git -C <store_dir> ls-remote`：CI 出的安装包没有烧录的仓库路径，`store_dir()` 落到不存在的
`~/Projects/tools/…`，git 必败，界面却说「网络或凭证」；有新版时一律教 `git pull && deploy.sh`，安装包用户照做不了。

守的：
1. Rust 先问 GitHub Releases API，只在 clone 装法才退回 git；结果带 `clone`；
2. 界面按 `clone` 给两种更新说法；出错原样显示原因（不再写死「网络或凭证」）。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import re
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def rust_fn(name):
    s = re.sub(r"(?<![:\"])//[^\n]*", "", LIB.read_text(encoding="utf-8"))
    i = s.index(f"async fn {name}(")
    return s[i:s.index("\n}\n", i)]


class TheRustSide(unittest.TestCase):
    def test_api_first_git_only_for_a_clone(self):
        f = rust_fn("check_update")
        api, git = f.find("releases/latest"), f.find('"ls-remote"')
        self.assertGreater(api, 0, "要先问 Releases API")
        self.assertGreater(git, api, "git 只能是退路")
        self.assertRegex(f[api:git], r"if !clone \{\s*return Err", "不是 clone 装法就不该去跑 git")
        self.assertNotIn("网络或凭证", f, "原因要照实说，不写死")
        self.assertEqual(f.count('"clone": clone'), 2, "api 与 git 两条路的结果都要带 clone")


def _about(upd):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        pg = br.new_page(viewport={"width": 1200, "height": 800})
        pg.goto(f"http://127.0.0.1:3304/harness.html?nav=settings&upd={upd}", timeout=30000)
        pg.wait_for_selector('[data-act="check-update"]', timeout=8000)
        pg.click('[data-act="check-update"]')
        pg.wait_for_timeout(500)
        t = pg.inner_text("[data-about]")
        br.close()
    return t


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class OnTheRealBundle(unittest.TestCase):
    def _t(self, upd):
        t = _about(upd)
        if t is None:
            self.skipTest("harness 3304 没起 —— skip 不是绿")
        return t

    def test_a_clone_is_told_to_pull_and_deploy(self):
        t = self._t("clone")
        self.assertIn("有新版 v99.0.0", t, "★ 前提：判成了有新版")
        self.assertIn("git pull", t)

    def test_an_installer_user_is_told_to_download(self):
        t = self._t("dmg")
        self.assertIn("有新版 v99.0.0", t, "★ 前提：判成了有新版")
        self.assertNotIn("git pull", t, "★★ 安装包用户照 git pull 做不了")
        self.assertIn(".dmg", t)

    def test_the_real_reason_is_shown(self):
        self.assertIn("检查网络或代理", self._t("err"))


if __name__ == "__main__":
    unittest.main()
