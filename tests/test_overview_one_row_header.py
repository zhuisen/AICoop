"""总览顶栏一行（用户 2026-10-15）：

「最小窗口的情况下总览页面顶部要一行展示所有，就是总览 codex gemini grok 刷新全池 检查token等等。
如果太小放不下，那最小尺寸下刷新全池、检查token、探针、定时、切号都减少字数并附上图标就够了」

## 2026-10-19 改写（交接包 page5 · 5b）

头部换成定高 32 的一行：`总览 · [Codex|Claude|Gemini|Grok] · 刷新 · 按住探针 · [定时|自动切号] · ⋯`。
「检查 token」收进 ⋯（交接包没有这颗按钮的位置；它仍在，只是换了地方 —— 闸见
`test_overview_5b`）。全名 / 短名不再「量了自己再判」（旧 `useOneRowHeader` + `nextCompact` 的死区），
而由 `ovLayout(内容区宽)` 直接给（`data-ov-layout`）。用户那句话守的东西不变：

1. 真 bundle 实量：860×560 下四档都是**一行**（按竖直中线判 —— 各控件高度不同，顶边本来就不齐）、
   无横向溢出、头部不被裁；宽窗口是全名。
2. 短名态**不丢**两样东西：探针的「计费」角标（唯一花钱的控件），以及悬浮能看到全名。
3. 拉宽拉窄来回走一遍，同一宽度给出同一结果（幂等）。

harness 静态服务（3304）没起时整类 skip —— **skip 不是绿**（memory.md §3）。
"""
import unittest
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
URL = "http://127.0.0.1:3304/harness.html?nav=home&agypool=3&dawn=on"
TABS = ("codex", "claude", "gemini", "grok")

HEAD_JS = """() => { const h = document.querySelector('[data-overview-head]'); if (!h) return null;
  const mids = [...h.children].map(e => { const r = e.getBoundingClientRect(); return r.height > 0 ? Math.round(r.top + r.height / 2) : null; })
                              .filter(x => x != null);
  const btns = [...h.querySelectorAll('[data-head-action]')];
  return { layout: document.querySelector('[data-ov-layout]').dataset.ovLayout,
           h: Math.round(h.getBoundingClientRect().height), mids,
           labels: btns.map(b => b.innerText.replace(/\\n/g, ' ').trim()),
           titles: btns.map(b => b.getAttribute('title') || (b.querySelector('[title]') || {}).title || ''),
           svgs: btns.map(b => b.querySelectorAll('svg').length),
           tabs: [...h.querySelectorAll('[data-provtab]')].map(t => t.dataset.provtab),
           over: document.documentElement.scrollWidth - innerWidth,
           headOver: h.scrollWidth - h.clientWidth }; }"""


def _measure():
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(URL, timeout=2).read(1)
    except Exception:
        return None
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        for w, h in ((860, 560), (1200, 800)):
            for tab in TABS:
                pg = br.new_page(viewport={"width": w, "height": h})
                pg.goto(URL, timeout=30000)
                pg.wait_for_timeout(1300)
                if tab != "codex":
                    pg.click('[data-provtab="%s"]' % tab)
                    pg.wait_for_timeout(900)
                out[(w, tab)] = pg.evaluate(HEAD_JS)
                pg.close()
        pg = br.new_page(viewport={"width": 860, "height": 600})
        pg.goto(URL, timeout=30000)
        pg.wait_for_timeout(1300)
        seq = []
        for w in (860, 1000, 1200, 1000, 860, 1200, 1000):
            pg.set_viewport_size({"width": w, "height": 600})
            pg.wait_for_timeout(250)
            seq.append((w, pg.evaluate("() => document.querySelector('[data-ov-layout]').dataset.ovLayout")))
        out["seq"] = seq
        br.close()
    return out


M = _measure()


@unittest.skipIf(M is None, "harness 3304 没起 / 无 playwright —— 这是 skip 不是绿")
class OneRowOnTheRealBundle(unittest.TestCase):
    def test_it_measured_the_header(self):
        for k, r in M.items():
            if k == "seq":
                continue
            with self.subTest(k=k):
                self.assertIsNotNone(r, "★★ 没有头部 —— 下面的断言全打空")
                self.assertEqual(r["tabs"], list(TABS), "★ 平台档顺序 / 个数不对")
                self.assertGreaterEqual(len(r["mids"]), 4, "★ 头部少于 总览 · 平台档 · 刷新 · ⋯")

    def test_min_window_is_one_row_with_short_labels(self):
        for tab in TABS:
            with self.subTest(tab=tab):
                r = M[(860, tab)]
                self.assertEqual(r["h"], 32, "★ 头部不是定高 32：%s" % r)
                self.assertLessEqual(max(r["mids"]) - min(r["mids"]), 1, "★★ %s 档在 860 下头部折成了两行：%s" % (tab, r))
                self.assertLessEqual(r["over"], 0, "横向溢出")
                self.assertLessEqual(r["headOver"], 0, "头部被裁")
        for tab in ("codex", "gemini"):
            with self.subTest(tab=tab):
                r = M[(860, tab)]
                self.assertEqual(r["layout"], "3")   # AICoop P5_Spec §01：860 也排 3 列
                self.assertEqual(len(r["labels"]), 4, "★ 刷新 / 探针 / 定时 / 自动切号一个都不能少：%s" % r["labels"])
                joined = " ".join(r["labels"])
                for full in ("刷新全池", "定时", "自动切号"):
                    self.assertNotIn(full, joined, "短名态还是全名")
                self.assertIn("计费", joined, "★★★ 短名态把「计费」角标丢了 —— 唯一花钱的控件必须一眼可辨")
                self.assertTrue(all(n >= 1 for n in r["svgs"]), "★ 短名必须附图标：%s" % r["svgs"])
                for full in ("刷新全池", "定时探针", "自动切号"):
                    self.assertTrue(any(full in t for t in r["titles"]), "★ 悬浮看不到全名「%s」：%s" % (full, r["titles"]))

    def test_wide_window_keeps_full_labels(self):
        for tab in ("codex", "gemini"):
            with self.subTest(tab=tab):
                r = M[(1200, tab)]
                self.assertEqual(r["layout"], "4")
                self.assertLessEqual(max(r["mids"]) - min(r["mids"]), 1)
                joined = " ".join(r["labels"])
                for full in ("刷新全池", "定时", "自动切号"):
                    self.assertIn(full, joined)

    def test_resizing_back_and_forth_is_idempotent(self):
        by_w = {}
        for w, mode in M["seq"]:
            by_w.setdefault(w, set()).add(mode)
        self.assertTrue(all(len(v) == 1 for v in by_w.values()), "★★ 同一宽度给出不同结果（来回翻）：%s" % M["seq"])
        self.assertEqual(by_w[860], {"3"})
        self.assertEqual(by_w[1000], {"3"})
        self.assertEqual(by_w[1200], {"4"})


if __name__ == "__main__":
    unittest.main()
