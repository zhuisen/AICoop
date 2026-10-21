"""窄窗下**不许断字**的闸。

起因是用户 2026-08-24 的截图:窗口一窄,总览头部就散架 ——
「总览」被劈成「总 / 览」、「刷新全池」→「刷新全 / 池」、「检查 token」→「检查 / token」、
「探针 全池」→「探针 全 / 池」。根因是 `GhostButton` / `ProbeButton` 既没有 `whiteSpace: nowrap`
也没有 `flexShrink: 0`,flex 在空间不够时**压缩按钮宽度**,文字只能在按钮内部折行。

修的时候在 760px 又发现**同一个病根的第二处**:hero 那行把日期劈成
「订阅至 2026- / 09-08」「至 2026- / 09-21」。**断开的日期比断开的按钮严重得多** ——
按钮只是难看,日期会被读成另一个日期。所以这条闸同时守两处,不只补被点名的那一处。

正确的形状是**两层**,缺一层都不成立:
  ① 原子(按钮、日期段、标题)`whiteSpace: nowrap` —— 永远不在内部断开;
  ② 容器 `flexWrap: "wrap"` —— 空间不够时让**整个原子**换行。
只做 ① 会横向溢出,只做 ② 原子照样被压扁。

⚠️ 这是**形状闸**,拦得住诚实改动(有人顺手删掉 nowrap),拦不住刻意绕过
(改用别的属性名、把样式挪进 CSS 文件)。真正的判据是像素 —— 每次改这块布局仍要按
CLAUDE.md §4 跑一遍 `?nav=home` 的窄宽度截图。已实测干净的下限:**700px**。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
APP = SRC / "App.tsx"
GHOST = SRC / "components" / "GhostButton.tsx"
# ★ 2026-10-19 总览照交接包 page5 重做：ProbeButton / RunwayHero 删除，卡片探针是 `ov/OvCard::HoldAb`，
#   顶部三栏是 `ov/OvHero`，总览头部在 `ov/Overview`；文字不换行由 `ov/overview.css` 的根规则统一兜住。
PROBE = SRC / "components" / "ov" / "OvCard.tsx"
OVERVIEW = SRC / "components" / "ov" / "Overview.tsx"
OVCSS = SRC / "components" / "ov" / "overview.css"
CARD = SRC / "components" / "AccountCard.tsx"
HERO = SRC / "components" / "ov" / "OvHero.tsx"


def strip_comments(src: str) -> str:
    """注释里正解释着这条规则(还引用了断字后的样子),朴素匹配必被它染红。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


class ButtonsNeverBreakMidWord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ghost = strip_comments(GHOST.read_text(encoding="utf-8"))
        cls.probe = strip_comments(PROBE.read_text(encoding="utf-8"))
        cls.app = strip_comments(APP.read_text(encoding="utf-8"))
        cls.card = strip_comments(CARD.read_text(encoding="utf-8"))
        cls.hero = strip_comments(HERO.read_text(encoding="utf-8"))
        cls.ov = strip_comments(OVERVIEW.read_text(encoding="utf-8"))
        cls.css = OVCSS.read_text(encoding="utf-8")

    def test_anchors_exist(self):
        """★ 先证明被测文件还是那个文件 —— 组件改名后断言会静默打空。"""
        self.assertIn("inline-flex", self.ghost, "GhostButton:不再是 inline-flex 按钮?")
        self.assertRegex(self.css, r"\.ov-ab \{\s*display: inline-flex", "卡片底栏按钮不再是 inline-flex?")
        self.assertIn('className="ov-ab ov-abw"', self.probe, "探针不再用底栏按钮的样式?")
        self.assertIn("总览", self.ov)

    # ---- ① 原子不断字 --------------------------------------------------------

    @staticmethod
    def _button_style_block(src: str) -> str:
        """截出**按钮自己**的样式块(从 `display: "inline-flex"` 起 400 字符)。

        ★ 不能对整个文件断言:`GhostButton.tsx` 里 `flexShrink: 0` 出现两次,另一处是
        **加载转圈的 spinner**。对全文断言时,把按钮的那条删掉照样绿 —— 变异测试当场抓到的空守卫。
        与全局那条「同前缀 ≠ 同标识」同族:**同文件里同名属性 ≠ 同一个元素**。
        """
        i = src.index('display: "inline-flex"')
        return src[i:i + 400]

    def test_shared_buttons_never_break_mid_word(self):
        """★ 两个按钮都不许**在按钮内部折行**（那是这一族闸的本意）。"""
        self.assertRegex(self._button_style_block(self.ghost), r'whiteSpace:\s*"nowrap"',
                         "GhostButton:样式块里没有 nowrap —— 窄窗下文字会在按钮内部折行")
        # 总览里所有按钮（含探针）由根规则兜住；行为闸 `test_overview_5b::CardsAreFixedAndNothingWraps` 实量。
        self.assertIn(".ov-root, .ov-root * { white-space: nowrap; }", self.css, "总览没有统一的 nowrap 根规则")

    def test_toolbar_buttons_hold_their_width_but_the_card_one_compresses(self):
        """★★ 2026-09-21：**两个按钮的要求从此相反**，别再统一断言。

        · `GhostButton` 在工具行里 —— 旁边是可省略的说明文字，**该退让的是文字**，
          所以它保持 `flexShrink: 0`。
        · `ProbeButton` 在**卡片动作条**里 —— 那一行 7 个控件、且用户要求「绝不换行」。
          不可收缩 + 不换行 = **横向溢出**（本仓算 bug）。所以它改成可收缩 +
          `minWidth` 兜底：最窄时文字自己被裁，而不是整块顶出去。
        """
        self.assertRegex(self._button_style_block(self.ghost), r"flexShrink:\s*0",
                         "GhostButton 不该被压缩 —— 工具行里该退让的是说明文字")
        # ★ 2026-10-19：卡片底栏的按钮**不再压缩**（`.ov-ab { flex-shrink: 0 }`）。理由换了：
        #   列数改由 `ovLayout` 按内容区宽给，任何宽度下卡片 ≥250px（`test_card_uniformity` 逐像素算），
        #   最宽那条底栏（切换 + 探针 + 刷新 + ⋯ ≈ 214）永远放得下 —— 压缩只会让「探针」被裁成「探」。
        self.assertRegex(self.css, r"\.ov-ab \{[^}]*flex-shrink: 0", "★ 底栏按钮可被压缩 —— 会被裁成半个字")

    def test_page_title_never_breaks(self):
        """「总览」被劈成「总 / 览」是用户报的第一个症状。"""
        m = re.search(r"<span style=\{\{[^}]*fontSize:\s*22[^}]*\}\}>总览</span>", self.ov, re.S)
        self.assertIsNotNone(m, "找不到总览标题 —— 断言可能打空了")
        self.assertIn("flexShrink: 0", m.group(0), "总览标题会被压缩")
        self.assertIn(".ov-root, .ov-root * { white-space: nowrap; }", self.css, "总览标题没有 nowrap")

    def test_hero_date_segments_never_break(self):
        """★ 断开的日期会被读成另一个日期 —— 比断开的按钮严重得多。

        ⚠️ **2026-09-21 改的是指向，不是判据。** 这两段原来都在 `App.tsx` 的旧 hero 里；
          hero 换成续航条之后，「订阅至」不再在总览顶部重复一遍（**没丢** ——
          每张卡片本来就有 `到期 {a.exp}`，hero 那份是同一个号的重复），
          窗口额度那段搬进了 `RunwayHero.tsx`。
        ★ 不变量一个字没变：**日期/额度这种原子永远不许在内部断开**。
          指向旧 markup 的断言必须跟着搬 —— 留着它只会假红，
          而一条会假红的闸，用户学会的是忽略它。
        """
        # 2026-10-19：这些原子都在 `.ov-root` 下，由根规则 `white-space: nowrap` 统一兜住；这里守「它们还在」
        #   且「不会被 flex 压扁」。真折没折由 `test_overview_5b` 在 1200 / 860 实量（文本节点的行数）。
        self.assertIn(".ov-root, .ov-root * { white-space: nowrap; }", self.css)
        # 2026-10-21 短日期（用户「到期日期挡住了」）：`{shortDate(a.exp, …)} 到期`，完整日期进悬浮
        self.assertRegex(self.card, r"\{shortDate\(a\.exp, Date\.now\(\)\)\} 到期", "找不到卡片上的「到期」那段 —— 断言可能打空了")
        # ★ 「临时借用」角标：左列收窄后实测被劈成「临时借 / 用」（2026-09-21 截图）。要让的是旁边带省略号的邮箱。
        mb = re.search(r"<span data-runway-borrowed[\s\S]*?>临时借用", self.hero)
        self.assertIsNotNone(mb, "找不到「临时借用」角标 —— 断言可能打空了")
        self.assertIn("flexShrink: 0", mb.group(0), "「临时借用」角标会被压缩")

    # ---- ② 容器允许整块换行 ---------------------------------------------------

    def test_the_header_drops_labels_instead_of_wrapping(self):
        """★ 2026-10-19 **改写**（交接包 page5 §4「窗口变窄」）：头部是**定高 32 的一行**，变窄时
        按钮先去掉文字只留图标、平台档只留 logo + 数字 —— 不再整块换行（原来那条「容器要 flexWrap」作废）。
        守的仍是同一件事：窄窗下不断字、不横向溢出；实量在 `test_overview_5b`（860 宽头部五个动作都在、零折行）。"""
        self.assertIn('<div data-overview-head="" style={{ display: "flex", alignItems: "center", gap: 12, height: 32, flexShrink: 0, minWidth: 0 }}>',
                      self.ov, "头部不再是定高的一行")
        self.assertIn("labels={layout.labels}", self.ov, "头部按钮的文字没跟版式走 —— 窄窗只能挤或折")
        tabs = strip_comments((SRC / "components" / "ov" / "OvHeader.tsx").read_text(encoding="utf-8"))
        self.assertIn("layout.tabNames &&", tabs, "平台档的名字没跟版式走")

    def test_rail_is_fixed_and_min_width_fits_three_columns(self):
        """★ AICoop P10_Nav（2026-10-21）：侧栏固定 64 宽，**不再折叠/展开**（原 `NARROW_W` 自动折叠随之删除）。

        于是窗口下限只剩一条约束：最小窗口下总览仍要排得下 3 列（P5_Spec §01「860 最小窗口 3 列」）。
        内容宽 = minWidth − 64（侧栏）− 32（内容区左右各 16）；3 列要 ≥ 3·245 + 2·12 = 759。
        单改其中一个数（侧栏变宽 / 内边距变大 / minWidth 变小）的症状是：最小窗口退成 2 列，不报错。
        """
        import json
        nav = strip_comments((ROOT / "codexbar" / "src" / "components" / "NavRail.tsx").read_text(encoding="utf-8"))
        self.assertIn("width: 64,", nav, "★ 侧栏不是 64 宽（P10_Nav）")
        self.assertNotIn("NARROW_W", self.app, "★ 自动折叠又回来了 —— P10_Nav 没有折叠态")
        m = re.search(r'flex: 1, minWidth: 0, padding: (\d+),', self.app)
        self.assertIsNotNone(m, "找不到内容区的内边距 —— 断言可能打空了")
        pad = int(m.group(1))
        conf = json.loads((ROOT / "codexbar" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        win = conf["app"]["windows"][0]
        self.assertGreaterEqual(win["minWidth"] - 64 - 2 * pad, 759,
                                "最小窗口下总览排不下 3 列：minWidth=%d pad=%d" % (win["minWidth"], pad))

    def test_scrollbars_are_themed_and_not_a_dead_rule(self):
        """★ 主窗滚动条必须有样式,且浅色主题那条**不能是死规则**。

        用户 2026-08-24 报「右侧有一条黑边」:主窗从来没给滚动条做过样式
        (`::-webkit-scrollbar` 之前只在 menubar.css 里给菜单栏列表做了一份),
        系统默认滚动条在深色底上就是一条黑带,而且**占布局宽度**,把图表右缘挤到底下。

        ⚠️ **harness 看不到这个** —— headless Chrome 默认覆盖式滚动条(不占宽),
        扫描全程报"干净"。这是继 `zoom` 之后第二次「验证环境 ≠ 运行环境」。
        所以只能用源码闸兜住。

        ★ 第二条断言防的是**死规则**:`.cb-light ::-webkit-scrollbar-thumb` 依赖根节点
        带 `cb-light`,而写完那条 CSS 时根节点上**根本没有这个 class** —— 规则永远不生效,
        浅色主题下白色拇指在白底上等于隐形,而且没有任何东西会报错。
        """
        css = (SRC / "App.css").read_text(encoding="utf-8")
        # ★ 断言的是**那条定宽规则真的在**,不是"这个词出现过"。
        #   第一版用 `assertIn("::-webkit-scrollbar", css)`,而 `-track`/`-thumb` 里都含这个子串
        #   ⇒ 把定宽那条删掉照样绿。**子串存在 ≠ 规则存在**(今天第三次同款空守卫)。
        self.assertRegex(css, r"::-webkit-scrollbar\s*\{[^}]*width",
                         "主窗没有给滚动条定宽 —— 会用系统默认,深色底上是一条黑带且占布局宽")
        self.assertRegex(css, r"::-webkit-scrollbar-track\s*\{[^}]*transparent",
                         "滚动条轨道没有置透明 —— 那条轨道就是用户看到的「黑边」")
        # ★ 必须**两个主题各有一条**。只写 `assertRegex(...thumb...)` 时,把深色那条删掉
        #   仍会被 `.cb-light` 那条匹配上 ⇒ 假绿(变异测试第三次抓到同款)。
        thumbs = re.findall(r"(^|\n)(\.cb-light\s+)?::-webkit-scrollbar-thumb\s*\{[^}]*background",
                            css)
        dark = [t for t in thumbs if not t[1]]
        light = [t for t in thumbs if t[1]]
        self.assertTrue(dark, "深色主题的滚动条拇指没有配色")
        self.assertTrue(light, "浅色主题的滚动条拇指没有配色 —— 白拇指在白底上等于隐形")
        if ".cb-light ::-webkit-scrollbar" in css:
            self.assertIn('className={theme === "light" ? "cb-light" : undefined}', self.app,
                          "写了 .cb-light 的滚动条规则,但根节点没有这个 class —— 死规则")

    def test_grid_columns_can_actually_shrink(self):
        """★★ CSS Grid 里裸 `1fr` = `minmax(auto, 1fr)`,最小值是 **min-content 不是 0**。

        后果:列**压不下去**,卡片内部那些 `minWidth:0` + 省略号**根本没机会生效**,
        只能整个网格溢出。2026-08-25 实测暴露 —— 差值角标从 `-8%` 变成 `-22%`(宽一个字符),
        860px 下网格自然宽 659 / 可用 644,右侧被裁。

        ⚠️ **真教训不是"下限要重新量"** —— 是**下限本来就不该随内容宽度浮动**。
        用 `minmax(0, 1fr)` 之后列能缩、省略号接手,布局不再受数据摆布。
        """
        self.assertNotRegex(self.app, r'gridTemplateColumns:\s*"1fr 1fr 1fr"',
                            "九宫格用了裸 1fr —— 列压不下去,内容一变宽就整体溢出")
        # ★ 2026-10-19：机制第三次换 —— 列数由 `ovLayout(内容区宽)` 给（4/3/2，交接包 page5），每列
        #   `minmax(0, 1fr)`（列能缩、省略号接手）；「卡片窄到装不下底栏」由 `test_card_uniformity` 逐宽度算。
        for src, name in ((self.ov, "Overview.tsx"),
                          (strip_comments((SRC / "components" / "ov" / "OvStrip.tsx").read_text(encoding="utf-8")), "OvStrip.tsx")):
            with self.subTest(f=name):
                self.assertRegex(src, r"gridTemplateColumns: `repeat\(\$\{(layout\.)?cols\}, minmax\(0, 1fr\)\)`",
                                 "{} 的网格列不是 minmax(0, 1fr) —— 列压不下去".format(name))
        return
        # ⚠️ 2026-09-21 **机制换了，性质没换**：从「固定 3 列 + 列可缩到 0」改成
        #   「按最小宽 auto-fill」。两者都保证内容永不撑爆布局，但走的是相反的路 ——
        #   前者让列缩、内部省略号接手；后者**让列数减少**，卡片反而更宽。
        #   换路的理由是实测：3 列在 880 窗口下把卡压到 211px，而卡里的动作条最紧要 ~234px
        #   ⇒ 无论怎么缩都装不下，只能折行（用户 2026-09-21 报的就是它）。
        self.assertRegex(self.app, r"CARD_GRID_COLS\s*=\s*`repeat\(auto-fill,\s*minmax\(\$\{CARD_MIN_W\}px",
                         "九宫格不是按最小宽自适应 —— 窄窗下卡片会被压到装不下动作条")
        m = __import__("re").search(r"const CARD_MIN_W = (\d+);", self.app)
        self.assertIsNotNone(m, "找不到 CARD_MIN_W")
        self.assertGreaterEqual(int(m.group(1)), 300,
                                "★★ 最小宽低于 300 —— 动作条会重新折行（实测最紧需要 ~234 内宽）")
        self.assertIn("gridTemplateColumns: CARD_GRID_COLS", self.app,
                      "九宫格没走那个常量 —— 常量对了也没用")

    def test_account_name_can_never_vanish(self):
        """★★ 只给 `minWidth: 0` 会让 flex 把名字压到 **0px 直接消失**。

        2026-08-25 实测:Pro1 那行徽章最多(PRO+活+USE+当前),860px 下自然宽 122 / 可用 114,
        flex 就把唯一可缩的名字压没了 —— **认不出这是哪个号,比裁掉半个日期严重得多**。
        所以名字要有**下限**(截成 `Pro…` 也还认得出),整行允许换行让徽章掉到第二行。
        """
        # ★ 名字那个 span 在 **AccountCard.tsx**,不在 App.tsx。
        #   第一版对着 self.app 断言 ⇒ 测试恒红,而恒红的测试**任何变异都会"变红"**,
        #   变异测试的绿灯全是假的(今天第二次踩:先证明基线是绿的,再做变异)。
        card = strip_comments((SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8"))
        # ★ 锚点**不要挂在字号数值上**。原来写死 `fontSize: 13.5`,2026-08-26 把字号提取成
        #   `CARD_TYPE`(用户选了 D 档)后这条立刻打空 —— 幸好有下面那句"断言可能打空了"接住,
        #   否则它会静默变成"永远通过"。改成认**被测的那个属性本身**(渲染 `{a.node}` 的 span)。
        # ★ `<span[^>]*?` 容许 style 前面有别的属性（2026-10-14 加了 `data-card-name` 给一屏闸用，
        #   原来写死 `<span style=` 当场打空 —— 又是下面那句"断言可能打空了"接住的）。
        m = re.search(r"<(?:span|b)[^>]*? style=\{\{[^}]*\}\}>\{a\.node\}", card, re.S)
        self.assertIsNotNone(m, "找不到账号名那个 span —— 断言可能打空了")
        self.assertNotRegex(m.group(0), r"minWidth:\s*0\b",
                            "账号名 minWidth 是 0 —— flex 会把它压到消失")
        self.assertRegex(m.group(0), r"minWidth:\s*[1-9]\d",
                         "账号名没有宽度下限")

    def test_the_title_row_still_has_something_that_yields(self):
        """窄窗下该让位的是**信息价值最低**的那一项，不是按钮。

        ⚠️ 2026-09-13：原来让位的是 `7 nodes · 6 活 · 0 冷 · 1 死` 那行摘要，
        用户要求删掉了它。所以这条闸改成盯**标题行里那个会缩的容器** ——
        断言不能继续找一个已经不存在的东西，那样它测的是"我还在"而不是"它会让位"。
        """
        m = re.search(r"总览</span>", self.ov)
        self.assertIsNotNone(m, "找不到总览标题 —— 断言打空了")
        block = self.ov[max(0, m.start() - 500):m.start() + 900]
        self.assertIn("minWidth: 0", block,
                      "标题行没有任何可收缩的容器 —— 窄窗下会挤按钮")
        self.assertIn("flexShrink: 0", block,
                      "★ 标题本身没有 flexShrink:0 —— 窄窗下「总览」会被劈成「总 / 览」")


class WideTableMinWidthIsDerivedNotMeasured(unittest.TestCase):
    """★★ 宽数据表的 `minWidth` 必须**由列宽算出来**，不许写一个实测常数。

    起因（2026-08-26，一轮里踩了两次同一类）：
      · `test_narrow_window_nowrap` 有条断言锚在字号字面量 `13.5` 上，字号提取成常量后当场打空；
      · `PlatformPage` 的 `TABLE_MIN = 700` 注释写着「900px 实测自然宽 698」——
        用户要求放大模型表字号、列宽全部重算后，那个 700 **立刻失真**。

    失真的症状**不是报错**：表照常渲染，只是在某个宽度下最右边一列被悄悄裁掉，
    而裁掉的正是「费用/百万」（这张表里唯一回答"钱花在哪个型号上"的列）。
    横向滚动条也不会出现 —— `minWidth` 太小时行会被约束成可用宽，内部继续溢出。

    ★ 所以判据是**结构性的**：`TABLE_MIN` 必须是一个由 `TABLE_TYPE` 各列宽相加的表达式。
      这样字号一改、列宽一改，下限自动跟上，没有"忘了同步"这一步可漏。
    """

    @classmethod
    def setUpClass(cls):
        cls.code = strip_comments((SRC / "pages" / "PlatformPage.tsx").read_text(encoding="utf-8"))
        cls.theme = strip_comments((SRC / "theme.ts").read_text(encoding="utf-8"))

    def test_anchor_exists(self):
        self.assertIn("TABLE_MIN", self.code, "TABLE_MIN 不见了 —— 断言可能打空了")
        self.assertIn("TABLE_TYPE", self.theme, "theme 里没有 TABLE_TYPE —— 断言可能打空了")

    def test_table_min_is_not_a_hardcoded_number(self):
        m = re.search(r"const TABLE_MIN\s*=\s*([^;]+);", self.code, re.S)
        self.assertIsNotNone(m, "找不到 TABLE_MIN 的定义")
        expr = m.group(1)
        self.assertNotRegex(expr.strip(), r"^\s*\d+\s*$",
                            "TABLE_MIN 又被写成一个常数了 —— 字号/列宽一改它就失真，"
                            "而症状是最右边一列被悄悄裁掉，不报错")
        self.assertIn("TZ.", expr, "TABLE_MIN 没有从列宽标尺推导")

    def test_grid_columns_come_from_the_scale(self):
        """列宽也不许散落成字面量 —— 那样 TABLE_MIN 推导得再对也白搭。"""
        m = re.search(r"gridTemplateColumns:\s*`([^`]+)`", self.code)
        self.assertIsNotNone(m, "找不到模型表的列模板")
        tpl = m.group(1)
        self.assertGreaterEqual(tpl.count("TZ."), 8,
                                "模型表的列宽还有写死的字面量:{}".format(tpl))

    def test_table_font_sizes_come_from_the_scale(self):
        """★ 字号与列宽必须同源。只放大字号不改列宽 = 数字串位。"""
        for token in ("TZ.body", "TZ.colHead", "TZ.groupHead"):
            self.assertIn(token, self.code, "模型表的字号没有走 {}".format(token))


if __name__ == "__main__":
    unittest.main()


class ControlGroupsNeverWrapIntoTwoRows(unittest.TestCase):
    """★★ 互斥单选控件组（`Seg` / `RangeBar`）在**支持的全部窗口宽度**下都只占一行。

    ## 起因（2026-09-16，用户截图点名）

    平台详情页头部「分模型 / 总量」折成两行，而紧邻的档位条「今日 7d 30d 年度 范围▾」
    是一行 —— 两个同类控件组高度对不齐。实测折行阈值 **≤1200px**，而窗口下限是 860px，
    也就是**日常宽度下几乎一直是坏的**（1400px 才不折；107px 被挤到 61px）。

    ## 根因不是 `Seg` 的 `flexWrap`

    那是它挤到极限时的兜底，是对的。错的是**这一行里被挤的是不该被挤的那个**：
    同排的源路径 span 自带 `overflow:hidden + textOverflow:ellipsis`，
    **它才是设计来吸收挤压的**；而控件组没有 `flexShrink: 0`，于是 flex 从两边一起压。
    ★ 判据：一行里谁能优雅退让谁就退让 —— **会截断的让给会省略号的**。

    ## ⚠️ 为什么非要新加探针

    现有的 `wrapped` 探针**结构上看不见这一类**：它判的是**叶子文本节点**的渲染高，
    而控件组折行时每个 span 仍是单行、折的是**容器**。
    所以「控件被压成竖排」这一整类只能靠肉眼发现 —— 2026-08-24 用户连报三处，
    2026-09-16 又报一次。本仓规矩：**同一类 bug 抓到第二次，交付物是一条会变红的闸**，
    不是再写一行散文。现在 `Seg` 与 `RangeBar` 的容器都带 `data-seg`，
    harness 的 `segRows` 探针按「容器 clientHeight ÷ 子项 offsetHeight」报行数。
    """

    #: 窗口下限 860（D 档字号，见 CLAUDE.md §2），1200 是实测的折行阈值，必须覆盖。
    WIDTHS = (1200, 1000, 860)
    VIEWS = ("platform:agy", "traffic", "relay")

    @classmethod
    def setUpClass(cls):
        import json as _json
        import shutil
        import subprocess
        import urllib.error
        import urllib.request
        cls._json, cls._sub = _json, subprocess
        cls.chrome = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if not Path(cls.chrome).exists() and not shutil.which("google-chrome"):
            raise unittest.SkipTest("本机没有 Chrome —— 跳过而不是假绿")
        try:
            urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=3).read(1)
        except (urllib.error.URLError, OSError) as e:
            raise unittest.SkipTest(
                "harness 静态服务(3304)没在跑：{} —— 先 `python3 codexbar/uishot/make_harness.py`。"
                "★ 跳过不是绿，别当它验过了".format(str(e)[:60]))

    def _segs(self, view: str, width: int):
        import html as _html
        out = self._sub.run(
            [self.chrome, "--headless=new", "--use-mock-keychain", "--disable-gpu", "--no-sandbox",
             "--window-size={},900".format(width), "--virtual-time-budget=3500", "--dump-dom",
             "http://127.0.0.1:3304/harness.html?nav={}&intro=0".format(view)],
            capture_output=True, text=True, timeout=120).stdout
        m = re.search(r"<title>__PROBE__(.*?)</title>", out, re.S)
        self.assertIsNotNone(m, "★ 没拿到探针 —— 是 harness 坏了，不是页面干净")
        return self._json.loads(_html.unescape(m.group(1))).get("segRows") or []

    def test_the_probe_actually_finds_the_control_groups(self):
        """★★★ 已知阳性自检 —— **必须先证明探针看得见目标**。

        少了这条，一个恒返回空数组的探针会让下面每一条都"通过"，
        而"没扫到"与"没折行"在报告里长得一模一样。这是本仓最贵的一类错。
        """
        segs = self._segs("platform:agy", 1200)
        self.assertGreaterEqual(
            len(segs), 2,
            "★★★ 平台详情页应当有 2 组控件（分模型/总量 + 档位条），探针只看到 {} 组 —— "
            "是 `data-seg` 掉了或探针坏了，不是页面没问题".format(len(segs)))

    def test_no_control_group_wraps_at_any_supported_width(self):
        bad = []
        for view in self.VIEWS:
            for w in self.WIDTHS:
                for s in self._segs(view, w):
                    if s["rows"] > 1:
                        bad.append("    {} @{}px · {} → {} 行（宽 {}px）"
                                   .format(view, w, s["opts"], s["rows"], s["w"]))
        self.assertEqual(
            bad, [],
            "★★ 这些控件组被挤成了多行：\n" + "\n".join(bad)
            + "\n   → 修法**不是**去掉 `Seg` 的 `flexWrap`（那是挤到极限时的兜底），"
              "\n     而是给控件组所在的那个 flex 容器加 `flexShrink: 0` ——"
              "\n     让同排自带省略号的说明文字去吸收挤压。")
