"""裸 `codex` 走不走轮换 wrapper（`codex-rotate::codex_wrap_gate`，samchen #4 本机⑤）。

夹具 PATH + 临时 `CODEXBAR_LOCAL_BIN`，不碰真 `~/.local/bin`。守的：
1. wrapper 在最前 ⇒ ok；2. 别的 codex 排在 wrapper 前面 ⇒ warn，给 PATH 修法；
3. 装过接管、wrapper 被 npm 改写成官方版 ⇒ warn，给重装 + npm 前缀两条修法；
4. 从没装过（可选步）⇒ 不报警，只说现状。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("cr_wrapgate", str(ROOT / "codex-rotate"))
CR = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(CR)

WRAP = "#!/bin/sh\n" + "# filler\n" * 800 + "# codex-profile-scope.sh\nexit 0\n"


class CodexWrapGate(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.lb, self.npm = self.d / "localbin", self.d / "npm" / "lib" / "node_modules" / "@openai" / "codex" / "bin"
        self.other = self.d / "other"
        for x in (self.lb, self.npm, self.other):
            x.mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"CODEXBAR_LOCAL_BIN": str(self.lb)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def put(self, p, body):
        p.write_text(body)
        p.chmod(0o755)
        return p

    def gate(self, *dirs):
        return CR.codex_wrap_gate(path=os.pathsep.join(str(x) for x in dirs))

    def test_wrapper_first_is_ok(self):
        self.put(self.lb / "codex", WRAP)
        self.put(self.other / "codex", "#!/bin/sh\n")
        self.assertEqual(self.gate(self.lb, self.other)["level"], "ok")

    def test_another_codex_ahead_of_the_wrapper_warns_with_the_path_fix(self):
        self.put(self.lb / "codex", WRAP)
        self.put(self.other / "codex", "#!/bin/sh\n")
        g = self.gate(self.other, self.lb)
        self.assertEqual(g["level"], "warn", "★★ npm 的 codex 排在前面却报 ok")
        self.assertIn("export PATH=", "\n".join(g["lines"]))

    def test_npm_overwrote_the_wrapper(self):
        real = self.put(self.npm / "codex.js", "#!/usr/bin/env node\n")
        (self.lb / "codex").symlink_to(real)
        (self.lb / "codex.before-codexbar").write_text("x")
        g = self.gate(self.lb)
        self.assertEqual(g["level"], "warn", "★★ 装过接管、wrapper 被 npm 改写回官方版却报 ok")
        joined = "\n".join(g["lines"])
        self.assertIn("连 codex 一起接管", joined)
        self.assertIn("npm config set prefix", joined)

    def test_never_installed_is_not_an_alarm(self):
        self.put(self.other / "codex", "#!/bin/sh\n")
        g = self.gate(self.other)
        self.assertEqual(g["level"], "ok", "可选步没装不是故障 —— 恒响的闸会被无视")
        self.assertIn("不走轮换", "\n".join(g["lines"]), "但要说清现状")

    def test_health_prints_it(self):
        import ast
        tree = ast.parse((ROOT / "codex-rotate").read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cmd_health")
        self.assertIn("codex_wrap_gate()", ast.unparse(fn))


if __name__ == "__main__":
    unittest.main()
