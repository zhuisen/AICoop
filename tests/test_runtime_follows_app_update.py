""".dmg 装机：App 更新后，复制出去的运行时必须跟着更新（2026-10-15，外部用户报）。

## 用户报的症状（转述，未在其机器上取证）
「codex 的自动轮换无法轮换；切号之后退出 codex 重进还是原来那个号」，用户是 GitHub 下载版，
怀疑「更新后有些配置没到位」。

## 沙箱复现确认的三处缺陷（`scratch/sim_dmg_update_20261015.py`）
1. ★★★ **运行时过期却报「已完成」**：Connector 把运行时**复制**到 `<数据目录>/runtime/`
   （为了 App 更新/删除时常驻服务不断），但 `plan()` 只看文件**在不在**。v1.8.0 接入 → 更新到新版，
   仍报 `runtime done`，而代理 / quotad / 终端里的 `codex-rotate` 永远跑接入那天的代码；
   App 自己调的却是 bundle 里的新脚本 ⇒ **同一份 state.json 两个版本在写**。
   09-21 起「点亮置顶 = 优先用该号」只有新代理认 —— 旧代理照旧按容量挑，界面上「切号」进不去代理。
2. ★★ **接入闸对每台 `.dmg` 机器误报「接线断了」**：⑥ 找 `<数据目录>/proxy/cxp`，
   而入口实际在 `<数据目录>/runtime/proxy/cxp`。恒亮的假红会把真问题淹掉。
3. ★ **运行时清单漏了 `dawn_sched.py`**（`codex-rotate` / `agy-rotate` 都会加载）——
   `.dmg` 机器上定时探针的 `--tick` 会直接崩。闸从源码**现解析**引用，不抄清单。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import importlib.machinery
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import connector  # noqa: E402


def _copy_runtime(dst):
    for rel in connector.RUNTIME_FILES:
        if (ROOT / rel).exists():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dst / rel)


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.src, self.store = d / "bundle", d / "appdata"
        for p in (self.src, self.store, d / "home", d / "bin", d / "agents"):
            p.mkdir(parents=True)
        _copy_runtime(self.src)
        self._env = {k: os.environ.get(k) for k in ("CODEX_HOME", "CODEXBAR_LOCAL_BIN", "CODEXBAR_LAUNCH_AGENTS")}
        os.environ.update(CODEX_HOME=str(d / "home"), CODEXBAR_LOCAL_BIN=str(d / "bin"),
                          CODEXBAR_LAUNCH_AGENTS=str(d / "agents"))
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in self._env.items()])
        orig = connector._svc_loaded
        connector._svc_loaded = lambda name: True          # 服务都在跑（老用户的常态）
        self.addCleanup(lambda: setattr(connector, "_svc_loaded", orig))
        connector.apply(self.src, self.store, ["runtime"])
        self.runtime = self.store / "runtime"

    def age_runtime(self, rel="proxy/proxy.py"):
        """模拟「接入之后 App 更新了」：bundle 里那份变了，运行时拷贝还是旧的。"""
        p = self.src / rel
        p.write_text(p.read_text(encoding="utf-8") + "\n# newer app\n", encoding="utf-8")

    def step(self, sid):
        return [s for s in connector.plan(self.src, self.store)["steps"] if s["id"] == sid][0]


class TheConnectorSeesAStaleRuntime(Sandbox):
    def test_fresh_copy_is_done(self):
        self.assertEqual(self.step("runtime")["state"], "done")
        self.assertEqual(connector.runtime_drift(self.src, self.runtime), [])

    def test_after_an_app_update_runtime_is_todo_and_says_why(self):
        self.age_runtime()
        st = self.step("runtime")
        self.assertEqual(st["state"], "todo", "★★★ App 更新后运行时仍报 done —— 代理永远跑旧代码")
        self.assertIn("旧", st["detail"])
        self.assertIn("proxy/proxy.py", st["detail"], "★ 要说出是哪个文件不同")
        self.assertFalse(connector.plan(self.src, self.store)["ready"])

    def test_services_must_be_reinstalled_to_load_the_new_code(self):
        """★★ 只复制不重启 = 磁盘上是新的、内存里还是旧的（quotad 把 codex-rotate 整份载进内存）。"""
        self.age_runtime()
        st = self.step("services")
        self.assertEqual(st["state"], "todo", "★★ 服务都在跑就报 done —— 新代码永远加载不进去")
        self.assertIn("重新", st["detail"])

    def test_reapplying_the_runtime_clears_the_drift(self):
        self.age_runtime()
        connector.apply(self.src, self.store, ["runtime"])
        self.assertEqual(connector.runtime_drift(self.src, self.runtime), [])
        self.assertEqual(self.step("runtime")["state"], "done")

    def test_a_missing_file_counts_as_drift(self):
        (self.runtime / "agy/pool.py").unlink()
        self.assertIn("agy/pool.py", connector.runtime_drift(self.src, self.runtime))
        self.assertIn("旧", self.step("runtime")["detail"],
                      "★ 老版本拷贝缺新文件（v1.8.0 没有 dawn_sched.py）也要说「旧」，不是通用文案")

    def test_every_service_the_installer_makes_is_checked(self):
        """服务集合从安装器**现解析**，不抄一份 —— 新加的 agydawn 漏查就等于没装也报 done。"""
        sh = (ROOT / "scripts/install-launchd.sh").read_text(encoding="utf-8")
        made = set(re.findall(r'emit\s+"?(\w+)"?', sh)) or set(re.findall(r"codex-rotate\.(\w+)", sh))
        self.assertTrue(made, "解析不到安装器的服务集合 —— 断言打空了")
        self.assertLessEqual(made, set(connector.SERVICES), made - set(connector.SERVICES))


def _load_cr():
    loader = importlib.machinery.SourceFileLoader("cr_rt", str(ROOT / "codex-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


class TheGateSpeaksForDmgInstalls(Sandbox):
    """接入闸由 App 调用：脚本在 bundle（= 本仓 ROOT），`STORE` = 数据目录。"""

    def gate(self):
        m = _load_cr()
        m.CODEX_HOME = Path(os.environ["CODEX_HOME"])
        m.STORE, m.STATE = self.store, self.store / "state.json"
        return m.codex_integration_gate()

    def check(self, g, cid):
        return {c["id"]: c for c in g["checks"]}.get(cid)

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.runtime)
        _copy_runtime(self.runtime)          # 与 ROOT（= 跑闸的 bundle）同版本

    def test_the_entry_under_runtime_counts(self):
        c = self.check(self.gate(), "entry")
        self.assertEqual(c["state"], "ok", "★★ .dmg 装机的 cxp 在 runtime/ 下，闸却说不存在：%s" % c["detail"])

    def test_a_runtime_in_step_with_the_app_is_ok(self):
        self.assertEqual(self.check(self.gate(), "runtime")["state"], "ok")

    def test_a_stale_runtime_is_red_and_points_at_the_connector(self):
        p = self.runtime / "proxy/proxy.py"
        p.write_text("# v1.8.0\n", encoding="utf-8")
        g = self.gate()
        c = self.check(g, "runtime")
        self.assertEqual(c["state"], "bad", "★★★ 运行时比 App 旧，闸却不吭声")
        self.assertIn("账号池接入", c["fix"], "★ 要说去哪修")
        self.assertEqual(g["state"], "broken")

    def test_a_clone_install_has_no_runtime_check(self):
        shutil.rmtree(self.runtime)
        self.assertIsNone(self.check(self.gate(), "runtime"), "clone 装机原地用，没有拷贝可比")


class TheRuntimeShipsEverySiblingItLoads(unittest.TestCase):
    def test_every_referenced_sibling_module_is_in_the_runtime(self):
        """★ 从运行时文件的源码**现解析**它们按路径加载的兄弟 `.py`，不抄一份清单。"""
        refs = set()
        for rel in connector.RUNTIME_FILES:
            p = ROOT / rel
            src = p.read_text(encoding="utf-8", errors="replace")
            # ★ 也按引用方自己的目录解析（全方面评审 §11）：`scan.py` 写的是 `parent / "agy_quota_series.py"`，
            #   只按仓根判存在会把子目录里的兄弟模块全漏掉。
            for m in re.findall(r'"([\w/]+\.py)"', src):
                for c in (ROOT / m, p.parent / m):
                    if c.is_file():
                        refs.add(c.resolve().relative_to(ROOT.resolve()).as_posix())
        self.assertIn("dawn_sched.py", refs, "解析没抓到已知引用 —— 断言打空了")
        self.assertIn("traffic/agy_quota_series.py", refs, "子目录里的兄弟模块没解析出来 —— 断言打空了")
        self.assertEqual(sorted(refs - set(connector.RUNTIME_FILES)), [],
                         "★★ 这些文件运行时会加载，却不在 RUNTIME_FILES —— .dmg 机器上直接崩")


if __name__ == "__main__":
    unittest.main()
