"""`codex-rotate next --json` 的窗口与 `helpers.ts::winRem` 同一条规则（2026-10-21 复查 B2）：
过了重置点、读数又拍在重置点之前 ⇒ 那个「已用」属于旧窗口 ⇒ 读不到（不参与 tightest）。
否则顶部「正在使用」画旧数，卡片环已判成未知 —— 同一个号三处三个数。

只读夹具：`_state` 打桩，不碰真 state.json，不发请求。"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_ld = importlib.machinery.SourceFileLoader("_cr_next_reset", str(ROOT / "codex-rotate"))
CR = importlib.util.module_from_spec(importlib.util.spec_from_loader(_ld.name, _ld))
_ld.exec_module(CR)


def _slot(label, five, week, captured_at):
    return {"label": label, "plan": "plus", "quota": {"captured_at": captured_at, "source": "usage-api",
            "primary": {"used_percent": five[0], "window_minutes": 300, "resets_at": five[1]},
            "secondary": {"used_percent": week[0], "window_minutes": 10080, "resets_at": week[1]}}}


class NextDropsWindowsPastReset(unittest.TestCase):
    def run_next(self, slots, last="A"):
        st = {"slots": slots, "last_aid": last}
        buf = io.StringIO()
        with mock.patch.object(CR, "_state", return_value=st), contextlib.redirect_stdout(buf):
            CR.cmd_next(["--json"])
        return json.loads(buf.getvalue())

    def test_a_reading_taken_before_the_reset_is_unknown(self):
        now = time.time()
        out = self.run_next({"A": _slot("A", (57, now - 600), (21, now + 3 * 86400), now - 1200)})
        cur = out["cur"]
        self.assertEqual([w["label"] for w in cur["wins"]], ["周"], "★★ 5h 过了重置点、读数更早 ⇒ 不该还在")
        self.assertEqual(cur["tightest"], 79, "tightest 只剩周窗口（不是旧 5h 的 43）")

    def test_a_reading_taken_after_the_reset_still_counts(self):
        now = time.time()
        out = self.run_next({"A": _slot("A", (5, now - 600), (21, now + 3 * 86400), now - 60)})
        self.assertEqual(sorted(w["label"] for w in out["cur"]["wins"]), ["5h", "周"],
                         "读数拍在重置之后 ⇒ 属于新窗口，照用")
        self.assertEqual(out["cur"]["tightest"], 79)

    def test_a_window_still_running_is_untouched(self):
        now = time.time()
        out = self.run_next({"A": _slot("A", (57, now + 9000), (21, now + 3 * 86400), now - 60)})
        self.assertEqual(out["cur"]["tightest"], 43)


if __name__ == "__main__":
    unittest.main()
