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
        两张卡都把操作交给共用的 `OvCard`（`actions=` + ⋯ 菜单），谁也不自己画一份。"""
        for f in (CARD, ACC):
            c = code(f)
            with self.subTest(f=f.name):
                i = c.index("<OvCard ")
                self.assertIn("actions={actions}", c[i:c.index("/>", c.index("footRight=", i))],
                              "★★ %s 的操作不是交给共用卡片画的" % f.name)
                self.assertIn("<OvMenu ", c, "★★ %s 没有 ⋯ 菜单" % f.name)

    def test_the_action_bar_is_the_same_floating_overlay(self):
        """★★ 与账号卡**同款浮层**（§5c 页面统一性）。

        ⚠️ 2026-09-21 换代：这条原来断言的是「同排预留一条隐形动作条」——
          那套机制（`reserveActions` / `visibility:hidden` 占位）是为了让**会长高的**
          内嵌动作条不把兄弟卡顶歪。用户当天要求「不改变高度，弹出功能按钮」，
          动作条改成绝对定位的浮层 ⇒ **卡片高度恒定，预留的理由本身消失了**，
          连代码一起删（本仓：删功能就连组件本体一起删，不留骨架）。
        ★ 真正的行为闸在 `test_card_uniformity.SelectingACardNeverChangesAnyHeight`
          （量真实高度）；这里只守「两张卡用的是同一套」。
        """
        # ★ 2026-10-19：`CardActionBar` 浮层随交接包 page5 删除，操作改成「底栏原位换成操作」：
        #   `.ov-fact` 与事实底栏叠在**同一个 28 高的槽**里（绝对定位），换的是透明度不是布局 ⇒ 卡片仍定高。
        #   行为闸在 `test_overview_5b::CardsAreFixedAndNothingWraps`（悬停前后量真实高度）。
        ov = code(OVCARD)
        for cls in ("ov-fdef", "ov-fact"):
            with self.subTest(layer=cls):
                i = ov.index('<div className="%s"' % cls)
                tag = ov[i:ov.index(">", ov.index("style={{", i))]
                self.assertIn('position: "absolute", inset: 0', tag, "★★ %s 回到文档流里 —— 悬停会把卡顶高" % cls)
        for f in (CARD, ACC):
            self.assertNotIn("CardActionBar", code(f), "★ 删掉的浮层又被引用了")
            self.assertNotIn("reserveActions", code(f), "★★ 预留逻辑又回来了 —— 它守的行为已经不存在了")

    def test_it_has_switch_rename_and_remove(self):
        c = code(CARD)
        for tok, why in (("onRename", "改名"), ("onRemove", "移除"), ("onSwitch", "切换")):
            with self.subTest(action=why):
                self.assertIn(tok, c, f"★★ agy 卡缺「{why}」—— 与 codex 卡不对齐")

    def test_remove_asks_twice(self):
        """★★★ 移除不可逆。把「确认删除」也压成图标等于让人凭记忆点。"""
        # ★ 2026-10-19：删除收进 ⋯ 菜单，二段确认由共用的 `OvMenu` 做（第一次点只换文字，再点才执行）。
        #   判据仍打在**分支条件**和**按钮做什么**上，不是「有没有确认两个字」。行为闸在
        #   `test_delete_confirm_one_row`（真 bundle、两池：第一次点零命令）。
        c = code(CARD)
        self.assertIn('{ key: "remove", label: "从池里移除", bad: true, confirm: "再点一次确认移除", onClick: onRemove', c,
                      "★★★ agy 卡的移除没挂二段确认")
        m = code(OVCARD)
        self.assertIn("if (it.confirm && arm !== it.key) { setArm(it.key); return; }", m,
                      "★★★ 第一次点就执行了 —— 不可逆操作一键就走")
        self.assertIn('{ key: "remove", label: "删除这个号"', code(ACC), "★ 账号卡的删除不在 ⋯ 里")

    def test_rename_does_not_submit_on_blur(self):
        """★ 与账号卡同一条：`onBlur` 一律放弃，不静默提交。"""
        c = code(CARD)
        i = c.index("onBlur")
        self.assertIn("setEditing(null)", c[i:i + 80], "★ onBlur 静默提交了")

    def test_the_rename_box_swallows_the_shortcut_keys(self):
        """★★ 全局 ⌘1~⌘9 是切号快捷键，输入框不拦的话打数字会切号
        （账号卡那边踩过一次）。"""
        c = code(CARD)
        i = c.index("onKeyDown")
        self.assertIn("stopPropagation", c[i:i + 120], "★★ 在改名框里打数字会切号")


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
        self.assertIn("agyPool.probe(", b, "★★ Gemini 档没有自己的探针")
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


if __name__ == "__main__":
    unittest.main()


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
        i = c.index('listen<{ page?: string; platform?: string | null }>("main-open-page"')
        seg = c[i:c.index("}),", i)]
        self.assertIn('} else if (pg === "overview") {', seg)
        self.assertIn('const pk = pf === "agy" ? "gemini" : pf;', seg, "★★ Gemini 行（键 agy）落不到 Gemini 档")
        self.assertIn("setProvider(pk)", seg, "★★ 主窗收到了档位却不切")
        # ★ 缺省必须不动 provider —— 不带档 / 脏值都不改档
        self.assertIn('if (pk === "codex" || pk === "claude" || pk === "gemini" || pk === "grok") setProvider(pk);', seg,
                      "★ 没有校验载荷 ⇒ 脏值能改档")
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


