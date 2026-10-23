"""Grok 不再标「只读」、不再挂锁（用户 2026-10-23「grok 不要变成只读了，解锁吧，看着不舒服」）。

只改**说法**：grok 仍是单号、没有池可切，所以照旧不出「切换 / 探针」（`QuotaRow` 的 `readOnly` 属性 = 不出切换列，
是能力，不是文案，保留）。总览卡与 Claude 本机卡同一套状态：在用 / 额度低 / 未探测。
"""
import pathlib
import re
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "codexbar" / "src"
FILES = ["components/GrokCard.tsx", "components/GrokRow.tsx", "components/ov/OvHeroRO.tsx",
         "components/PlatformChips.tsx", "platforms.ts"]


def code(rel):
    """去掉注释，只看会渲染 / 会进悬浮提示的那部分。"""
    s = (SRC / rel).read_text(encoding="utf-8")
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"\{/\*.*?\*/\}", "", s, flags=re.S)
    return "\n".join(l.split("//")[0] if not l.strip().startswith("*") else "" for l in s.splitlines())


class GrokIsNotLabelledReadOnly(unittest.TestCase):
    def test_no_read_only_wording_in_grok_ui(self):
        for f in FILES:
            with self.subTest(f=f):
                self.assertNotIn("只读", code(f))

    def test_menubar_grok_head_and_chip_have_no_lock(self):
        mb = code("MenuBar.tsx")
        self.assertIn('plat === "grok" ? "当前号" :', mb)
        self.assertNotIn('readOnly: p.key === "grok"', mb)
        self.assertNotIn("Lock", code("components/PlatformChips.tsx"))
        self.assertNotIn("Lock", code("components/GrokRow.tsx"))

    def test_overview_grok_card_uses_the_claude_states(self):
        card = code("components/GrokCard.tsx")
        self.assertIn('const state = rem == null ? "unprobed" : ovIsLow(rem) ? "low" : "inuse";', card)
        self.assertIn('state={state}', card)
        self.assertNotIn('state="readonly"', card)
        ov = code("components/ov/Overview.tsx")
        self.assertNotIn('<AccountsTitle name="Grok" readOnly', ov)

    def test_grok_still_has_no_switch(self):
        """能力边界不变：菜单栏 grok 行仍不出「切换」。"""
        self.assertRegex(code("components/GrokRow.tsx"), r'QuotaRow platform="grok"[^>]*readOnly')


if __name__ == "__main__":
    unittest.main()
