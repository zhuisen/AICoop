"""一屏仪表盘（用户 2026-10-14：「最小的画面都能标题一行处理完，图表一个界面展示完」
+「智能调控一屏大小的，其他版块也要处理」，从两档 demo 里选的「仪表盘式一屏」）。

判据全是**量出来的**，在真 bundle 上跑（harness 静态服务 3304）：

① AI用量 / 平台详情：KPI 条**一行**、没有格子出框；页面根不滚；
   底部列表/模型表在**自己的框里滚**（证明是滚动不是裁切）；图表高度不低于改动前的固定值，
   大窗口下**长高**（证明是撑满不是写死）。
② KPI 只缩 hero 数字：标签 12.5px / 小字 11px 是 D 档定稿，**不许跟着缩**。
③ 比最小窗口还窄时退回换行 —— **缩到下限仍放不下就换行，绝不裁**。
④ 代理轮换：汇总条**整条**一行（放不下就整条挪到标题下面，不在内部折成竖排）；页面根不滚。
⑤ 中转站：表格最右一列不被卡片裁掉。
"""
import unittest
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:3304/harness.html?nav="
MIN_WIN = (860, 560)      # tauri.conf.json 的 minWidth/minHeight
BIG_WIN = (1440, 900)

KPI_JS = """() => {
  const s = document.querySelector('[data-kpi-fit]');
  if (!s) return null;
  const sr = s.getBoundingClientRect();
  // ★ 让出去的格子仍在 DOM 里（隐形 + 绝对定位），按「可见格」量，否则它的 top=0 会被数成第二行
  const dropped = [...s.querySelectorAll('[data-kpi-dropped]')].map(c => c.children[0].textContent);
  const cells = [...s.children].filter(c => !c.hasAttribute('data-kpi-dropped'));
  const rs = cells.map(c => c.getBoundingClientRect());
  const px = sel => [...s.querySelectorAll(sel)].map(e => parseFloat(getComputedStyle(e).fontSize));
  const droppedShown = [...s.querySelectorAll('[data-kpi-dropped]')].filter(c => getComputedStyle(c).visibility !== 'hidden').length;
  return {n: cells.length, fit: s.dataset.kpiFit, dropped, droppedShown,
          rows: new Set(rs.map(r => Math.round(r.top))).size,
          outside: rs.filter(r => r.left < sr.left - .5 || r.right > sr.right + .5).length,
          value: px('.cb-kpi-v'),
          label: cells.map(c => parseFloat(getComputedStyle(c.children[0]).fontSize)),
          sub: cells.filter(c => c.children[2]).map(c => parseFloat(getComputedStyle(c.children[2]).fontSize)),
          root: (() => { const p = s.parentElement; return p.scrollHeight - p.clientHeight; })()};
}"""
BOX_JS = """(sel) => { const e = document.querySelector(sel); if (!e) return null;
  return {h: e.clientHeight, over: e.scrollHeight - e.clientHeight, oy: getComputedStyle(e).overflowY}; }"""
SVG_JS = """() => Math.max(0, ...[...document.querySelectorAll('svg')]
  .map(s => s.getBoundingClientRect()).filter(r => r.width > 300).map(r => r.height))"""
CARDS_JS = """() => {
  const g = document.querySelector('[data-cards-grid]');
  if (!g) return null;
  let sc = g.parentElement;
  while (sc && !/(auto|scroll)/.test(getComputedStyle(sc).overflowY)) sc = sc.parentElement;
  const top = sc.getBoundingClientRect().top;
  // P5（2026-10-21）：网格里还有「置顶 / 其余」两条区段标签（整行），只量卡片
  const rs = [...g.children].filter(c => c.hasAttribute('data-aid')).map(c => c.getBoundingClientRect());
  const rowBottoms = [...new Set(rs.map(r => Math.round(r.bottom - top)))].sort((a, b) => a - b);
  const root = document.querySelector('.ov-root');
  return {n: rs.length, h: Math.round(rs[0].height), visible: sc.clientHeight, oy: getComputedStyle(sc).overflowY,
          rows: rowBottoms.length, root: root ? root.scrollHeight - root.clientHeight : null,
          fullRows: rowBottoms.filter(b => b <= sc.clientHeight + 1).length,
          name: g.querySelector('[data-card-name]') && parseFloat(getComputedStyle(g.querySelector('[data-card-name]')).fontSize)};
}"""
LOGS_JS = """() => {
  const st = document.querySelector('[data-rot-stats]');
  if (!st) return null;
  const head = st.parentElement, page = head.parentElement;
  const tops = [...st.children].map(c => Math.round(c.getBoundingClientRect().top));
  const others = [...head.children].filter(c => c !== st).map(c => Math.round(c.getBoundingClientRect().top + c.getBoundingClientRect().height / 2));
  return {mode: st.dataset.rotStats, statN: st.children.length, statRows: new Set(tops).size,
          otherSpread: Math.max(...others) - Math.min(...others),
          statsBelow: st.getBoundingClientRect().top >= Math.max(...[...head.children].filter(c => c !== st).map(c => c.getBoundingClientRect().bottom)) - 1,
          root: page.scrollHeight - page.clientHeight};
}"""
RELAY_JS = """() => {
  const h = [...document.querySelectorAll('span')].find(e => e.textContent.trim() === '日均实扣');
  if (!h) return null;
  const head = h.parentElement, card = head.parentElement;
  return {right: h.getBoundingClientRect().right, cardRight: card.getBoundingClientRect().right,
          headOver: head.scrollWidth - head.clientWidth,
          endpointW: head.children[1].getBoundingClientRect().width,
          headLines: (() => { const r = document.createRange(); r.selectNodeContents(head.children[1]);
                              return new Set([...r.getClientRects()].map(x => Math.round(x.top))).size; })(),
          rows: document.querySelectorAll('[data-relay]').length};
}"""


def _measure():
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(BASE + "home", timeout=2).read(1)
    except Exception:
        return None
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)

        def visit(key, nav, size, js, arg=None):
            pg = br.new_page(viewport={"width": size[0], "height": size[1]})
            pg.goto(BASE + nav, timeout=30000)
            pg.wait_for_timeout(2600)
            out[key] = {k: (pg.evaluate(v) if a is None else pg.evaluate(v, a)) for k, (v, a) in js.items()}
            pg.close()

        for name, nav, box in (("traffic", "traffic&tab=30d", "[data-traffic-list]"),
                               ("platform", "platform:claude", "[data-platform-table]")):
            for tag, size in (("min", MIN_WIN), ("big", BIG_WIN)):
                visit(f"{name}:{tag}", nav, size,
                      {"kpi": (KPI_JS, None), "box": (BOX_JS, box), "svg": (SVG_JS, None)})
        visit("traffic:tight", "traffic&tab=30d", (700, 560), {"kpi": (KPI_JS, None)})
        visit("traffic:narrow", "traffic&tab=30d", (640, 560), {"kpi": (KPI_JS, None)})
        for tag, size in (("min", MIN_WIN), ("big", BIG_WIN)):
            visit(f"home:{tag}", "home", size, {"cards": (CARDS_JS, None)})
        visit("logs:min", "logs", MIN_WIN, {"h": (LOGS_JS, None)})
        visit("logs:big", "logs", BIG_WIN, {"h": (LOGS_JS, None)})
        visit("relay:min", "relay", MIN_WIN, {"t": (RELAY_JS, None)})
        br.close()
    return out


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class OneScreenDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _measure()
        if cls.r is None:
            raise unittest.SkipTest("没有 playwright，或 harness 静态服务（3304）没在跑")

    def _kpi(self, key):
        k = self.r[key]["kpi"]
        self.assertIsNotNone(k, f"{key}: KPI 条压根没渲染 —— 探针沉默 ≠ 通过")
        self.assertGreaterEqual(k["n"], 6, f"{key}: KPI 只渲染了 {k['n']} 格")
        return k

    def test_kpi_is_one_row_and_nothing_sticks_out(self):
        for key in ("traffic:min", "platform:min", "traffic:big", "platform:big"):
            k = self._kpi(key)
            self.assertEqual(k["rows"], 1, f"{key}: KPI 折成了 {k['rows']} 行")
            self.assertEqual(k["outside"], 0, f"{key}: {k['outside']} 格伸出了 KPI 条")

    def test_max_share_gives_way_first(self):
        """用户 2026-10-14：「最小尺寸下，AI用量信息，去掉最大占比」—— 整格让出去，其余保持原字号。"""
        lo, hi = self._kpi("traffic:min"), self._kpi("traffic:big")
        self.assertEqual(lo["dropped"], ["最大占比"])
        self.assertEqual(lo["droppedShown"], 0, "让出去的格子还看得见（会叠在 KPI 条左上角）")
        self.assertEqual(set(lo["value"]), {29}, "让出最大占比后 860 宽应放得下原字号")
        self.assertEqual(hi["dropped"], [], "宽窗口下最大占比应在")
        self.assertEqual(hi["n"], 7)

    def test_only_the_hero_number_shrinks(self):
        k = self._kpi("traffic:tight")
        self.assertEqual(k["dropped"], ["最大占比"], "先让格子，再缩数字")
        self.assertLess(max(k["value"]), 29, "700 宽下 6 格 29px 放不下，这里没缩说明适配没生效")
        self.assertGreaterEqual(min(k["value"]), 20)
        self.assertEqual(set(k["label"]), {12.5}, "★ 标签 12.5px 是定稿，不许跟着缩")
        self.assertEqual(set(k["sub"]), {11}, "★ 小字 11px 是定稿（9px 时用户报过「没看到」）")
        self.assertEqual(set(self._kpi("traffic:big")["value"]), {29}, "大窗口下应保持原字号")

    def test_overview_cards_stay_148_and_the_box_scrolls(self):
        """★ 2026-10-19 **作废并改写**（PLAN §4 F5 · 需用户确认）。

        原判据（用户 2026-10-14「最小尺寸下，总览页面里面的账号卡片要缩小」）：860×560 下
        卡片换紧凑型、完整露出两排。交接包 page5 改成**卡片定高 148、任何宽度不变**（§5「卡片等高 148」），
        `useCardType` / `CARD_TYPE_COMPACT` 随旧卡一起删除。两者不能同时成立：
        实测 860×560 卡片区可见 270px，两排要 308px —— 第二排露出 110/148（74%）。

        守的仍是「一屏仪表盘」那条底线：页面根不滚、卡片区自己滚、第二排至少露出 2/3（看得出下面还有）；
        大窗口一屏放得下全部。"""
        lo, hi = self.r["home:min"]["cards"], self.r["home:big"]["cards"]
        self.assertIsNotNone(lo, "总览卡片没渲染")
        self.assertGreaterEqual(lo["n"], 4, "夹具卡片太少，证不到两排")
        self.assertEqual({lo["h"], hi["h"]}, {148}, "★★ 卡片不是定高 148（交接包 §5）")
        self.assertGreaterEqual(lo["fullRows"], 1)
        self.assertGreaterEqual(lo["visible"] - 148 - 12, 148 * 2 / 3, "★ 860×560 下第二排露出不到 2/3 —— 看不出下面还有")
        self.assertIn(lo["oy"], ("auto", "scroll"), "★★ 卡片区不滚 —— 装不下的那排被裁掉")
        self.assertLessEqual(lo["root"], 1, "★★ 总览页面根在滚")
        self.assertEqual(hi["fullRows"], hi["rows"], "大窗口下应一屏放下全部卡片")

    def test_below_the_minimum_it_wraps_instead_of_clipping(self):
        k = self._kpi("traffic:narrow")
        self.assertEqual(k["fit"], "wrap")
        self.assertGreater(k["rows"], 1)
        self.assertEqual(k["outside"], 0, "★★ 数字被裁比折行严重得多")

    def test_the_page_does_not_scroll_its_list_does(self):
        for key in ("traffic:min", "platform:min"):
            d = self.r[key]
            self.assertLessEqual(d["kpi"]["root"], 1, f"{key}: 页面根在滚（溢出 {d['kpi']['root']}px）")
            self.assertIsNotNone(d["box"], f"{key}: 底部框没渲染")
            self.assertIn(d["box"]["oy"], ("auto", "scroll"))
            self.assertGreater(d["box"]["over"], 0, f"{key}: 夹具下底部内容应多于一屏 —— 否则证不到它是滚而不是裁")

    def test_the_chart_fills_but_never_shrinks(self):
        for name, floor in (("traffic", 156), ("platform", 190)):
            lo, hi = self.r[f"{name}:min"]["svg"], self.r[f"{name}:big"]["svg"]
            self.assertGreaterEqual(lo, floor, f"{name}: 小窗口图表 {lo}px 低于改动前的 {floor}px")
            self.assertGreater(hi, lo, f"{name}: 大窗口下图表没长高（{lo} → {hi}），不是撑满")

    def test_rotation_summary_is_one_whole_line(self):
        lo, hi = self.r["logs:min"]["h"], self.r["logs:big"]["h"]
        self.assertIsNotNone(lo, "代理轮换的汇总条没渲染")
        self.assertGreaterEqual(lo["statN"], 5)
        self.assertEqual(lo["statRows"], 1, f"★ 860 宽下汇总条折成了 {lo['statRows']} 行")
        self.assertEqual(lo["mode"], "row")
        self.assertTrue(lo["statsBelow"], "汇总条应整条挪到标题行下面")
        self.assertLessEqual(lo["otherSpread"], 2, "标题行本身折行了")
        self.assertLessEqual(lo["root"], 1, f"代理轮换页面根在滚（溢出 {lo['root']}px）")
        self.assertEqual(hi["mode"], "inline", "宽窗口下汇总条应并在标题行里（2026-09-07 定稿）")
        self.assertEqual(hi["statRows"], 1)

    def test_relay_table_is_not_clipped(self):
        t = self.r["relay:min"]["t"]
        self.assertIsNotNone(t, "中转站表头没渲染")
        self.assertGreaterEqual(t["rows"], 1)
        self.assertLessEqual(t["right"], t["cardRight"] + .5, "「日均实扣」列被卡片裁掉了")
        self.assertLessEqual(t["headOver"], 0, "表头比卡片宽 —— 卡片 overflow:hidden 会裁掉右侧")
        # ★ 原来写死列宽时 endpoint 列被压到 ~20px，只剩「ht…」
        self.assertGreaterEqual(t["endpointW"], 55, f"endpoint 列只剩 {t['endpointW']:.0f}px")
        # ★ 按文字行数量，不按盒子高：网格单元格默认拉伸到行高，盒子高之比恒为 1（第一版就是这么空的）
        self.assertEqual(t["headLines"], 1, "表头「endpoint / key」折成了两行")


if __name__ == "__main__":
    unittest.main(verbosity=2)
