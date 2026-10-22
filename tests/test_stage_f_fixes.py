"""阶段 F（§11 构建 / 发布 / 测试 + 文档漂移）—— 全方面评审 2026-10-22 的修复闸。

另几条落在原有的闸里：锁外整份写 → `test_lock_order.EveryWholeStateSaveHoldsTheStateLock`；
陈旧阈值 → `test_quota_staleness`；子目录兄弟模块 → `test_runtime_follows_app_update`；
不动真源码 → `test_quota_anchor_wiring`。
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    from . import _isolation  # noqa: F401  ★ 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "codexbar"
DEPLOY = (APP / "scripts" / "deploy.sh").read_text(encoding="utf-8")
BUILD_RS = (APP / "src-tauri" / "build.rs").read_text(encoding="utf-8")


#: 本机私有、gitignored 的说明文件（`.gitignore` 77–79 行）。干净 checkout（CI）里没有 ⇒ 相关断言**明说跳过**，不报错。
PRIVATE_DOCS = ("CLAUDE.md", "AGENTS.md")


def _doc(name):
    p = ROOT / name
    if not p.is_file():
        if name in PRIVATE_DOCS:
            raise unittest.SkipTest("%s 是本机私有文件（gitignored），这台机器上没有" % name)
        raise AssertionError("%s 不见了" % name)
    return p.read_text(encoding="utf-8")


def _code(s):
    return "\n".join(re.sub(r"(?<![:\"'])//.*|#(?![!{]).*", "", ln) for ln in s.splitlines())


class TheBuildNumberCannotGoStale(unittest.TestCase):
    """build.rs 原来只在 `.git/HEAD` / `refs` 变时重跑：干净时构建一次，改完文件再构建，产物仍报 B=0。"""

    def test_build_rs_reruns_on_index_and_on_every_deploy(self):
        code = _code(BUILD_RS)
        self.assertIn('println!("cargo:rerun-if-changed=../../.git/index");', code)
        self.assertIn('println!("cargo:rerun-if-env-changed=CODEXBAR_BUILD_STAMP");', code)

    def test_deploy_changes_the_stamp_before_building(self):
        code = _code(DEPLOY)
        i = code.index('export CODEXBAR_BUILD_STAMP="$(date +%s)-$$"')
        self.assertLess(i, code.index("npx tauri build --bundles app"), "★ 戳要在构建之前换")


class APrereleaseTagIsNotCalledARelease(unittest.TestCase):
    """tag `v1.12.0-beta.1`、manifest `1.12.0` 时 B=0，界面与 deploy.sh 都说「这就是 release v1.12.0」。"""

    def deploy_ver(self, tag, ver="1.12.0"):
        """真跑 deploy.sh 里那行 `case`（抠出来单独执行）。"""
        line = re.search(r'^case "\$TAG" in .*esac$', DEPLOY, re.M)
        self.assertTrue(line, "deploy.sh 没有预发布那行")
        r = subprocess.run(["bash", "-c", 'VER=%s; TAG=%s; %s; echo "$VER"' % (ver, tag, line.group(0))],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip()

    def test_deploy_reports_the_prerelease(self):
        self.assertEqual(self.deploy_ver("v1.12.0-beta.1"), "1.12.0-beta.1")

    def test_a_plain_or_older_tag_leaves_the_version_alone(self):
        self.assertEqual(self.deploy_ver("v1.12.0"), "1.12.0")
        self.assertEqual(self.deploy_ver("v1.11.0-beta.2"), "1.12.0", "★ 别把上一个版本的预发布段安到新版本上")

    def test_build_rs_and_the_ui_carry_it(self):
        self.assertIn('println!("cargo:rustc-env=CODEXBAR_PRERELEASE={}", prerelease());', _code(BUILD_RS))
        self.assertIn('.strip_prefix(&format!("{}-", ver))', BUILD_RS)
        h = (APP / "src" / "helpers.ts").read_text(encoding="utf-8")
        self.assertIn('invoke<string>("build_prerelease")', h)
        self.assertIn("const base = pre ? `${v}-${pre}` : v;", h)
        self.assertIn("build_prerelease,", (APP / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8"))


class DeployFailsLoudly(unittest.TestCase):
    def test_a_build_failure_shows_the_real_error(self):
        code = _code(DEPLOY)
        self.assertNotIn("npx tauri build --bundles app 2>&1 | tail -3", code,
                         "★ `| tail -3` 把编译报错截得只剩一行")
        self.assertRegex(code, r'if ! npx tauri build --bundles app > "\$_buildlog" 2>&1; then\s*\n\s*tail -40 "\$_buildlog"')

    def test_a_failed_post_check_exits_non_zero(self):
        code = _code(DEPLOY)
        self.assertGreaterEqual(code.count("_verify_fail=1"), 2, "两种后验失败都要记下")
        self.assertRegex(code.rstrip(), r'if \[ "\$_verify_fail" != "0" \]; then[\s\S]*exit 1\s*\nfi$',
                         "★ 后验失败照样 exit 0 ⇒ 调用方读到的是「部署成功」")

    def test_the_script_still_parses(self):
        with tempfile.TemporaryDirectory():
            r = subprocess.run(["bash", "-n", str(APP / "scripts" / "deploy.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class RustUnitTestsRunInCI(unittest.TestCase):
    def test_doctests_are_off_and_ci_runs_the_lib_tests(self):
        cargo = (APP / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
        lib = cargo[cargo.index("[lib]"):]
        lib = lib[:lib.index("\n[")]
        self.assertIn("doctest = false", lib)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("- run: cargo test --lib --manifest-path codexbar/src-tauri/Cargo.toml", ci)


class TheDocsMatchTheInstaller(unittest.TestCase):
    """文档漂移：写「6 个 / 5 个服务、keepalive 已取消、otel 不在安装器、CI 出 Windows 产物、跑 unittest」。
    服务清单从 `install-launchd.sh` 现读，改服务不改文档会红。"""

    @classmethod
    def setUpClass(cls):
        sh = (ROOT / "scripts" / "install-launchd.sh").read_text(encoding="utf-8")
        cls.services = re.findall(r"^emit (\w+) ", sh, re.M)
        cls.words = {5: "five", 6: "six", 7: "seven", 8: "eight"}
        cls.sh = sh

    def test_the_count_is_read_from_the_installer(self):
        self.assertIn("keepalive", self.services)
        self.assertIn("otel", self.services)

    def test_every_doc_states_the_real_count(self):
        n = len(self.services)
        self.assertIn("(re)load the %s codex-rotate launchd agents" % self.words[n], self.sh)
        self.assertIn("**生成并加载 %d 个 launchd 服务**" % n, _doc("README.md"))

    def test_the_private_docs_state_the_real_count(self):
        n = len(self.services)
        self.assertIn("generates + loads **%d** services" % n, _doc("CLAUDE.md"))
        self.assertIn("现 **%d 个**" % n, _doc("AGENTS.md"))

    def test_no_doc_still_says_keepalive_is_gone_or_ci_builds_windows(self):
        for f in ("README.md",) + tuple(x for x in PRIVATE_DOCS if (ROOT / x).is_file()):
            t = _doc(f)
            self.assertNotIn("keepalive 定时器已取消（2026-08-29）", t, f)
            self.assertNotIn("dual-platform build", t, f)
            self.assertNotIn("of `macos-latest` and `windows-latest` and attaches", t, f)
            self.assertNotIn("产出 macOS `.dmg` 与 Windows", t, f)

    def test_the_documented_test_command_is_the_ci_one(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("python3 -m pytest tests/ -q", ci)
        for f in PRIVATE_DOCS:
            t = _doc(f)
            self.assertIn("python3 -m pytest tests/ -q", t, f)
            self.assertNotIn("先跑 `python3 -m unittest discover", t, f)
            self.assertNotIn("Do not go looking for `pytest`", t, f)
            self.assertNotIn("根目录无第三方统一测试框架", t, f)
        self.assertNotIn("`python3 -m unittest discover -s tests -p 'test_*.py' -v`.", _doc("CLAUDE.md"))


class TheMainGuardComesLast(unittest.TestCase):
    """全方面评审 §11 存疑（2026-10-23 核实 20 个文件）：TestCase 写在 `unittest.main()` 之后，
    单文件直跑（`python3 tests/test_x.py`）就漏掉后面的类 —— pytest 下照收，所以从没红过。"""

    def test_no_test_class_after_the_main_block(self):
        import ast
        bad = []
        for p in sorted((ROOT / "tests").glob("test_*.py")):
            t = ast.parse(p.read_text(encoding="utf-8"))
            idx = [i for i, x in enumerate(t.body) if isinstance(x, ast.If) and "__main__" in ast.unparse(x.test)]
            if idx and any(isinstance(x, (ast.ClassDef, ast.FunctionDef)) for x in t.body[idx[-1] + 1:]):
                bad.append(p.name)
        self.assertEqual(bad, [], "★ 这些文件的测试类在 `unittest.main()` 之后")


class GeminiStalenessKeepsItsOwnThreshold(unittest.TestCase):
    """阶段 F 评审 codex：codex 的阈值放宽到 90 分钟时，Gemini 跟着放宽了 —— 它没有夜间放慢，3 分钟一刷。"""

    def test_a_forty_minute_old_gemini_reading_is_stale(self):
        import json as _json
        now = 2_000_000_000
        js = ("import('file://%s').then(m => console.log(JSON.stringify(m.agyPoolFreshness("
              "[{quota_at: %d}, {quota_at: %d}], %d))))") % ((APP / "src" / "helpers.ts").as_posix(), now - 40 * 60, now - 60, now)
        r = subprocess.run(["node", "--experimental-strip-types", "-e", js], capture_output=True, text=True, timeout=60)
        got = _json.loads([ln for ln in r.stdout.splitlines() if ln.strip()][-1])
        self.assertEqual((got["stale"], got["fresh"]), (1, 1), "★ 40 分钟没更新的 Gemini 读数被当成新鲜")


class LateWritesNeverResurrectARemovedAccount(unittest.TestCase):
    """阶段 F 评审 codex（high）：联网之后的定向写回用 `setdefault(a, {})`，请求期间被 remove 的号会以残缺槽位复活。
    同一类的所有写回点都改走 `_patch_slot`；这里按源码逐个核，新增的写回点用了 `setdefault` 就红。"""

    def test_no_slot_write_back_uses_setdefault(self):
        bad = []
        for f in ("codex-rotate", "daemon/quota_daemon.py"):
            for i, ln in enumerate((ROOT / f).read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r'\["slots"\]\.setdefault\(a, \{\}\)\.update\(', ln):
                    bad.append("%s:%d" % (f, i))
        self.assertEqual(bad, [], "★ 这些写回点会复活已删除的号：改用 `_patch_slot`")

    def test_patch_slot_skips_a_missing_account(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("cr_stage_f", str(ROOT / "codex-rotate"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cr = importlib.util.module_from_spec(spec)
        loader.exec_module(cr)
        st = {"slots": {"a": {"label": "x"}}}
        cr._patch_slot(st, "gone", {"quota": {}})
        cr._patch_slot(st, "a", {"quota": {"k": 1}})
        self.assertEqual(st, {"slots": {"a": {"label": "x", "quota": {"k": 1}}}})

    def test_keepalive_restamps_identity_when_the_token_is_still_valid(self):
        src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
        i = src.index("ok, msg = _refresh_slot(aid, slot, min_valid_seconds=thresh_h * 3600)")
        self.assertIn('if msg == "still valid":\n                _restamp_from_file(aid, slot)', src[i:i + 600],
                      "★ 代理带回来的新 id_token 永远进不了槽位")


class LongAgyCommandsDoNotWriteLiveSeen(unittest.TestCase):
    """阶段 E/F 评审两方：quota / health 跑十几秒，把开头读的 `live_seen` 写回 ⇒ 盖掉期间 switch 写的新值，前端误报 drift。"""

    def test_quota_and_health_leave_live_seen_alone(self):
        src = (ROOT / "agy-rotate").read_text(encoding="utf-8")
        for fn in ("cmd_quota", "cmd_health"):
            i = src.index("\ndef %s(" % fn)
            body = src[i:src.find("\ndef ", i + 1)]
            calls = re.findall(r"P\.merge_back\(pool, before, \(([^)]*)\)\)", body)
            self.assertTrue(calls, fn)
            for c in calls:
                self.assertNotIn('"live_seen"', c, "★ %s 把联网前读的 live_seen 写回去了" % fn)


class DeployChecksTheBakedBuildNumber(unittest.TestCase):
    """阶段 F 评审 codex：deploy 只报自己现算的 B，二进制里实际烤的是多少没人核。"""

    def test_build_rs_leaves_the_baked_number_for_deploy(self):
        self.assertIn('join("build_number"), &b)', BUILD_RS)
        self.assertIn('println!("cargo:rustc-env=CODEXBAR_BUILD={}", b);', BUILD_RS, "烤进去的与写出来的是同一个值")

    def test_deploy_fails_when_they_disagree(self):
        i = DEPLOY.index('_baked_f=""')
        seg = DEPLOY[i:DEPLOY.index('if [ "$B" = "0" ]; then', i)]
        self.assertIn('elif [ "$(cat "$_baked_f")" != "$B" ]; then', seg)
        self.assertIn("_verify_fail=1", seg, "对不上要让部署以非零退出")
        self.assertLess(DEPLOY.index('B=$(git rev-list --count "$TAG..HEAD"'), i, "先算 B 再比")


if __name__ == "__main__":
    unittest.main()
