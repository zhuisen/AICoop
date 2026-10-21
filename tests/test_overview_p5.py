"""总览 P5 定稿（交接包 `~/Downloads/AICoop_handoff/boards/05_overview/P5_Final.dc.html`，2026-10-21）的行为闸。

两层：
  · 纯函数（node 直接跑真文件）：Toast 堆的几何（`toastStack.ts`）、⌘K 的筛选 / 移动 / 按键判定（`cmdk.ts`）；
  · 真点击（harness，`127.0.0.1:3304`，Playwright 发真实鼠标事件 —— CSS `:hover` 会生效）：
    用卡弹层 Enter 不确认、删除要等撤销窗口过去才真删、置顶进置顶区且撤销插回原位、停轮换换标签、
    卡宽 < 240 时 ⚡ 进 ···、⌘K。
★ harness 的 `run_rotate` 打桩会记下每次调用（`window.__RUN_ROTATE__`），并真改 `pin` / `rotate` 的 STATE ——
  所以这里断言的是「发出去了什么命令」，不是「按钮上写了什么字」。
"""
try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401
import json
import subprocess
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
BASE = "http://127.0.0.1:3304/harness.html?nav=home"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def node(mod, expr):
    script = "import('%s').then(m => console.log(JSON.stringify(%s)))" % ((SRC / mod).as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class ToastStackGeometry(unittest.TestCase):
    def test_collapsed(self):
        g = node("toastStack.ts", "m.toastStackGeom(4, false)")
        self.assertEqual(g["height"], 40 + 2 * 8, "收起：40 + min(2, n-1)*8")
        ks = [it for it in g["items"]]
        self.assertEqual(ks[-1], {"y": 0, "scale": 1, "opacity": 1}, "最新一条在最前、不缩不透")
        self.assertEqual(ks[-2]["y"], -8)
        self.assertAlmostEqual(ks[-2]["scale"], 0.95)
        self.assertAlmostEqual(ks[-3]["opacity"], 0.6)
        self.assertEqual(ks[0]["opacity"], 0, "k > 2 的那条看不见")

    def test_expanded(self):
        g = node("toastStack.ts", "m.toastStackGeom(3, true)")
        self.assertEqual(g["height"], 40 + 2 * 48)
        self.assertEqual([it["y"] for it in g["items"]], [-96, -48, 0])
        self.assertTrue(all(it["opacity"] == 1 and it["scale"] == 1 for it in g["items"]))

    def test_empty(self):
        self.assertEqual(node("toastStack.ts", "m.toastStackGeom(0, false)"), {"height": 0, "items": []})


class CmdKLogic(unittest.TestCase):
    ITEMS = json.dumps([{"label": "切到 号%d" % i, "hint": "Codex"} for i in range(5)]
                       + [{"label": "打开 设置", "hint": "⌘,"}, {"label": "刷新全池", "hint": "免费"},
                          {"label": "打开 中转站", "hint": ""}])

    def test_filter_caps_at_seven_and_matches_hint(self):
        self.assertEqual(len(node("cmdk.ts", "m.cmdkFilter(%s, '')" % self.ITEMS)), 7)
        self.assertEqual([x["label"] for x in node("cmdk.ts", "m.cmdkFilter(%s, '免费')" % self.ITEMS)], ["刷新全池"],
                         "提示文字也参与筛选")
        self.assertEqual(node("cmdk.ts", "m.cmdkFilter(%s, 'codex')" % self.ITEMS)[0]["label"], "切到 号0", "不分大小写")

    def test_move_clamps(self):
        self.assertEqual(node("cmdk.ts", "[m.cmdkMove(0,-1,3), m.cmdkMove(2,1,3), m.cmdkMove(1,1,3), m.cmdkMove(0,1,0)]"), [0, 2, 2, 0])

    def test_only_plain_cmd_k(self):
        e = "{metaKey:%s,ctrlKey:%s,shiftKey:%s,altKey:false,key:'%s'}"
        got = node("cmdk.ts", "[%s].map(m.isCmdK)" % ",".join([e % ("true", "false", "false", "k"), e % ("false", "true", "false", "K"),
                                                              e % ("true", "false", "true", "k"), e % ("false", "false", "false", "k")]))
        self.assertEqual(got, [True, True, False, False])


class ToastQueueLogic(unittest.TestCase):
    """`toastQueue.ts`：到期 / 挤出 / 撤销 / 悬停暂停的次数与时刻（四方评审 2026-10-22：「删除」靠它到期才真删）。"""

    def run_q(self, body):
        return node("toastQueue.ts", "(() => { let s = m.tqEmpty(), r; const out = {}; %s; return out; })()" % body)

    def test_evicted_exactly_once_and_never_again(self):
        o = self.run_q("for (let i = 1; i <= 5; i++) { r = m.tqPush(s, i, 3200, 0, 4); s = r.s; out['p' + i] = r.evicted; }"
                       " out.ids = s.items.map(x => x.id); out.due = m.tqDue(s, 3200).expired")
        self.assertEqual([o["p%d" % i] for i in range(1, 6)], [[], [], [], [], [1]], "第 5 条把最老那条挤出，只挤一次")
        self.assertEqual(o["ids"], [2, 3, 4, 5])
        self.assertEqual(o["due"], [2, 3, 4, 5], "被挤出的那条不会再到期一次")

    def test_hold_pauses_and_resume_keeps_the_remaining_time(self):
        o = self.run_q("s = m.tqPush(s, 1, 3200, 0, 4).s; s = m.tqHold(s, true, 1000);"
                       " out.during = m.tqDue(s, 99999).expired; out.next = m.tqNext(s); s = m.tqHold(s, true, 5000);"
                       " s = m.tqHold(s, false, 10000); out.after1 = m.tqDue(s, 12100).expired; out.after2 = m.tqDue(s, 12200).expired")
        self.assertEqual(o["during"], [], "悬停中一条都不到期")
        self.assertIsNone(o["next"], "悬停中不挂计时器")
        self.assertEqual(o["after1"], [], "★★ 离开后还剩 2.2 s，不是立刻消失（原来只再等 1.2 s）")
        self.assertEqual(o["after2"], [1])

    def test_remove_means_it_never_expires(self):
        o = self.run_q("s = m.tqPush(s, 1, 3200, 0, 4).s; s = m.tqRemove(s, 1); out.d = m.tqDue(s, 99999).expired; out.n = m.tqNext(s)")
        self.assertEqual(o, {"d": [], "n": None}, "撤销 / 点掉之后不再到期（删除不提交）")

    def test_rearm_restarts_only_that_one(self):
        o = self.run_q("s = m.tqPush(s, 1, 3200, 0, 4).s; s = m.tqPush(s, 2, 3200, 0, 4).s; s = m.tqRearm(s, 1, 8000, 3000);"
                       " out.d = m.tqDue(s, 3200).expired; out.has = m.tqHas(s, 1); out.miss = m.tqRearm(s, 9, 100, 0).items.length")
        self.assertEqual(o, {"d": [2], "has": True, "miss": 2}, "原地换字只重算那一条；不在堆里的不凭空加一条")


class UndoPinStep(unittest.TestCase):
    """撤销只逆转这一步，作用在撤销那一刻的顺序上（四方评审 codex#4）。"""

    def test_undo_pin_keeps_a_later_unpin(self):
        # [A,B] → 置顶 C → 取消 A → 撤销「置顶 C」⇒ [B]，不是 [A,B]
        self.assertEqual(node("cardOrder.ts", "m.undoPinStep(['B','C'], 'C', null)"), ["B"])

    def test_undo_unpin_goes_back_to_its_rank(self):
        self.assertEqual(node("cardOrder.ts", "[m.undoPinStep(['B','C'], 'A', 0), m.undoPinStep(['B'], 'A', 5), m.undoPinStep([], 'A', 1)]"),
                         [["A", "B", "C"], ["B", "A"], ["A"]])


def _harness_up():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    try:
        urllib.request.urlopen(BASE, timeout=2).read(1)
        return True
    except Exception:
        return False


class RenderedInteractions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _harness_up():
            raise unittest.SkipTest("没有 playwright 或 harness 静态服务（3304）没在跑")
        from playwright.sync_api import sync_playwright
        cls._pw = sync_playwright().start()
        cls.br = cls._pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls._pw.stop()

    def page(self, w=1200, h=800, q=""):
        pg = self.br.new_page(viewport={"width": w, "height": h})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + q, timeout=30000)
        pg.wait_for_timeout(2200)
        self.addCleanup(pg.close)
        self.addCleanup(lambda: self.assertEqual(errs, [], "页面报错"))
        n = pg.locator("[data-cards-grid] > [data-aid]").count()
        self.assertGreaterEqual(n, 4, "★ 卡片没渲染出来 —— 下面的断言没有判别力")
        return pg

    def calls(self, pg, verb):
        return pg.evaluate("(v) => (window.__RUN_ROTATE__ || []).filter(a => a[0] === v)", verb)

    def cards(self, pg):
        return pg.locator("[data-cards-grid] > [data-aid]")

    def test_credit_popover_enter_never_spends_a_card(self):
        pg = self.page()
        card = pg.locator("[data-cards-grid] > [data-aid]:has([data-use-credit-row])").first
        card.hover()
        card.locator("[data-card-chip]").click()
        pop = card.locator("[data-use-credit-dialog]")
        self.assertTrue(pop.is_visible())
        first = pop.locator("[data-use-credit-row]").first.get_attribute("data-use-credit-row")
        self.assertEqual(pop.locator("[data-selected]").get_attribute("data-use-credit-row"), first, "默认选最先过期那张")
        pg.keyboard.press("Enter")
        pg.keyboard.press("Enter")
        self.assertEqual(self.calls(pg, "use-credit"), [], "★★ 连按回车不能花掉一张卡")
        # 焦点落在「确认使用」/ 单选行上时的回车、空格也不能花卡（评审 Opus M5：上面那两下回车只是在 chip 上开关）
        if not pop.is_visible():
            card.hover(); card.locator("[data-card-chip]").click()
        pop.locator("[data-use-credit-confirm]").focus()
        pg.keyboard.press("Enter"); pg.keyboard.press(" ")
        pop.locator("[data-use-credit-row]").first.focus()
        pg.keyboard.press("Enter")
        self.assertEqual(self.calls(pg, "use-credit"), [], "★★ 焦点在确认钮 / 单选行上按回车或空格也不能花卡")
        if not pop.is_visible():
            card.hover(); card.locator("[data-card-chip]").click()
        pop.locator("[data-use-credit-confirm]").click()
        pg.wait_for_timeout(300)
        got = self.calls(pg, "use-credit")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][2:], ["--card", first], "确认时传的是选中那张的 id")

    def test_delete_waits_for_the_undo_window(self):
        pg = self.page()
        card = self.cards(pg).nth(1)
        aid = card.get_attribute("data-aid")
        card.hover()
        card.locator("[data-ov-ab=more]").click()
        card.locator("[data-ov-mi=remove]").click()
        self.assertIn("codex-rotate login", pg.locator("[data-ov-confirm]").inner_text())
        pg.locator("[data-confirm-delete]").click()
        pg.wait_for_timeout(300)
        self.assertEqual(pg.locator(f"[data-cards-grid] > [data-aid='{aid}']").count(), 0, "确认后卡片立刻消失")
        self.assertEqual(self.calls(pg, "remove"), [], "★★ 撤销窗口还没过，不许真删")
        pg.locator("[data-toast-undo]").first.click()
        pg.wait_for_timeout(4000)
        self.assertEqual(pg.locator(f"[data-cards-grid] > [data-aid='{aid}']").count(), 1, "撤销后卡片回来")
        self.assertEqual(self.calls(pg, "remove"), [], "★★ 撤销了就永远不删")
        # 再删一次、放着不动 ⇒ toast 到点才真删，且只删一次
        card = pg.locator(f"[data-cards-grid] > [data-aid='{aid}']")
        card.hover(); card.locator("[data-ov-ab=more]").click(); card.locator("[data-ov-mi=remove]").click()
        pg.locator("[data-confirm-delete]").click()
        pg.mouse.move(5, 5)
        pg.wait_for_timeout(4200)
        self.assertEqual(len(self.calls(pg, "remove")), 1, "撤销窗口过去 ⇒ 真删，恰好一次")

    def test_pin_moves_into_the_pinned_section_and_undo_restores_order(self):
        pg = self.page()
        pinned0 = pg.locator("[data-cards-grid] > [data-ov-pinned]").evaluate_all("els => els.map(e => e.dataset.aid)")
        rest = pg.locator("[data-cards-grid] > [data-aid]:not([data-ov-pinned])").first
        aid = rest.get_attribute("data-aid")
        rest.hover()
        rest.locator("[data-pin-ghost]").click()
        pg.wait_for_timeout(900)
        pinned1 = pg.locator("[data-cards-grid] > [data-ov-pinned]").evaluate_all("els => els.map(e => e.dataset.aid)")
        self.assertEqual(pinned1, pinned0 + [aid], "新置顶的号排在置顶区末尾（先置顶先用）")
        self.assertIn("第 %d 个用" % len(pinned1), pg.locator("[data-toast]").last.inner_text())
        self.assertEqual(pg.locator("[data-ov-sec]").count(), 2, "有置顶时才出两个分区标题")
        pg.locator("[data-toast-undo]").last.click()
        pg.wait_for_timeout(900)
        pinned2 = pg.locator("[data-cards-grid] > [data-ov-pinned]").evaluate_all("els => els.map(e => e.dataset.aid)")
        self.assertEqual(pinned2, pinned0, "撤销 = 整份恢复原来的置顶顺序")

    def test_unpin_undo_inserts_back_at_the_same_rank(self):
        pg = self.page()
        pinned0 = pg.locator("[data-cards-grid] > [data-ov-pinned]").evaluate_all("els => els.map(e => e.dataset.aid)")
        self.assertGreaterEqual(len(pinned0), 2, "★ 夹具里置顶号不足 2 个，验不了「插回原位」（夹具变了，先修夹具，不许 skip）")
        first = pg.locator(f"[data-cards-grid] > [data-aid='{pinned0[0]}']")
        first.locator("[data-pin-badge]").click()
        pg.wait_for_timeout(900)
        self.assertNotIn(pinned0[0], pg.locator("[data-cards-grid] > [data-ov-pinned]").evaluate_all("els => els.map(e => e.dataset.aid)"))
        pg.locator("[data-toast-undo]").last.click()
        pg.wait_for_timeout(900)
        self.assertEqual(pg.locator("[data-cards-grid] > [data-ov-pinned]").evaluate_all("els => els.map(e => e.dataset.aid)"), pinned0,
                         "★ 取消第 1 个再撤销，它要回到第 1 个，不是排到末尾")

    def test_undo_of_an_older_pin_keeps_a_later_unpin(self):
        """[P1,P2] → 置顶 X → 取消 P1 → 点「置顶 X」那条的撤销 ⇒ [P2]（原来会把 P1 也恢复回来）。"""
        pg = self.page()
        pinned0 = pg.locator("[data-cards-grid] > [data-ov-pinned]").evaluate_all("els => els.map(e => e.dataset.aid)")
        self.assertGreaterEqual(len(pinned0), 2)
        x = pg.locator("[data-cards-grid] > [data-aid]:not([data-ov-pinned])").first
        xa = x.get_attribute("data-aid")
        x.hover(); x.locator("[data-pin-ghost]").click(); pg.wait_for_timeout(900)
        pg.locator(f"[data-cards-grid] > [data-aid='{pinned0[0]}'] [data-pin-badge]").click(); pg.wait_for_timeout(900)
        pg.locator("[data-toast-stack]").hover(); pg.wait_for_timeout(500)   # 悬停展开堆，才点得到后面那条
        pg.locator("[data-toast]:has-text('已置顶') [data-toast-undo]").click(); pg.wait_for_timeout(900)
        got = pg.locator("[data-cards-grid] > [data-ov-pinned]").evaluate_all("els => els.map(e => e.dataset.aid)")
        self.assertEqual(got, pinned0[1:], "★★ 撤销「置顶 X」把后来的「取消 P1」也撤了")
        self.assertNotIn(xa, got)

    def test_billed_probe_never_overlaps_for_one_account(self):
        """计费探针的在途锁（四方评审 codex#3 / Opus M1）：同一个号在途时，卡上再点、其它动作熄掉转圈之后再点、
        ⌘K 再发，都不许发第二次；全池在途时单号也不发。"""
        pg = self.page(q="&probe_delay=6000")
        # ★ 选 ⌘K「探针 · 下一个号（X）」打的那个号（`board.next`）。原来取「第一张不在用的卡」，两者只在夹具
        #   某个时刻碰巧是同一个号 —— 夹具的额度窗口按真实时间走，过了某个钟点就分开，⌘K 那一下打到另一个号上，
        #   闸就红了（2026-10-22 06 点实测：卡 5530 vs ⌘K qq55）。
        pg.keyboard.press("Meta+k"); pg.keyboard.type("探针"); pg.wait_for_timeout(200)
        lab = pg.locator("[data-cmdk-item=probe]").inner_text() if pg.locator("[data-cmdk-item=probe]").count() else ""
        pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
        node = lab.split("（")[-1].split("）")[0] if "（" in lab else ""
        nxt = pg.evaluate("""(n) => { const c = [...document.querySelectorAll('[data-cards-grid] > [data-aid]')]
            .find(c => c.innerText.split('\\n').map(x => x.trim()).includes(n));
            return c && c.dataset.aid; }""", node)
        self.assertTrue(nxt, "⌘K 里没有「探针 · 下一个号」，或那个号没有卡 —— 打谁无从核对（%r）" % lab)
        card = pg.locator(f"[data-cards-grid] > [data-aid='{nxt}']")
        card.hover(); card.locator("[data-ov-ab=probe]").click()
        pg.wait_for_timeout(1700)                                    # 过了 1.5 s 的连点窗口
        other = pg.locator("[data-cards-grid] > [data-aid]:not([data-ov-off])").nth(3)
        other.hover(); other.locator("[data-ov-ab=rotate]").click()  # 另一个动作跑完会熄掉单槽的 loadingAction
        pg.wait_for_timeout(600)
        card.hover(); card.locator("[data-ov-ab=probe]").click(force=True)
        pg.keyboard.press("Meta+k"); pg.keyboard.type("探针")
        if pg.locator("[data-cmdk-item=probe]").count():
            pg.locator("[data-cmdk-item=probe]").dispatch_event("mousedown")
        pg.wait_for_timeout(300)
        probes = [c for c in self.calls(pg, "probe") if c[1] != "--all"]
        self.assertEqual(len(probes), 1, "★★★ 同一个号的计费探针在途时又发了一次：%s" % probes)
        pg.wait_for_timeout(6500)
        card.hover(); card.locator("[data-ov-ab=probe]").click()
        pg.wait_for_timeout(300)
        self.assertEqual(len([c for c in self.calls(pg, "probe") if c[1] != "--all"]), 2, "已知阳性：回来之后能再发")

    def test_pending_delete_survives_leaving_the_page(self):
        """撤销窗口里切到别的页再回来：卡片仍隐藏；窗口过去只删一次（评审 agy#1 / codex#2）。"""
        pg = self.page()
        card = self.cards(pg).nth(1)
        aid = card.get_attribute("data-aid")
        card.hover(); card.locator("[data-ov-ab=more]").click(); card.locator("[data-ov-mi=remove]").click()
        pg.locator("[data-confirm-delete]").click()
        pg.mouse.move(5, 5)
        pg.keyboard.press("Meta+k"); pg.keyboard.type("设置"); pg.keyboard.press("Enter")
        pg.wait_for_timeout(500)
        self.assertEqual(pg.locator("[data-ov-page]").count(), 0, "已知阳性：真的离开了总览")
        pg.locator("button[data-page='overview']").click()
        pg.wait_for_timeout(600)
        self.assertEqual(pg.locator(f"[data-cards-grid] > [data-aid='{aid}']").count(), 0, "★★ 回到总览，撤销窗口里的号又出现了")
        pg.wait_for_timeout(3500)
        self.assertEqual([c for c in self.calls(pg, "remove")], [["remove", aid]], "★★ 窗口过去只删一次，且用 aid（不用会变的名字）")
        pg.wait_for_timeout(1500)
        self.assertEqual(pg.locator(f"[data-cards-grid] > [data-aid='{aid}']").count(), 0, "删成功之后不再出现")

    def test_rotate_off_swaps_the_tag_and_lights_the_mark(self):
        pg = self.page()
        card = pg.locator("[data-cards-grid] > [data-aid]:not([data-ov-off])").nth(1)
        aid = card.get_attribute("data-aid")
        card.hover()
        card.locator("[data-ov-ab=rotate]").click()
        pg.wait_for_timeout(900)
        c = pg.locator(f"[data-cards-grid] > [data-aid='{aid}']")
        self.assertEqual(c.get_attribute("data-ov-off"), "", "停轮换的号留在主网格里")
        self.assertEqual(c.locator("[data-ov-tag]").first.get_attribute("data-ov-tag"), "off")
        self.assertIn("不轮换", c.locator("[data-ov-tag]").first.inner_text())
        self.assertEqual(c.locator("[data-rot-mark]").count(), 1, "名称行的琥珀 ⊘ 亮起")
        self.assertEqual(self.calls(pg, "rotate")[-1], ["rotate", aid, "--off"])
        c.locator("[data-rot-mark]").click()
        pg.wait_for_timeout(900)
        self.assertEqual(self.calls(pg, "rotate")[-1], ["rotate", aid, "--on"], "点 ⊘ 角标 = 放回自动轮换")
        self.assertIsNone(c.get_attribute("data-ov-off"))

    def test_probe_moves_into_the_menu_below_240(self):
        pg = self.page()
        card = self.cards(pg).nth(1)
        card.hover()
        self.assertTrue(card.locator("[data-ov-ab=probe]").is_visible(), "1200 宽（卡 ~266）底栏有 ⚡")
        pg.add_style_tag(content="[data-cards-grid]{grid-template-columns:repeat(4,230px)!important}")
        card.hover()
        self.assertFalse(card.locator("[data-ov-ab=probe]").is_visible(), "卡宽 230 < 240 ⇒ 底栏 ⚡ 藏起来")
        card.locator("[data-ov-ab=more]").click()
        self.assertTrue(card.locator("[data-ov-mi=probe]").is_visible(), "⚡ 进 ··· 首项")
        pg.add_style_tag(content="[data-cards-grid]{grid-template-columns:repeat(4,245px)!important}")
        self.assertFalse(card.locator("[data-ov-mi=probe]").is_visible(), "卡宽 245 ⇒ 菜单里没有探针")

    def test_cmdk_opens_filters_and_closes(self):
        pg = self.page()
        pg.keyboard.press("Meta+Shift+K")
        self.assertEqual(pg.locator("[data-ov-cmdk]").count(), 0, "Shift+⌘K 不是它")
        pg.keyboard.press("Meta+k")
        self.assertEqual(pg.locator("[data-ov-cmdk]").count(), 1)
        self.assertLessEqual(pg.locator("[data-cmdk-item]").count(), 7)
        pg.keyboard.type("刷新")
        self.assertEqual(pg.locator("[data-cmdk-item]").all_inner_texts()[0].split("\n")[1], "刷新全池")
        pg.keyboard.press("Escape")
        self.assertEqual(pg.locator("[data-ov-cmdk]").count(), 0)
        pg.locator("[data-ov-kchip]").click()
        self.assertEqual(pg.locator("[data-ov-cmdk]").count(), 1, "标题旁的 ⌘K chip 也能打开")


if __name__ == "__main__":
    unittest.main(verbosity=2)
