"""环境闸：跑 UI 闸的机器不许开着「减弱动态效果」（否则动效 / 计时类断言成片假红）。

起因（2026-10-23，v2.0.0）：`invariants-macos` 第一次在 GitHub 上跑 UI 闸，9 条动效 / 计时类断言红，本机 2963 条全绿。
红的值全停在起点或终点（logo 没飞、透明度没降到 55%）。两个假说同样能解释：
  (a) runner 开着「减弱动态效果」⇒ 页面走 reduced-motion 分支；
  (b) runner 上较新的浏览器对 `--virtual-time-budget` 推进定时器 / 过渡的方式不同。
判别结果（v2.1.0 的 CI，n=1）：runner 的浏览器与本机同为 156，`reduce=true`（本机 false）⇒ 假说 (a) 成立、(b) 排除。
修法在 `.github/workflows/ci.yml`（跑测试前关掉减弱动态效果）。这条在 `CODEXBAR_REQUIRE_HARNESS=1` 下核它真关掉了：
还开着就红，并说清楚该做什么；其余情况只把数据打进 `-rs` 的 skip 原因。原因里刻意不写会被 conftest 认作「harness 不在」的词。
"""
import json
import os
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
        info = json.dumps(got, ensure_ascii=False).replace("Chrome", "Cr").replace("chrome", "cr")
        if os.environ.get("CODEXBAR_REQUIRE_HARNESS") == "1" and got.get("reduce") is True:
            self.fail("★ 这台机器开着「减弱动态效果」，动效 / 计时类 UI 闸会成片假红。"
                      "CI：确认 ci.yml 里 turn off Reduce Motion 那一步生效；本机：系统设置 → 辅助功能 → 显示 → 关掉减弱动态效果。" + info)
        self.skipTest("诊断：" + info)


if __name__ == "__main__":
    unittest.main()
