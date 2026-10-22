"""菜单栏弹窗重开（用户 2026-10-22）：关掉 ≥1 分钟再开 ⇒ 回到默认（账号页 · Codex 档）；1 分钟内重开（误关）⇒ 保持原样。"""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGIC = ROOT / "codexbar/src/mbLogic.ts"
MB = ROOT / "codexbar/src/MenuBar.tsx"


def node(expr):
    js = "import('%s').then(m => console.log(JSON.stringify(%s)))" % (LOGIC.as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class ReopenRule(unittest.TestCase):
    def test_threshold(self):
        self.assertEqual(node("[m.reopenResets(null, 1e6), m.reopenResets(0, 59_999), m.reopenResets(0, 60_000), m.reopenResets(0, 3_600_000)]"),
                         [False, False, True, True])

    def test_wired_on_show_and_resets_tab_and_platform(self):
        src = re.sub(r"//[^\n]*", "", MB.read_text(encoding="utf-8"))
        i = src.index("const hiddenAt = useRef")
        body = src[i:src.index("}, [setTab, setPlat]);", i)]
        self.assertIn("onFocusChanged", body)
        self.assertIn('listen("menubar-shown"', body)
        self.assertRegex(body, r"reopenResets\(hiddenAt\.current, Date\.now\(\)\)")
        self.assertIn('setTab("acc")', body)
        self.assertIn('setPlat("codex")', body)


if __name__ == "__main__":
    unittest.main()
