"""刘海屏版空闲额度格子（AICoop 交接包 2026-10-21 · `11_idle/P11_NotchHover`）的闸。

画板：空闲时光标进刘海「靠近」区（左右 60、向下 32）亮中性白光晕；停在刘海上 180 ms 展开额度格子
（与托盘悬停面板同一份数据）；有一家 < 10% 时右肩叠珊瑚红 + 小红点；有 AI 在跑时照旧走 4e 卡片。
进出 / 停留判定在 Rust `notch.rs`（`closed_step` / `in_near` / `on_notch` 单测）；这里守网页那半：

  ① `notchIdle.ts` 行为（node 直接跑零 import 模块）：版面 ÷1.5、光晕不透明度 / 过渡、点格子去哪；
  ② 真 bundle 的 `--dump-dom`（harness 127.0.0.1:3304，跑不到就 skip 不是绿）：`?nt=I` 场景。

不碰凭证；harness 用的是脱敏夹具。
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "codexbar" / "src" / "notchIdle.ts"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness-notch.html?notrans=1"


def node(expr):
    js = "import('%s').then(m => console.log(JSON.stringify(%s)))" % (MOD.as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", js],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class TheBoardDividedByOnePointFive(unittest.TestCase):
    def test_four_cells_in_one_row_of_a_300_panel(self):
        g = node("m.notchGrid(4)")
        self.assertEqual(g["cw"], 69, "(300 − 2×6 − 3×4) / 4")
        self.assertEqual([p["x"] for p in g["pos"]], [6, 79, 152, 225])
        self.assertEqual(g["h"], 6 + 74.5 + 6)

    def test_eight_cells_make_two_rows_and_none_make_no_panel(self):
        self.assertEqual(node("m.notchGrid(8).h"), 6 + 74.5 * 2 + 4 + 6)
        self.assertEqual(node("m.notchGrid(8).pos[4]"), {"x": 6, "y": 6 + 74.5 + 4})
        self.assertEqual(node("m.notchGrid(0).h"), 0)

    def test_panel_width_is_the_4e_card_width(self):
        """★ Rust 命中区按 `CARD_W` 算（空闲格子直接复用），两边不一致 = 面板的一侧点不到 / 移出去不收。"""
        self.assertEqual(node("m.PANEL_W"), 300)
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "notch.rs").read_text(encoding="utf-8")
        self.assertRegex(rs, r"pub const CARD_W: f64 = 300\.0;")


class TheNeutralGlow(unittest.TestCase):
    def test_opacity_follows_near_open_lit_and_reduce(self):
        def c(lit=False, reduce=False, near=False, idleOpen=False, cardOpen=False):
            return {"lit": lit, "reduce": reduce, "near": near, "idleOpen": idleOpen, "cardOpen": cardOpen}
        cases = [
            (c(), 0),
            (c(near=True), 1),
            (c(near=True, idleOpen=True), 0.55),
            (c(idleOpen=True), 0.55),
            (c(lit=True, idleOpen=True), 0.55),
            (c(lit=True, near=True), 0),
            (c(near=True, cardOpen=True), 0),
            (c(reduce=True, near=True), 0),
            (c(reduce=True, idleOpen=True), 0),
        ]
        got = node("[%s].map(m.idleGlowOpacity)" % ",".join(json.dumps(c) for c, _ in cases))
        self.assertEqual(got, [v for _, v in cases],
                         "空闲格子开着 55%（中途开跑也不变）、4e 开着不亮、收起时只有空闲且靠近才亮、减弱动态效果不显示")

    def test_fades_in_at_once_and_out_after_300ms(self):
        self.assertEqual(node("[m.idleGlowTransition(1), m.idleGlowTransition(0.55), m.idleGlowTransition(0)]"),
                         ["opacity 200ms ease-out 0ms", "opacity 200ms ease-out 0ms", "opacity 200ms ease-out 300ms"])

    def test_the_coral_shoulder_is_only_there_when_low(self):
        lo, ok = node("[m.idleGlowShadow(true), m.idleGlowShadow(false)]")
        self.assertIn("rgba(255,138,115,.55)", lo)
        self.assertNotIn("255,138,115", ok)
        self.assertIn("rgba(233,237,243,.30)", ok)


class WhereACellGoes(unittest.TestCase):
    def test_four_overviews_and_usage_details_for_metered(self):
        self.assertEqual(node("['codex','claude','agy','grok','kimi','deepseek'].map(k => m.cellTarget(k).page)"),
                         ["overview"] * 4 + ["traffic"] * 2)


# ── ② 真 bundle ──────────────────────────────────────────────────────────

def _harness_up():
    try:
        urllib.request.urlopen(BASE, timeout=3).read(64)
        return Path(CHROME).exists()
    except Exception:                               # noqa: BLE001
        return False


_CACHE = {}


def dom(query, budget=3000, scene="I"):
    """★ 场景走形参：`URLSearchParams.get` 取第一个同名参数，在 query 里再拼一个 `nt=` 不会生效（verification ⑨）。"""
    query = "&nt=%s%s" % (scene, query)
    key = (query, budget)
    if key in _CACHE:
        return _CACHE[key]
    prof = tempfile.mkdtemp(prefix="notchidle-")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--use-mock-keychain", "--disable-gpu",
                            "--user-data-dir=" + prof, "--window-size=500,700",
                            "--virtual-time-budget=%d" % budget, "--dump-dom", BASE + query],
                           capture_output=True, text=True, timeout=90)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    h = re.sub(r"<script[\s\S]*?</script>", "", r.stdout)
    if "data-notch-idle" not in h or "data-nt-idle" not in h:
        raise AssertionError("空闲格子没渲染出来（没有 data-notch-idle / data-nt-idle）—— 零渲染不是通过")
    _CACHE[key] = h
    return h


def body_json(h, name):
    m = re.search(r'%s="([^"]*)"' % name, h)
    assert m, "body 上没有 %s" % name
    return json.loads(unescape(m.group(1)))


@unittest.skipUnless(_harness_up(), "harness 3304 没起 / 没有 Chrome —— 这是 skip 不是绿")
class OnTheRealBundle(unittest.TestCase):
    def test_idle_open_shows_the_grid_not_the_4e_card(self):
        h = dom("")
        i = body_json(h, "data-nt-idle")
        self.assertEqual((i["x"], i["y"], i["w"], i["h"], i["op"]), ((179 - 300) / 2, 42, 300, 86.5, 1),
                         "面板在刘海下沿下 10 pt、居中、300 × 86.5、看得见")
        self.assertEqual([c["k"] for c in i["cells"]], ["codex", "claude", "agy", "grok"])
        self.assertEqual([round(c["w"], 2) for c in i["cells"]], [69] * 4)
        self.assertIn('data-notch-open="0"', h, "★ 空闲那种展开不许同时冒出 4e 卡片")
        self.assertEqual(body_json(h, "data-nt-errors"), [])

    def test_in_bar_cells_are_tinted_16_and_others_9(self):
        i = body_json(dom(""), "data-nt-idle")
        self.assertEqual([c["bg"].rsplit(",", 1)[1].strip(" )") for c in i["cells"]], ["0.16", "0.16", "0.16", "0.09"])


    def test_near_lights_the_neutral_glow_with_a_low_dot(self):
        i = body_json(dom("&ntopen=0&ntnear=1"), "data-nt-idle")
        self.assertEqual((i["glow"], i["op"], i["lowdot"]), (1, 0, True))
        i = body_json(dom("&ntopen=0&ntnear=1&ntcells=ok"), "data-nt-idle")
        self.assertEqual((i["glow"], i["lowdot"]), (1, False), "没有低额度 ⇒ 没有小红点")
        i = body_json(dom("&ntopen=0"), "data-nt-idle")
        self.assertEqual((i["glow"], i["lowdot"]), (0, False), "不靠近 ⇒ 不亮")

    def test_open_dims_the_glow_to_55(self):
        self.assertEqual(body_json(dom(""), "data-nt-idle")["glow"], 0.55)

    def test_reduce_motion_shows_no_glow(self):
        self.assertEqual(body_json(dom("&ntopen=0&ntnear=1&ntreduce=1"), "data-nt-idle")["glow"], 0)

    def test_clicking_a_cell_opens_that_platform_and_dismisses(self):
        for key, page in (("codex", "overview"), ("kimi", "traffic")):
            h = dom("&ntcells=8&ntpick=%s&ntat=1800" % key)
            self.assertIn("ntpick →命中 1", body_json(h, "data-nt-clicks"))
            em = [e for e in body_json(h, "data-nt-emit") if e["event"] == "open-main-page"]
            self.assertEqual([e["payload"] for e in em], [{"page": page, "platform": key}])
            self.assertIn("notch_dismiss={}", body_json(h, "data-nt-calls"))
            i = body_json(h, "data-nt-idle")
            self.assertEqual((i["op"], i["glow"]), (0, 0), "★ 点完真的收起，光晕不反跳到 100%")

    def test_running_keeps_the_4e_card_and_the_platform_glow(self):
        h = dom("", scene="A")
        i = body_json(h, "data-nt-idle")
        self.assertEqual((i["op"], i["glow"], i["runglow"]), (0, 0, 0.6), "在跑：格子不出现、中性光晕不亮、平台色光晕 60%")
        self.assertIn('data-notch-open="1"', h)

    def test_the_idle_grid_gets_no_platform_glow_and_the_4e_card_no_white_glow(self):
        self.assertEqual(body_json(dom(""), "data-nt-idle")["runglow"], 0)
        i = body_json(dom("&ntact=1"), "data-nt-idle")
        self.assertEqual((i["op"], i["glow"], i["runglow"]), (1, 0.55, 0),
                         "★ 空闲格子开着时 AI 开跑：格子与 55% 白光晕不变，平台色光晕不在格子头顶亮")
        i = body_json(dom("&ntnear=1", scene="B"), "data-nt-idle")
        self.assertEqual((i["glow"], i["lowdot"]), (0, False), "★ 4e 卡片开着（空闲、没开格子那种）不挂白光晕和小红点")

    def test_the_drip_retracts_while_the_idle_grid_is_open(self):
        self.assertEqual(body_json(dom("&ntcur=0,0"), "data-nt-idle")["drip"], "0",
                         "★ 展开后 Rust 不再推光标：果冻下垂必须按「任一种展开」收起，不能冻在最后一帧")

    def test_an_open_grid_that_runs_out_of_cells_closes_itself(self):
        h = dom("&ntempty=1")
        self.assertIn("notch_dismiss={}", body_json(h, "data-nt-calls"), "★ 不留一块看不见的展开命中区")
        self.assertIn('data-notch-open="0"', h)

    def test_each_kind_reports_its_own_height(self):
        calls = [json.loads(c.split("=", 1)[1]) for c in body_json(dom(""), "data-nt-calls") if c.startswith("notch_card_resize=")]
        self.assertIn({"h": 86.5, "mode": "idle"}, calls)
        self.assertTrue(any(c.get("mode") == "run" for c in calls), "4e 那份也照报（Rust 各存一份）")
        self.assertNotIn(0, [c["h"] for c in calls], "0 格不报高度")


if __name__ == "__main__":
    unittest.main()
