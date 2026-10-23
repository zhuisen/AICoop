"""请求页增量合并（用户 2026-10-23「增量显示，而不是再全量加载」）：`requests.ts::mergePayload` / `sinceOf`。

跑真文件（`node --experimental-strip-types`，`requests.ts` 零 import）。实测：两天 9490 行整读 4.7 MB，增量一次 20 KB（n=1）。
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

TS = (Path(__file__).resolve().parents[1] / "codexbar" / "src" / "requests.ts").as_posix()
NODE = shutil.which("node")


def _row(key, t, out=10):
    return {"key": key, "platform": "codex", "t_end": t, "output": out}


def _pay(rows, partial, ws=1000.0, ok=True):
    return {"ok": ok, "requests": rows, "days": {}, "window_start": ws, "partial": partial}


def _run(expr):
    js = "import('file://%s').then(m => { const P = (x) => m.parsePayload(x); console.log(JSON.stringify(%s)); })" % (TS, expr)
    r = subprocess.run([NODE, "--experimental-strip-types", "--no-warnings", "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(NODE, "没有 node")
class MergeByKey(unittest.TestCase):
    def merge(self, prev, nxt):
        got = _run("m.mergePayload(P(%s), P(%s))" % (json.dumps(prev), json.dumps(nxt)))
        return [(r["key"], r["output"]) for r in got["requests"]], got["partial"]

    def test_partial_overrides_by_key_appends_and_sorts(self):
        rows, partial = self.merge(_pay([_row("a", 1100), _row("b", 1200)], False),
                                   _pay([_row("b", 1200, out=99), _row("c", 1300)], True))
        self.assertEqual(rows, [("c", 10), ("b", 99), ("a", 10)], "★ 新行并进来、同 key 新值覆盖、按时间倒序")
        self.assertFalse(partial, "合并后的是全部")

    def test_rows_older_than_the_window_are_dropped(self):
        rows, _ = self.merge(_pay([_row("old", 900), _row("a", 1100)], False), _pay([_row("c", 1300)], True, ws=1000))
        self.assertEqual([k for k, _ in rows], ["c", "a"], "★ 滑出窗口的旧行要剪掉，不然列表只增不减地变长")

    def test_a_full_payload_replaces(self):
        rows, _ = self.merge(_pay([_row("a", 1100), _row("b", 1200)], False), _pay([_row("c", 1300)], False))
        self.assertEqual([k for k, _ in rows], ["c"], "整读 = 全部，以它为准")

    def test_since_is_the_newest_row_in_seconds(self):
        self.assertEqual(_run("m.sinceOf(P(%s))" % json.dumps(_pay([_row("a", 1100), _row("b", 1250.5)], False))), 1250.5)
        self.assertIsNone(_run("m.sinceOf(P(%s))" % json.dumps(_pay([], False))), "手里没有 ⇒ 读全部")


class TheHookUsesTheIncrementalPath(unittest.TestCase):
    def test_wiring(self):
        src = (Path(TS).parent / "hooks" / "useRequests.ts").read_text(encoding="utf-8")
        code = "\n".join(l for l in src.split("\n") if not l.lstrip().startswith(("//", "*", "/*")))
        self.assertIn('invoke<string>("read_requests", { since })', code, "★ 轮询要带 since")
        self.assertIn("mergePayload(held.current, p)", code, "★ 收到的一段要并进手里那份")
        self.assertRegex(code, r"sinceFull\.current >= FULL_EVERY", "隔一段时间整读一次兜底")


if __name__ == "__main__":
    unittest.main()
