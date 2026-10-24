"""`codex-rotate restart-stale`：只重启跑旧代码的服务，代理忙时先等（samchen #4，用户 2026-10-24 选「自动重启」）。

守的：
1. 只 kickstart **旧的**那几个；都是新的就一条命令都不发；
2. 代理有在途请求 ⇒ 等它空下来再重启；等满还忙 ⇒ **不重启**，说清原因；
3. 查不了在途请求（`None`）⇒ 不重启（「查不到」≠「没有」）；
4. 服务进程按 launchd 给的 pid、按它命令行里的脚本路径找代码根 —— `.dmg` 装法跑的是 `runtime/` 副本。
全部打桩：不碰真进程表、不调真 launchctl。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_cli():
    loader = importlib.machinery.SourceFileLoader("cr_restart", str(ROOT / "codex-rotate"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


class R:
    def __init__(self, out="", rc=0, err=""):
        self.stdout, self.returncode, self.stderr = out, rc, err


class RestartStale(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.calls = []

        def run(cmd, *a, **k):
            self.calls.append(cmd)
            return R()
        self.cli.subprocess.run = run
        self.clock = [0.0]

    def _go(self, stale, inflight, wait=60):
        self.cli._daemon_staleness = lambda: (stale, [])
        seq = list(inflight)
        self.cli._proxy_inflight = lambda pid: seq.pop(0) if len(seq) > 1 else seq[0]

        def sleep(s):
            self.clock[0] += s
        return self.cli.restart_stale_daemons(wait_secs=wait, poll=1.0, sleep=sleep, now=lambda: self.clock[0])

    def kicked(self):
        return [c[-1].rsplit(".", 1)[-1] for c in self.calls if c[:2] == ["launchctl", "kickstart"]]

    def test_fresh_services_are_left_alone(self):
        r = self._go([], [0])
        self.assertEqual(self.kicked(), [], "都是新的却发了 kickstart")
        self.assertEqual(r["restarted"], [])

    def test_only_the_stale_one_is_restarted(self):
        r = self._go([("quotad", "旧", "11")], [0])
        self.assertEqual(self.kicked(), ["quotad"])
        self.assertEqual(r["restarted"], ["quotad"])

    def test_a_busy_proxy_is_restarted_once_idle(self):
        r = self._go([("proxy", "旧", "22")], [2, 1, 0])
        self.assertEqual(self.kicked(), ["proxy"], "空下来之后要重启")
        self.assertGreaterEqual(self.clock[0], 2, "★ 有在途请求时没等就重启了")

    def test_a_proxy_still_busy_after_the_wait_is_not_killed(self):
        r = self._go([("proxy", "旧", "22")], [3], wait=5)
        self.assertEqual(self.kicked(), [], "★★ 等满了还忙却照样重启 —— 会掐断正在生成的回答")
        self.assertTrue(r["skipped"] and "仍有 3 个请求" in r["skipped"][0][1])
        self.assertLessEqual(self.clock[0], 6, "等待超过上限")

    def test_unknown_inflight_is_not_treated_as_idle(self):
        r = self._go([("proxy", "旧", "22")], [None])
        self.assertEqual(self.kicked(), [], "★ 查不了在途请求时当成空闲重启了")
        self.assertTrue(r["skipped"])

    def test_a_stopped_proxy_is_started_without_waiting(self):
        r = self._go([("proxy", "**没有在跑**", None)], [5])
        self.assertEqual(self.kicked(), ["proxy"], "没在跑的服务要拉起来")
        self.assertEqual(self.clock[0], 0)

    def test_a_failed_kickstart_is_reported(self):
        self.cli._daemon_staleness = lambda: ([("quotad", "旧", "11")], [])
        self.cli.subprocess.run = lambda *a, **k: R(rc=113, err="Could not find service")
        r = self.cli.restart_stale_daemons()
        self.assertEqual(r["restarted"], [])
        self.assertIn("重装", r["skipped"][0][1])


class TheProcessIsFoundWhereItReallyRuns(unittest.TestCase):
    def test_the_code_root_comes_from_the_process_command_line(self):
        cli = load_cli()

        def run(cmd, *a, **k):
            if cmd[:2] == ["launchctl", "print"]:
                return R("\tstate = running\n\tpid = 4242\n")
            if cmd[0] == "ps":
                return R("/opt/homebrew/bin/python3 /Users/x/store/runtime/proxy/proxy.py\n")
            return R()
        cli.subprocess.run = run
        pid, root = cli._daemon_proc("proxy")
        self.assertEqual(pid, "4242", "pid 要取 launchd 给的")
        self.assertEqual(root, Path("/Users/x/store/runtime"), "★ .dmg 装法跑的是 runtime/ 副本，代码根要从命令行取")

    def test_no_pid_from_launchd_and_none_from_pgrep_means_not_running(self):
        cli = load_cli()
        cli.subprocess.run = lambda cmd, *a, **k: R("\tstate = not running\n" if cmd[0] == "launchctl" else "")
        self.assertEqual(cli._daemon_proc("quotad")[0], None)


if __name__ == "__main__":
    unittest.main()
