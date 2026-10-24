"""Gemini 档与 Codex 档**功能对齐**（用户 2026-09-13：「gemini 的功能也没有 1:1 同步上 codex」）。

用户圈出来的是两块：**Hero 区**（当前使用中 + 建议切到）和**卡片展开的动作条**。

## ★★★ 对齐**不等于**照搬，三件东西刻意没做，每一条都有事实依据

| 没做 | 为什么 |
|---|---|
| 「探针」 | 它跑的是 `codex-rotate probe --all`，扣的是 **codex** 的额度。挂在 Gemini 档上 = 用户看着 agy 的卡按下去、花的是另一家的钱 |
| 「检查 token」 | agy 没有对等物（那是问 OpenAI 服务端 token 是否被作废） |
| 「自动切号」开关 | agy 的自动选号发生在 `bin/agy` **拉起进程之前**，不是 app 能开关的运行期行为。给一个点了没用的开关，比没有这个开关糟 |

给一个点下去没反应、或者扣错家钱的按钮，比缺一个按钮糟得多 —— 这一组闸两头都守。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
APP = SRC / "App.tsx"
CARD = SRC / "components" / "AgyCard.tsx"
ACC = SRC / "components" / "AccountCard.tsx"
RS = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"


def code(p):
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//.*", "", s)


OV = SRC / "components" / "ov" / "Overview.tsx"


def _member(src, head):
    """`cx` / `gx` 里一个成员的定义：从 `head` 到下一个成员（或注释 / 对象结尾）。P5 评审修复 2026-10-22。"""
    i = src.index(head)
    m = re.compile(r"\n    (?:[A-Za-z]+: |//)|\n  };").search(src, i + len(head))
    return src[i:m.start()]
OVCARD = SRC / "components" / "ov" / "OvCard.tsx"


def gemini_block():
    """总览里 **Gemini 档**的头部动作 + 三栏 + 网格拼起来。

    ★ 2026-10-19：总览从 App 搬进 `ov/Overview.tsx`（交接包 page5），分档从 JSX 里的
      `{provider === "gemini" && …}` 换成 `if (codexOn) … else if (agyOn) …` 的分支 ——
      判据跟着取 `agyOn` 那几个分支，守的东西不变。
    ⚠️ 不能只取一段：**动作与网格不在同一处**，只切一段会让「有没有探针/检查 token」对着半页源码判。
    """
    c = code(OV)
    out = []
    for start in ("} else if (agyOn) {\n    actions", "} else if (agyOn) {\n    const c = ovCounts"):
        i = c.find(start)
        assert i >= 0, "★ 解析不到 Gemini 档 —— 判据看不懂了，先修闸：%r" % start
        out.append(c[i:c.index("} else if (prov === \"claude\")", i)])
    return "\n".join(out)


# ★ 2026-09-24：原 `TheGeminiTabHasAHeroLikeCodex`（自绘 Hero +「建议切到 X」+ 前端排名的平局/未知规则）
#   已随用户拍板「Gemini 总览同步 codex 的规范」整体撤掉 —— Hero 换成 codex 同一个 `RunwayHero`，
#   「下一个」由 `agy/pool.py::pick` 决定。接替它的闸在 `tests/test_gemini_follows_codex_rotation.py`。


class TheGeminiCardHasTheSameActionBar(unittest.TestCase):

    def test_the_card_has_the_same_hover_footer(self):
        """★ 2026-10-19 改写：「选中后出动作条」换成交接包的「悬停时底栏原位换成操作」——
        两张卡都把操作交给共用的 `OvCard`（`actions=` + ⋯ 菜单），谁也不自己画一份。
        P5（2026-10-21）：⋯ 菜单换成共用的 `CardMenu`（`OvMenu` 删除）。"""
        for f in (CARD, ACC):
            c = code(f)
            with self.subTest(f=f.name):
                i = c.index("<OvCard ")
                self.assertIn("actions={actions}", c[i:c.index("drag={drag} />", i)],
                              "★★ %s 的操作不是交给共用卡片画的" % f.name)
                self.assertIn("<CardMenu ", c, "★★ %s 没有 ⋯ 菜单" % f.name)

    def test_the_action_bar_is_the_same_floating_overlay(self):
        """★★ 与账号卡**同款**（§5c 页面统一性）：默认底栏与操作组在共用 `OvCard` 的**同一个 28 高底栏**里互换。

        ✗ 2026-10-19 版（`.ov-fdef` / `.ov-fact` 各自 `position:absolute; inset:0` 叠放、换透明度）
          已被 AICoop P5（2026-10-21）取代：§3.3「条件渲染互换，不是交叉淡化」⇒ CSS 切 `display`，
          底栏是定高 28 的盒子。行为闸在 `test_overview_5b::CardsAreFixedAndNothingWraps`（悬停前后量真实高度）。
        """
        ov = code(OVCARD)
        i = ov.index('<div data-ov-foot=""')
        foot = ov[i:ov.index("</div>", i)]
        self.assertIn("height: 28", foot[:foot.index(">")], "★★ 底栏不再定高 —— 悬停会把卡顶高")
        for cls in ("ov-fdef", "ov-fact"):
            with self.subTest(layer=cls):
                self.assertIn('className="%s"' % cls, foot, "★★ %s 不在同一个底栏里" % cls)
        css = (SRC / "components" / "ov" / "overview.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.ov-card \.ov-fact \{ display: none;", "★★ 操作组默认不是藏起来的")
        for f in (CARD, ACC):
            self.assertNotIn("CardActionBar", code(f), "★ 删掉的浮层又被引用了")
            self.assertNotIn("reserveActions", code(f), "★★ 预留逻辑又回来了 —— 它守的行为已经不存在了")

    def test_it_has_switch_rename_and_remove(self):
        """P5（2026-10-21）：改名从卡片挪进「详情」面板（交接包 §5 名字行可就地改），两档共用一个 `DetailSheet`。"""
        c = code(CARD)
        for tok, why in (("onShowDetail", "详情（含改名）"), ("onRemove", "移除"), ("onSwitch", "切换")):
            with self.subTest(action=why):
                self.assertIn(tok, c, f"★★ agy 卡缺「{why}」—— 与 codex 卡不对齐")
        ov = code(OV)
        self.assertEqual(ov.count("<DetailSheet "), 2, "★★ 两档的详情不是同一个面板")
        self.assertEqual(ov.count("onRename={(next) =>"), 2, "★★ 有一档的详情不能改名")
        self.assertIn("p.agyPool.renameTo(a.label, next)", ov, "★★ Gemini 改名没接 agy-rotate")
        self.assertIn('["rename", a.aid, next]', ov, "★★ Codex 改名身份不是 aid")

    def test_remove_asks_twice(self):
        """★★★ 移除不可逆。

        ✗ 2026-10-19 版（⋯ 菜单里「再点一次确认」）已被 AICoop P5（2026-10-21）取代：
          ⋯ → 删除 ⇒ Alert Dialog（默认焦点在「取消」）⇒ 确认后先隐藏、toast 带「撤销」，**toast 到期才真删**。
          行为闸在 `test_overview_p5::RenderedInteractions::test_delete_waits_for_the_undo_window`。
        """
        for f in (CARD, ACC):
            with self.subTest(f=f.name):
                self.assertRegex(code(f), r'\{ key: "remove", label: "删除", icon: <IcTrash />, bad: true, onClick: onRemove \}',
                                 "★★★ %s 的删除不在 ⋯ 里" % f.name)
        ov = code(OV)
        self.assertEqual(ov.count("remove: (a: "), 2, "★★ 两档的删除不是同一条路")
        self.assertEqual(ov.count("setConfirmDel({ id: a."), 2, "★★★ 有一档的删除没先弹确认")
        self.assertIn("onConfirm={() => { const c = confirmDel; setConfirmDel(null); c.go(); }}", ov,
                      "★★★ 确认框的「删除」没走延迟删除")

    def test_rename_does_not_submit_on_blur(self):
        """★ 与账号卡同一条：失焦不静默提交（P5：改名框在详情面板的名字行里，只有 ✓ / Enter 才提交）。"""
        c = code(SRC / "components" / "ov" / "OvLayers.tsx")
        i = c.index("function NameRow(")
        body = c[i:c.index("\n}\n", i)]
        self.assertIn("data-ov-rename", body, "★ 已知阳性：没找到改名框")
        self.assertNotIn("onBlur", body, "★ 失焦会提交改名")

    def test_the_rename_box_swallows_the_shortcut_keys(self):
        """★★ 全局 ⌘1~⌘9 是切号快捷键，输入框不拦的话打数字会切号
        （账号卡那边踩过一次）。"""
        c = code(SRC / "components" / "ov" / "OvLayers.tsx")
        i = c.index("data-ov-rename")
        j = c.index("onKeyDown", i)
        self.assertIn("e.stopPropagation()", c[j:j + 60], "★★ 在改名框里打数字会切号")


class TheThingsDeliberatelyLeftOut(unittest.TestCase):
    """★★★ 两头都要守：缺按钮是缺陷，**多一个扣错家钱的按钮更糟**。"""

    def test_the_probe_is_agys_own_not_codexs(self):
        """★★★ **这条 2026-09-13 被用户推翻并改写过。**

        旧的是「Gemini 档不许有 ProbeButton」，理由是探针扣 codex 的额度。
        用户原话：「探针做，做另外的机制，扣的是 agy 的额度啊…不是照搬 codex 的方法啊」。
        现在 agy 有了自己的探针（起 `agy -p`，花 agy 自己的额度），
        旧闸锁死的是一个**已经不成立的前提**。

        改写后守的是真正的那条：**Gemini 档绝不能去跑 codex 的那条命令。**
        """
        b = gemini_block()
        # P5 评审修复 2026-10-22：头部按钮经计费在途锁 `gx.probeAll()`；它的定义才是真发命令的地方，两处都验
        self.assertIn("gx.probeAll()", b, "★★ Gemini 档没有自己的探针")
        self.assertNotIn("cx.probeAll", b, "★★★ Gemini 档调了 codex 的全池探针")
        d = _member(code(OV), 'probeAll: () => withBilled("agy:*"')
        self.assertIn("agyPool.probe(", d, "★★ gx.probeAll 没有走 agyPool.probe()")
        b = b + d
        for bad in ('"probe-all"', '["probe", "--all"]', 'run("probe'):
            with self.subTest(token=bad):
                self.assertNotIn(bad, b,
                                 f"★★★ Gemini 档跑了 codex 的 {bad} —— 扣的是另一家的额度")

    def test_the_health_check_is_agys_own_too(self):
        """★ 同理：`health` 走 `agyPool.health()`（刷 token + 打 API，零消耗），
        不是 codex 那条 `run("health", ["health"])`。"""
        b = gemini_block()
        self.assertIn("agyPool.health()", b, "★★ Gemini 档没有检查 token")
        self.assertNotIn('run("health"', b, "★★★ Gemini 档跑了 codex 的 health")

    def test_the_bridge_still_refuses_login(self):
        """★★★ `login` 会起一个交互式 agy，GUI 里跑必然挂死。
        放开 rename/remove **不等于**把白名单变成摆设。"""
        rs = code(RS)
        i = rs.index("async fn run_agy_rotate(")
        m = re.search(r'ALLOWED: &\[&str\] = &\[([^\]]*)\]', rs[i:i + 400])
        self.assertIsNotNone(m, "★ 白名单不见了 —— 参数直接进 argv")
        allowed = set(re.findall(r'"([a-z-]+)"', m.group(1)))
        self.assertNotIn("login", allowed, "★★★ GUI 能跑 login —— 必然挂死")
        self.assertTrue(allowed <= {"quota", "switch", "live", "rename", "remove", "pin", "borrow",  # pin/borrow 2026-09-24 审过：只写池、不联网、不起 agy
                                    "health", "probe", "rotate", "auto-switch",
                                    # dawn-probe 2026-10-15 审过：--status/--enable/--disable/--time 只写池；
                                    # --no-wait 起的是与 `probe` 同一条 `agy -p`（非交互、不睡），默认关
                                    "dawn-probe"},
                        f"★★ 白名单里有没审过的子命令: {sorted(allowed)}")


class TheHarnessCanReachTheExpandedCard(unittest.TestCase):
    """★★★ 动作条**只在选中后出现**。没有一个能选中卡的打桩开关，
    这一整块在 harness 里一个像素都验不到，而截图会正常渲染、探针会报干净。"""

    def test_pickcard_exists(self):
        h = (ROOT / "codexbar" / "uishot" / "make_harness.py").read_text(encoding="utf-8")
        self.assertIn("p.get('pickcard')", h, "★★★ harness 选不中卡片 ⇒ 动作条验不到")
        # ★ 必须点**卡片本身**：名字那个 span 上没有 onClick，靠冒泡才到卡上。
        self.assertIn("[data-cards-grid] > div", h, "★ 点的不是卡片本体")




class ClickingARowGoesToTheOverviewNotTheUsagePage(unittest.TestCase):
    """★★ 用户 2026-09-14：「菜单栏我不同的账号点击进去，为什么是跳转到 ai 用量那里了？」

    根因：三档的「点行」语义被做得不一致 ——
      · 账号行（codex）走 `navigate-overview`（用户 2026-08-11 从三个 demo 里选的**方案 A**：
        点行开主界面、换号走行上的「切换」）
      · agy / grok 那两档走的是 `navigate-platform` ⇒ `setPage("traffic")` ⇒ **AI 用量**的平台详情页
      · 而 agy 的**当值号**没有 `onSwitch`，点行时还会退回 `onOpen` —— 同一档内两种行为

    现在三档一致：**点行 = 弹主界面的总览，并停在这一行所属的那一档**。
    """

    MB = (ROOT / "codexbar" / "src" / "MenuBar.tsx")
    ROW = (ROOT / "codexbar" / "src" / "components" / "AgyRow.tsx")

    def test_no_row_jumps_to_the_usage_page(self):
        c = code(self.MB)
        i = c.index('<div className="mb-list">')
        seg = c[i:c.index("</div>\n      </div>", i)]
        self.assertNotIn("navigate-platform", seg,
                         "★★ 又有行点击跳到 AI 用量的平台详情页了")

    def test_every_row_carries_its_own_tab(self):
        """★ 不带档的话主窗会停在**上次那一档** —— 点 Gemini 的行落在 Codex 档上。
        「打开主窗口」和「去哪一档」是两件事，前者不该顺带决定后者。"""
        # ★ 2026-10-19（交接包 4f）：行点击统一走 `openOverview(<请求账本的平台键>)` →
        #   `open-main-page {page:"overview", platform}`；四档各带自己的键（Gemini 的键是 `agy`）。
        c = code(self.MB)
        for k in ('openOverview("codex")', 'openOverview("agy")', 'openOverview("grok")',
                  'openOverview("claude")'):
            with self.subTest(tab=k):
                self.assertIn(k, c, f"★ 缺 {k}")

    def test_the_main_window_honours_the_tab(self):
        """★★ 只发不收等于没发。判据打在**监听那一侧**。"""
        # ★ 2026-10-19：`navigate-overview` 删除，统一走 `main-open-page {page, platform}`（PLAN §2.3）。
        c = code(APP)
        # ★ 2026-10-24：没点名平台时按「新的一次打开」落档（landingProvider，见 test_overview_landing.py）
        i = c.index('("main-open-page", (e) => {')
        seg = c[i:c.index("}),", i)]
        self.assertIn('} else if (pg === "overview") {', seg)
        self.assertIn('const pk0 = pf === "agy" ? "gemini" : pf;', seg, "★★ Gemini 行（键 agy）落不到 Gemini 档")
        self.assertIn('const named: PoolKey | null = pk0 === "codex" || pk0 === "claude" || pk0 === "gemini" || pk0 === "grok" ? pk0 : null;', seg,
                      "★ 没有校验载荷 ⇒ 脏值能改档")
        self.assertIn('const ovNamed = pg === "overview" ? named : null;', seg, "点名只对总览生效")
        self.assertIn("setProvider((cur) => landingProvider(cur, ovNamed, fresh))", seg, "★★ 主窗收到了档位却不切")
        self.assertNotIn('"navigate-overview"', c, "★ 旧事件的监听又回来了 —— 一次点击会跳两回")

    def test_clicking_an_agy_row_does_not_switch(self):
        """★★ 换号走名字旁边那个「切换」徽章，点行只开主界面 ——
        与账号行同一条语义。混着来的症状就是用户报的那个跳转。"""
        # ★ 2026-10-19：四家共用 `mb/QuotaRow` 的外形；点击语义在那里，AgyRow 只负责把 onOpen 交下去。
        q = code(self.ROW.parent / "mb" / "QuotaRow.tsx")
        i = q.index('<div className={`qrow')
        self.assertIn("onClick={switching ? undefined : onOpen}", q[i:i + 220],
                      "★★ 点行又变回切号了")
        c = code(self.ROW)
        self.assertNotRegex(c, r"onOpen=\{\s*onSwitch", "★★ AgyRow 把切号塞进了点行")
        self.assertGreaterEqual(c.count("onOpen={onOpen}"), 2, "★ AgyRow 有一种形态没把 onOpen 交下去")


# ⚠️ `TheShortcutBadgeOnlyAppearsWhereItWorks`（2026-09-14：⌘N 按档切号 + 角标只在接了线的档画）
#   2026-10-16 被用户的新要求取代：⌘N 在总览上切 Codex/Gemini/Grok 档，不再切号，卡上角标撤掉。
#   新契约与闸在 `tests/test_overview_shortcut_switches_tab.py`。


if __name__ == "__main__":
    unittest.main()
