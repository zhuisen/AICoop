"""`.dmg` 装机布局下，每个入口在**不设任何变量**时都求出同一个数据目录（B85，2026-10-16 四方评审）。

## 现场
Connector 把脚本复制进 `<store>/runtime/`、把 `~/.local/bin/*` 链过去。数据在 `<store>/`。
原来各入口按 `__file__` 推数据目录 ⇒ 终端 `codex-rotate` 读写 `runtime/state.json`，后台服务读
`<store>/state.json`：两份状态、两把锁（沙箱实跑确认）。`agy-rotate` 同样落到 `runtime/.agy-pool.json`。
既有的闸全都**显式传了** `CODEX_ROTATE_STORE`，所以永远是绿的。

## 守的
1. `.dmg` 布局：11 个 Python 入口 + 3 个 shell 入口，`env -i`（HOME 指临时目录、PATH=/usr/bin:/bin）下
   求出的数据目录都 = `<store>`，不是 `<store>/runtime`。
2. clone 布局（目录不叫 runtime）：数据目录 = 仓库根，行为不变。
3. 发布出去的脚本里没有作者的 clone 路径 / npm prefix 写死在代码里（注释除外）。
4. zstd 候选表在 `traffic/scan.py` 与 `codex-rotate` 两处相同。

★ 设了 `CODEXBAR_BUNDLE_SCRIPTS=<CodexBar.app/Contents/Resources/scripts>` 时，夹具从**构建出来的包**里取脚本
  （release.yml 在 macOS 上这么跑），并要求 `RUNTIME_FILES` 一个不缺 —— 包里少一个文件（B77 的 `dawn_sched.py`）
  在源码树上永远看不出来。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import connector  # noqa: E402

_BUNDLE = os.environ.get("CODEXBAR_BUNDLE_SCRIPTS")
#: 夹具的脚本来源：默认是源码树，release 时是构建出来的 `.app` 里那份。
SRC_ROOT = Path(_BUNDLE).resolve() if _BUNDLE else ROOT

EXTRA = ["traffic/scan.py", "traffic/agy_quota_sampler.py", "traffic/agy_rotation.py",
         "grok-quota-sampler", "grok-quota", "agy-quota", "claude_otel_env.py"]

#: (文件, 读数据目录的表达式) —— 在子进程里按路径加载模块后求值。
PY_SITES = [
    ("codex-rotate", "m.STORE"),
    ("agy/pool.py", "m.STORE"),
    ("proxy/proxy.py", "m.STORE"),
    ("traffic/scan.py", "m._STORE"),
    ("traffic/rotation.py", "m.store_dir()"),
    ("traffic/quota_anchors.py", "Path(m.default_path()).parent"),
    ("traffic/agy_quota_sampler.py", "m._STORE"),
    ("traffic/agy_rotation.py", "m._store()"),
    ("grok-quota-sampler", "m._STORE"),
    # ★ OTel 接收端写账本的目录 = <store>/traffic/otel-ledger（读的人是 requests.py / scan.py）。
    ("traffic/otel_receiver.py", "m.default_dir().parent.parent"),
    ("claude_otel_env.py", "m._store()"),
]

PROBE = r"""
import sys, importlib.util, importlib.machinery
from pathlib import Path
p, expr = sys.argv[1], sys.argv[2]
sys.path.insert(0, str(Path(p).parent))
spec = importlib.util.spec_from_loader("m_probe", importlib.machinery.SourceFileLoader("m_probe", p))
m = importlib.util.module_from_spec(spec); sys.argv = [p]; spec.loader.exec_module(m)
print(Path(str(eval(expr))).resolve())
"""


def _clean_env(home):
    return {"HOME": str(home), "PATH": "/usr/bin:/bin", "AGY_KEYRING": "0", "LANG": "en_US.UTF-8"}


def _layout(base, code_dir_name):
    """建一份布局：<base>/store/<code_dir_name>/ 放代码。返回 (store, code)。"""
    store = base / "store"
    code = store / code_dir_name if code_dir_name == "runtime" else base / code_dir_name
    for rel in sorted(set(connector.RUNTIME_FILES) | set(EXTRA)):
        src = SRC_ROOT / rel
        if src.exists():
            (code / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, code / rel)
    store.mkdir(parents=True, exist_ok=True)
    return (store if code_dir_name == "runtime" else code), code


def _fake_codex_dir(base):
    d = base / "fakebin"
    d.mkdir()
    f = d / "codex"
    f.write_text('#!/bin/sh\necho "STORE=$CODEX_ROTATE_STORE"\n')
    f.chmod(0o755)
    return d


class _Layout(unittest.TestCase):
    CODE_DIR = "runtime"

    def setUp(self):
        self.base = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = self.base / "home"
        (self.home / ".codex").mkdir(parents=True)
        (self.home / ".codex" / "rotateproxy.config.toml").write_text("")
        self.store, self.code = _layout(self.base, self.CODE_DIR)

    def py_store(self, rel, expr):
        r = subprocess.run([sys.executable, "-I", "-c", PROBE, str(self.code / rel), expr],
                           capture_output=True, text=True, timeout=60, env=_clean_env(self.home),
                           cwd=str(self.base))
        self.assertEqual(r.returncode, 0, "%s 加载失败：%s" % (rel, r.stderr[-400:]))
        return Path(r.stdout.strip().splitlines()[-1])

    def sh_store(self, rel, args):
        fake = _fake_codex_dir(self.base) if not (self.base / "fakebin").exists() else self.base / "fakebin"
        env = _clean_env(self.home)
        env["PATH"] = "%s:/usr/bin:/bin" % fake
        r = subprocess.run(["bash", str(self.code / rel)] + args, capture_output=True, text=True,
                           timeout=60, env=env, cwd=str(self.base))
        m = re.search(r"STORE=(.*)", r.stdout)
        self.assertIsNotNone(m, "%s 没走到 exec：rc=%s %s" % (rel, r.returncode, (r.stderr or r.stdout)[-300:]))
        return Path(m.group(1).strip()).resolve()


class EveryEntryFindsTheStoreInADmgLayout(_Layout):
    def test_python_entries(self):
        for rel, expr in PY_SITES:
            with self.subTest(rel=rel):
                got = self.py_store(rel, expr)
                self.assertEqual(got, self.store, "★★★ %s 的数据目录是 %s（应为 %s）" % (rel, got, self.store))

    def test_shell_entries(self):
        for rel, args in (("proxy/cxp", ["doctor"]), ("proxy/cxd", ["--version"]),
                          ("scripts/codex-wrapper-with-logout-guard.sh", ["doctor"])):
            with self.subTest(rel=rel):
                got = self.sh_store(rel, args)
                self.assertEqual(got, self.store, "★★★ %s 导出的 CODEX_ROTATE_STORE 是 %s" % (rel, got))


class TheCloneLayoutIsUnchanged(_Layout):
    CODE_DIR = "codex-account-rotator"

    def test_python_entries(self):
        for rel, expr in PY_SITES:
            with self.subTest(rel=rel):
                self.assertEqual(self.py_store(rel, expr), self.code)

    def test_shell_entries(self):
        for rel, args in (("proxy/cxp", ["doctor"]), ("proxy/cxd", ["--version"]),
                          ("scripts/codex-wrapper-with-logout-guard.sh", ["doctor"])):
            with self.subTest(rel=rel):
                self.assertEqual(self.sh_store(rel, args), self.code)


def _code_lines(path):
    """去掉注释与 docstring 之后的代码行（python 用 AST 剥 docstring；shell 去掉 # 开头的行）。"""
    src = path.read_text(encoding="utf-8")
    if path.suffix in (".sh",) or src.startswith("#!/usr/bin/env bash") or src.startswith("#!/bin/bash"):
        return [(i, re.sub(r"\s#.*$", "", l)) for i, l in enumerate(src.splitlines(), 1)
                if not l.lstrip().startswith("#")]
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return list(enumerate(src.splitlines(), 1))
    doc = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            b = n.body[0]
            if isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant) \
                    and isinstance(b.value.value, str):
                doc.update(range(b.lineno, b.end_lineno + 1))
    return [(i, l.split("#", 1)[0]) for i, l in enumerate(src.splitlines(), 1) if i not in doc]


class NoAuthorPathInShippedCode(unittest.TestCase):
    BANNED = (re.compile(r"Projects/tools/codex-account-rotator"),
              re.compile(r"\$\{?HOME\}?/\.local/npm-global/bin/codex"))

    def test_shipped_files(self):
        files = sorted(set(connector.RUNTIME_FILES) | set(EXTRA))
        self.assertGreater(len(files), 20, "选择器没选中文件")
        hits = []
        for rel in files:
            p = SRC_ROOT / rel
            if not p.exists():
                continue
            for i, line in _code_lines(p):
                if any(b.search(line) for b in self.BANNED):
                    hits.append("%s:%d %s" % (rel, i, line.strip()[:90]))
        self.assertEqual(hits, [], "★★ 发布的脚本里写死了作者机器上的路径：\n" + "\n".join(hits))


@unittest.skipUnless(_BUNDLE, "只在给了构建产物时跑（release.yml）")
class TheBuiltBundleCarriesEveryRuntimeFile(unittest.TestCase):
    def test_nothing_is_missing(self):
        self.assertTrue(SRC_ROOT.is_dir(), f"CODEXBAR_BUNDLE_SCRIPTS 指向的目录不存在：{SRC_ROOT}")
        missing = [r for r in connector.RUNTIME_FILES if not (SRC_ROOT / r).is_file()]
        self.assertEqual(missing, [], "★★★ 安装包里缺运行时文件 —— Connector 复制出去的 runtime 不完整")


class ZstdCandidatesAgree(unittest.TestCase):
    def test_same_table(self):
        def table(rel):
            m = re.search(r"^ZSTD_CANDIDATES = (\(.*?\))", (ROOT / rel).read_text(encoding="utf-8"), re.M)
            self.assertIsNotNone(m, "%s 里没有 ZSTD_CANDIDATES" % rel)
            return ast.literal_eval(m.group(1))
        a, b = table("traffic/scan.py"), table("codex-rotate")
        self.assertEqual(a, b, "★ zstd 候选表两处不同")
        self.assertIn("/usr/local/bin/zstd", a, "★ 没有 Intel Homebrew 的位置")


if __name__ == "__main__":
    unittest.main()
