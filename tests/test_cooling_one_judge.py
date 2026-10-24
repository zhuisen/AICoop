"""冷却只有一个裁判（samchen #4 ④⑤）。

原来代理选号认「冷却后读到新额度」与「窗口已重置」两条提前放行，而 `codex-rotate`（ensure-live / 选号 / list /
next 的 cool_min）与 `traffic/rotation.py`（泳道「冷却到」）只比 `cooling_until > now` —— 代理早已重新在用的号，
界面与 ensure-live 仍当它冷却。另一半：`_patch_slot` 为了用代理的判据，持着 state 锁 exec 整个 proxy.py。

守的：
1. 同一个槽位，代理 / codex-rotate 各处 / rotation.py 给出同一个答案（提前解冻与仍冷却两个方向）；
2. codex-rotate 里不再有裸的 `cooling_until > now` 判断；
3. `_patch_slot` 加载的是零 import 的 `cooling.py`，不是 proxy.py；`cooling.py` 进了运行时清单与安装包。
纯函数夹具，不碰真 state。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import ast
import importlib.machinery
import importlib.util
import json
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "traffic"))
sys.path.insert(0, str(ROOT))


def _load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(m)
    return m


CR = _load("cr_cool", ROOT / "codex-rotate")
PX = _load("px_cool", ROOT / "proxy" / "proxy.py")
import rotation as ROT  # noqa: E402


def slot(recovered):
    now = time.time()
    cooled = now - 1800
    q = {"captured_at": (now - 60) if recovered else (cooled - 60),
         "primary": {"used_percent": 20 if recovered else 100, "window_minutes": 300, "resets_at": now + 3 * 3600},
         "secondary": {"used_percent": 40, "window_minutes": 10080, "resets_at": now + 4 * 86400}}
    return {"label": "x", "cooling_until": now + 2 * 3600, "cooled_at": cooled, "quota": q}


class EveryJudgeAgrees(unittest.TestCase):
    def verdicts(self, sl):
        now = time.time()
        return {"proxy": PX.cooling(sl, now),
                "codex-rotate": CR._is_cooling(sl, now),
                "ensure-live": not CR._can_go_live(sl),
                "rotation": ROT._cooling_until(sl, now) is not None}

    def test_a_recovered_account_is_free_everywhere(self):
        v = self.verdicts(slot(recovered=True))
        self.assertEqual(v, {k: False for k in v}, f"★★ 代理已在用的号，别处仍当它冷却：{v}")

    def test_a_cooling_account_is_cooling_everywhere(self):
        v = self.verdicts(slot(recovered=False))
        self.assertEqual(v, {k: True for k in v}, f"仍冷却的号被某处放行了：{v}")

    def test_writing_a_fresh_quota_clears_the_mark(self):
        sl = slot(recovered=False)
        st = {"slots": {"a": sl}}
        fresh = slot(recovered=True)["quota"]
        CR._patch_slot(st, "a", {"quota": fresh})
        self.assertNotIn("cooling_until", st["slots"]["a"], "★ 读到新额度却没删冷却 —— 只比 cooling_until 的界面会一直显示冷却")
        st2 = {"slots": {"a": slot(recovered=False)}}
        CR._patch_slot(st2, "a", {"quota": slot(recovered=False)["quota"]})
        self.assertIn("cooling_until", st2["slots"]["a"], "仍见底的读数不能解冻")


class NoBareComparisonsLeft(unittest.TestCase):
    def test_codex_rotate_has_no_raw_cooling_until_judgement(self):
        src = (ROOT / "codex-rotate").read_text(encoding="utf-8")
        code = "\n".join(re.sub(r"#.*$", "", l) for l in src.splitlines())
        bad = [l.strip() for l in code.splitlines()
               if re.search(r"cooling_until[\"']?\)?(?:,\s*0\))?\s*(?:or 0\)\s*)?(>|<=)\s*(now|time\.time\(\))", l)
               and "_is_cooling" not in l and "def _is_cooling" not in l]
        allowed = ['if "quota" in patch and (sl.get("cooling_until") or 0) > now and not _cool().cooling(sl, now):',
                   'return (sl.get("cooling_until") or 0) > now and _cool().cooling(sl, now)']
        self.assertEqual([b for b in bad if b not in allowed], [], "裸的 cooling_until 比较 —— 换成 _is_cooling")

    def test_patch_slot_never_loads_the_proxy(self):
        tree = ast.parse((ROOT / "codex-rotate").read_text(encoding="utf-8"))
        fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        def consts(fn):   # 代码里的字符串字面量，不含 docstring（docstring 正在解释「原来加载 proxy.py」）
            doc = ast.get_docstring(fn, clean=False)
            return {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, str)} - {doc}
        for name in ("_patch_slot", "_cool", "_is_cooling"):
            self.assertFalse({c for c in consts(fns[name]) if "proxy" in c}, f"{name} 又去加载 proxy.py（持锁时 exec 大模块）")
            self.assertNotIn("_px", {n.id for n in ast.walk(fns[name]) if isinstance(n, ast.Name)})
        self.assertIn("cooling.py", consts(fns["_cool"]))

    def test_the_module_ships(self):
        import connector
        self.assertIn("cooling.py", connector.RUNTIME_FILES)
        res = json.loads((ROOT / "codexbar/src-tauri/tauri.conf.json").read_text())["bundle"]["resources"]
        self.assertEqual(res.get("../../cooling.py"), "scripts/cooling.py")
        self.assertIn("cooling.py", CR.DAEMON_SOURCES["proxy"], "代理启动时 import 它 —— 改了要重启")
        self.assertNotIn("import", "\n".join(l for l in (ROOT / "cooling.py").read_text().splitlines()
                                              if l.startswith(("import ", "from "))), "cooling.py 要零 import")


if __name__ == "__main__":
    unittest.main()
