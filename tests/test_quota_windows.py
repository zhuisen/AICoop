"""额度窗口判据的**三处一致性**闸。

起因:2026-08-25 用户报「Plus 的 5 小时额度回来了」。实测 `state.json` 确认 ——
plus5 的 `primary.window_minutes = 300`(5 小时)、weekly 退到了 `secondary`。

**为什么旧代码会丢掉它**:这段逻辑要挡的东西从没变过 —— Codex 仍会返回**空槽**
`{window_minutes: 0, resets_at: null}`。但 2026-07 那会儿真窗口只剩周(10080)/月(43200),
于是「够大(>=5000)」**恰好等价于**「非空」,当时就用了这个代理判据。
5h 回归后等价关系断了(`300 < 5000`)—— **一个合法窗口被当垃圾丢掉,用户看不到自己的额度。**

★ 教训不是"阈值调小点",是**别用量级去猜语义**:量级一变,判据就失效,而且失效得很安静。

**为什么必须做成闸**:同一判据有**三份副本**,跨语言没法共用:
  · `codexbar/src/helpers.ts` —— 主界面
  · `codex-rotate`            —— CLI
  · `codexbar/src-tauri/src/lib.rs` —— **托盘标题**
漏改任何一份的症状都是"有的地方看得见 5h、有的地方看不见",**没有一处会报错**。
(与仓库里 `quotaColor` / `rem_rgb` 那对同族:CLAUDE.md 明写「改阈值必须两处一起改」。)
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "codexbar" / "src" / "helpers.ts"
ROTATE = ROOT / "codex-rotate"
LIB_RS = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"


def strip_comments(src: str) -> str:
    """注释里正解释着这条规则(还引用了旧阈值 5000),朴素匹配必被它染红。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return re.sub(r"^\s*#[^\n]*", "", src, flags=re.M)


class WindowPredicateIsConsistent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = strip_comments(HELPERS.read_text(encoding="utf-8"))
        cls.py = strip_comments(ROTATE.read_text(encoding="utf-8"))
        cls.rs = strip_comments(LIB_RS.read_text(encoding="utf-8"))

    def test_anchors_exist(self):
        """★ 先证明三个被测目标都还在 —— 改名后断言会静默打空。"""
        self.assertIn("REAL_WINDOW_MIN", self.ts, "helpers.ts 里的判据不见了")
        self.assertIn("REAL_WINDOW_MIN", self.py, "codex-rotate 里的判据不见了")
        self.assertIn("window_minutes", self.rs, "lib.rs 托盘不再读 window_minutes?")

    def test_no_copy_still_discards_the_5h_window(self):
        """★★ 三份都不得再按量级丢窗口。5h = 300 分钟,任何 >300 的下限都会吞掉它。"""
        for name, src, pat in (
            ("helpers.ts", self.ts, r"REAL_WINDOW_MIN\s*=\s*(\d+)"),
            ("codex-rotate", self.py, r"REAL_WINDOW_MIN\s*=\s*(\d+)"),
        ):
            m = re.search(pat, src)
            with self.subTest(f=name):
                self.assertIsNotNone(m, "{}:找不到阈值".format(name))
                v = int(m.group(1))
                self.assertLessEqual(v, 300,
                                     "{} 的下限是 {},会把 5 小时窗口(300)当空槽丢掉".format(name, v))

    def test_rust_tray_does_not_discard_the_5h_window(self):
        """托盘那份是 Rust 写死的比较,不走常量 —— 单独断言。

        ★ 必须**只挑「有效性」那个比较**。第一版把所有 `wm >= N` 都收进来,于是
        标签用的 `wm >= 40000.0`(月/周分档)也被当成下限报红 —— **同一个变量的比较,
        语义完全不同**。判据:有效性那处紧跟 `used_percent` 一起决定要不要这个窗口。
        """
        # ★ 锚点只认 `match (wm ...` 这一处 —— 标签分档用的是 `if wm >= 40000.0`,形状不同,
        #   不会被误收。**别再把前面的 `let wm/let used` 一起写进正则**:2026-08-28 给托盘加
        #   「未确认的窗口不参与」时中间多了两行 let,这条当场打空(靠下面那句自检接住的)。
        m = re.search(r"match \(wm\s*([><=]+)\s*([0-9.]+)", self.rs, re.S)
        self.assertIsNotNone(m, "找不到托盘的窗口有效性判断 —— 断言可能打空了")
        op, v = m.group(1), float(m.group(2))
        self.assertIn(op, (">", ">="), "有效性判断的方向反了")
        self.assertLessEqual(v, 300.0,
                             "lib.rs 托盘的下限是 {},会丢掉 5 小时窗口".format(v))

    def test_labels_cover_short_windows(self):
        """★★ 标签必须按**实际时长**分档。旧版是 `>=40000 ? 月 : 周` —— 300 分钟会被标成「周」,
        **那比不显示更糟:它把 5 小时的余量说成一周的余量。**

        三份都要有「周」那一档(10000)和更短的档(1440),否则短窗口会掉进「周」里。
        """
        for name, src in (("helpers.ts", self.ts), ("codex-rotate", self.py), ("lib.rs", self.rs)):
            with self.subTest(f=name):
                self.assertRegex(src, r"\b10000(?:\.0)?\b",
                                 "{}:标签没有「周」这一档,短窗口会被并进周".format(name))
                self.assertRegex(src, r"\b1440(?:\.0)?\b",
                                 "{}:标签没有比周更短的档 —— 5h 会被标成周".format(name))

    def test_real_state_still_parses(self):
        """★ 拿**真实 state.json** 交叉验证:5h 窗口确实在,且判据不会丢掉它。

        这条是"用真数据验"而不是"用夹具验" —— 这次的 bug 正是真数据变了才暴露的。
        没有 5h 窗口的机器上自动跳过(不制造假红)。
        """
        state = ROOT / "state.json"
        if not state.exists():
            self.skipTest("本机没有 state.json")
        d = json.loads(state.read_text(encoding="utf-8"))
        wins = []
        for s in (d.get("slots") or {}).values():
            q = s.get("quota") or {}
            for k in ("primary", "secondary"):
                wm = (q.get(k) or {}).get("window_minutes")
                if wm:
                    wins.append(wm)
        if not any(w and w < 5000 for w in wins):
            self.skipTest("本机当前没有短于 5000 分钟的窗口,无从验证")
        m = re.search(r"REAL_WINDOW_MIN\s*=\s*(\d+)", self.ts)
        short = min(w for w in wins if w < 5000)
        self.assertLessEqual(int(m.group(1)), short,
                             "真实数据里有 {} 分钟的窗口,而判据下限是 {} —— 它会被丢掉"
                             .format(short, m.group(1)))


class HeroRingLabelMatchesItsNumber(unittest.TestCase):
    """★★ 汇总环的数字取 `tightest`(跨窗口最小),标签**必须取同一个窗口**的名字。

    只有一个窗口时两者永远一致,所以这个缺陷在 5h 缺席的那一年里根本不可能暴露。
    5h 回归 ⇒ Plus 号有两个窗口 ⇒ 数字可能来自周、标签却写着「5h」。

    ★ 2026-10-19：总览照交接包 page5 重做 —— 「正在使用」那颗环（`ov/OvHero`）取轮换板的
      `cur.tightest`，卡片环（`AccountCard` → `ov/OvCard`）取 `a.tightest`；App 不再自己画环。
    """
    SURFACES = ("components/ov/OvHero.tsx", "components/AccountCard.tsx", "components/AccountRow.tsx")

    def test_no_surface_summarises_with_the_first_window(self):
        """★★ **单个汇总数字一律取「最紧」的窗口**：hero 环、卡片环、菜单栏行、托盘标题。

        `windows[0]` 是 primary —— plus 号的 primary 现在是 **5h**,而真正卡住人的
        可能是周。用第一个 = **把约束藏起来**,而且它显示的还是个正常的绿数字。
        """
        for rel in self.SURFACES:
            code = strip_comments((ROOT / "codexbar" / "src" / rel).read_text(encoding="utf-8"))
            with self.subTest(f=rel):
                self.assertNotRegex(code, r"windows\[0\]",
                                    "{}:还在用 windows[0] 做汇总 —— 会藏掉更紧的那个窗口".format(rel))
                self.assertRegex(code, r"tightest",
                                 "{}:没有用 tightest".format(rel))
        hero = strip_comments((ROOT / "codexbar" / "src" / "components" / "ov" / "OvHero.tsx").read_text(encoding="utf-8"))
        self.assertIn("const pct = cur?.tightest ?? null;", hero, "★ 「正在使用」的环不是最紧那个窗口")

    def test_helpers_derives_tightest_from_the_window_list(self):
        ts = strip_comments(HELPERS.read_text(encoding="utf-8"))
        self.assertIn("tightestWin", ts, "helpers 没有导出 tightestWin")
        self.assertRegex(ts, r"reduce\(\(a, b\) =>",
                         "tightest 不是从窗口列表里挑出来的,拿不到它是哪个窗口")

class OverviewCardsShareOneRule(unittest.TestCase):
    """★★ 总览四家的卡（2026-10-19 交接包 page5）：条色、数字色**同一个判据** `overview.ts::ovIsLow`，
    四张卡共用一个行组件 `ov/OvCard::OvWinRow`。

    ## 这一条取代了两条旧闸（作废记录，PLAN §4）
    - `WindowColourRule`（C′，2026-08-26）与 `NumberAndBarNeverDisagree`（策略③）守的是
      `helpers.ts::winBarColor / winNumColor / quotaLevel`：≤10 红、<50 琥珀、否则按窗口取色 / 中性灰。
      交接包 page5 的窗口行只有「5h 青 / 周 绿 / 显示整数 <10% 橙红」三种色（与菜单栏 4f 同一套），
      **<50 琥珀那一档被交接稿去掉了**；那三个函数随之无人调用，按「删组件连本体一起删」删除。
    - 两条旧闸真正守的两件事**原样保留**：
      ① 识别是常态、报警是例外且优先（低 ⇒ 夺色，否则按窗口取色）；
      ② 条与数字**同一个判据**、各家卡**谁也不许手写阈值** —— 剩 7% 时条红、数字琥珀的老毛病不能回来。
    """
    OVCARD = ROOT / "codexbar" / "src" / "components" / "ov" / "OvCard.tsx"
    CARDS = ("components/AccountCard.tsx", "components/AgyCard.tsx", "components/GrokCard.tsx",
             "components/ov/ClaudeCard.tsx")

    @classmethod
    def setUpClass(cls):
        c = strip_comments(cls.OVCARD.read_text(encoding="utf-8"))
        i = c.index("export function OvWinRow(")
        cls.row = c[i:c.index("\n}\n", i)]

    def test_low_takes_over_and_identity_survives(self):
        self.assertIn("const low = ovIsLow(w.pct);", self.row, "行的 low 不是 ovIsLow 给的")
        self.assertRegex(self.row, r'const bar = off \? "var\(--tx3\)" : low \? "var\(--bad\)" : w\.kind === "5h" \? "var\(--ovB5\)" : "var\(--ovBw\)";',
                         "条色不是「低额度夺色、否则按窗口取色」")

    def test_number_uses_the_same_predicate(self):
        self.assertRegex(self.row, r'w\.pct == null \? "var\(--ovPh\)" : low \? "var\(--badTx\)" : "var\(--tx\)"',
                         "数字色没跟条色同一个判据 —— 条红数字不红")

    def test_the_threshold_judges_the_displayed_integer(self):
        """★ 判的是**显示出来的整数**：剩 9.6% 环上写 10，就不该是红的（与托盘 / 菜单栏同口径）。"""
        ts = strip_comments((ROOT / "codexbar" / "src" / "overview.ts").read_text(encoding="utf-8"))
        self.assertIn("Math.round(pct) < OV_LOW_PCT", ts)

    def test_no_card_hand_rolls_a_threshold(self):
        for rel in self.CARDS:
            code = strip_comments((ROOT / "codexbar" / "src" / rel).read_text(encoding="utf-8"))
            with self.subTest(f=rel):
                self.assertRegex(code, r"<OvCard\b", "{} 没走共用的 OvCard（窗口行由它画）".format(rel))
                self.assertNotRegex(code, r"pct\s*[<>]=?\s*(10|50)\b", "{} 手写了一份阈值（10 / 50）".format(rel))
                self.assertNotIn("quotaColor(", code, rel)
        self.assertNotIn("winBarColor", HELPERS.read_text(encoding="utf-8"), "★ 已删的旧配色又回来了却没人用")
        c = strip_comments(self.OVCARD.read_text(encoding="utf-8"))
        self.assertEqual(len(re.findall(r"<OvWinRow ", c)), 2, "★ OvCard 的 ④ / ⑤ 两槽不都走 OvWinRow")


class MenubarRowsShareOneRule(unittest.TestCase):
    """★★ 菜单栏四家的行（2026-10-19 交接包 4f）：条色、数字色、整行警示**同一个判据** `mbLogic.isLow`。

    同一个 C′ 思路（识别是常态、报警是例外且优先），只是阈值换成交接稿的 <10%：
      · 条：低 ⇒ `--bad`，否则 5h `--b5`（青）/ 周 `--bw`（绿）；
      · 数字：低 ⇒ `--bad`，否则中性 `--tx`；
      · 整行：任一窗口低 ⇒ `qlow`（浅橙红底）。
    三处都只认 `isLow`，四个行组件谁也不许自己写阈值。
    """
    QROW = ROOT / "codexbar" / "src" / "components" / "mb" / "QuotaRow.tsx"
    ROWS = ("components/AccountRow.tsx", "components/AgyRow.tsx", "components/GrokRow.tsx",
            "components/mb/ClaudeRow.tsx")

    @classmethod
    def setUpClass(cls):
        cls.q = strip_comments(cls.QROW.read_text(encoding="utf-8"))

    def test_bar_number_and_row_use_is_low(self):
        self.assertRegex(self.q, r'const bar = low \? "var\(--bad\)" : w\.label === "5h" \? "var\(--b5\)" : "var\(--bw\)"',
                         "条色不是「低额度夺色、否则按窗口取色」")
        self.assertRegex(self.q, r'low \? "var\(--bad\)" : "var\(--tx\)"', "数字色没跟条色同一个判据")
        self.assertRegex(self.q, r"const low = isLow\(w\.pct\)", "格子的 low 不是 isLow 给的")
        self.assertRegex(self.q, r"wins\.some\(\(w\) => w != null && isLow\(w\.pct\)\)", "整行警示不是 isLow 给的")

    def test_no_row_hand_rolls_a_threshold(self):
        for rel in self.ROWS:
            code = strip_comments((ROOT / "codexbar" / "src" / rel).read_text(encoding="utf-8"))
            with self.subTest(f=rel):
                self.assertNotRegex(code, r"[<>]=?\s*(10|50)\b|\b(10|50)\s*[<>]",
                                    "{} 手写了一份阈值（10 / 50）".format(rel))
                for m in re.finditer(r"const low\s*=\s*([^;]+);", code):
                    self.assertIn("isLow(", m.group(1), "{} 自己算了 low，没走 isLow".format(rel))
                self.assertNotIn("quotaColor(", code, rel)
                self.assertNotIn("winBarColor(", code, rel)
                self.assertIn("QuotaRow", code, "{} 没走共用的 QuotaRow".format(rel))


if __name__ == "__main__":
    unittest.main()
