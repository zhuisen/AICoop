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
        self.assertEqual(node("resizeMath.ts", "[0,3,4,7,157,160].map(x => m.quantizeDown(x))"),
                         [0, 0, 4, 4, 156, 160], "★ 必须向下取：向上取图表会比容器高 1–3px")

    def test_header_mode_is_a_pure_function_of_content_width(self):
        """★ 2026-10-19 **改写**：头部全名 / 短名不再「量了自己再判」（`useOneRowHeader` + `nextCompact`
        的 16px 死区，随交接包 page5 一起删除），而由 `ovLayout(内容区宽)` 直接给 —— 判据不读头部自己的宽度，
        所以没有反馈环、也就不需要死区。守的是同一件事：同一宽度永远同一结果。"""
        r = node("overview.ts", "[1099, 1100, 1100, 899, 900].map(w => m.ovLayout(w).labels)")
        self.assertEqual(r, [False, True, True, False, False])
        self.assertNotIn("nextCompact", code("resizeMath.ts"), "★ 删掉的判据又回来了却没人用它")

    def test_runway_signature_only_tracks_which_names_fit(self):
        items = '[[50,"Egan"],[5,"qq55"],[10,"不可用 2"]]'
        r = node("runwayFit.ts", "[300, 301, 600, 0].map(w => m.fitSignature(%s, 65, w))" % items)
        self.assertEqual(r[0], r[1], "★ 差 1px 签名不该变 —— 否则还是逐像素重渲染")
        self.assertNotEqual(r[0], r[2])
        self.assertEqual(r[3], "000", "量不到宽度时一个名字都不写")
        self.assertEqual(node("runwayFit.ts", 'm.segFits(5, 65, 300, "qq55")'), False)


class TheCodeIsWiredThatWay(unittest.TestCase):
    def test_relay_bar_rerenders_only_when_the_signature_flips(self):
        """2026-10-19：续航条从 RunwayHero 换成 `ov/OvHero::RelayBar`，同一条规矩照搬。"""
        s = code("components/ov/OvHero.tsx")
        self.assertRegex(s, r"if \(sig !== last\) \{ last = sig; setSig\(sig\); \}")
        self.assertEqual(len(re.findall(r"setSig\(", s)), 1, "★ 别处又直接 setState 了")
        self.assertNotRegex(s, r"new ResizeObserver\(\(\) => setW\(", "★ 又成了每像素 setState")
        self.assertIn("fitSignature(items.current, 100, wRef.current, 11)", s)
        self.assertIn("segFits(b.width, 100, w, s.label ?? \"\", 11)", s, "★ 签名与渲染必须同一组权重 / 字号")

    def test_overview_layout_effect_has_no_deps(self):
        s = code("components/ov/Overview.tsx")
        self.assertRegex(s, r"new ResizeObserver\(\(\) => setCw\(ovBand\(el\.clientWidth\)\)\);[\s\S]{0,160}\}, \[\]\);",
                         "★ 版式 RO 带了依赖 = 每次翻档拆 RO 重建")
        self.assertEqual(len(re.findall(r"setCw\(", s)), 2, "★ 别处直接存原始宽度 —— 拖一路整页每像素重渲染")
        self.assertEqual(node("overview.ts", "[0, 899, 900, 1099, 1100, 2000].map(m.ovBand)"), [0, 0, 900, 900, 1100, 1100])
        self.assertEqual(node("overview.ts", "[0, 899, 900, 1099, 1100, 2000].map(w => JSON.stringify(m.ovLayout(m.ovBand(w))) === JSON.stringify(m.ovLayout(w)))"),
                         [True] * 6, "★ 档下沿必须与原宽度给出同一版式")


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
