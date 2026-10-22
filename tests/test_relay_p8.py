"""AICoop P8（中转站页改版，阶段 5）的闸。

1. **后端 `group`**：登记表行多一个平台分组字段。缺席 = 沿用旧值（编辑表单不带它时不许清掉），
   空串 = 清回「按 host 自动成组」。
2. **纯逻辑 `relayView.ts`**：分组、同组合计（读不到 / 多币种 ⇒ 不相加）、本月是否覆盖到月初、
   横幅优先级与「见底」建议、还能撑几天只有一个来源。
3. **真 bundle 渲染**：路线图五个入口（VS Code「不经过代理」）、悬停卡、横幅、视角切换、删除要确认。

★ 测试绝不碰真数据：store 两个目录都指到 tmpdir（同 `test_relay_store.py`）。
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relay import store  # noqa: E402


class GroupField(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "codex-home").mkdir()
        self._env = {k: os.environ.get(k) for k in ("CODEX_ROTATE_STORE", "CODEX_HOME")}
        os.environ["CODEX_ROTATE_STORE"] = str(root / "store")
        os.environ["CODEX_HOME"] = str(root / "codex-home")
        self.addCleanup(self._restore)
        self.assertIn(self.tmp.name, str(store.store_path()), "★ store 没跟着 tmpdir 走 —— 会写真数据")

    def _restore(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def row(self, **kw):
        return {"id": "tokendun", "label": "TokenDun", "base_url": "https://api.example-relay.test/v1",
                "key": "sk-TESTONLY-0000000000000000000000000000", **kw}

    def test_group_is_saved_trimmed(self):
        store.upsert(self.row(group="  TokenDun 平台 "))
        self.assertEqual(store.get("tokendun")["group"], "TokenDun 平台")

    def test_absent_group_keeps_the_old_one(self):
        """★ 编辑表单 / CLI 不带 `group` 时整行重建会把它清掉 —— 用户分好的组自己散开。"""
        store.upsert(self.row(group="A"))
        store.upsert(self.row(label="改名"))
        self.assertEqual(store.get("tokendun")["group"], "A")

    def test_empty_string_clears_back_to_auto(self):
        store.upsert(self.row(group="A"))
        store.upsert(self.row(group=""))
        self.assertIsNone(store.get("tokendun")["group"])

    def test_redacted_status_carries_group_and_no_key(self):
        store.upsert(self.row(group="A"))
        rows = store.redacted()["relays"]
        self.assertEqual(rows[0]["group"], "A")
        self.assertNotIn("key", rows[0])


class CoveredRanges(unittest.TestCase):
    def test_union_merges_overlap_and_adjacent_only(self):
        from relay.monitor import merge_covered as m
        self.assertEqual(m([["2026-10-01", "2026-10-14"]], [["2026-10-15", "2026-10-22"]]), [["2026-10-01", "2026-10-22"]])
        self.assertEqual(m([["2026-09-01", "2026-09-01"]], [["2026-10-15", "2026-10-22"]]),
                         [["2026-09-01", "2026-09-01"], ["2026-10-15", "2026-10-22"]], "★ 断档被并成了一段")
        self.assertEqual(m(None, [["bad", "x"]]), [])


PURE = ROOT / "codexbar" / "src" / "relayView.ts"


def _node(expr):
    script = ("import('file://%s').then(m => { let v; try { v = (%s); } catch (e) { v = {__throw: String(e)}; }"
              " console.log(JSON.stringify(v === undefined ? null : v)); });" % (PURE.as_posix(), expr))
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip()]
    if not out:
        raise AssertionError(f"node 没有产出：{r.stderr[-600:]}")
    return json.loads(out[-1])


ROWS = ('[{id:"a",label:"A",base_url:"https://x.test/v1",enabled:true},'
        '{id:"b",label:"B",base_url:"https://X.test:8443/v2",enabled:true},'
        '{id:"c",label:"C",base_url:"https://y.test/v1",enabled:true,group:"Y 平台"},'
        '{id:"d",label:"D",base_url:"https://z.test/v1",enabled:false,group:"Y 平台"}]')


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class RelayViewLogic(unittest.TestCase):
    def test_groups_by_explicit_group_then_host(self):
        g = _node(f"m.groupRelays({ROWS}).map(g => [g.name, g.ids])")
        self.assertEqual(g, [["x.test", ["a", "b"]], ["Y 平台", ["c", "d"]]], "★ host 大小写 / 端口不同被分成了两组")
        self.assertEqual(_node('m.groupRelays([{id:"a",label:"Solo",base_url:"https://q.test",enabled:true}])[0].name'), "Solo")

    def test_sum_never_adds_unknown_or_mixed_currency(self):
        self.assertEqual(_node('m.sumOf([1.5, 2], ["USD","USD"])'), {"v": 3.5, "unit": "USD", "mixed": False})
        self.assertEqual(_node('m.sumOf([1.5, null], ["USD","USD"])')["v"], None, "★★ 读不到被当 0 加进合计")
        self.assertEqual(_node('m.sumOf([1, 2], ["USD","CNY"])'), {"v": None, "unit": None, "mixed": True})
        self.assertEqual(_node('m.sumOf([], [])')["v"], None)
        # ★ 评审 gemini 阶段 5：读不到的账户没有币种，不能因此报「多币种」。
        self.assertEqual(_node('m.sumOf([1.5, null], ["USD", null])'), {"v": None, "unit": "USD", "mixed": False})
        self.assertTrue(_node('m.sumOf([1.5, 2], ["USD", null])')["mixed"], "有的有币种、有的没有 ⇒ 不能相加")

    def test_run_days_has_one_source(self):
        self.assertEqual(_node("[m.runDays(0, 30), m.runDays(5, 3.9), m.runDays(5, null), m.runDays(null, 2.2)]"),
                         [0, 3, None, 2])

    def test_month_sum_says_when_it_does_not_reach_the_first(self):
        now = 'new Date(2026, 9, 22, 12)'
        days = ('[{date:"2026-09-28",actual_cost:9,cost:30},{date:"2026-10-03",actual_cost:1,cost:4},'
                '{date:"2026-10-22",actual_cost:2,cost:8}]')
        full = _node(f'm.monthSum({days}, {now}, "actual_cost", [["2026-09-20","2026-10-22"]])')
        self.assertEqual(full, {"v": 3, "complete": True})
        self.assertEqual(_node(f'm.monthSum({days}, {now}, "actual_cost")'), {"v": 3, "complete": False},
                         "★ 没有覆盖证据（旧快照）却说是整月")
        # ★ 评审 codex 阶段 5：一条旧月份记录 + 中间断档 —— 只看 daily 最早一天会判成整月。
        gap = _node(f'm.monthSum([{{date:"2026-09-01",actual_cost:5,cost:9}},{{date:"2026-10-22",actual_cost:1,cost:4}}], {now},'
                    f' "actual_cost", [["2026-09-01","2026-09-01"],["2026-10-15","2026-10-22"]])')
        self.assertEqual(gap, {"v": 1, "complete": False}, "★ 断档被当成整月")
        self.assertEqual(_node(f'm.monthSum([], {now}, "cost")')["v"], None, "★★ 没有证据 = 读不到，不是 $0")
        self.assertEqual(_node(f'm.monthSum([], {now}, "cost", [["2026-09-25","2026-10-22"]])'), {"v": 0, "complete": True},
                         "看过整月、一天都没用 = 确实是 0")

    def test_today_models_three_states(self):
        now = 'new Date(2026, 9, 22, 12)'
        d = lambda unit, req, models='[{model:"m",requests:1,total_tokens:9,actual_cost:1,cost:2}]', date="2026-10-22": (
            f'{{balance:1,unit:"{unit}",today:{{requests:{req}}},daily:[{{date:"{date}",actual_cost:1,cost:2,requests:1,total_tokens:9,models:{models}}}]}}')
        ok = _node(f'm.todayModels([{d("USD", 1)}, {d("USD", 2)}], {now})')
        self.assertEqual((ok["why"], ok["rows"][0]["actual_cost"]), (None, 2))
        self.assertEqual(_node(f'm.todayModels([{d("USD", 1)}, {d("CNY", 1)}], {now})')["why"], "mixed",
                         "★ 多币种的按模型金额被直接相加（评审阶段 5）")
        self.assertEqual(_node(f'm.todayModels([{d("USD", 1)}, null], {now})')["why"], "unknown",
                         "★ 一个账户整个没数据，合计却只算了另一个")
        self.assertEqual(_node(f'm.todayModels([{d("USD", "null", date="2026-10-20")}], {now})')["why"], "unknown",
                         "★★ 今日请求数读不到被当成 0 ⇒「今天还没有请求」")
        self.assertEqual(_node(f'm.todayModels([{d("USD", 0, date="2026-10-20")}], {now})'), {"rows": [], "why": None})

    def test_banner_priority_and_suggestion(self):
        ent = ('[{id:"a",data:{balance:0,unit:"USD"}},{id:"b",data:{balance:3,unit:"USD"}},'
               '{id:"c",data:{balance:50,unit:"USD"}},{id:"d",data:{balance:99,unit:"USD"}}]')
        b = _node(f'm.bannerOf({ROWS}, {ent}, "a")')
        self.assertEqual((b["kind"], b["isExit"], b["alt"]["id"]), ("zero", True, "c"),
                         "★ 建议的不是余额最多的启用账户（d 停用着，不能建议）")
        b = _node(f'm.bannerOf({ROWS}, [{{id:"a",data:{{balance:0}}}}], "a")')
        self.assertIsNone(b["alt"], "没有可切的账户却给了建议")
        b = _node(f'm.bannerOf({ROWS}, [{{id:"a",data:{{balance:null}}}},{{id:"b",stale:true,stale_since:5,data:{{balance:4}}}}], "b")')
        self.assertEqual(b["kind"], "nobal", "★ 余额读不到排在过期快照之前")
        b = _node(f'm.bannerOf({ROWS}, [{{id:"b",stale:true,stale_since:5,data:{{balance:4}}}}], "b")')
        self.assertEqual(b, {"kind": "stale", "since": 5})
        self.assertIsNone(_node(f'm.bannerOf({ROWS}, [{{id:"a",data:{{balance:4}}}}], "a")'))
        b = _node(f'm.bannerOf({ROWS}, [{{id:"a",data:{{balance:0,unit:"USD"}}}},{{id:"b",data:{{balance:50,unit:"CNY"}}}},'
                  f'{{id:"c",data:{{balance:9,unit:"USD"}}}}], "a")')
        self.assertEqual(b["alt"]["id"], "c", "★ 拿 CNY 50 与 USD 9 比大小（评审 codex 阶段 5）")

    def test_save_ratio_only_when_both_known(self):
        self.assertAlmostEqual(_node("m.saveRatio(0.36, 0.0863)"), 4.1714, places=3)
        self.assertEqual(_node("[m.saveRatio(null, 1), m.saveRatio(1, 0), m.saveRatio(0, 1)]"), [None, None, None])

    def test_hover_timing(self):
        self.assertEqual(_node("[m.hoverDelay(false,false), m.hoverDelay(true,false), m.hoverDelay(true,true)]"), [180, 0, 80])
        self.assertEqual(_node("m.hoverY(192, 236)"), 132, "★ 最下面的入口悬停卡出了底")


HARNESS = "http://127.0.0.1:3304"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _harness_up():
    try:
        urllib.request.urlopen(HARNESS + "/harness.html", timeout=2)
        return True
    except Exception:
        return False


@unittest.skipUnless(_harness_up() and Path(CHROME).exists(), "harness 没在跑 —— skip 不是绿")
class Rendered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close()
        cls.pw.stop()

    def _page(self, q="", w=1200, h=800, sel="[data-relay-detail]"):
        pg = self.br.new_page(viewport={"width": w, "height": h})
        pg.goto(f"{HARNESS}/harness.html?nav=relay&{q}")
        pg.wait_for_selector(sel, timeout=15000)
        pg.wait_for_timeout(400)
        return pg

    def test_route_map_has_five_entries_and_vscode_bypasses(self):
        pg = self._page()
        r = pg.evaluate("""() => [...document.querySelectorAll('[data-route-entry]')].map(e => [e.dataset.routeEntry, e.lastElementChild.textContent])""")
        pg.close()
        self.assertEqual([x[0] for x in r], ["codex", "cxp exec · omc", "\\codex", "cxd", "VS Code"])
        by = dict(r)
        # 默认夹具 `conn=mixed`：wrapper 是别人的（external）
        self.assertEqual(by["\\codex"], "看你的 wrapper")
        self.assertEqual(by["VS Code"], "不经过代理")

    def test_backslash_codex_follows_the_wrapper_state(self):
        """★★ `\\codex` 走不走代理取决于 PATH wrapper（全方面评审 §4：原来无条件写「走代理」）。"""
        for conn, want in (("ready", "走代理"), ("fresh", "不经过代理"), ("mixed", "看你的 wrapper")):
            with self.subTest(conn=conn):
                pg = self._page(f"conn={conn}")
                r = pg.evaluate("""() => [...document.querySelectorAll('[data-route-entry]')].map(e => [e.dataset.routeEntry, e.lastElementChild.textContent])""")
                pg.close()
                self.assertEqual(dict(r)["\\codex"], want)

    def test_hover_card_opens_after_delay_and_slides(self):
        pg = self._page()
        pg.hover('[data-route-entry="codex"]')
        pg.wait_for_timeout(60)
        early = pg.evaluate("() => document.querySelector('[data-route-hover]').dataset.routeHover")
        pg.wait_for_timeout(300)
        first = pg.evaluate("() => [document.querySelector('[data-route-hover]').dataset.routeHover, getComputedStyle(document.querySelector('[data-route-hover]')).opacity]")
        pg.hover('[data-route-entry="VS Code"]')
        pg.wait_for_timeout(40)
        moved = pg.evaluate("() => document.querySelector('[data-route-hover]').dataset.routeHover")
        pg.close()
        self.assertEqual(early, "", "★ 掠过就弹卡（要停 180 ms）")
        self.assertEqual(first[0], "codex")
        self.assertEqual(moved, "VS Code", "★ 已开着时换入口没有直接滑过去")

    def test_zero_balance_banner_offers_the_pool(self):
        pg = self._page("relay=zero")
        r = pg.evaluate("""() => { const b = document.querySelector('[data-relay-banner]');
            return b && [b.dataset.relayBanner, b.textContent, document.querySelector('[data-relay-balance]').textContent]; }""")
        pg.close()
        self.assertIsNotNone(r, "余额 0 却没有横幅")
        self.assertEqual(r[0], "zero")
        self.assertIn("切回账号池", r[1])
        self.assertIn("0", r[2])

    def test_today_models_render_on_the_default_fixture(self):
        """★ 夹具日期按本机自然日（评审 gemini 阶段 5：UTC 日期让新加坡 0–8 点「今天」那行落到昨天）。"""
        pg = self._page()
        r = pg.evaluate("() => [document.querySelectorAll('[data-relay-model]').length, !!document.querySelector('[data-relay-models-none]')]")
        pg.close()
        self.assertEqual(r, [2, False])

    def test_stale_snapshot_banner_and_dim(self):
        pg = self._page("relay=stale")
        r = pg.evaluate("() => [...document.querySelectorAll('[data-relay-banner]')].map(b => b.dataset.relayBanner)")
        pg.close()
        self.assertEqual(r, ["stale"])

    def test_pair_shows_view_seg_and_sums(self):
        pg = self._page("relay=pair")
        r = pg.evaluate("""() => ({ views: [...document.querySelectorAll('[data-relay-view]')].map(b => b.dataset.relayView),
            bal: document.querySelector('[data-relay-balance]').textContent,
            accs: document.querySelectorAll('[data-relay-acc]').length })""")
        pg.click('[data-relay-view="sum"]')
        pg.wait_for_timeout(150)
        total = pg.evaluate("() => document.querySelector('[data-relay-balance]').textContent")
        pg.click('[data-relay-view="tokendun2"]')
        pg.wait_for_timeout(150)
        one = pg.evaluate("() => document.querySelector('[data-relay-balance]').textContent")
        pg.close()
        self.assertEqual(r["views"], ["sum", "tokendun", "tokendun2"])
        self.assertIn("69.88", r["bal"], "出口在这一组时，默认视角应是出口账户")
        self.assertIn("82.28", total, "★ 同组同币种的合计不是两者之和")
        self.assertEqual(r["accs"], 2, "平台节点下没有两个账户")
        self.assertIn("12.4", one)

    def test_failed_write_never_reports_success(self):
        """★ 评审 gemini 阶段 5：`ok:false` 是正常返回不是异常；停用当前出口写盘失败时还说「出口回落到账号池」。"""
        pg = self._page("relayfail=set")
        pg.click('[data-act="menu:tokendun"]')
        pg.click('[data-act="toggle:tokendun"]')
        pg.wait_for_timeout(400)
        body = pg.evaluate("() => document.body.innerText")
        pg.close()
        self.assertNotIn("已停用", body)
        self.assertIn("写盘失败", body, "失败原因没给用户看")

    def test_delete_needs_confirmation(self):
        pg = self._page()
        pg.click('[data-act="menu:tokendun"]')
        pg.click('[data-act="del:tokendun"]')
        pg.wait_for_selector("[data-ov-confirm]", timeout=3000)
        before = pg.evaluate("() => window.__relayCalls.filter(c => c.startsWith('remove')).length")
        pg.click("[data-confirm-cancel]")
        pg.wait_for_timeout(100)
        gone = pg.evaluate("() => !document.querySelector('[data-ov-confirm]')")
        pg.click('[data-act="menu:tokendun"]')
        pg.click('[data-act="del:tokendun"]')
        pg.click("[data-confirm-delete]")
        pg.wait_for_timeout(300)
        after = pg.evaluate("() => window.__relayCalls.filter(c => c.startsWith('remove'))")
        pg.close()
        self.assertEqual(before, 0, "★★ 点「删除」就直接删了，没等确认")
        self.assertTrue(gone)
        self.assertEqual(after, ["remove:tokendun"], "确认后没发 / 发了不止一次")


if __name__ == "__main__":
    unittest.main()
