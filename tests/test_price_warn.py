"""Token 消耗页「N 项价格待核」弱警告（用户 2026-10-22 #11）。

判据 `rates.ts::priceWarnings`：用过的模型里 ① 牌价备注「YYYY-MM-DD 后翻倍」那天已过 ② 没有牌价（走兜底价）。
认不出名字的占位（unknown / <synthetic>）本来就只能走兜底，不报。只读源码 + node 跑纯函数 + harness 真 bundle。
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATES = ROOT / "codexbar/src/rates.ts"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def node(expr):
    js = "import('%s').then(m => console.log(JSON.stringify(%s)))" % (RATES.as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def warns(used, today):
    return node("m.priceWarnings(%s, %s)" % (json.dumps([{"model": m, "platform": p} for m, p in used]), json.dumps(today)))


class PriceWarnings(unittest.TestCase):
    def test_promo_expires_the_day_after(self):
        used = [("gemini-4-argon-high", "agy")]
        self.assertEqual(warns(used, "2026-11-30"), [], "当天还在介绍价内")
        got = warns(used, "2026-12-01")
        self.assertEqual([(w["kind"], w["model"], w["date"]) for w in got], [("promo", "gemini-4-argon-high", "2026-11-30")])

    def test_unpriced_used_model_is_reported_placeholders_are_not(self):
        got = warns([("gpt-9-imaginary", "codex"), ("unknown", "agy"), ("<synthetic>", "claude"), ("", "codex")], "2026-10-22")
        self.assertEqual([(w["kind"], w["model"]) for w in got], [("unpriced", "gpt-9-imaginary")])

    def test_each_model_once_and_promo_first(self):
        got = warns([("zz-new", "codex"), ("gemini-4-argon", "agy"), ("zz-new", "codex"), ("gemini-4-argon", "agy")], "2026-12-05")
        self.assertEqual([w["key"] for w in got], ["promo:gemini-4-argon", "unpriced:zz-new"])

    def test_priced_model_without_promo_is_quiet(self):
        self.assertEqual(warns([("claude-opus-5-5", "claude")], "2030-01-01"), [])


def _reachable():
    try:
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2)
        return True
    except OSError:
        return False


@unittest.skipUnless(_reachable(), "harness 127.0.0.1:3304 不可达（先跑 make_harness.py 并起静态服务）")
class TheTokenPageShowsIt(unittest.TestCase):
    def test_weak_stack_renders_in_the_header_and_is_not_amber(self):
        prof = tempfile.mkdtemp(prefix="pricewarn-")
        try:
            r = subprocess.run([CHROME, "--headless=new", "--use-mock-keychain", "--disable-gpu", "--user-data-dir=" + prof,
                                "--window-size=1200,800", "--virtual-time-budget=4000", "--dump-dom",
                                "http://127.0.0.1:3304/harness.html?nav=traffic"], capture_output=True, text=True, timeout=90)
        finally:
            shutil.rmtree(prof, ignore_errors=True)
        h = re.sub(r"<script[\s\S]*?</script>", "", r.stdout)
        self.assertIn("data-token-page", h, "Token 消耗页没渲染出来")
        m = re.search(r'<span class="ov-xs"[^>]*data-price-warn="(\d+)"[^>]*style="([^"]*)"', h)
        if m is None and "data-price-warn" not in h:
            # 快照是本机真数据（2026-10-22 有 claude-haiku-5-5 无牌价）；哪天全有牌价了就没有阳性可验 —— 跳过，不假红
            self.skipTest("harness 快照里没有缺价 / 优惠到期的模型")
        self.assertIsNotNone(m, "价格待核堆叠的结构变了（找不到 data-price-warn + style）")
        self.assertGreaterEqual(int(m.group(1)), 1)
        self.assertIn("项价格待核", h)
        self.assertNotRegex(m.group(2).lower(), r"--xstx:\s*(#f5b544|#8a5a0e|#9a6512)", "弱警告不能染琥珀")


if __name__ == "__main__":
    unittest.main()
