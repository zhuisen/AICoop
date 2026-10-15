"""拖窗口时少干活（2026-10-15 三方评审第 2 步 + 第 3 步①；用户选 ①）。

用户原话：「放大和缩小页面的尺寸，整个变化的流畅性不行，ui 转变也不好」。
三方一致的根因之一：ResizeObserver 回调里逐像素 setState / 强制同步布局。

## 守的
1. 图表高度向下取到 4px —— 拖 40px 只重画 ~10 次，且永远不高于容器（向上取会溢出，一屏页面的根开始滚）。
2. KPI 条拖窗口时**不再**逐格 `getComputedStyle`（每格的单位宽只随内容/字体变，量一次缓存）。
3. 续航色带只在「哪几段写得下名字」翻转时重渲染（签名比较）。
4. 顶栏全名/短名：当前档存 ref（不再每次翻档拆 RO 重建），回全名要多 16px 余量（临界点来回拖不翻）。
5. zoom 的去抖与滞回在 Rust（`zoom_tests` + `test_window_zoom.py`）。
⚠️ 帧率、pageZoom 跳变只能 WKWebView 真机量；这里守的是「工作量」与「判据」，不是流畅度。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import re
import subprocess
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness.html"


def node(mod, expr):
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                        "import('%s').then(m => console.log(JSON.stringify(%s)))" % ((SRC / mod).as_posix(), expr)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def code(rel):
    s = (SRC / rel).read_text(encoding="utf-8")
    s = re.sub(r"\{/\*.*?\*/\}", "", s, flags=re.S)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)


class PureJudgements(unittest.TestCase):
    def test_fill_height_rounds_down_to_4(self):
        self.assertEqual(node("hooks/useFillHeight.ts", "[0,3,4,7,157,160].map(x => m.quantizeDown(x))"),
                         [0, 0, 4, 4, 156, 160], "★ 必须向下取：向上取图表会比容器高 1–3px")

    def test_header_needs_slack_to_come_back(self):
        r = node("hooks/useOneRowHeader.ts",
                 "[m.nextCompact(true, 400, 910, 900), m.nextCompact(true, 400, 915, 900), m.nextCompact(true, 400, 916, 900)]")
        self.assertEqual(r, [True, True, False], "★ 紧凑态回全名要多出 16px 余量，否则临界点来回拖就来回翻")

    def test_runway_signature_only_tracks_which_names_fit(self):
        items = '[[50,"Egan"],[5,"qq55"],[10,"不可用 2"]]'
        r = node("runwayFit.ts", "[300, 301, 600, 0].map(w => m.fitSignature(%s, 65, w))" % items)
        self.assertEqual(r[0], r[1], "★ 差 1px 签名不该变 —— 否则还是逐像素重渲染")
        self.assertNotEqual(r[0], r[2])
        self.assertEqual(r[3], "000", "量不到宽度时一个名字都不写")
        self.assertEqual(node("runwayFit.ts", 'm.segFits(5, 65, 300, "qq55")'), False)


class TheCodeIsWiredThatWay(unittest.TestCase):
    def test_runway_hero_sets_width_only_when_the_signature_flips(self):
        s = code("components/RunwayHero.tsx")
        self.assertRegex(s, r"if \(sig !== last\) \{ last = sig; setBarW\(w\); \}")
        self.assertEqual(len(re.findall(r"setBarW\(", s)), 1, "★ 别处又直接 setBarW 了")
        self.assertIn("Math.max(e.weekly ?? 1, 5), e.label", s, "★ 签名用的段权重必须与渲染同一组")

    def test_header_effect_does_not_depend_on_compact(self):
        s = code("hooks/useOneRowHeader.ts")
        self.assertIn("}, [gap, ...deps]);", s, "★ compact 回到依赖里 = 每次翻档拆 RO 重建")


def _measure():
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(BASE, timeout=2).read(1)
    except Exception:
        return None
    init = """(() => { window.__gcs = 0; const o = window.getComputedStyle;
      window.getComputedStyle = function () { if ((new Error().stack || '').includes('/assets/')) window.__gcs++;
        return o.apply(this, arguments); }; })()"""
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = br.new_page(viewport={"width": 1000, "height": 900})
        pg.add_init_script(init)
        pg.goto(BASE + "?nav=traffic", timeout=30000)
        pg.wait_for_timeout(2000)
        chart = "[...document.querySelectorAll('svg[viewBox]')].find(s => s.viewBox.baseVal.width > 200)"
        pg.evaluate("""() => { window.__vb = 0; window.__gcs = 0; const c = %s;
          new MutationObserver(ms => { window.__vb += ms.length; })
          .observe(c, {attributes: true, attributeFilter: ['viewBox']}); }""" % chart)
        h0 = pg.evaluate("() => (%s).viewBox.baseVal.height" % chart)
        for i in range(1, 41):
            pg.set_viewport_size({"width": 1000 + i * 3, "height": 900 + i})
            pg.wait_for_timeout(30)
        pg.wait_for_timeout(300)
        out = pg.evaluate("""() => { const s = %s;
          return { vb: window.__vb, gcs: window.__gcs, h: s.viewBox.baseVal.height }; }""" % chart)
        out["h0"] = h0
        br.close()
    return out


M = _measure()


@unittest.skipIf(M is None, "harness 3304 没起 / 无 playwright —— 这是 skip 不是绿")
class OnTheRealBundle(unittest.TestCase):
    def test_chart_redraws_every_4px_not_every_px(self):
        self.assertGreater(M["h"], M["h0"], "夹具下图表没长高 —— 证不到节流（断言打空）")
        self.assertLessEqual(M["vb"], 12, "★★ 拖 40px 图表重画了 %d 次 —— 还是逐像素" % M["vb"])

    def test_kpi_strip_does_not_force_layout_while_dragging(self):
        self.assertEqual(M["gcs"], 0, "★★ 拖窗口时 bundle 里调了 %d 次 getComputedStyle（强制同步布局）" % M["gcs"])


if __name__ == "__main__":
    unittest.main()
