"""`agy-rotate quota` 联网之后的写回不许回滚别人期间写的字段（全方面评审 2026-10-22，GPT + Gemini，Opus 复核）。

原实现：锁外 `P.load()` 整池 → 并行取额度十几秒 → `P.save(pool)` 整份落盘。期间终端 / `bin/agy` wrapper
写的置顶、停轮换、切号、增删号全被回滚；丢掉的 `rotate_off` 会让定时探针和自动切号再去用这个号。
现在：`P.merge_back` 锁内重读，只合并本命令改过的字段；期间删掉的号不复活。

真池文件放临时目录（`AGY_POOL_STORE`）；联网（`_refresh_one` / `fetch_quota`）打桩，钥匙串由 `_isolation` 关掉。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class QuotaMergesBack(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cbx_agyq_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        old = {k: os.environ.get(k) for k in ("AGY_POOL_STORE", "CODEXBAR_QUOTA_ANCHORS", "AGY_USAGE_REPORT")}
        os.environ.update(AGY_POOL_STORE=self.dir, AGY_USAGE_REPORT="0",
                          CODEXBAR_QUOTA_ANCHORS=os.path.join(self.dir, ".quota-anchors.json"))
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in old.items()])
        import agy.pool as P
        self.P = importlib.reload(P)
        self.addCleanup(importlib.reload, P)
        self.assertEqual(str(self.P.POOL.parent), self.dir, "夹具没隔离 —— 会写真池")
        loader = importlib.machinery.SourceFileLoader("agy_rotate_merge", str(ROOT / "agy-rotate"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.cli = importlib.util.module_from_spec(spec)
        loader.exec_module(self.cli)
        self.cli.P = self.P
        self.cli._log = lambda m: None
        self.cli._mark_live = lambda pool: "A"
        self.cli._refresh_one = lambda sub, a, pool, skew=120: ({"token": {"access_token": "t-" + sub}}, "")
        self.during = None
        groups = [{"displayName": "Gemini Models", "buckets": [
            {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 0.5, "resetTime": None}]}]

        def fetch(tok, anchor=None):
            if self.during:
                fn, self.during = self.during, None
                fn()
            return groups, ""
        self.P.fetch_quota = fetch
        self.P.fetch_tier = lambda tok: (None, "stub")   # 档位读取是联网的；不打桩就真打 Google
        self.P.save({"accounts": {"A": {"label": "a"}, "B": {"label": "b"}, "C": {"label": "c"}}})

    def disk(self):
        return json.loads(self.P.POOL.read_text())

    def concurrently(self, fn):
        def run():
            with self.P._lock(self.P.POOL):
                p = self.P.load()
                fn(p)
                self.P.save(p)
        self.during = run

    def quota(self):
        with redirect_stdout(io.StringIO()):
            self.cli.cmd_quota(["--json"])

    def test_known_positive_the_reading_lands(self):
        self.quota()
        self.assertEqual(self.disk()["accounts"]["B"]["quota"]["gemini"]["remaining"], 0.5)

    def test_a_pause_and_a_pin_written_meanwhile_survive(self):
        def f(p):
            p["accounts"]["B"]["rotate_off"] = True
            p["pinned"] = ["C"]
        self.concurrently(f)
        self.quota()
        d = self.disk()
        self.assertTrue(d["accounts"]["B"].get("rotate_off"), "★ 期间停的轮换被整份回滚")
        self.assertEqual(d.get("pinned"), ["C"], "★ 期间的置顶被整份回滚")
        self.assertIsNotNone(d["accounts"]["B"].get("quota"), "这次读数本身要落盘")

    def test_an_account_removed_meanwhile_stays_removed(self):
        self.concurrently(lambda p: p["accounts"].pop("C"))
        self.quota()
        self.assertNotIn("C", self.disk()["accounts"], "★ 期间删掉的号被写回来了")


if __name__ == "__main__":
    unittest.main()
