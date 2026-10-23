"""测试隔离的**唯一实现** —— 任何会起 agy / codex 脚本子进程的测试模块都必须 import 它。

★★★ 为什么不只放在 `tests/__init__.py`（2026-09-24 事故）：
  `python3 -m unittest discover -s tests -p 'test_agy*'` 这种按文件名过滤的跑法
  **既不导入 `tests/__init__.py`，也匹配不到 `test_isolation_bootstrap.py`** ⇒ 隔离一个都没生效 ⇒
  测试夹具 `new@x.y` 被写进了用户真实的钥匙串（agy 登录态），`auth/agy/new.json` 落进真凭证目录，
  还有测试经 `bin/agy` 对**真实账号池**跑了 `auto`。隔离不能依赖「跑法恰好对」。
  闸：`tests/test_isolation_bootstrap.py::EveryScriptSpawningTestImportsTheIsolation`。

★ 全部用 setdefault 语义：调用方显式指定过的不覆盖。
"""
import atexit
import os
import shutil
import tempfile

if not os.environ.get("CODEXBAR_QUOTA_ANCHORS"):
    _d = tempfile.mkdtemp(prefix="codexbar-test-anchors-")
    os.environ["CODEXBAR_QUOTA_ANCHORS"] = os.path.join(_d, ".quota-anchors.json")
    atexit.register(shutil.rmtree, _d, True)
# 钥匙串**没有临时目录这种东西** —— 只能关掉。
os.environ.setdefault("AGY_KEYRING", "0")
os.environ.setdefault("AGY_USAGE_REPORT", "0")   # B88：别在测试里起真 agy 跑 /usage
os.environ.setdefault("CODEXBAR_LAUNCHCTL", "0")
# ★ grok 的两个落盘标记（`grok-quota-sampler::grok_recent` 按 mtime 判「刚跑过」）指到不存在的路径：
#   否则你刚用过 grok，测试起的采样器就会当它在跑、拿**真** auth 去打 xAI（2026-10-23 采样器放宽门时补）。
_g = os.path.join(tempfile.gettempdir(), "codexbar-test-no-grok")
os.environ.setdefault("GROK_AUTH_PATH", os.path.join(_g, "auth.json"))
os.environ.setdefault("GROK_LOG_PATH", os.path.join(_g, "unified.jsonl"))
# ★★ agy 账号池默认也指到临时目录：`bin/agy` → `agy-rotate auto` 对真池跑一次，
#   装进钥匙串的就是**真凭证**（Google 签发），源头那道 `is_google_issued` 挡不住它。
if not os.environ.get("AGY_POOL_STORE"):
    _p = tempfile.mkdtemp(prefix="codexbar-test-agypool-")
    os.environ["AGY_POOL_STORE"] = _p
    atexit.register(shutil.rmtree, _p, True)
# ★ Claude（P3b 设计第 0 层闸 G2，2026-10-22）：Claude Code 的配置根同样指到临时目录、真二进制换成 false。
#   今天没有测试起真 `claude`，但 `claude_otel_env.py` 会改 `<CLAUDE_CONFIG_DIR>/settings.json` ——
#   哪个用例忘了设，改的就是用户真配置；钥匙串没有临时目录，起真 `claude auth` 会覆盖登录态。
if not os.environ.get("CLAUDE_CONFIG_DIR"):
    _c = tempfile.mkdtemp(prefix="codexbar-test-claude-")
    os.environ["CLAUDE_CONFIG_DIR"] = _c
    atexit.register(shutil.rmtree, _c, True)
# ★ 真二进制拦在 PATH 上（阶段 4 评审：原来的 `CLAUDE_REAL=/usr/bin/false` 没有任何代码读它，是空闸）。
#   PATH 最前面放一个 `claude` 桩，跑到就 exit 97 —— `subprocess.run(["claude", …])` 起不到真 Claude。
#   绝对路径调用拦不住，那一类由 `test_isolation_bootstrap.py::NoTestSpawnsClaudeByAbsolutePath` 盯。
if not os.environ.get("CODEXBAR_TEST_CLAUDE_STUB"):
    _b = tempfile.mkdtemp(prefix="codexbar-test-bin-")
    _s = os.path.join(_b, "claude")
    with open(_s, "w", encoding="utf-8") as _fh:
        _fh.write("#!/bin/sh\necho 'tests/_isolation.py: real claude is blocked in tests' >&2\nexit 97\n")
    os.chmod(_s, 0o755)
    os.environ["PATH"] = _b + os.pathsep + os.environ.get("PATH", "")
    os.environ["CODEXBAR_TEST_CLAUDE_STUB"] = _s
    atexit.register(shutil.rmtree, _b, True)
