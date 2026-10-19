"""★★ **缺一个额度窗口时，画出来并说明为什么 —— 不许留一行空白。**

## 由来（2026-09-13，用户连报两次）

    「我有个号缺少了5小时额度窗口」      → agy 卡
    「还存在一个问题 gemini 和 grok 缺少了 5h 额度」 → 菜单栏两行

四处都是同一个写法：`visibility: hidden` 的同构占位行（为了跨卡对齐），
于是用户看到的是**一整行空白**，连 `—` 都没有。

本仓 §5d 的规矩是「**读不到显 `—`，不显 `0`**」，而"什么都不显"比显 0 更糟：
它把「读不到」伪装成「这里本该有点什么」，而两者的下一步动作完全不同。

## ★ 两种缺失的文案**必须不同**，这是这一组闸真正在守的东西

    agy 缺某格   = **这一次没取到**（2026-09-15 起走 `retrieveUserQuotaSummary`，
                    每个号按账号直接拿到完整摘要含周窗口）→ 点 ↻ 重取
    grok 缺「5h」 = **上游根本没有这个窗口**（实测 `window_minutes = 10080`，只有周）
                    → 永远看不到，等也没用

合并成一句话，就等于把两种状态又折叠回同一个值 —— 正是本仓反复吃亏的那一类。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C = ROOT / "codexbar" / "src" / "components"
#: 「缺一格要说清为什么」只对 **agy** 成立了。
#: ★ grok 的那一格 2026-09-15 被用户直接取消（「grok 修改，取消 5h 窗口」）——
#:   xAI 只回 WEEKLY，那一格**永远不会有数**，补三版（隐藏行 → `—` → 「无此窗口」）
#:   都是在给一件不存在的东西找体面画法。现在的判据在 `GrokShowsOnlyItsOwnWindow`。
TARGETS = {
    "AgyCard": C / "AgyCard.tsx",
    "AgyRow": C / "AgyRow.tsx",
}
GROK = {"GrokCard": C / "GrokCard.tsx", "GrokRow": C / "GrokRow.tsx"}


def code(p):
    """剥注释 —— 本仓注释密度极高，闸撞上自己的说明文字已是惯犯（空守卫形态⑫）。"""
    s = p.read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//.*", "", s)


class NoWindowRowIsSilentlyBlank(unittest.TestCase):

    #: 窗口行的渲染入口。判据要切到**这一段**，不能整文件扫 ——
    #: `AgyCard` 的**动作条**也用 `visibility: hidden` 占位（那是对的：兄弟卡要等高），
    #: 整文件断言会把它一起判红（实测假红一次）。
    # 2026-10-19：总览卡的窗口行由 `toWin()` 生成、交给共用外壳 `ov/OvCard::OvWinRow` 画。
    ROW_ENTRY = {"AgyCard": "const toWin = ", "AgyRow": "MB_WIN_SLOTS.map",
                 "GrokCard": "slotRows.map", "GrokRow": "className=\"mb-row-meta\""}

    def _rows_region(self, name):
        c = code(TARGETS[name])
        i = c.index(self.ROW_ENTRY[name])
        return c[i:i + 1800]

    def test_no_invisible_placeholder_rows(self):
        """★★ `visibility: hidden` 是这个缺陷的**唯一写法**，四处都曾用它。"""
        for name in TARGETS:
            with self.subTest(component=name):
                self.assertNotIn('visibility: "hidden"', self._rows_region(name),
                                 f"★★ {name} 又用隐藏行占位了 —— 用户看到的是一整行空白")

    #: 缺失行上**写给人看的那句话**。两张卡 2026-09-14 从 `—  ↻—` 改成了直接写原因
    #: （用户实报「我的 grok 五小时额度没刷新？还丢失了？」）；两行受菜单栏宽度限制仍用 `↻—`。
    #: ★ 判据因此改成「**这一行上有没有一个能读的结论**」，而不是某个字符。
    #:   上一版钉的是字面 `↻—`，于是把 `—` 换成更清楚的中文时**闸自己红了**，
    #:   而语义是变好的 —— 逐字匹配守的是"代码长什么样"，不是"用户看不看得懂"。
    #: ★ 2026-10-19（交接包 4f）：菜单栏行的外形搬进 `mb/QuotaRow`。AgyRow 给缺失格 `refill: "—"`，
    #:   QuotaRow 统一画成 `—` + `↻—` 并**照样画条槽**（高度判据见下面那条测试的 AgyRow 分支）。
    SAYS = {"AgyCard": ("这次没读到",), "AgyRow": ('refill: "—"',)}

    def test_every_component_can_render_a_dash(self):
        """★ 正面：四处都必须有那个缺失行。只验"没有隐藏行"的话，
        把整行删掉（对齐一起塌）也能变绿。"""
        for name, p in TARGETS.items():
            with self.subTest(component=name):
                c = code(p)
                self.assertTrue(any(w in c for w in self.SAYS[name]),
                                f"★ {name} 没有缺失窗口那一行（找不到 {self.SAYS[name]}）")

    def test_the_missing_row_still_keeps_its_height(self):
        """★★ 跨卡/跨行对齐靠这一行撑着。把它整个删掉，旁边的卡就会比它高一截，
        而 harness 的折行探针对"少了一行"是**沉默**的。
        判据：缺失分支里仍然画着**标签 + 条槽**。★ 条槽是高度的来源，所以它是这条闸的核心；
        2026-09-14 我一度把它删掉（想给中文腾地方），这条闸当场红 —— 红得对。"""
        for name, p in TARGETS.items():
            if name == "AgyRow":
                # ★ 条槽现在由 QuotaRow 的 `Cell` 画：读不到（`pct == null`）的格子走的是**同一段 JSX**，
                #   条槽那个 span 不受 `pct` 条件控制。判据打在 `Cell` 函数体上：过了「这家没有这个窗口」
                #   那条 early-return 之后，条槽必须无条件出现，且读不到时只是把填充宽度算成 0。
                with self.subTest(component=name):
                    q = code(C / "mb" / "QuotaRow.tsx")
                    body = q[q.index("function Cell("):]
                    after = body[body.index("if (!w) {"):]
                    after = after[after.index("}\n") + 2:]
                    self.assertIn('background: "var(--track)"', after, "★★ 缺失格没有条槽 —— 高度对不齐")
                    self.assertIn("w.pct == null ? 0", after, "★★ 缺失格的条槽不是空槽")
                    self.assertIn("↻{w.refill}", after, "★ 缺失格没写 ↻—")
                continue
            if name == "AgyCard":
                # ★ 2026-10-19：缺失格交给 `OvWinRow` 画：条槽那个 span **不受 pct 条件控制**，填充才受。
                with self.subTest(component=name):
                    c = code(p)
                    self.assertRegex(c, r'if \(!row\) return \{ label: lbl, pct: null, reset: "", kind, absent: true, note: "没读到"',
                                     "★★ 缺失格没有交给窗口行去画（或没写「没读到」）")
                    ov = code(C / "ov" / "OvCard.tsx")
                    body = ov[ov.index("export function OvWinRow("):]
                    body = body[:body.index("\n}\n")]
                    i = body.index('background: "var(--track)"')
                    self.assertNotIn("w.pct != null", body[max(0, i - 200):i], "★★ 条槽被 pct 条件包住了 —— 缺失格没有槽")
                    self.assertIn("{w.pct != null && (", body[i:], "★ 填充应只在有数时画")
                continue
            with self.subTest(component=name):
                c = code(p)
                # ⚠️ 锚点要落在**渲染那一段**里。文案同时出现在 `missTitle` 里，
                #   从文件开头 `index()` 会命中那一处，而它离 `barTrack` 很远 ⇒ 假红。
                #   所以先切到行渲染入口之后再找（本仓「命中了但命中错了」的又一次）。
                base = c.index(self.ROW_ENTRY[name])
                anchor = next(w for w in self.SAYS[name] if w in c[base:])
                i = base + c[base:].index(anchor)
                seg = c[max(base, i - 900):i + 60]
                self.assertIn("barTrack", seg, f"★★ {name} 缺失行没有条槽 —— 高度对不齐")


class TheTwoKindsOfMissingAreNotTheSameSentence(unittest.TestCase):
    """★★★ 这一组才是重点：两种缺失的**原因不同、下一步动作也不同**。"""

    def test_agy_says_this_read_missed_it(self):
        """agy 缺一格 = **这一次没取到**（见本文件 docstring）。
        ★ 2026-10-16 更正：原断言要的是「只有当前登录的号读得到」—— 那句话 B53（2026-09-15）就证伪了
          （云端按账号返回完整摘要含周），闸却一直守着它，菜单栏也一直在说这句假话。"""
        for name in ("AgyCard", "AgyRow"):
            with self.subTest(component=name):
                c = code(TARGETS[name])
                self.assertIn("这次没读到", c, f"★★ {name} 没说清是「这一次没取到」")
                self.assertNotIn("当前登录", c, f"★★ {name} 又在说「只有当值号读得到」—— B53 已证伪")

    def test_neither_borrows_the_others_wording(self):
        """★★★ 把 grok 的「上游没有」套到 agy 上 = 告诉用户"等也没用"，
        而事实是切过去就能看到；反过来则是让人一直等一个永远不会来的数。"""
        for name in ("AgyCard", "AgyRow"):
            with self.subTest(component=name):
                self.assertNotIn("只有周窗口", code(TARGETS[name]),
                                 f"★★★ {name} 用了 grok 的说法 —— 那会让人以为等也没用")
        for name, path in GROK.items():
            with self.subTest(component=name):
                self.assertNotIn("切过去再刷新", code(path),
                                 f"★★★ {name} 用了 agy 的说法 —— 那个数永远不会来")


class GrokShowsOnlyItsOwnWindow(unittest.TestCase):
    """★★ grok **只画周**，不为它没有的窗口补格（用户 2026-09-15 直接指定）。

    xAI 只回 WEEKLY —— 2026-09-15 实测（`scratch/agy_raw_buckets_*` 同款做法）：
    `window_minutes = 10080`，27 个模型 2 个桶，**没有 5h**。那一格永远不会有数。

    此前补过三版：`visibility:hidden` 的空行 → `—` → 「无此窗口」。
    三版都是在给**一件根本不存在的东西**找一种体面的画法，而它每一版都让用户
    再问一次「我的 5h 额度呢」。**最后的答案是不画。**

    ⚠️ **2026-10-19 被交接包 page5 改写**：「只有周额度的平台 5h 显示 — 占位」（总览卡 148 定高，
      五个槽位固定，空着一槽反而不齐）。所以总览卡的 5h 槽现在画「—」+ 悬浮「xAI 只有周额度」；
      菜单栏行仍不画。不变的是这条闸守的那半：**不按 winSlots 去补别家的窗口**（PLAN §4）。

    ⚠️ 对齐**不靠这条闸保证** —— 条形区由 `flex:1` 的留白压在卡片底边，末行对齐。
      那是像素问题，判据在 `sweep.py` 的跨卡对齐检查（`data-cards-grid` 按排比较），
      不是这里。**别在这个文件里用静态断言去"证明"对齐。**
    """

    def test_grok_does_not_pad_foreign_window_slots(self):
        for name, path in GROK.items():
            with self.subTest(component=name):
                c = code(path)
                self.assertNotIn("winSlots", c,
                                 f"★ {name} 又开始按 winSlots 补格了 —— 那一格永远不会有数")

    def test_grok_card_takes_no_winslots_prop(self):
        """★ 连 prop 一起删，不留骨架（本仓规矩：删版块就连组件本体一起删）。"""
        app = code(ROOT / "codexbar" / "src" / "components" / "ov" / "Overview.tsx")   # 2026-10-19 起调用点在这
        i = app.index("<GrokCard")
        self.assertNotIn("winSlots", app[i:i + 400],
                         "★ 调用点还在传 winSlots —— 死 prop 会让下一个人以为它还有用")

    def test_the_weekly_row_is_still_there(self):
        """★★ 正面：删的是 5h，**不是把 grok 的条整条删掉**。
        只验"没有 winSlots"的话，把整块条形区删掉也能变绿。"""
        for name, path in GROK.items():
            with self.subTest(component=name):
                # 2026-10-19：GrokCard 的周行是外壳的 ⑤ 槽 `ww`（5h 槽按交接包画 — 占位，见 PLAN §4）。
                self.assertIn('ww={{ label: "周", pct: rem' if name == "GrokCard" else "周", code(path),
                              f"★★ {name} 连周窗口都不画了")


class TheMenubarRowsShowEveryWindowNotJustTheTightest(unittest.TestCase):
    """★★ 2026-09-13 用户实报「gemini 缺少 5h」的**直接根因**：
    `AgyRow` 此前只渲染 `agyTightest(...)` 那一格，于是当值号明明有 5h + 周两格，
    行上只看得到其中一格 —— 而旁边 codex 的行有两格。"""

    def test_agyrow_iterates_fixed_slots(self):
        c = code(TARGETS["AgyRow"])
        self.assertIn("MB_WIN_SLOTS.map", c, "★★ 又退回只画最紧的那一格")
        self.assertIn("agyWinRows", c, "★ 没有取全部窗口")

    def test_the_slots_are_fixed_not_data_driven(self):
        """★ 槽位写死成 `["5h","周"]`，不是"有什么画什么" —— 后者会让
        非当值号的行少一格、比旁边矮一截，而那个矮没有任何地方解释。"""
        c = code(TARGETS["AgyRow"])
        m = re.search(r'MB_WIN_SLOTS = \[([^\]]+)\]', c)
        self.assertIsNotNone(m, "★ 槽位表的形状变了 —— 判据看不懂了，先修闸")
        self.assertEqual(re.findall(r'"([^"]+)"', m.group(1)), ["5h", "周"])


if __name__ == "__main__":
    unittest.main()
