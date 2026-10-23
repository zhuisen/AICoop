"""总览「其余 · 按可用度」打开期间顺序不动 + 板子先画上次（用户 2026-10-23）。

- `overview.ts::stableOrder`：照上次画过的顺序；新出现的接在后面；已不在的消失。
- 冷启动先画上次的板子（`useRotationBoard` 读写 localStorage `aicoop_board_<source>`），置顶区不再先空后跳。
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS = (ROOT / "codexbar" / "src" / "overview.ts").as_posix()
NODE = shutil.which("node")


def _strip(src):
    return "\n".join(l for l in src.split("\n") if not l.lstrip().startswith(("//", "*", "/*", "{/*")))


@unittest.skipUnless(NODE, "没有 node")
class StableOrder(unittest.TestCase):
    def order(self, prev, items):
        js = ("import('file://%s').then(m => console.log(JSON.stringify(m.stableOrder(%s, %s, x => x))))"
              % (TS, json.dumps(prev), json.dumps(items)))
        r = subprocess.run([NODE, "--experimental-strip-types", "--no-warnings", "-e", js], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_keeps_the_drawn_order_when_numbers_change(self):
        self.assertEqual(self.order(["a", "b", "c"], ["c", "a", "b"]), ["a", "b", "c"], "★ 数字变了、新排序是 c a b，画面仍 a b c")

    def test_new_items_go_last_and_gone_items_vanish(self):
        self.assertEqual(self.order(["a", "b", "c"], ["d", "c", "a"]), ["a", "c", "d"])

    def test_no_previous_order_means_the_computed_one(self):
        self.assertEqual(self.order(None, ["c", "a", "b"]), ["c", "a", "b"])
        self.assertEqual(self.order([], ["c", "a"]), ["c", "a"])


class Wiring(unittest.TestCase):
    def test_overview_freezes_only_the_auto_rest_and_resets(self):
        src = _strip((ROOT / "codexbar" / "src" / "components" / "ov" / "Overview.tsx").read_text(encoding="utf-8"))
        self.assertIn('codexMode === "auto" && !p.preview ? freeze("codex", codexRest0', src)
        self.assertIn('agyMode === "auto" && !p.preview ? freeze("gemini", agyRest0', src)
        self.assertRegex(src, r"Date\.now\(\) - blurAt >= 60_000\) \{ frozen\.current = \{\}", "★ 失焦 ≥ 60 s 回来 = 下次打开，按新数字排")
        self.assertRegex(src, r"if \(frozenProv\.current !== prov\) \{[^}]*frozen\.current = \{\}", "★ 切档要重置")
        self.assertRegex(src, r"const setSortFor = \(k: string, m: SortMode\) => \{ frozen\.current = \{\};", "自己换排序要立刻生效")

    def test_board_is_seeded_from_and_written_to_the_cache(self):
        src = _strip((ROOT / "codexbar" / "src" / "hooks" / "useRotationBoard.ts").read_text(encoding="utf-8"))
        self.assertIn("localStorage.getItem(cacheKey)", src, "★ 冷启动先画上次的板子")
        self.assertIn("localStorage.setItem(cacheKey, raw)", src, "读成功才写缓存")


if __name__ == "__main__":
    unittest.main()
