"""一屏仪表盘（用户 2026-10-14：「最小的画面都能标题一行处理完，图表一个界面展示完」
+「智能调控一屏大小的，其他版块也要处理」，从两档 demo 里选的「仪表盘式一屏」）。

判据全是**量出来的**，在真 bundle 上跑（harness 静态服务 3304）：

① AI用量 / 平台详情：KPI 条**一行**、没有格子出框；页面根不滚；
   底部列表/模型表在**自己的框里滚**（证明是滚动不是裁切）；图表高度不低于改动前的固定值，
   大窗口下**长高**（证明是撑满不是写死）。
② KPI 7 格任何宽度一行、字号不变（数字 24 / 标签 12.5 / 副标 11.5），860 靠短标签（AICoop R2，2026-10-22
   取代 10-14 的「让出最大占比 + 只缩 hero 数字」，偏离 R2-2）。
③ 数字**绝不截断**（在最小窗口 860 上量）。
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
  // AICoop R2（2026-10-22）：7 格网格 [data-kpis] > [data-kpi]；数字 [data-kpi-value]、副标 [data-kpi-sub]。
  const s = document.querySelector('[data-kpis]');
  if (!s) return null;
  const sr = s.getBoundingClientRect();
  const cells = [...s.querySelectorAll('[data-kpi]')];
  const rs = cells.map(c => c.getBoundingClientRect());
  const px = sel => [...s.querySelectorAll(sel)].map(e => parseFloat(getComputedStyle(e).fontSize));
  const page = document.querySelector('[data-token-page],[data-token-detail]');
  return {n: cells.length, labels: cells.map(c => c.getAttribute('data-kpi')),
          rows: new Set(rs.map(r => Math.round(r.top))).size,
          outside: rs.filter(r => r.left < sr.left - .5 || r.right > sr.right + .5).length,
          clipped: [...s.querySelectorAll('[data-kpi-value]')].filter(e => e.scrollWidth > e.clientWidth + 1).length,
          value: px('[data-kpi-value]'),
          label: cells.map(c => parseFloat(getComputedStyle(c.children[0]).fontSize)),
          sub: px('[data-kpi-sub]'),
          root: page ? page.scrollHeight - page.clientHeight : null};
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
  const page = document.querySelector('[data-rot-page]');
  const head = page.children[0];
  const cells = [...st.querySelectorAll('[data-kpi]')];
  const tops = cells.map(c => Math.round(c.getBoundingClientRect().top));
  const others = [...head.children].map(c => Math.round(c.getBoundingClientRect().top + c.getBoundingClientRect().height / 2));
  const vals = [...st.querySelectorAll('[data-kpi-value]')];
  return {statN: cells.length, statRows: new Set(tops).size,
          clipped: vals.filter(v => v.scrollWidth > v.clientWidth + 1).length,
          otherSpread: Math.max(...others) - Math.min(...others),
          root: page.scrollHeight - page.clientHeight,
          recScroll: (() => { const l = document.querySelector('[data-rec-list]'); return l ? getComputedStyle(l).overflowY : null; })()};
}"""
RELAY_JS = """() => {
  // AICoop P8：中转站账户表（明细块里）。表头是含「还能撑」的那一行。
  const h = [...document.querySelectorAll('[data-relay-detail] span')].find(e => e.textContent.trim() === '还能撑' && e.parentElement.children.length === 6);
  if (!h) return null;
  const head = h.parentElement, card = head.closest('[data-relay-detail]');
  const last = head.children[head.children.length - 1];
  return {right: last.getBoundingClientRect().right, cardRight: card.getBoundingClientRect().right,
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
                               ("platform", "platform:claude", "[data-platform-scroll]")):
            for tag, size in (("min", MIN_WIN), ("big", BIG_WIN)):
                visit(f"{name}:{tag}", nav, size,
                      {"kpi": (KPI_JS, None), "box": (BOX_JS, box), "svg": (SVG_JS, None)})
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

    def test_all_seven_cells_stay_and_860_uses_short_labels(self):
        """★ 2026-10-22 **改写**（AICoop R2，偏离 R2-2，待用户确认）。

        原判据（用户 2026-10-14「最小尺寸下，AI用量信息，去掉最大占比」）：860 宽整格让出「最大占比」、
        仍放不下再缩 hero 数字。R2 稿写「任何宽度一行 7 列，窄窗靠缩短写法」（860 用短标签 Token / 请求 /
        日均 / 费用 / 日均费 / 最大 / 缓存），两者不能同时成立，按稿。守的仍是同一条底线：**一行、不出框、不截断**。"""
        lo, hi = self._kpi("traffic:min"), self._kpi("traffic:big")
        self.assertEqual(lo["n"], 7)
        self.assertEqual(hi["n"], 7)
        self.assertEqual(lo["labels"][5], "最大", "860 宽「最大占比」写短名")
        self.assertEqual(hi["labels"][5], "最大占比")
        for key in ("traffic:min", "platform:min"):
            self.assertEqual(self._kpi(key)["clipped"], 0, f"★★ {key}: 有数字被截断 —— 截断比让格更糟")

    def test_type_sizes_do_not_shrink(self):
        """R2 稿：数字 24、标签 12.5、副标 11.5，任何宽度不变（字号不变，窄窗缩短内容）。"""
        for key in ("traffic:min", "traffic:big", "platform:min"):
            k = self._kpi(key)
            self.assertEqual(set(k["value"]), {24}, key)
            self.assertEqual(set(k["label"]), {12.5}, key)
            self.assertEqual(set(k["sub"]), {11.5}, key)

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

    # ★ 2026-10-22 删掉 `test_below_the_minimum_it_wraps_instead_of_clipping`（700 / 640 宽）：
    #   窗口最小 860（tauri.conf.json `minWidth`），那两档在 app 里到不了；「绝不裁」改在 860 上直接量（上面 clipped）。

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
        """AICoop P7：7 格 KPI 任何宽度一行（取代 09-07「并在标题行」/ 10-14「整条下移」两版，合同被取代）。"""
        for key in ("logs:min", "logs:big"):
            with self.subTest(win=key):
                m = self.r[key]["h"]
                self.assertIsNotNone(m, "代理轮换的 7 格指标没渲染")
                self.assertEqual(m["statN"], 7)
                self.assertEqual(m["statRows"], 1, f"★ 指标折成了 {m['statRows']} 行")
                self.assertEqual(m["clipped"], 0, "有指标数字被截断")
                self.assertLessEqual(m["otherSpread"], 2, "标题行本身折行了")
                self.assertLessEqual(m["root"], 1, f"代理轮换页面根在滚（溢出 {m['root']}px）")
                self.assertEqual(m["recScroll"], "auto", "轮换记录不在自己的容器里滚")

    def test_relay_table_is_not_clipped(self):
        t = self.r["relay:min"]["t"]
        self.assertIsNotNone(t, "中转站表头没渲染")
        self.assertGreaterEqual(t["rows"], 1)
        self.assertLessEqual(t["right"], t["cardRight"] + .5, "「出口」列被卡片裁掉了")
        self.assertLessEqual(t["headOver"], 0, "表头比卡片宽 —— 卡片 overflow:hidden 会裁掉右侧")
        # ★ 原来写死列宽时 endpoint 列被压到 ~20px，只剩「ht…」（P8 起这一列是 key 指纹前缀）
        self.assertGreaterEqual(t["endpointW"], 55, f"key 列只剩 {t['endpointW']:.0f}px")
        # ★ 按文字行数量，不按盒子高：网格单元格默认拉伸到行高，盒子高之比恒为 1（第一版就是这么空的）
        self.assertEqual(t["headLines"], 1, "表头「key」折成了两行")


if __name__ == "__main__":
    unittest.main(verbosity=2)
