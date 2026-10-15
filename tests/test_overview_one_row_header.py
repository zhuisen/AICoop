"""总览顶栏一行（用户 2026-10-15）：

「最小窗口的情况下总览页面顶部要一行展示所有，就是总览 codex gemini grok 刷新全池 检查token等等。
如果太小放不下，那最小尺寸下刷新全池、检查token、探针、定时、切号都减少字数并附上图标就够了」

## 守的
1. `nextCompact`：全名放不下才进紧凑；紧凑态拿**上次全名态量到的宽度**判回不回得去 —— 否则来回翻。
2. 真 bundle 实量：860×560 下三档都是**一行**、动作条是短名、无横向溢出；宽窗口仍是全名。
3. 紧凑态**不丢**两样东西：探针的「计费」角标（唯一花钱的控件），以及悬浮能看到全名。
4. 拉宽拉窄来回走一遍，同一宽度给出同一结果（幂等）。

harness 静态服务（3304）没起时整类 skip —— **skip 不是绿**（memory.md §3）。
"""
import json
import subprocess
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
URL = "http://127.0.0.1:3304/harness.html?nav=home&agypool=3&dawn=on"

HEAD_JS = """() => { const h = document.querySelector('[data-overview-head]'); if (!h) return null;
  const k = [...h.children];
  const btns = [...h.querySelectorAll('[data-head-action]')];
  return { mode: h.dataset.overviewHead,
           tops: k.map(e => Math.round(e.getBoundingClientRect().top)),
           labels: btns.map(b => b.innerText.replace(/\\n/g, ' ').trim()),
           titles: btns.map(b => b.getAttribute('title') || (b.querySelector('[title]') || {}).title || ''),
           svgs: btns.map(b => b.querySelectorAll('svg').length),
           over: document.documentElement.scrollWidth - innerWidth,
           headOver: h.scrollWidth - h.clientWidth }; }"""


def node_eval(expr):
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                        "import('%s').then(m => console.log(JSON.stringify(%s)))"
                        % ((SRC / "hooks" / "useOneRowHeader.ts").as_posix(), expr)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class TheDecisionIsStable(unittest.TestCase):
    def test_enter_and_leave(self):
        self.assertEqual(node_eval("[m.nextCompact(false, 900, 800, 0), m.nextCompact(false, 700, 800, 0)]"),
                         [True, False])

    def test_compact_judges_by_the_last_full_width(self):
        """★ 紧凑态自己的宽度（400）肯定放得下 —— 拿它判就会立刻切回全名、又放不下、再切回来。"""
        self.assertEqual(node_eval("[m.nextCompact(true, 400, 800, 900), m.nextCompact(true, 400, 950, 900)]"),
                         [True, False])


def _measure():
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(URL, timeout=2).read(1)
    except Exception:
        return None
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        for w, h in ((860, 560), (1200, 800)):
            for tab in ("codex", "gemini", "grok"):
                pg = br.new_page(viewport={"width": w, "height": h})
                pg.goto(URL, timeout=30000)
                pg.wait_for_timeout(1300)
                if tab != "codex":
                    pg.click('[data-provtab="%s"]' % tab)
                    pg.wait_for_timeout(1000)
                out[(w, tab)] = pg.evaluate(HEAD_JS)
                pg.close()
        pg = br.new_page(viewport={"width": 860, "height": 600})
        pg.goto(URL, timeout=30000)
        pg.wait_for_timeout(1300)
        seq = []
        for w in (860, 940, 1200, 940, 860, 1200, 940):
            pg.set_viewport_size({"width": w, "height": 600})
            pg.wait_for_timeout(250)
            seq.append((w, pg.evaluate("() => document.querySelector('[data-overview-head]').dataset.overviewHead")))
        out["seq"] = seq
        br.close()
    return out


M = _measure()


@unittest.skipIf(M is None, "harness 3304 没起 / 无 playwright —— 这是 skip 不是绿")
class OneRowOnTheRealBundle(unittest.TestCase):
    def test_min_window_is_one_row_with_short_labels(self):
        for tab in ("codex", "gemini", "grok"):
            r = M[(860, tab)]
            self.assertIsNotNone(r, tab)
            self.assertEqual(len(set(r["tops"])), 1, "★★ %s 档在 860 下顶栏折成了两行：%s" % (tab, r))
            self.assertLessEqual(r["over"], 0, "横向溢出")
            self.assertLessEqual(r["headOver"], 0, "顶栏被裁")
        for tab in ("codex", "gemini"):
            r = M[(860, tab)]
            self.assertEqual(r["mode"], "compact")
            self.assertEqual(len(r["labels"]), 5, "★ 五个动作一个都不能少：%s" % r["labels"])
            joined = " ".join(r["labels"])
            for full in ("刷新全池", "检查 token", "探针 全池", "自动切号"):
                self.assertNotIn(full, joined, "紧凑态还是全名")
            self.assertIn("计费", joined, "★★★ 紧凑态把「计费」角标丢了 —— 唯一花钱的控件必须一眼可辨")
            self.assertTrue(all(n >= 1 for n in r["svgs"]), "★ 短名必须附图标：%s" % r["svgs"])
            for full in ("刷新全池", "检查 token", "自动切号"):
                self.assertTrue(any(full in t for t in r["titles"]), "★ 悬浮看不到全名「%s」：%s" % (full, r["titles"]))

    def test_wide_window_keeps_full_labels(self):
        for tab in ("codex", "gemini"):
            r = M[(1200, tab)]
            self.assertEqual(r["mode"], "full")
            self.assertEqual(len(set(r["tops"])), 1)
            self.assertIn("刷新全池", " ".join(r["labels"]))

    def test_resizing_back_and_forth_is_idempotent(self):
        by_w = {}
        for w, mode in M["seq"]:
            by_w.setdefault(w, set()).add(mode)
        self.assertTrue(all(len(v) == 1 for v in by_w.values()), "★★ 同一宽度给出不同结果（来回翻）：%s" % M["seq"])
        self.assertEqual(by_w[860], {"compact"})
        self.assertEqual(by_w[1200], {"full"})


if __name__ == "__main__":
    unittest.main()
