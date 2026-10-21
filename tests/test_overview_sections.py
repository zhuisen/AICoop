"""总览按**供应商分档**（2026-09-13，用户给了样式：`● Codex 6 │ ● Google 1 │ +`）。

## 分档不是筛选，是因为三家的账号语义根本不同

    Codex   池 · 经本地代理**逐请求**换号 · 5h/周双窗口 · 探针**要花钱**
    Google  池 · **启动前**换凭证（agy 只在启动时读）· 额度是随时可读的比例
    xAI     单号只读 · 周窗口

## ★★★ 这一组闸真正在守的东西

分档之后，页面上原有的一切都默认变成了「**当前这一档**的信息」。而总览上大部分东西
其实是 **codex 池专属**的：Hero（当值号）、`7 nodes · 6 活` 摘要、`6/7 新鲜` 覆盖度、
失效账号折叠区、以及那一排动作按钮。

它们挂在别家的档上时**看起来毫无异样**，但说的是另一家的事。其中最危险的是
**「探针 全池」—— 它是花钱的**：用户看着 agy 的卡按下去，扣的是 codex 的额度。
所以下面逐个钉，而不是只钉「有没有分档」。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "codexbar" / "src"


def _strip(src):
    src = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", l) for l in src.splitlines())


# ★ 2026-10-19 总览照交接包 page5 重做：分档、头部动作、三栏、网格全在 `ov/Overview.tsx`，
#   平台档本体在 `ov/OvHeader.tsx::OvTabs`（ProviderTabs 删除）。守的东西不变，锚点跟着真源走。
OV = _strip((SRC / "components" / "ov" / "Overview.tsx").read_text(encoding="utf-8"))


def _member(src, head):
    """`cx` / `gx` 里一个成员的定义：从 `head` 到下一个成员（或注释 / 对象结尾）。P5 评审修复 2026-10-22。"""
    i = src.index(head)
    m = re.compile(r"\n    (?:[A-Za-z]+: |//)|\n  };").search(src, i + len(head))
    return src[i:m.start()]
TABS = _strip((SRC / "components" / "ov" / "OvHeader.tsx").read_text(encoding="utf-8"))
# ★ 2026-09-13：平台清单搬到了 `platforms.ts`，主窗分档 Tab 与**菜单栏 logo 芯片行**
#   共用这一份（菜单栏 v4 稿 §9.1）。判据跟着真源走。
PLAT = (SRC / "platforms.ts").read_text(encoding="utf-8")


def _branch(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i + len(start))]


ACTIONS = {
    "codex": _branch(OV, "if (codexOn) {\n    actions = (", "} else if (agyOn) {\n    actions"),
    "gemini": _branch(OV, "} else if (agyOn) {\n    actions", '} else if (prov === "claude") {\n    actions'),
    "claude": _branch(OV, '} else if (prov === "claude") {\n    actions', "} else {\n    actions"),
    "grok": _branch(OV, "} else {\n    actions", "const pending = "),
}


class TheOverviewIsTabbedByProvider(unittest.TestCase):

    KEYS = re.findall(r'\{ key: "([a-z]+)"', PLAT)
    NOTES = re.findall(r'note: "([^"]+)"', PLAT)

    def test_four_tabs_in_the_glow_order(self):
        """2026-10-19：交接包 page5 加了 Claude 档，顺序改成与刘海光晕同一套（Codex → Claude → Gemini → Grok），
        不再是「账号数量降序」。"""
        self.assertEqual(self.KEYS, ["codex", "claude", "gemini", "grok"], "★ 档位或顺序不对")
        self.assertIn("const TAB_ORDER: PoolKey[] = POOL_PLATFORMS.map((p) => p.key);", OV, "★ 总览的档序不从清单推")

    def test_each_tab_explains_its_own_rotation(self):
        """★★ 说明必须**互不相同**。四段一样等于没分档 —— 而"看起来分了"比没分更糟：
        它让人以为差异已经被解释过了。"""
        self.assertEqual(len(self.NOTES), 4)
        self.assertEqual(len(set(self.NOTES)), 4, "★★ 有两档的说明一字不差")
        self.assertIn("note: POOL_PLATFORMS.find((x) => x.key === k)?.note", OV, "★★ 说明没传给档 —— 写了没人显示")
        self.assertRegex(TABS, r"title=\{`\$\{tb\.name\} · \$\{tb\.count\} 个号\$\{tb\.note \? ` · \$\{tb\.note\}` : \"\"\}",
                         "★★ 档的悬浮提示里没有这一家的轮换说明")

    def test_the_notes_name_the_actual_mechanism(self):
        """★ 判据打在**机制词**上。写成「Google 的账号」这种同义反复也能过长度检查，但它什么都没说。"""
        joined = " ".join(self.NOTES)
        for word in ("逐请求", "启动前", "只读", "只看额度"):
            with self.subTest(word=word):
                self.assertIn(word, joined, f"★ 没有一档提到「{word}」这个关键差异")

    def test_the_count_is_what_gets_rendered(self):
        """★★ 计数是「主网格里画出来几张」，不是「池里有几个」。死号 / 停用号在下面的条里，
        算进来就会出现「Codex 7」配着 6 张卡 —— 而那个差额没有任何地方解释。"""
        self.assertIn('name: "Codex", count: cMain.length', OV, "★★ Codex 的计数不是主网格的张数")
        # P5（2026-10-21）：主网格分「置顶 / 其余」两区，两区合起来 = 排序后的 codexShown（= cMain）。
        self.assertIn("grid = grid0(sections(codexPinned, codexRest, (a, i) => codexCard(a, i, true)));", OV)
        self.assertIn("const codexPinned = codexShown.filter((a) => a.pinRank !== null)", OV)
        self.assertIn("const codexRest = codexShown.filter((a) => a.pinRank === null)", OV, "★★ 两区合起来不等于 codexShown —— 计数与张数对不上")
        self.assertIn("const codexSorted = ovSort(cMain,", OV, "★★ 主网格画的不是 cMain —— 计数与张数对不上")
        self.assertRegex(OV, r"const codexShown = p\.preview \? applyOrder\(codexSorted,[^;]*: codexSorted;")

    def test_the_choice_is_remembered(self):
        """★ 这一档是"我在管哪一家账号"，不是一次性筛选 —— 切到别的页再回来不该跳回第一档。"""
        self.assertIn('localStorage.setItem(STORE_KEY, k)', PLAT, "★ 分档没有被记住")
        # ★★ 旧值必须还认得：2026-09-13 之前存的是 `google`/`xai`，
        #   不迁移的话停在 Gemini 档的用户下次打开会**静默跳回 Codex**。
        self.assertIn('v === "google"', PLAT, "★★ 没有迁移旧的 provider 值")
        self.assertIn('v === "xai"', PLAT, "★★ 没有迁移旧的 provider 值")

    def test_the_identity_survives_selection(self):
        """★ 选中态是平台色底，识别标（logo）是「这一档是谁」—— 两件事。
        选中时去掉识别标，就只能靠文字猜它是哪一家（860 档连名字都没有）。"""
        i = TABS.index("{tabs.map((tb, i) => {")
        seg = TABS[i:TABS.index("})}", i)]
        self.assertRegex(seg, r"\n\s*<PlatformLogo platform=\{LOGO\[tb\.key\]\}", "★ 识别 logo 不是每档都画")
        self.assertNotRegex(seg, r"on && <PlatformLogo|!on && <PlatformLogo", "★ 识别 logo 随选中态消失")


class CodexOnlyThingsStayOnTheCodexTab(unittest.TestCase):
    """★★★ 分档之后，页面上的一切默认都在说「当前这一档」。

    但总览上大半是 codex 池专属的，挂在别家档上**看起来毫无异样**却说的是另一家的事。
    """

    def test_the_hero_is_per_tab(self):
        # `p.board ?` 也是判据的一部分 —— 板子没读到时不画数字全是「—」的空条，而是「正在读 / 没读到」。
        self.assertIn('const hero = codexOn\n    ? (p.board ? <PoolHero source="codex"', OV, "★★ Codex 的三栏没收进 Codex 档")
        self.assertIn('? (p.agyBoard ? <PoolHero source="agy"', OV, "★★ Gemini 的三栏不是读 Gemini 的板")

    def test_the_dead_strip_is_codex_only(self):
        i = OV.index('<OvStrip kind="dead"')
        branch = OV[OV.rindex("if (codexOn) {", 0, i):i]
        self.assertNotIn("} else", branch, "★★ 失效条不在 Codex 档的分支里")
        self.assertIn("below = cDead.length > 0 ? (", branch)   # P5：折叠条挪进网格下方的 `below` 槽

    def test_the_billed_probe_button_cannot_appear_on_another_tab(self):
        """★★★ 最危险的一条：探针**是花钱的**。挂错档 = 看着 A 的卡、花 B 的额度。
        每一档只能出现**花它自己钱**的那一颗，Claude / Grok 一颗都没有。"""
        # P5 评审修复 2026-10-22：头部按钮经计费在途锁调 `cx.probeAll()` / `gx.probeAll()`，命令在定义里
        self.assertIn("cx.probeAll()", ACTIONS["codex"], "★ Codex 档的探针不见了 —— 判据失准，先修闸")
        self.assertIn("gx.probeAll()", ACTIONS["gemini"], "★ Gemini 档的探针不见了")
        self.assertIn('p.run("probe-all", ["probe", "--all"]', _member(OV, 'probeAll: () => withBilled("codex:*"'))
        self.assertIn("p.agyPool.probe()", _member(OV, 'probeAll: () => withBilled("agy:*"'))
        for k, seg in ACTIONS.items():
            with self.subTest(tab=k):
                if k != "codex":
                    self.assertNotIn('"probe-all"', seg, f"★★★ codex 的探针出现在 {k} 档")
                    self.assertNotIn("cx.probeAll", seg, f"★★★ codex 的探针出现在 {k} 档")
                if k != "gemini":
                    self.assertNotIn("agyPool.probe", seg, f"★★★ agy 的探针出现在 {k} 档")
                    self.assertNotIn("gx.probeAll", seg, f"★★★ agy 的探针出现在 {k} 档")
                if k in ("claude", "grok"):
                    self.assertNotIn("<ProbeHold", seg, f"★★★ {k} 档有探针 —— 它根本没有可探的池")

    def test_the_freshness_line_is_per_tab(self):
        """★ `6/7 新鲜` 数的是 codex 池的快照覆盖度；Gemini 档另有一行数 Gemini 池。"""
        self.assertIn("codexFresh", ACTIONS["codex"])
        for k in ("gemini", "claude", "grok"):
            with self.subTest(tab=k):
                self.assertNotIn("codexFresh", ACTIONS[k], f"★ codex 的新鲜度出现在 {k} 档")
        self.assertNotIn("agyFresh", ACTIONS["codex"])


class TheExtraCardsStillStayOutOfThePool(unittest.TestCase):
    """★★★ 分档**不能**顺手把 grok/agy 并进 codex 池的数组。

    那个数组同时驱动计数徽章、探针全池的号数、自动切号 ——
    混进去之后会"切"到一个切不了的东西上，**而且不报错**。
    """

    def test_neither_card_is_rendered_from_the_codex_pool(self):
        i = OV.index("const codexCard = ")
        seg = OV[i:OV.index("const agyCard = ", i)]
        self.assertIn("<AccountCard", seg, "★ 锚点失准：codexCard 不画 AccountCard 了")
        for tag in ("<GrokCard", "<AgyCard", "<ClaudeCard"):
            with self.subTest(card=tag):
                self.assertNotIn(tag, seg, f"★★★ {tag} 跑进了 codex 池那张网格")

    def test_every_tab_owns_its_grid(self):
        """★ 每档各自一张 `data-cards-grid`。uishot 的对齐闸按排比较 —— 分档之后它只在同一档内比。"""
        self.assertEqual(len(re.findall(r"<div[^>]*\bdata-cards-grid=", OV)), 1, "★ 网格有第二份写法")
        self.assertEqual(len(re.findall(r"\bgrid = grid0\(", OV)), 4, "★ 不是四档各一张网格")


if __name__ == "__main__":
    unittest.main()
