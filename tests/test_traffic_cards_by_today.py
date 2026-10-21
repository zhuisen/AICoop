"""用量页底部平台卡按「今日」token 降序（用户 2026-10-15：「AI用量最下面的卡片，按今日的 token 消耗进行排序」）。

截图里的顺序是 Claude 392M · Codex 13M · Grok 4M · Antigravity 93M —— 卡片跟着列表的用户排序走，
而卡片的大字是「今日」，读者按大字找最忙的那家，排序却按别的口径。

## 守的
1. `sortCardsByToday`：按卡上那个「今日」值降序；相同保持原顺序；**不改**传入的列表（列表/图例仍按用户排序）。
2. 「今日」取值与卡片大字同源（`cardTodayOf`）：今日档 = 整档合计，其余档 = 最后一个桶。
3. 真 bundle：30d 与今日两档下，DOM 里的卡片顺序与 `data-today` 降序一致。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import re
import subprocess
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def ts_eval(expr):
    src = (SRC / "traffic.ts").read_text(encoding="utf-8")
    for dep in ("rates", "theme"):
        src = src.replace('from "./%s"' % dep, 'from "%s"' % (SRC / ("%s.ts" % dep)).as_posix())
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "traffic.ts"
        f.write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                            "import('%s').then(m => console.log(JSON.stringify(%s)))" % (f.as_posix(), expr)],
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


L = ('[{k:"claude",total:900,buckets:[{total:5},{total:392}]},{k:"codex",total:100,buckets:[{total:1},{total:13}]},'
     '{k:"grok",total:50,buckets:[{total:9},{total:4}]},{k:"agy",total:30,buckets:[{total:0},{total:93}]},'
     '{k:"kimi",total:1,buckets:[]}]')


class TheOrder(unittest.TestCase):
    def test_range_view_sorts_by_the_last_bucket(self):
        self.assertEqual(ts_eval("m.sortCardsByToday(%s, false).map(x => x.k)" % L),
                         ["claude", "agy", "codex", "grok", "kimi"])

    def test_today_view_sorts_by_the_total(self):
        self.assertEqual(ts_eval("m.sortCardsByToday(%s, true).map(x => x.k)" % L),
                         ["claude", "codex", "grok", "agy", "kimi"])

    def test_ties_keep_the_given_order_and_input_is_untouched(self):
        r = ts_eval('(() => { const l = [{k:"a",total:1,buckets:[{total:7}]},{k:"b",total:1,buckets:[{total:7}]},'
                    '{k:"c",total:1,buckets:[{total:9}]}]; const o = m.sortCardsByToday(l, false);'
                    ' return [o.map(x => x.k), l.map(x => x.k)]; })()')
        self.assertEqual(r, [["c", "a", "b"], ["a", "b", "c"]], "★ 列表/图例仍按用户排序 —— 不许原地改")

    def test_the_card_shows_the_same_number_it_is_sorted_by(self):
        """2026-10-22 改写（AICoop R2）：卡上「今日」改成**今天这一天**的 token（卡底一行），
        排序、`data-today`、卡底数字三处都读 `todayTok(data, key, today)`，不再按「最后一个桶」。"""
        code = re.sub(r"//[^\n]*", "", (SRC / "pages" / "TrafficPage.tsx").read_text(encoding="utf-8"))
        self.assertIn("[...list].sort((a, b) => todayTok(data, b.key, today) - todayTok(data, a.key, today))", code)
        self.assertIn("{cards.map((r) => (\n                <TkCard", code, "★ 渲染的不是排好序的那份")
        self.assertIn("data-today={todayTok(data, r.key, today)}", code, "★ 排序口径与卡上的数不同源")
        self.assertIn("今日 <span style={{ color: p.text }}>{fmtTokL(todayB?.total ?? 0, L)}", code)
        self.assertIn("const todayB: Bucket | undefined = data.platforms[r.key]?.days[today];", code)


def _cards(q):
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen("http://127.0.0.1:3304/harness.html", timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = br.new_page(viewport={"width": 1200, "height": 800})
        pg.goto("http://127.0.0.1:3304/harness.html?" + q, timeout=30000)
        pg.wait_for_timeout(1800)
        r = pg.evaluate("() => [...document.querySelectorAll('[data-plat-card]')]"
                        ".map(e => [e.dataset.platCard, Number(e.dataset.today)])")
        br.close()
    return r


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class OnTheRealBundle(unittest.TestCase):
    def test_cards_are_in_descending_today_order(self):
        for q in ("nav=traffic", "nav=traffic&tab=today"):
            r = _cards(q)
            if r is None:
                self.skipTest("harness 3304 没起 —— skip 不是绿")
            with self.subTest(q=q):
                self.assertGreaterEqual(len(r), 3, "卡片没渲染出来：%s" % r)
                vals = [v for _, v in r]
                self.assertEqual(vals, sorted(vals, reverse=True), "★★ 卡片没按今日降序：%s" % r)
                self.assertGreater(len(set(vals)), 1, "夹具里今日值全相同 —— 断言打空了")


if __name__ == "__main__":
    unittest.main()
