"""AICoop P3（「请求」页，阶段 6）补的几条：均速取中位数、慢请求第二档、Scroll Fade、读失败表头变暗、速度读不到只写「—」。

纯逻辑走 node 直接加载 `requests.ts`（零 import）；渲染走真 bundle（harness 3304）。
"""
import json
import shutil
import subprocess
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PURE = ROOT / "codexbar" / "src" / "requests.ts"
HARNESS = "http://127.0.0.1:3304"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _node(expr):
    script = ("import('file://%s').then(m => { const R = (o) => Object.assign({key:'k',platform:'codex',t_start:null,t_end:1,model:'m',"
              "source:'交互',session:null,session_title:null,account:null,input:1000,cached:0,output:10,reasoning:null,ttft_ms:null,"
              "gen_ms:null,total_ms:null,tool_ms:null,tps:null,est:false,session_req_n:null}, o); let v;"
              " try { v = (%s); } catch (e) { v = {__throw: String(e)}; } console.log(JSON.stringify(v === undefined ? null : v)); });"
              % (PURE.as_posix(), expr))
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip()]
    if not out:
        raise AssertionError(f"node 没有产出：{r.stderr[-600:]}")
    return json.loads(out[-1])


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class Logic(unittest.TestCase):
    def test_average_speed_is_the_median_like_the_backend(self):
        """★ 后端 `avg_tps` 是中位数（托盘 / 刘海读它）；前端原来算术平均 ⇒ 同一个「均速」两个数。
        夹具 10 / 20 / 90：中位 20、平均 40 —— 只有这种不对称的数据分得开两者。"""
        got = _node("m.dayMetrics([R({tps:10}), R({tps:20}), R({tps:90})])")
        self.assertEqual(got["avgTps"], 20)
        self.assertEqual(_node("m.dayMetrics([R({tps:10}), R({tps:30}), R({tps:90}), R({tps:100})])")["avgTps"], 60)
        self.assertEqual(_node("m.dayMetrics([R({tps:10}), R({tps:20}), R({tps:90}), R({tps:999, est:true})])")["avgTps"], 20,
                         "★ 估值行不进均速（用户 10-22）")
        self.assertIsNone(_node("m.dayMetrics([R({tps:50, est:true})])")["avgTps"], "全是估值 ⇒ 读不到，不是 0")
        self.assertIsNone(_node("m.dayMetrics([])")["avgTps"])

    def test_average_speed_rounds_like_python(self):
        """★ 中位数恰好落在 .x5 上时与后端 `round(_median, 1)` 同值（评审 P6-codex-3）。期望值由真 Python 算出来，不抄。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("rq", ROOT / "traffic" / "requests.py")
        rq = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rq)
        for xs in ([1, 10.2, 10.3, 100], [7.2, 7.3], [0.1, 0.4], [3.3, 3.4, 9]):
            with self.subTest(xs=xs):
                got = _node("m.dayMetrics([%s])" % ",".join("R({tps:%r})" % x for x in xs))["avgTps"]
                self.assertEqual(got, round(rq._median(xs), 1))

    def test_slow_speed_only_for_measured_rows(self):
        self.assertEqual(_node("m.slowWhy(R({tps:7.25}))"), "慢请求：速度 7.3 t/s，低于 10 t/s。")
        self.assertIsNone(_node("m.slowWhy(R({tps:7, est:true}))"), "★ 估值是下限，判慢会误报")
        self.assertIsNone(_node("m.slowWhy(R({tps:null}))"), "★ 读不到不是慢")
        self.assertIsNone(_node("m.slowWhy(R({tps:12}))"))
        self.assertIn("首字等了 31.0 s", _node("m.slowWhy(R({tps:3, ttft_ms:31000}))"), "首字档优先")


def _harness_up():
    try:
        urllib.request.urlopen(HARNESS + "/harness.html", timeout=2)
        return True
    except Exception:
        return False


@unittest.skipUnless(_harness_up() and Path(CHROME).exists(), "harness 没在跑 —— skip 不是绿")
class Rendered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def _page(self, q="", w=1200, h=760):
        pg = self.br.new_page(viewport={"width": w, "height": h})
        pg.goto(f"{HARNESS}/harness.html?nav=requests{q}")
        pg.wait_for_selector("[data-req-row]", timeout=15000)
        pg.wait_for_timeout(400)
        self.addCleanup(pg.close)
        return pg

    FADES = "() => ({ top: document.querySelector('[data-req-fade=top]').dataset.on, bot: document.querySelector('[data-req-fade=bot]').dataset.on," \
            " over: (s => s.scrollHeight > s.clientHeight + 2)(document.querySelector('[data-req-scroll]')) })"

    def test_scroll_fade_follows_the_real_scroll_position(self):
        pg = self._page()
        a = pg.evaluate(self.FADES)
        self.assertTrue(a["over"], "夹具没溢出 —— 底部渐隐验不到")
        self.assertEqual((a["top"], a["bot"]), ("0", "1"), "★ 顶上还能往上滚吗？没有 ⇒ 顶部渐隐不该亮")
        pg.evaluate("() => { const s = document.querySelector('[data-req-scroll]'); s.scrollTop = s.scrollHeight; }")
        pg.wait_for_timeout(200)
        b = pg.evaluate(self.FADES)
        self.assertEqual((b["top"], b["bot"]), ("1", "0"), "★ 滚到底：顶部该亮、底部该灭")

    def test_short_list_has_no_bottom_fade(self):
        """★ 画板初值 `scB:1`：不溢出时底部渐隐也亮着 —— 这里按实际尺寸算。"""
        pg = self._page()
        assert pg.evaluate(self.FADES)["bot"] == "1", "长列表先亮着（已知阳性）"
        pg.click("[data-req-filter=grok]")       # 夹具里 grok 只有几条 ⇒ 不溢出
        pg.wait_for_timeout(250)
        a = pg.evaluate(self.FADES)
        self.assertFalse(a["over"], "筛到 grok 仍溢出 —— 这条判不了")
        self.assertEqual((a["top"], a["bot"]), ("0", "0"), "★ 换数据后没重量：不溢出的列表还亮着底部渐隐")

    def test_fade_follows_a_resize(self):
        pg = self._page()
        assert pg.evaluate(self.FADES)["bot"] == "1"
        pg.set_viewport_size({"width": 1200, "height": 2600})
        pg.wait_for_timeout(300)
        a = pg.evaluate(self.FADES)
        self.assertFalse(a["over"], "放大到 2600 高仍溢出 —— 这条判不了")
        self.assertEqual(a["bot"], "0", "★ 窗口变高后不再溢出，底部渐隐还亮着（ResizeObserver 没接上）")

    def test_unknown_speed_is_a_bare_dash(self):
        pg = self._page()
        cells = pg.evaluate("() => [...document.querySelectorAll('[data-req-row]')].map(r => r.children[7].textContent.trim())")
        dash = [c for c in cells if c.startswith("—")]
        self.assertTrue(dash, "夹具里没有速度读不到的行 —— 闸没有判别力")
        self.assertTrue(all(c == "—" for c in dash), f"★ 读不到写成了带单位的 {dash[:2]}")
        self.assertTrue(any(c.endswith("t/s") for c in cells), "读到的速度丢了单位")

    def test_stale_dims_the_header_too(self):
        pg = self._page("&req=stale")
        pg.wait_for_selector("[data-req-banner]", timeout=8000)
        op = pg.evaluate("() => getComputedStyle(document.querySelector('[data-req-head] > span')).opacity")
        self.assertEqual(op, "0.55")
