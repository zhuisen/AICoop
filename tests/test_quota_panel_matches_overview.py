"""悬浮面板（空闲托盘）与工作台总览的额度口径对齐（用户 2026-10-21「额度有问题…怀疑是数值有缓存问题，复查代码」）。

复查结论：没有「缓存不更新」那种 bug；对不上的是几处**口径分叉**，各一条闸：
  B1 面板的 Claude 5 分钟才读一次、光标靠近托盘也不补读 ⇒ 刚停手悬停，比总览旧最多 5 分钟；
  B3 面板的 agy 倒计时直接 fmtEta，没过「未启动」判定（总览走 agyResetText）；
  B4 grok 降级时面板丢了倒计时（总览退回 last_good.period_end）；
  B5 grok 上次读数过了周期末仍当作当前值（两处都画上周的 0%）；
  B7 agy 沿用的旧读数（seen_at）面板不降灰。
（B2 在 `test_next_drops_windows_past_reset.py`。）"""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "codexbar" / "src"


def strip_comments(s):
    s = re.sub(r"\{/\*[\s\S]*?\*/\}", "", s)
    s = re.sub(r"/\*[\s\S]*?\*/", "", s)
    return re.sub(r"(?m)(^|[^:\"'])//.*$", r"\1", s)


def node(mod, expr):
    js = "import('%s').then(m => console.log(JSON.stringify(%s)))" % ((SRC / mod).as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", js],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class GrokLastGoodExpiresWithItsPeriod(unittest.TestCase):
    def test_b5(self):
        a = "{last_good: {used_percent: 100, fetched_at: 0, period_end: %s}}"
        got = node("grok.ts", "[m.grokLastGoodRemPct(%s, 1000), m.grokLastGoodRemPct(%s, 1000),"
                              " m.grokLastGoodRemPct(%s, 1000), m.grokLastGoodRemPct({last_good: null}, 1000)]"
                   % (a % 2000, a % 1000, a % "null"))
        self.assertEqual(got, [0, None, 0, None],
                         "★★ 周期还没结束 ⇒ 照用；周期末已到 ⇒ 读不到（不是 0）；不知道周期末 ⇒ 照用")


class TheIdlePanelReadsLikeTheOverview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = strip_comments((SRC / "hooks" / "useIdleTray.ts").read_text(encoding="utf-8"))

    def test_b1_claude_is_read_as_often_as_the_overview_and_on_approach(self):
        self.assertIn("const CLAUDE_EVERY_MS = 60_000;", self.c, "面板的 Claude 读得比总览（60 s）慢")
        ov = strip_comments((SRC / "hooks" / "useClaudeQuota.ts").read_text(encoding="utf-8"))
        self.assertRegex(ov, r"60_?000", "总览那边的间隔变了 ⇒ 这条闸的前提要跟着核")
        self.assertRegex(self.c, r'listen<boolean>\("idle-near"[\s\S]{0,200}?dispatchEvent\(new Event\(NEAR_READ\)\)',
                         "★ 光标靠近托盘不补读 ⇒ 悬停看到的是旧数")
        self.assertRegex(self.c, r"const onNear = \(\) => \{[\s\S]{0,160}?readClaude\(\); readGrok\(\); readAgy\(\);",
                         "补读没读三家")

    def test_b3_agy_reset_goes_through_the_shared_rule(self):
        self.assertIn("agyResetText(a5).text", self.c, "★★ agy 倒计时没过「未启动」判定")
        self.assertNotRegex(self.c, r"fmtEta\(a5\.reset_at\)")

    def test_b4_grok_countdown_survives_a_degraded_read(self):
        self.assertIn("gNow === null ? g.last_good?.period_end : g.quota?.period_end", self.c)
        self.assertNotRegex(self.c, r"g\?\.quota\?\.period_end \? fmtEta", "降级时倒计时又只读 quota（那时是 null）")

    def test_b7_carried_agy_rows_are_dimmed(self):
        self.assertIn("agy: agyStale || a5?.seen_at != null", self.c)


if __name__ == "__main__":
    unittest.main()
