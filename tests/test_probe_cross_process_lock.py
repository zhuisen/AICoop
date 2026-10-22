"""计费探针跨进程互斥（全方面评审 2026-10-22：菜单栏不经过总览的 `withBilled`，`cmd_probe` 也没有占位）。

菜单栏、总览、⌘K、dawn-probe 各起一个 `probe` 子进程；前端在途锁只管自己那个 webview。
现在 `cmd_probe` 按号占 flock：别的进程正在探这个号 ⇒ 跳过，不排队、不重复计费。

临时 store；`_billed_probe` / `_probe_quota` 打桩（不发任何请求），另一进程用本测试持有的 flock 模拟。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import contextlib
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OneBillPerAccountAtATime(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="cbx_probelock_"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        (self.dir / "auth").mkdir()
        old = os.environ.get("CODEX_ROTATE_STORE")
        os.environ["CODEX_ROTATE_STORE"] = str(self.dir)
        try:
            loader = importlib.machinery.SourceFileLoader("cr_probelock", str(ROOT / "codex-rotate"))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            self.m = importlib.util.module_from_spec(spec)
            loader.exec_module(self.m)
        finally:
            if old is None:
                os.environ.pop("CODEX_ROTATE_STORE", None)
            else:
                os.environ["CODEX_ROTATE_STORE"] = old
        self.assertEqual(self.m.STORE, self.dir, "夹具没隔离")
        self.m._save_state({"active": "A", "slots": {
            "A": {"label": "a", "plan": "plus", "file": "A.json"},
            "B": {"label": "b", "plan": "plus", "file": "B.json"}}})
        self.billed = []
        self.m._probe_quota = lambda aid, slot, is_active: (None, "stub")
        self.m._billed_probe = lambda aid, slot, is_active, model, effort: (
            self.billed.append(aid), (None, "HTTP 400 stub", ""))[1]
        self.m._write_last_probe = lambda *a, **k: None
        real_sleep = self.m.time.sleep
        self.m.time.sleep = lambda s: None
        self.addCleanup(setattr, self.m.time, "sleep", real_sleep)

    def hold(self, aid):
        fh = open(self.dir / f".probe-{uuid.uuid5(uuid.NAMESPACE_OID, aid).hex[:12]}.lock", "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(fh.close)

    def probe(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.m.cmd_probe([], aids=["A", "B"])
        return out.getvalue()

    def test_known_positive_both_are_billed_when_nobody_else_probes(self):
        self.probe()
        self.assertEqual(self.billed, ["A", "B"])

    def test_an_account_being_probed_elsewhere_is_skipped(self):
        self.hold("A")
        out = self.probe()
        self.assertEqual(self.billed, ["B"], "★★ 另一个进程正在探 A，这里又给 A 计了一次费")
        self.assertIn("另一个进程正在探这个号", out)

    def test_the_lock_is_released_after_each_account(self):
        """占住的锁在探完那个号后就放掉 —— 否则一次全池探针会把之后所有单号探针挡在外面。"""
        self.probe()
        self.hold("A")   # 能占到 = 已释放（LOCK_NB 占不到会抛）

    def test_lock_files_do_not_carry_the_account_id(self):
        self.probe()
        names = [p.name for p in self.dir.glob(".probe-*.lock")]
        self.assertEqual(len(names), 2)
        self.assertFalse(any(n in (".probe-A.lock", ".probe-B.lock") for n in names))


if __name__ == "__main__":
    unittest.main()
