"""AICoop P7（代理轮换改版，阶段 5）要的三个后端口径。

1. **换号 = 账号变了**。同号空闲 > `SEG_GAP_SECS` 再上岗会断成两段，但不是换号 ——
   算进来 KPI「换号」与接力线 / 轮换记录对不上（agy 版本来就只数 changes）。
2. **右列「5h 额度」只看 5h 窗口**（`window_minutes == 300`），不是最紧窗口；Pro 没有 5h ⇒ None。
3. **冷却中 = `cooling_until` 晚于现在**；已过 / 读不到 ⇒ None。

纯函数，按路径 import（`rotation.py` 顶层只有常量）。
"""
import importlib.util
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("rot_p7", ROOT / "traffic" / "rotation.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def segs_of(*runs):
    return [{"acc": a, "start": s, "end": e, "requests": 1, "tokens": 0, "by_model": []} for a, s, e in runs]


class SwitchesCountAccountChangesOnly(unittest.TestCase):
    def test_same_account_resuming_is_not_a_switch(self):
        segs = R.classify_enter(segs_of(("A", 0, 100), ("A", 2000, 2100), ("B", 2200, 2300)), [])
        self.assertEqual(R._switches(segs), 1)
        self.assertEqual(segs[1]["enter_reason"], "resume")
        evs = [e for e in R._events(segs, []) if e["type"] in ("switch", "failover")]
        self.assertEqual([(e["from"], e["to"]) for e in evs], [("A", "B")], "★ 同号重入被记成了一次换号")

    def test_real_switches_still_count(self):
        segs = R.classify_enter(segs_of(("A", 0, 100), ("B", 200, 300), ("A", 400, 500)), [])
        self.assertEqual(R._switches(segs), 2)
        self.assertEqual(len([e for e in R._events(segs, []) if e["type"] == "switch"]), 2)


class FiveHourColumn(unittest.TestCase):
    NOW = time.time()

    def slot(self, *wins, cap=None):
        q = {"captured_at": cap or self.NOW}
        for key, mins, used, ra in wins:
            q[key] = {"window_minutes": mins, "used_percent": used, "resets_at": ra}
        return {"quota": q}

    def test_picks_the_5h_window_not_the_tightest(self):
        s = self.slot(("primary", 300, 20, self.NOW + 3600), ("secondary", 10080, 90, self.NOW + 86400))
        self.assertEqual(R._quota_pct(s, 300), 80.0)
        self.assertEqual(R._quota_pct(s), 10.0, "最紧窗口那一列不该被改")

    def test_pro_without_5h_is_none(self):
        self.assertIsNone(R._quota_pct(self.slot(("primary", 10080, 30, self.NOW + 86400)), 300))

    def test_reset_passed_without_new_reading_is_none(self):
        s = self.slot(("primary", 300, 20, self.NOW - 60), cap=self.NOW - 3600)
        self.assertIsNone(R._quota_pct(s, 300), "★ 过了重置点却没有新读数 ⇒ 未知，不画满")


class AgyFiveHourIsNeverAStaleReading(unittest.TestCase):
    """★ 评审（codex，阶段 5）：重置点已过的桶仍返回 80% —— 把窗口重置前的旧数当成现在的额度。"""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("agy_rot_p7", ROOT / "traffic" / "agy_rotation.py")
        cls.A = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.A)

    def acc(self, **b):
        return {"quota_summary": [{"displayName": "Gemini Models", "buckets": [
            {"window": "week", "remainingFraction": 0.5}, {"window": "5h", "remainingFraction": 0.8, **b}]}]}

    def test_three_states(self):
        now = 1_800_000_000.0
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        self.assertEqual(self.A._quota_5h(self.acc(resetTime=iso(now + 3600)), now), 80)
        self.assertIsNone(self.A._quota_5h(self.acc(resetTime=iso(now - 60)), now), "★ 重置点已过还报旧数")
        self.assertIsNone(self.A._quota_5h(self.acc(seenAt=now - 25 * 3600), now), "★ 沿用超过 24 h 的桶还报旧数")
        self.assertIsNone(self.A._quota_5h({"quota_summary": []}, now))


class CoolingUntil(unittest.TestCase):
    def test_three_states(self):
        now = 1_000_000.0
        self.assertEqual(R._cooling_until({"cooling_until": now + 60}, now), now + 60)
        self.assertIsNone(R._cooling_until({"cooling_until": now - 1}, now))
        self.assertIsNone(R._cooling_until({"cooling_until": "x"}, now))
        self.assertIsNone(R._cooling_until(None, now))




# ── 前端（AICoop P7）：纯逻辑 `rotationView.ts` + 真 bundle 渲染 ─────────────────
import json
import shutil
import subprocess
import urllib.request

PURE = ROOT / "codexbar" / "src" / "rotationView.ts"
HARNESS = "http://127.0.0.1:3304"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _node(expr):
    script = ("import('file://%s').then(m => { let v; try { v = (%s); } catch (e) { v = {__throw: String(e)}; }"
              " console.log(JSON.stringify(v === undefined ? null : v)); });" % (PURE.as_posix(), expr))
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip()]
    if not out:
        raise AssertionError(f"node 没有产出：{r.stderr[-600:]}")
    return json.loads(out[-1])


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class RecordsLogic(unittest.TestCase):
    def test_pro_fallback_is_a_reason_not_a_type(self):
        """★ 后端的 Pro 保底是 `type: switch, reason: pro_fallback` —— 按 type 判就永远认不出来（旧页面就是这样）。"""
        k = _node('m.recKind({t:1,type:"switch",from:"A",to:"P",reason:"pro_fallback",text:"",accs:[]})')
        self.assertEqual(k, "pro")
        self.assertEqual(_node('m.recKind({t:1,type:"switch",from:"A",to:"B",reason:"stream_err",text:"",accs:[]})'), "err")

    def test_stream_text_says_billed_and_whether_it_switched(self):
        """★ 稿写「重试成功」—— 观测不到，不照抄；随后 120 s 内同号换走 ⇒「随后换号」，否则「未换号」。"""
        r = _node('m.recsOf(['
                  '{t:100,type:"stream_err",from:"A",to:null,reason:"stream_err",text:"x",accs:["A"]},'
                  '{t:150,type:"switch",from:"A",to:"B",reason:"stream_err",text:"A → B · 断流 → 轮换 · 上号 3m / 1.0M / 2 次",accs:["A","B"]},'
                  '{t:900,type:"stream_err",from:"B",to:null,reason:"stream_err",text:"x",accs:["B"]}], 1000)'
                  '.map(r => [r.kind, r.head, r.prevStats, r.onDuty])')
        self.assertEqual(r[0], ["stream", "B 流中断 · 未换号 · 已计费", None, None])
        self.assertEqual(r[1], ["err", "A → B · 断流 → 轮换", "上号 3m / 1.0M / 2 次", 850], "★ 上一号统计没挪进展开面板 / 接班时长不对")
        self.assertEqual(r[2][1], "A 流中断 · 随后换号 · 已计费")
        self.assertNotIn("重试成功", json.dumps(r, ensure_ascii=False))

    def test_billed_unknown_has_its_own_filter(self):
        c = _node('m.recCounts([{kind:"billed"},{kind:"safe"},{kind:"err"},{kind:"stream"},{kind:"pro"}])')
        self.assertEqual((c["billed"], c["err"], c["switch"], c["all"]), (1, 2, 1, 5))

    def test_quota_tone_never_paints_unknown_as_full(self):
        self.assertEqual(_node("[m.quota5hTone(null), m.quota5hTone(7), m.quota5hTone(44), m.quota5hTone(82)]"),
                         ["none", "bad", "warn", "ok"])

    def test_concurrent_sessions_are_not_counted_twice(self):
        """★ 评审 codex 阶段 5：同号两段完全重叠的 5 分钟被算成 600 s，还跨过了「≥ 10 分钟算在岗」。"""
        r = _node('m.todGrid(["A"], [{acc:"A",start:1800000000,end:1800000300},{acc:"A",start:1800000000,end:1800000300},'
                  '{acc:"A",start:1800000200,end:1800000400}], [])[0]')
        self.assertEqual(r["secs"], 400)
        self.assertEqual(sum(r["days"]), 0)

    def test_best_window_and_narrow_text(self):
        self.assertEqual(_node("m.bestText(m.bestWindow(Array.from({length:48},(_, i) => i >= 41 && i <= 46 ? 3 : 0)), false)"),
                         "20:30–23:30")
        self.assertEqual(_node("m.bestText(41, true)"), "20–23 点")
        self.assertEqual(_node("m.bestText(m.bestWindow(new Array(48).fill(0)), false)"), "—", "★ 没上过岗却报了常用时段")


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

    def _page(self, q, w=1200, h=800, sel="[data-rot-lane]"):
        pg = self.br.new_page(viewport={"width": w, "height": h})
        pg.goto(f"{HARNESS}/harness.html?nav=logs&{q}")
        pg.wait_for_selector(sel, timeout=15000)
        pg.wait_for_timeout(400)
        return pg

    def test_lanes_follow_pool_order_and_columns_say_unknown(self):
        pg = self._page("rot=ok")
        r = pg.evaluate("""() => [...document.querySelectorAll('[data-rot-lane]')].map(l => ({
            acc: l.dataset.rotLane, tps: l.querySelector('[data-rot-tps]').textContent.trim(),
            q: l.lastElementChild.textContent.trim() }))""")
        pg.close()
        by = {x["acc"]: x for x in r}
        self.assertEqual(len(r), 6)
        self.assertEqual(by["plus4"]["tps"], "102", "★ t/s 不是实测行的中位数（88 / 102 / 140）")
        self.assertEqual(by["plus6"]["tps"], "—", "★★ 估值行进了 t/s —— 用户 10-22 定：只取实测")
        self.assertEqual(by["Pro1"]["q"], "—", "★★ Pro 没有 5h 窗口却画了数 —— 读不到不许当满额")
        self.assertEqual(by["plus3"]["q"], "7%")

    def test_names_fit_their_column(self):
        """★★ 名字不截断（用户 2026-09-07 截图 `Pr…`）。最坏情况 `?rot=procur`（Pro 号当班：PRO + 当前）在 860 宽实量：
        名字右缘不越过账号列、名字自身没被裁。夹具名 `Pro1` 太短（实测 28px，标签也放得下），所以换成长名 `Pro1-backup`。"""
        pg = self._page("rot=procur&rotname=Pro1-backup", w=860, h=700)
        r = pg.evaluate("""() => [...document.querySelectorAll('[data-lane]')].map(c => {
            const n = c.firstElementChild, cr = c.getBoundingClientRect(), nr = n.getBoundingClientRect();
            return {acc: c.dataset.lane, over: nr.right - cr.right, clip: n.scrollWidth - n.clientWidth,
                    tags: [...c.children].slice(1).map(x => x.textContent)}; })""")
        pg.close()
        pro = next(x for x in r if x["acc"] == "Pro1-backup")
        self.assertEqual(pro["tags"], ["当前", "PRO"], "探针失准：最坏情况没渲染出来")
        for x in r:
            with self.subTest(acc=x["acc"]):
                self.assertLessEqual(x["over"], 0.5, "★★ 名字越过了账号列")
                self.assertLessEqual(x["clip"], 0)

    def test_long_window_switches_to_the_account_by_time_grid(self):
        pg = self._page("rotwin=168", sel="[data-rot-tod]")
        r = pg.evaluate("""() => ({ tl: !!document.querySelector('[data-rot-timeline]'),
            rows: [...document.querySelectorAll('[data-rot-tod] [data-rot-lane]')].map(l => l.querySelectorAll('[data-tod-cell]').length),
            concl: document.querySelector('[data-tod-conclusion]').textContent,
            recTitle: document.querySelector('[data-rot-records]').textContent })""")
        pg.close()
        self.assertFalse(r["tl"], "7d 仍画着时间线")
        self.assertTrue(r["rows"] and all(n == 48 for n in r["rows"]), r["rows"])
        self.assertIn("断流最集中在", r["concl"])
        self.assertIn("最近 24h", r["recTitle"], "★ 长周期下记录只列最近 24h，标题没说")

    def test_gemini_has_no_429_or_stream_numbers(self):
        """★ agy 没有代理：429 / 断流写「—」、筛选里没有这两个 chip（画成 0 = 说它确实没发生过）。"""
        pg = self._page("rotplat=agy")
        r = pg.evaluate("""() => ({ k429: document.querySelector('[data-kpi="429"] [data-kpi-value]').textContent,
            kerr: document.querySelector('[data-kpi="断流"] [data-kpi-value]').textContent,
            chips: [...document.querySelectorAll('[data-rec-filter]')].map(b => b.dataset.recFilter),
            label: document.querySelector('[data-kpi="会话"]') != null })""")
        pg.close()
        self.assertEqual((r["k429"], r["kerr"]), ("—", "—"))
        self.assertNotIn("429", r["chips"])
        self.assertNotIn("err", r["chips"])
        self.assertTrue(r["label"], "Gemini 的「请求」没改叫「会话」")

    def test_gemini_long_window_has_no_stream_mode(self):
        pg = self._page("rotplat=agy&rotwin=168", sel="[data-rot-tod]")
        r = pg.evaluate("() => [[...document.querySelectorAll('[data-tod-mode]')].map(b => b.dataset.todMode),"
                        " document.querySelector('[data-tod-conclusion]').textContent]")
        pg.close()
        self.assertEqual(r[0], ["duty"], "★ Gemini 没有代理，却给了「断流」模式")
        self.assertNotIn("没有断流", r[1], "★★ 看不到断流却说「本期没有断流」")

    def test_first_record_open_and_raw_log_replaces_the_list(self):
        pg = self._page("rot=ok", sel="[data-rec]")
        before = pg.evaluate("() => [document.querySelectorAll('[data-rec-open]').length, document.querySelectorAll('[data-rec]').length]")
        pg.click("[data-raw-toggle]")
        pg.wait_for_timeout(200)
        after = pg.evaluate("() => [document.querySelectorAll('[data-rec]').length, document.querySelectorAll('[data-raw-line]').length,"
                            " [...document.querySelectorAll('[data-raw-filter]')].map(b => b.dataset.rawFilter)]")
        pg.close()
        self.assertEqual(before[0], 1, "★ 默认不是只展开第一条")
        self.assertGreater(before[1], 5)
        self.assertEqual(after[0], 0, "原始日志没有替换记录列表")
        self.assertGreater(after[1], 0)
        self.assertEqual(after[2], ["all", "refresh", "switch", "cool"], "★ 旧运行日志的筛选丢了")


if __name__ == "__main__":
    unittest.main()
