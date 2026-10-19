"""「Claude 实测速度」开关：合并 / 冲突不覆盖 / 关只删自己的 / 已有即已开 / 原子写与备份 / 不碰其它键。

★ 全部在临时目录里：`CLAUDE_CONFIG_DIR` 指夹具（Claude Code 自己认这个变量），store 与 OTel 账本也指临时目录，
  `CLAUDE_OTEL_PORT_PROBE=0` 不探真端口。不起 Chrome，所以用临时 HOME 是安全的。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("claude_otel_env", ROOT / "claude_otel_env.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

SECRET = "sk-ant-NEVER-PRINT-ME"
ENV_KEYS = ("CLAUDE_CONFIG_DIR", "CODEX_ROTATE_STORE", "REQUESTS_OTEL_DIR", "CLAUDE_OTEL_PORT_PROBE")


def _user_doc():
    """一份「别人的」settings.json：顶层键有序、env 里有一个密钥。"""
    return {"model": "opus", "permissions": {"allow": ["Bash(ls)"]},
            "env": {"ANTHROPIC_API_KEY": SECRET, "FOO": "bar"}, "theme": "dark"}


class _Sandbox(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="claude-otel-env-")).resolve()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.cfg = self.base / "home" / ".claude"
        self.store = self.base / "store"
        self.otel = self.store / "traffic" / "otel-ledger"
        self.store.mkdir(parents=True)
        self._old = {k: os.environ.get(k) for k in ENV_KEYS}
        os.environ.update({"CLAUDE_CONFIG_DIR": str(self.cfg), "CODEX_ROTATE_STORE": str(self.store),
                           "REQUESTS_OTEL_DIR": str(self.otel), "CLAUDE_OTEL_PORT_PROBE": "0"})
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    @property
    def path(self):
        return self.cfg / "settings.json"

    def write(self, doc, indent=2):
        self.cfg.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(doc, indent=indent) + "\n", encoding="utf-8")
        return self.path.read_bytes()

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def backups(self):
        d = self.store / "backups" / "claude-settings"
        return sorted(d.glob("settings-*.json")) if d.exists() else []

    def cli(self, *args):
        env = dict(os.environ, HOME=str(self.base / "home"))
        r = subprocess.run([sys.executable, "-I", str(ROOT / "claude_otel_env.py"), *args, "--json"],
                           capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout, json.loads(r.stdout)


class EnableMergesWithoutTouchingAnythingElse(_Sandbox):
    def test_the_twelve_keys_are_added_and_the_rest_survives_in_order(self):
        before = self.write(_user_doc())
        out = M.enable()
        self.assertTrue(out["changed"])
        doc = self.read()
        self.assertEqual(list(doc), ["model", "permissions", "env", "theme"], "顶层键的顺序变了")
        self.assertEqual(doc["permissions"], {"allow": ["Bash(ls)"]})
        self.assertEqual(list(doc["env"])[:2], ["ANTHROPIC_API_KEY", "FOO"], "env 里原有的键被挪动了")
        self.assertEqual(doc["env"]["ANTHROPIC_API_KEY"], SECRET)
        for k, v in M.OURS.items():
            self.assertEqual(doc["env"][k], v)
        self.assertEqual(len(doc["env"]), 2 + len(M.OURS))
        self.assertEqual(M.status()["state"], "on")
        # 备份 = 原文件逐字节，0600
        bk = self.backups()
        self.assertEqual(len(bk), 1)
        self.assertEqual(bk[0].read_bytes(), before)
        self.assertEqual(stat.S_IMODE(bk[0].stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.cfg.iterdir()], ["settings.json"], "临时文件没清掉")

    def test_a_missing_file_is_created(self):
        M.enable()
        self.assertEqual(self.read(), {"env": dict(M.OURS)})
        self.assertEqual(self.backups(), [], "没有原文件就不该有备份")

    def test_the_original_indent_is_kept(self):
        self.write(_user_doc(), indent=4)
        M.enable()
        self.assertTrue(self.path.read_text().startswith('{\n    "model"'), "缩进被改成了别的")


class AForeignOtelSetupIsNeverOverwritten(_Sandbox):
    def _assert_refused(self, doc, key):
        before = self.write(doc)
        with self.assertRaises(M.SettingsError):
            M.enable()
        self.assertEqual(self.path.read_bytes(), before, "★★★ 冲突时写了用户的文件")
        st = M.status()
        self.assertEqual(st["state"], "conflict")
        self.assertIn(key, st["conflicts"])
        self.assertEqual(self.backups(), [])

    def test_an_endpoint_pointing_elsewhere(self):
        d = _user_doc()
        d["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://collector.example:4318"
        self._assert_refused(d, "OTEL_EXPORTER_OTLP_ENDPOINT")

    def test_one_of_our_keys_with_another_value(self):
        d = _user_doc()
        d["env"]["CLAUDE_CODE_ENABLE_TELEMETRY"] = "0"
        self._assert_refused(d, "CLAUDE_CODE_ENABLE_TELEMETRY")

    def test_the_cli_reports_key_names_never_values(self):
        d = _user_doc()
        d["env"]["OTEL_EXPORTER_OTLP_HEADERS"] = "Authorization=Bearer " + SECRET
        self.write(d)
        raw, res = self.cli("enable")
        self.assertFalse(res["ok"])
        self.assertEqual(res["state"], "conflict")
        self.assertIn("OTEL_EXPORTER_OTLP_HEADERS", res["error"])
        self.assertNotIn(SECRET, raw, "★★★ stdout 里出现了 settings.json 的值")
        self.assertNotIn("bar", raw.replace("bar_", ""), "stdout 里出现了别的 env 值")


class AlreadyOnReadsAsOnAndIsNotRewritten(_Sandbox):
    def test_a_hand_written_trial_set_reads_as_on(self):
        d = _user_doc()
        d["env"].update(M.OURS)
        before = self.write(d)
        mtime = self.path.stat().st_mtime_ns
        self.assertEqual(M.status()["state"], "on")
        out = M.enable()
        self.assertFalse(out["changed"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, mtime, "已开时不该重写")
        self.assertEqual(self.backups(), [])


class DisableRemovesOnlyWhatWeWrote(_Sandbox):
    def test_enable_then_disable_round_trips_byte_for_byte(self):
        before = self.write(_user_doc())
        M.enable()
        M.disable()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(M.status()["state"], "off")
        self.assertFalse((self.store / ".claude-otel-env.json").exists(), "记录没删")

    def test_a_key_the_user_already_had_is_kept(self):
        d = _user_doc()
        d["env"]["OTEL_LOG_USER_PROMPTS"] = "0"        # 与我们的值相同，但不是我们写的
        self.write(d)
        M.enable()
        M.disable()
        self.assertEqual(self.read()["env"].get("OTEL_LOG_USER_PROMPTS"), "0", "★★ 删了用户自己的键")

    def test_a_key_the_user_changed_afterwards_is_kept(self):
        self.write(_user_doc())
        M.enable()
        doc = self.read()
        doc["env"]["OTEL_TRACES_EXPORT_INTERVAL"] = "5000"
        self.write(doc)
        M.disable()
        env = self.read()["env"]
        self.assertEqual(env.get("OTEL_TRACES_EXPORT_INTERVAL"), "5000", "★★ 值已被用户改过还删")
        self.assertNotIn("OTEL_TRACES_EXPORTER", env)

    def test_an_env_we_created_is_removed_again(self):
        self.write({"model": "opus"})
        M.enable()
        M.disable()
        self.assertEqual(self.read(), {"model": "opus"})

    def test_without_a_record_the_full_set_counts_as_ours(self):
        d = _user_doc()
        d["env"].update(M.OURS)
        self.write(d)
        M.disable()
        self.assertEqual(self.read()["env"], {"ANTHROPIC_API_KEY": SECRET, "FOO": "bar"})

    def test_without_a_record_a_partial_set_is_left_alone(self):
        d = _user_doc()
        d["env"]["CLAUDE_CODE_ENABLE_TELEMETRY"] = "1"
        before = self.write(d)
        M.disable()
        self.assertEqual(self.path.read_bytes(), before)


class WritesAreAtomicAndBackedUp(_Sandbox):
    def test_a_concurrent_change_aborts_the_write(self):
        before = self.write(_user_doc())
        self.path.write_text(json.dumps({"changed": "by claude"}), encoding="utf-8")
        with self.assertRaises(M.SettingsError):
            M._atomic_write(self.path, {"x": 1}, before)
        self.assertEqual(self.read(), {"changed": "by claude"})
        self.assertEqual([p.name for p in self.cfg.iterdir()], ["settings.json"])

    def test_invalid_json_is_never_touched(self):
        self.cfg.mkdir(parents=True)
        self.path.write_text('{"env": {', encoding="utf-8")
        with self.assertRaises(M.SettingsError):
            M.enable()
        self.assertEqual(self.path.read_text(), '{"env": {')
        self.assertEqual(M.status()["state"], "error")

    def test_a_symlinked_settings_file_stays_a_symlink(self):
        real = self.base / "dotfiles" / "settings.json"
        real.parent.mkdir()
        real.write_text(json.dumps(_user_doc(), indent=2) + "\n")
        self.cfg.mkdir(parents=True)
        self.path.symlink_to(real)
        M.enable()
        self.assertTrue(self.path.is_symlink(), "symlink 被换成了普通文件")
        self.assertEqual(json.loads(real.read_text())["env"]["OTEL_TRACES_EXPORTER"], "otlp")

    def test_only_five_backups_are_kept(self):
        self.write(_user_doc())
        for _ in range(4):
            M.enable()
            M.disable()
        self.assertLessEqual(len(self.backups()), M.KEEP_BACKUPS)
        self.assertGreater(len(self.backups()), 0)


class TheThreeStatesComeFromTheReceiver(_Sandbox):
    def _on(self):
        d = _user_doc()
        d["env"].update(M.OURS)
        self.write(d)

    def _status_file(self, st):
        self.otel.mkdir(parents=True, exist_ok=True)
        (self.otel / ".status.json").write_text(json.dumps(st))

    def test_off(self):
        self.write(_user_doc())
        self.assertEqual(M.status()["ui"], "off")

    def test_on_but_nothing_received_yet(self):
        self._on()
        self.assertEqual(M.status()["ui"], "on_waiting")

    def test_on_and_received(self):
        self._on()
        self._status_file({"last_post_at": 1792384243.1, "listening": True})
        st = M.status()
        self.assertEqual(st["ui"], "on_receiving")
        self.assertEqual(st["receiver"]["last_post_at"], 1792384243.1)

    def test_on_but_the_receiver_could_not_bind(self):
        self._on()
        self._status_file({"last_post_at": None, "listening": False, "last_error": "端口 4318 已被别的程序占用"})
        st = M.status()
        self.assertEqual(st["ui"], "on_down")
        self.assertIn("4318", st["receiver"]["error"])


def _ts(expr, st, read_err=None):
    src = (ROOT / "codexbar" / "src" / "claudeOtel.ts").as_posix()
    script = ("import('%s').then(m => { const st = %s; const re = %s; "
              "console.log(JSON.stringify(%s)); })" % (src, json.dumps(st), json.dumps(read_err), expr))
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", script],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheSettingsRowSaysWhatToDo(unittest.TestCase):
    """设置页那一行的文案（`claudeOtel.ts`，零 import）。"""

    def st(self, **kw):
        base = {"ok": True, "state": "on", "ui": "on_waiting", "error": None, "conflicts": [],
                "settings": "~/.claude/settings.json",
                "receiver": {"last_post_at": None, "listening": None, "error": None, "port_open": True}}
        base.update(kw)
        return base

    def test_waiting_tells_you_to_reopen_the_session(self):
        self.assertIn("重开 Claude Code 会话", _ts("m.claudeOtelWarn(st, re)", self.st()))

    def test_receiving_shows_the_time_without_a_warning_mark(self):
        w = _ts("m.claudeOtelWarn(st, re)", self.st(ui="on_receiving", receiver={
            "last_post_at": 1792384243, "listening": True, "error": None, "port_open": True}))
        self.assertTrue(w.startswith("已收到数据"), w)

    def test_conflict_names_the_keys_and_locks_the_toggle(self):
        st = self.st(state="conflict", ui="conflict", conflicts=["OTEL_A", "OTEL_B", "OTEL_C"])
        self.assertEqual(_ts("m.claudeOtelWarn(st, re)", st), "⚠ 已有别的 OTel 配置（OTEL_A、OTEL_B 等 3 项），没有改动")
        self.assertTrue(_ts("m.claudeOtelLocked(st)", st))

    def test_a_port_conflict_is_shown(self):
        st = self.st(ui="on_down", receiver={"last_post_at": None, "listening": False,
                                             "error": "端口 4318 已被别的程序占用", "port_open": True})
        self.assertIn("4318", _ts("m.claudeOtelWarn(st, re)", st))

    def test_unreadable_is_not_off(self):
        self.assertIsNone(_ts("m.claudeOtelOn(st)", None))
        self.assertIn("读不到", _ts("m.claudeOtelWarn(st, re)", None, "script not found"))
        self.assertTrue(_ts("m.claudeOtelOn(st)", self.st()))
        self.assertFalse(_ts("m.claudeOtelOn(st)", self.st(state="off", ui="off")))


class TheSettingsPageWiresTheRow(unittest.TestCase):
    def test_the_row_is_rendered_and_calls_the_command(self):
        tsx = (ROOT / "codexbar" / "src" / "pages" / "SettingsPage.tsx").read_text(encoding="utf-8")
        self.assertIn("<ClaudeOtelRow t={t} />", tsx)
        self.assertIn('invoke<string>("claude_otel", { action })', tsx)
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        self.assertIn('"status" | "enable" | "disable"', rs)
        self.assertRegex(rs, r"read_statusline_quota, claude_otel,", "命令没注册进 invoke_handler")


if __name__ == "__main__":
    unittest.main()
