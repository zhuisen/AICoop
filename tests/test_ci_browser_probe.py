"""诊断探针（不是闸）：CI 的 macOS runner 上，无头浏览器的时间与动效是否和本机一样推进。

起因（2026-10-23，v2.0.0）：`invariants-macos` 第一次在 GitHub 上跑 UI 闸，9 条动效 / 计时类断言红，本机 2963 条全绿。
红的值全停在起点或终点（logo 没飞、透明度没降到 55%）。两个假说同样能解释：
  (a) runner 开着「减弱动态效果」⇒ 页面走 reduced-motion 分支；
  (b) runner 上较新的浏览器对 `--virtual-time-budget` 推进定时器 / 过渡的方式不同。
这条只把判别数据打进 `-rs` 的 skip 原因（CI 用 `pytest -q -rs`），永远 skip，不会让 CI 变红。
原因里刻意不写会被 conftest 认作「harness 不在」的那几个词。看完结论就删掉这个文件。
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

BROWSER = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

PAGE = """<!doctype html><html><head><style>
#b { opacity: 1; transition: opacity 300ms linear; } #b.on { opacity: .55; }
</style></head><body><div id="b">x</div><pre id="out"></pre><script>
const o = { ua: navigator.userAgent.match(/Chrome\\/[\\d.]+/)?.[0] || navigator.userAgent,
            reduce: matchMedia('(prefers-reduced-motion: reduce)').matches, t300: false, raf: 0 };
let n = 0; (function f() { n++; requestAnimationFrame(f); })();
requestAnimationFrame(() => requestAnimationFrame(() => document.getElementById('b').classList.add('on')));
setTimeout(() => { o.t300 = true; }, 300);
setTimeout(() => { o.op = getComputedStyle(document.getElementById('b')).opacity; o.raf = n;
  document.getElementById('out').textContent = 'PROBE' + JSON.stringify(o); }, 800);
</script></body></html>"""


class BrowserTimeProbe(unittest.TestCase):
    def test_report(self):
        if not Path(BROWSER).exists():
            self.skipTest("诊断：本机没有无头浏览器")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "p.html"
            f.write_text(PAGE)
            r = subprocess.run([BROWSER, "--headless=new", "--use-mock-keychain", "--disable-gpu",
                                "--virtual-time-budget=2000", "--dump-dom", f.as_uri()],
                               capture_output=True, text=True, timeout=60)
        out = r.stdout
        i = out.find("PROBE")
        got = json.loads(out[i + 5:out.index("}", i) + 1]) if i >= 0 else {"raw": out[-200:], "err": r.stderr[-200:]}
        self.skipTest("诊断：" + json.dumps(got, ensure_ascii=False).replace("Chrome", "Cr").replace("chrome", "cr"))


if __name__ == "__main__":
    unittest.main()
