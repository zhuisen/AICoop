"""两条 2026-09-23 的用户需求，各一组**行为闸**（真渲染 + 真计时，不是源码文本匹配）。

## ① 菜单栏跟着代理轮换走

用户原话：「现在是代理轮换的状态，我希望菜单栏显示的账号信息跟着代理轮换走」。

此前菜单栏（托盘标题 + 弹窗里高亮的那一行）读的都是 `state.active` —— **上次 CLI 切换**
留下的号，也就是 `~/.codex/auth.json` 里那个，只有**不走代理直连**时才用得上。
逐请求轮换下 `active` 可以几天不变，菜单栏就一直挂着一个代理根本没在用的号。
现在改读 `last_aid`（proxy.py 每次成功响应后写入），取不到才退回 `active`。

★★ **夹具里 `last_aid` 与 `active` 必须不同**（make_harness.py 已这样造）——
  两者相同时，读哪个都是同一个像素，改没改都绿（本仓形态⑩）。本文件第一条先证这个前提。

## ② 卡片动作弹层打开后到点直接收回（2026-10-19 随弹层一起作废，见文末；仍成立的「收回不生硬」改守悬停底栏）

★ 用 Chrome headless 的 `--virtual-time-budget` **真的让时间走过去**，而不是断言源码里有个数字：
  那种断言在「计时器根本没挂上」「挂上了但被每次渲染重置」时同样是绿的。
"""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "codexbar" / "uishot" / "app"
HARNESS = "http://127.0.0.1:3304"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _probe(page_file, query, js, width=1300, budget=9000):
    import urllib.request
    src = APP_DIR / page_file
    if not Path(CHROME).exists() or not src.exists():
        return None
    try:
        urllib.request.urlopen(HARNESS, timeout=2).read(1)
    except Exception:
        return None
    page = APP_DIR / ("mfprobe_" + page_file)
    page.write_text(src.read_text(encoding="utf-8").replace(
        "</body>", f"<script>{js}</script></body>", 1), encoding="utf-8")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--use-mock-keychain", "--disable-gpu",
                            f"--window-size={width},900", f"--virtual-time-budget={budget}",
                            "--dump-dom", f"{HARNESS}/{page.name}?{query}"],
                           capture_output=True, text=True, timeout=240)
        m = re.search(r"__MF__(\{.*?\})\s*</title>", r.stdout, re.S)
        return json.loads(m.group(1)) if m else None
    finally:
        page.unlink(missing_ok=True)


# 菜单栏：读出高亮（「✓ 在用」）落在哪一行，以及夹具里 active / last_aid 各是谁。
_MB_PROBE = r"""
setTimeout(function () {
 // ★ 夹具经打桩的 IPC 读 —— harness 的 `STATE` 在闭包里，全局取不到（第一版就栽在这，
 //   两个 label 都是 null，「前提成立」那条当场判红才发现）。
 window.__TAURI_INTERNALS__.invoke('read_state', {}).then(function (S) {
  var out = {};
  function lab(aid) { return S && S.slots && S.slots[aid] ? S.slots[aid].label : null; }
  out.activeLabel = S ? lab(S.active) : null;
  out.lastLabel = S ? lab(S.last_aid) : null;
  out.rows = [].slice.call(document.querySelectorAll('.mb-row-info')).length;
  out.inUse = [];
  [].slice.call(document.querySelectorAll('.mb-row-info')).forEach(function (r) {
    if ((r.textContent || '').indexOf('在用') >= 0) {
      var n = r.querySelector('.mb-row-name');
      out.inUse.push(n ? n.textContent.trim() : '?');
    }
  });
  out.oldWord = [].slice.call(document.querySelectorAll('.mb-row-info'))
      .some(function (r) { return /✓ 当前/.test(r.textContent || ''); });
  document.title = '__MF__' + JSON.stringify(out);
 });
}, 2800);
"""


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheMenubarHighlightsWhatTheProxyIsUsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _probe("harness-menubar.html", "w=352&tab=acc", _MB_PROBE, width=520)
        if cls.r is None:
            raise unittest.SkipTest("harness 静态服务（3304）没在跑")

    def test_the_fixture_can_tell_the_two_apart(self):
        """★★ 前提：夹具里两者不同。相同的话下面那条改没改都绿。"""
        self.assertTrue(self.r["activeLabel"] and self.r["lastLabel"],
                        f"★★ 夹具没给出 active / last_aid：{self.r}")
        self.assertNotEqual(self.r["activeLabel"], self.r["lastLabel"],
                            "★★ 夹具里 active == last_aid —— 这组闸没有判别力")

    def test_it_actually_rendered_rows(self):
        self.assertGreaterEqual(self.r["rows"], 3, f"★ 菜单栏账号行没渲染：{self.r}")

    def test_exactly_one_row_is_in_use_and_it_is_the_proxys(self):
        """★★★ 高亮**只有一行**，且是 `last_aid` 那个号，不是 `active`。"""
        self.assertEqual([self.r["lastLabel"]], self.r["inUse"],
                         f"★★★ 「在用」落在 {self.r['inUse']}，"
                         f"应是代理最近用的 {self.r['lastLabel']}（不是 CLI 切换的 {self.r['activeLabel']}）")

    def test_the_old_wording_is_gone(self):
        """★ 「✓ 当前」是 `active` 那套语义的文案，留着会与「在用」并存成两个答案。"""
        self.assertFalse(self.r["oldWord"], "★ 菜单栏行里还有「✓ 当前」")


class TheTrayTitleFollowsTheProxyToo(unittest.TestCase):
    """托盘标题在 Rust 里，harness 渲染不到 —— 只能守**判据的形状**，并与前端比对。

    ⚠️ 这是结构闸不是行为闸，已知它拦不住「写对了但读错了字段名」以外的错误。
      托盘的像素证据只能靠真机（TCC 挡住了截屏，见 CLAUDE.md §2）。
    """

    def test_rust_prefers_last_aid_and_falls_back_to_active(self):
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("fn format_tray_title()")
        seg = rs[i:rs.index("\nfn ", i + 1)]
        code = "\n".join(l.split("//")[0] for l in seg.splitlines())
        self.assertIn('state["last_aid"]', code, "★★ 托盘没读 last_aid —— 仍停在上次 CLI 切换的号")
        self.assertIn("contains_key(last)", code,
                      "★ 没核 last_aid 还在池子里 —— 指向已删的号时托盘会显示 `codex`")
        self.assertIn('state["active"]', code, "★ 取不到 last_aid 时没退回 active")

    def test_frontend_uses_the_same_rule(self):
        """★ 跨语言两份实现，判据必须一致：都是「last_aid 在池里就用它，否则 active」。"""
        # 2026-10-17 起判据抽进 `helpers.ts::inUseAid`（刘海条也要用），TS 侧只此一份。
        src = ROOT / "codexbar" / "src"
        helpers = (src / "helpers.ts").read_text(encoding="utf-8")
        self.assertRegex(helpers, r"export function inUseAid\(state: AppState\)[^{]*\{\s*"
                                  r"return\s*\(state\.last_aid\s*&&\s*state\.slots\?\.\[state\.last_aid\]\)"
                                  r"\s*\?\s*state\.last_aid\s*:\s*state\.active;",
                         "★ 前端的「在用」判据与托盘不一致")
        for f in (src / "hooks" / "useStore.ts", src / "NotchHud.tsx"):
            self.assertRegex(f.read_text(encoding="utf-8"), r"\binUseAid\(state\)",
                             f"★ {f.name} 没走 inUseAid —— 又多出一份「在用」判据")
        # 刘海条里 inUseAid 调了两处，只核「出现过」会被另一处兜住；另写一份判据绕不开这两个字段。
        notch = re.sub(r"//[^\n]*", "", (src / "NotchHud.tsx").read_text(encoding="utf-8"))
        self.assertNotRegex(notch, r"state\.(active|last_aid)\b",
                            "★ 刘海条自己读 active/last_aid —— 又多出一份「在用」判据")
        store = re.sub(r"//[^\n]*", "", (src / "hooks" / "useStore.ts").read_text(encoding="utf-8"))
        rhs = re.findall(r"\bconst inUseNode\s*=\s*([^;]+);", store)
        self.assertEqual(rhs, ["inUseAid(state)"], "★ useStore 的 inUseNode 没走 inUseAid")


# ★ 2026-10-19 **作废并取代**（交接包 page5 · 5b，PLAN §4 F5）：
#   原来两组闸守的是「点卡片弹出的动作弹层」（`CardActionBar`）：到 `CARD_ACTIONS_LIFE_MS`（5 s）直接收回、
#   收回时原路退回（cbSink 140 ms）+ 倒计时细线。交接包把这层浮层整个删掉，换成**悬停时底栏原位换成操作**
#   （`ov/OvCard` 的 `.ov-fact`），鼠标一离开就收 —— 「打开后一直挂着盖住卡片」这个问题本身不存在了，
#   定时收回、倒计时细线随之删除（常量与 keyframes 一起删）。
#   两条用户诉求里**仍成立的那条**原样守：收回不许「一帧就没了」（用户 2026-09-23：「现在太生硬了」），
#   且收回途中点不中（不会点中一个正在消失的按钮）。用 Playwright 的**真鼠标 + 真时间**（不开 notrans）。
_HOVER_JS = """async () => {
  const card = document.querySelectorAll('[data-cards-grid] > [data-aid]')[1];
  const fact = card && card.querySelector('[data-ov-actions]');
  if (!fact) return null;
  const read = () => { const cs = getComputedStyle(fact); return { op: cs.display === 'none' ? 0 : +cs.opacity, pe: cs.display === 'none' ? 'none' : cs.pointerEvents }; };
  return read();
}"""
_LEAVE_JS = """async () => {
  const card = document.querySelectorAll('[data-cards-grid] > [data-aid]')[1];
  const fact = card.querySelector('[data-ov-actions]');
  const out = [];
  const t0 = performance.now();
  while (performance.now() - t0 < 700) {
    const cs = getComputedStyle(fact);
    // ★ P5：没显示的那组是 display:none（opacity 仍是 1）⇒ 按 display 判
    const hid = cs.display === 'none';
    out.push({ t: Math.round(performance.now() - t0), op: hid ? 0 : +cs.opacity, pe: hid ? 'none' : cs.pointerEvents });
    await new Promise(r => setTimeout(r, 16));
  }
  return out;
}"""


def _hover_leave():
    import os
    import urllib.request
    if os.environ.get("OV_REBUILD") == "1":      # tools/mutate.py 变异源码后必须重编，否则测的是旧 bundle
        cb = ROOT / "codexbar"
        subprocess.run(["npx", "vite", "build", "--outDir", "uishot/app"], cwd=cb, check=True, capture_output=True, timeout=300)
        subprocess.run(["python3", "uishot/make_harness.py"], cwd=cb, check=True, capture_output=True, timeout=300)
    try:
        from playwright.sync_api import sync_playwright
        urllib.request.urlopen(HARNESS + "/harness.html", timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True, args=["--use-mock-keychain"])
        pg = br.new_page(viewport={"width": 1200, "height": 860})
        pg.goto(HARNESS + "/harness.html?nav=home", timeout=30000)
        pg.wait_for_timeout(2600)
        box = pg.locator("[data-cards-grid] > [data-aid]").nth(1).bounding_box()
        before = pg.evaluate(_HOVER_JS)
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + 40)
        pg.wait_for_timeout(500)
        shown = pg.evaluate(_HOVER_JS)
        pg.mouse.move(5, box["y"] + box["height"] + 300)
        trail = pg.evaluate(_LEAVE_JS)
        br.close()
    return before, shown, trail


@unittest.skipIf(not Path(CHROME).exists(), "没有 Chrome")
class TheHoverActionsLeaveTheWayTheyCame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = _hover_leave()
        if r is None:
            raise unittest.SkipTest("harness 静态服务（3304）没在跑 / 没有 playwright —— skip 不是绿")
        cls.before, cls.shown, cls.trail = r

    def test_it_was_hidden_then_shown(self):
        """★★ 先证悬停真的换出了操作 —— 没出来时「收回不生硬」是白绿。"""
        self.assertIsNotNone(self.before, "★★ 找不到第 2 张卡的操作层")
        self.assertLess(self.before["op"], .05, "★ 没悬停时操作就露着")
        self.assertEqual("none", self.before["pe"], "★ 没悬停时操作点得中")
        self.assertGreater(self.shown["op"], .95, "★★ 真鼠标悬停了，操作没换出来")
        self.assertNotEqual("none", self.shown["pe"], "★★ 换出来了却点不中")

    def test_leaving_puts_the_footer_back(self):
        """✗「收回不许一帧就没了」已被 AICoop P5（2026-10-21）取代：交接包 §3.3 写明默认底栏与操作组
        **互换，不是交叉淡化**（只有入场 `inUp .16s`）。这里只守仍成立的那半：离开后操作收起、不残留。"""
        self.assertLess(self.trail[-1]["op"], .05, "★★ 700 ms 后操作还挂着")

    def test_it_cannot_be_clicked_while_leaving(self):
        """★ 退场中还能点 = 会点中一个正在消失的按钮（旧闸同一条）。"""
        for x in self.trail:
            if x["op"] < .95:
                with self.subTest(t=x["t"]):
                    self.assertEqual("none", x["pe"], "★ 退场中还能点")


if __name__ == "__main__":
    unittest.main(verbosity=2)
