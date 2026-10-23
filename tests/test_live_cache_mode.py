"""「今日 token」跟设置里的缓存口径走（用户 2026-10-23「第三条改成跟设置走」）。

审查发现：悬停面板 / 菜单栏在跑条 / 刘海的「今日」用的是请求账本 `input + output` —— **恒含缓存**，且只有四家
（不含 Kimi / DeepSeek）；用量页按设置可以是「不含缓存读」，同一个「今日」两处差几十倍。
修法两半：
1. 实时快照在 `useLive` 出口按口径重塑一次（`live.ts::applyLiveCacheMode`），所有读 `tokens` 的入口跟着变；
   后端给出缓存读 / 写两项原料（`requests.py::_tok_sums`）。
2. 各处底栏的「今日」总数先取用量快照（全部 AI、已按口径），与菜单栏今日 Tab 同一个数；快照没到才退回 1。
"""
import json
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
LIVE = (SRC / "live.ts").as_posix()


def node(expr):
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                        "import('%s').then(m => console.log(JSON.stringify(%s)))" % (LIVE, expr)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


SNAP = json.dumps({
    "v": 1, "generated_at": 1,
    "platforms": {"claude": {"running": True, "n_sessions": 1, "tps": 50, "tokens_today": 1000,
                             "cache_read_today": 700, "cache_write_today": 200,
                             "sessions": [{"id": "s", "title": "t", "tps": 50, "tokens": 600, "cache_read": 400,
                                           "cache_write": 100, "last_t_end": 1, "active": True}]}},
    "today": {"tokens": 1500, "cache_read": 900, "cache_write": 250, "avg_tps": None, "n": 3}})


class TheSnapshotFollowsTheCacheMode(unittest.TestCase):
    def shaped(self, mode):
        return node("m.applyLiveCacheMode(m.parseLive(%s), %s)" % (json.dumps(SNAP), json.dumps(mode)))

    def test_full_is_unchanged(self):
        s = self.shaped("full")
        self.assertEqual((s["today"]["tokens"], s["platforms"]["claude"]["tokens_today"]), (1500, 1000))

    def test_no_read_drops_cache_read_everywhere(self):
        s = self.shaped("noRead")
        c = s["platforms"]["claude"]
        self.assertEqual(s["today"]["tokens"], 1500 - 900)
        self.assertEqual(c["tokens_today"], 1000 - 700)
        self.assertEqual(c["sessions"][0]["tokens"], 600 - 400, "★ 会话行（悬停面板 / 刘海 / 在跑条）也要跟")

    def test_none_drops_read_and_write(self):
        s = self.shaped("none")
        self.assertEqual(s["today"]["tokens"], 1500 - 900 - 250)
        self.assertEqual(s["platforms"]["claude"]["sessions"][0]["tokens"], 600 - 400 - 100)

    def test_running_rows_see_the_shaped_tokens(self):
        rows = node("m.runningRows(m.applyLiveCacheMode(m.parseLive(%s), 'noRead'))" % json.dumps(SNAP))
        self.assertEqual(rows[0]["tokens"], 200)

    def test_old_snapshot_without_cache_fields_degrades_to_full(self):
        old = json.loads(SNAP)
        old["today"].pop("cache_read"); old["today"].pop("cache_write")
        s = node("m.applyLiveCacheMode(m.parseLive(%s), 'none')" % json.dumps(json.dumps(old)))
        self.assertEqual(s["today"]["tokens"], 1500, "后端旧版没给原料 ⇒ 扣不了，照原数（不编）")


class TheWiringIsInOnePlace(unittest.TestCase):
    def test_use_live_reshapes_once(self):
        src = (SRC / "hooks" / "useLive.ts").read_text(encoding="utf-8")
        self.assertIn("applyLiveCacheMode(live, mode)", src)
        self.assertRegex(src, r"return \{ live: shaped, error \}")

    def test_footers_prefer_the_traffic_snapshot(self):
        hv = (SRC / "TpsHover.tsx").read_text(encoding="utf-8")
        self.assertIn("useTodayTotal()", hv)
        self.assertRegex(hv, r"todayTotal != null \? fmtTokens\(todayTotal\)")
        mb = (SRC / "MenuBar.tsx").read_text(encoding="utf-8")
        self.assertIn("todayTokens={today?.totalTok ?? live?.today.tokens ?? null}", mb)
        nh = (SRC / "NotchHud.tsx").read_text(encoding="utf-8")
        self.assertRegex(nh, r"today \? fmtTok\(today\.totalTok\) : live \? fmtTokens\(live\.today\.tokens\)")
        hook = (SRC / "hooks" / "useTodayTotal.ts").read_text(encoding="utf-8")
        self.assertIn("applyPlatformPrefs(applyCacheMode(traffic, mode), prefs)", hook)


if __name__ == "__main__":
    unittest.main()
