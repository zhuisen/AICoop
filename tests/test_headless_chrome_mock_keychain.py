"""直接起 Headless Chrome 的地方必须带 `--use-mock-keychain`（2026-10-17，B86）。

## 现场
一次 `HOME=$(mktemp -d) python3 -m unittest discover …`（为了模拟干净的 CI runner）跑到
`test_card_uniformity.py` 起 Chrome 时，Chrome 去读「Chrome Safe Storage」钥匙串 → 在假 HOME 下
找不到 `login.keychain-db` → SecurityAgent 弹出 **Keychain Not Found** 模态框，测试卡在那里等人点。
那一轮因此跑了 25 分钟仍没结束、被当成「慢」停掉 —— 实际是**阻塞在一个用户看得见、会话里看不见的弹窗上**。

## 守的
仓库里每个含 `--headless…` 的参数列表（AST 里的 list/tuple 字面量）都同时含 `--use-mock-keychain`。
Playwright 不在此列：它默认就带 `--use-mock-keychain` 和 `--password-store=basic`（2026-10-17 读进程命令行实测）。
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLAG = "--use-mock-keychain"
HEADLESS = "--head" + "less"          # 拆开写：这个文件自己的字面量不算一个启动点


def _launch_sites():
    files = [*sorted((ROOT / "tests").glob("*.py")), *sorted((ROOT / "codexbar" / "uishot").glob("*.py")),
             *sorted((ROOT / "tools").glob("*.py"))]
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.List, ast.Tuple)):
                strs = [e.value for e in n.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if any(s.startswith(HEADLESS) for s in strs):
                    yield f, n.lineno, strs


class EveryHeadlessChromeUsesTheMockKeychain(unittest.TestCase):
    def test_the_probe_sees_the_launch_sites(self):
        """★ 选择器先证明自己选中了东西：2026-10-17 时有 16 处。"""
        self.assertGreaterEqual(len(list(_launch_sites())), 16, "★ 一个启动点都没扫到 —— 探针坏了")

    def test_each_launch_carries_the_flag(self):
        bad = ["%s:%d" % (f.relative_to(ROOT), ln) for f, ln, strs in _launch_sites() if FLAG not in strs]
        self.assertEqual(bad, [], "★★ 这些地方起 Chrome 没带 %s —— 在隔离 HOME 下会弹「Keychain Not Found」"
                                  "模态框并把测试卡住：\n  %s" % (FLAG, "\n  ".join(bad)))


if __name__ == "__main__":
    unittest.main()
