"""刘海额度条（`codexbar/src-tauri/src/notch.rs` + `codexbar/src/NotchHud.tsx`）的静态闸。

★ 2026-10-19 起展开态是交接包 4e 的「④ 悬浮卡片 + 光桥」（v1.11.0 的额度环面板退役）。卡片本身的行为闸
  （Tab 规则、告警、版面、logo 来向、果冻下垂、真 bundle 的 DOM）在 `tests/test_notch_card.py`；这里守窗口、
  光晕、取数这些跨版本不变的不变量。

守的都是「错了不报错、只是看着怪」的那一类：
  · 尺寸常量分在 Rust / TS / CSS 三处，对不上时卡片被裁或偏到一边；
  · 少了 fullScreenAuxiliary，切到全屏应用就不见了 —— 2026-10-17 PR #1 作者实测确认过要的就是全屏可见；
  · 新窗口没进 capabilities，invoke/listen 全部静默失败，刘海上永远是一条空槽；
  · 默认关是用户定的（2026-10-17），被顺手改成默认开会让所有人的刘海上多出一条东西。

2026-10-17 四方评审（Opus 5.5 / gpt-6.1-sol / gemini-4-argon / grok-4.7）之后加了两层：
  · **行为闸**：`notchSegs.ts` 是纯函数，node 直接跑真文件 —— 画什么、旧数怎么标、读不到怎么说、
    设置页那一行怎么说「开着但没显示」，都在边界输入上断言，不再只核源码长什么样；
  · **结构闸**：评审抓到的每一类缺陷各一条（数据源、合盖不拆窗、坐标、抢焦点、吞点击、代次、权限）。

不 import 任何项目模块、不碰凭证；node 那半只读 `codexbar/src/*.ts`。
"""
try:
    # ★ 本文件只起 node（跑 notchSegs.ts），不起任何脚本；但它断言了 `agy-quota-updated` 这类事件名，
    #   `test_isolation_bootstrap` 按子串把它算作脚本测试 —— 照规矩引入隔离，免得以后真加了脚本测试时漏掉。
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "codexbar"
RS = APP / "src-tauri" / "src" / "notch.rs"
# ★ 2026-10-19 起「谁在跑」（判据 + FSEvents 监听）从 notch.rs 抽到 activity.rs，刘海与托盘胶囊共用一条
ACT = APP / "src-tauri" / "src" / "activity.rs"
LIB = APP / "src-tauri" / "src" / "lib.rs"
TSX = APP / "src" / "NotchHud.tsx"
CARD = APP / "src" / "notchCard.ts"
CSS = APP / "src" / "notch.css"
SETTINGS = APP / "src" / "pages" / "SettingsPage.tsx"
APP_TSX = APP / "src" / "App.tsx"
SEGS = APP / "src" / "notchSegs.ts"
CAPS = APP / "src-tauri" / "capabilities"
DATA = APP / "src" / "hooks" / "useNotchData.ts"


def code_only(path):
    """去掉注释再匹配 —— 注释里正写着那些词（verification.md 形态⑫）。"""
    s = path.read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/\"])//[^\n]*", "", s)


_code = code_only


def run_segs(expr):
    """把 notchSegs.ts 连同它 import 的 agy.ts / helpers.ts 拷进临时目录（改写成带扩展名的路径），用 node 跑。"""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        for name in ("helpers.ts", "agy.ts", "notchSegs.ts"):
            src = (APP / "src" / name).read_text(encoding="utf-8")
            src = re.sub(r'from "\./(helpers|agy)"', r'from "./\1.ts"', src)
            (d / name).write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                            "import('%s').then(m => console.log(JSON.stringify(%s)))" % ((d / "notchSegs.ts").as_posix(), expr)],
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _one(path, pattern, what):
    hits = re.findall(pattern, path.read_text(encoding="utf-8"), re.M)
    assert len(hits) == 1, f"{path.name} 里 {what} 命中 {len(hits)} 次，应为 1"
    return hits[0]


class SizesAgree(unittest.TestCase):
    def test_card_width_is_the_same_in_three_places(self):
        """4e 卡片宽 300：Rust 按它摆窗口与命中区，网页按它画。对不上 ⇒ 卡片被窗口裁掉一截，或命中区与卡片错位。"""
        rs = float(_one(RS, r"^pub const CARD_W: f64 = (\d+(?:\.\d+)?);", "CARD_W"))
        ts = float(_one(CARD, r"^export const CARD_W = (\d+);", "CARD_W"))
        css = float(_one(CSS, r"--cw: (\d+)px", "--cw"))
        self.assertEqual(rs, ts, "notch.rs 与 notchCard.ts 的卡片宽不一致")
        self.assertEqual(rs, css, "notch.rs 与 notch.css 的 --cw 不一致")
        self.assertRegex(code_only(TSX), r'\["--cw" as string\]: `\$\{C\.CARD_W\}px`', "组件没把 CARD_W 交给 --cw")
        self.assertNotRegex(code_only(RS), r"\bPANEL_W\b", "v1.11.0 的面板宽已随旧面板退役，别留一个没人用的常量")

    def test_card_gap_is_the_same_in_three_places(self):
        """卡片在刘海下沿下方 10 pt（交接包「刘海与卡片之间 10 pt 空隙算卡片内」）：Rust 命中区按它算。"""
        rs = float(_one(RS, r"^pub const CARD_GAP: f64 = (\d+(?:\.\d+)?);", "CARD_GAP"))
        ts = float(_one(CARD, r"^export const CARD_GAP = (\d+);", "CARD_GAP"))
        card = re.search(r"(?m)^\.nh-card \{([^}]*)\}", code_only(CSS)).group(1)
        css = float(re.search(r"top: calc\(var\(--nh\) \+ (\d+)px\)", card).group(1))
        self.assertEqual((rs, ts, css), (rs, rs, rs), "刘海与卡片之间的空隙三处不一致 ⇒ 穿过空隙时会被判成离开")

    def test_flare_matches_the_css(self):
        rs = float(_one(RS, r"^const FLARE: f64 = (\d+(?:\.\d+)?);", "FLARE"))
        css = float(_one(CSS, r"--flare: (\d+)px", "--flare"))
        self.assertEqual(rs, css, "notch.rs 的 FLARE 与 notch.css 的 --flare 不一致")

    def test_window_has_room_for_the_whole_blurred_glow(self):
        """光晕带 blur，窗口留的透明边装不下时，模糊的边缘会被窗口裁出一圈直边。
        blur(σ) 往外 2σ 才淡到 2% —— 第一版按 1σ 留边，作者一眼看出「限制了范围」（2026-10-17）。"""
        css = _code(CSS)
        flare = float(_one(RS, r"^const FLARE: f64 = (\d+(?:\.\d+)?);", "FLARE"))
        gx = float(_one(RS, r"^const GLOW_X: f64 = (\d+(?:\.\d+)?);", "GLOW_X"))
        gy = float(_one(RS, r"^const GLOW_Y: f64 = (\d+(?:\.\d+)?);", "GLOW_Y"))
        layers = re.findall(r"(?m)^\.nh-glow \.(g\d) \{(.*?)\}", css, re.S)
        self.assertEqual([n for n, _ in layers], ["g1", "g2"], "光晕应是贴边 g1 + 散开 g2 两层")
        for name, body in layers:
            extra_w = float(re.search(r"width: calc\(var\(--nw\) \+ var\(--flare\) \* 2 \+ (\d+)px\)", body).group(1))
            extra_h = float(re.search(r"height: calc\(var\(--nh\) \+ (\d+)px\)", body).group(1))
            top = float(re.search(r"top: (-?\d+)px", body).group(1))
            blur = float(re.search(r"filter: blur\((\d+)px\)", body).group(1))
            self.assertGreaterEqual(flare + gx, flare + extra_w / 2 + 2 * blur, f"{name}：两侧透明边装不下光晕 + 2σ")
            self.assertGreaterEqual(gy, top + extra_h + 2 * blur, f"{name}：下方透明边装不下光晕 + 2σ")

    def test_window_has_room_for_the_alert_flash(self):
        """告警快闪团（60 宽、blur 9）在某一段中点；最靠边的那一段也要连 2σ 一起装进透明边。"""
        css = _code(CSS)
        ga = re.search(r"(?m)^\.nh-glow \.ga \{([^}]*)\}", css).group(1)
        w = float(re.search(r"width: (\d+)px", ga).group(1))
        top = float(re.search(r"top: (-?\d+)px", ga).group(1))
        extra_h = float(re.search(r"height: calc\(var\(--nh\) \+ (\d+)px\)", ga).group(1))
        blur = float(re.search(r"filter: blur\((\d+)px\)", ga).group(1))
        flare = float(_one(RS, r"^const FLARE: f64 = (\d+(?:\.\d+)?);", "FLARE"))
        gx = float(_one(RS, r"^const GLOW_X: f64 = (\d+(?:\.\d+)?);", "GLOW_X"))
        gy = float(_one(RS, r"^const GLOW_Y: f64 = (\d+(?:\.\d+)?);", "GLOW_Y"))
        lefts = run_card("[1,2,3,4].flatMap(n => [...Array(n).keys()].map(i => m.alertBlobLeft(i, n, 179)))")
        self.assertGreaterEqual(min(lefts) - 2 * blur, -(flare + gx), "最左那一段的快闪团被窗口左边裁掉")
        self.assertLessEqual(max(lefts) + w + 2 * blur, 179 + flare + gx, "最右那一段的快闪团被窗口右边裁掉")
        self.assertGreaterEqual(gy, top + extra_h + 2 * blur, "快闪团下方装不下 2σ")


class WindowBehaviour(unittest.TestCase):
    def test_sits_above_the_menubar(self):
        self.assertEqual(_one(RS, r"setLevel: (\d+)isize", "setLevel"), "26",
                         "层级必须是 NSStatusWindowLevel+1，低了会被菜单栏盖住")

    def test_visible_over_full_screen_apps(self):
        line = _one(RS, r"let behavior: usize = (.+);", "collectionBehavior")
        self.assertIn("1 << 8", line, "少了 fullScreenAuxiliary(1<<8)，全屏应用里就看不到了")
        self.assertIn("1 << 0", line, "少了 canJoinAllSpaces(1<<0)，切桌面就不见了")

    def test_turning_off_destroys_the_window(self):
        src = RS.read_text(encoding="utf-8")
        body = src[src.index("pub fn set_enabled"):]
        off = body[:body.index("return Ok(Status { active: false, reason: None });")]
        self.assertIn("drop_window(app)", off, "关掉时要销毁窗口，隐藏的 WKWebView 仍常驻两个系统进程")
        self.assertIn("remove_monitors()", off, "关掉时要拆鼠标监听")
        drop = src[src.index("fn drop_window("):src.index("fn reconcile(")]
        self.assertIn(".destroy()", drop, "drop_window 是销毁，不是隐藏")

    def test_commands_are_registered(self):
        lib = LIB.read_text(encoding="utf-8")
        block = re.search(r"generate_handler!\[(.*?)\]\)", lib, re.S)
        self.assertIsNotNone(block, "找不到 invoke_handler 的 generate_handler![...]")
        for cmd in ("set_notch_hud", "notch_geometry", "notch_panel_height", "notch_card_resize", "notch_activity"):
            self.assertRegex(block.group(1), rf"\b{cmd}\b", f"{cmd} 没注册进 invoke_handler")

    def test_window_has_capabilities(self):
        caps = [json.loads(f.read_text(encoding="utf-8")) for f in CAPS.glob("*.json")]
        mine = [c for c in caps if "notch" in c["windows"]]
        self.assertTrue(mine, "notch 窗口不在任何 capability 里 ⇒ invoke/listen 全部静默失败")

    def test_window_gets_only_what_it_needs(self):
        """★ 原来并进 default，顺带拿到了自启动开关、通知、窗口操作 —— 它只画一条线（评审 2026-10-17）。"""
        caps = [json.loads(f.read_text(encoding="utf-8")) for f in CAPS.glob("*.json")]
        mine = [c for c in caps if "notch" in c["windows"]]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["windows"], ["notch"], "notch 不能和别的窗口共用一份 capability")
        self.assertEqual(mine[0]["permissions"], ["core:default"])

    def test_page_is_built(self):
        self.assertIn("notch.html", (APP / "vite.config.ts").read_text(encoding="utf-8"),
                      "vite 没把 notch.html 打进包，窗口会是空白")


class DefaultsAndColour(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(_one(SETTINGS, r"^\s*notchHud: (\w+),", "notchHud 默认值"), "false")

    def test_startup_only_turns_it_on_when_enabled(self):
        app = APP_TSX.read_text(encoding="utf-8")
        self.assertRegex(app, r"if \(st\.notchHud\) invoke(<[^>]*>)?\(\"set_notch_hud\"",
                         "启动时只在开着的情况下调用；无条件调用会让关着的用户也建一次窗口")

    def test_uses_the_tray_colour_rule(self):
        """刘海条和托盘标题是同一类"瞄一眼"的指示，必须同一套颜色（ui.md「额度色阈值只有一条规则」）。
        ★ 改成行为断言：原来的正则核的是那一行字，换个写法就红、写错阈值却可能照样绿。"""
        r = run_segs("[49.9, 50, 1, 0.6, 0.4, 0].map(m.segColor)")
        amber, green, red = "#E0901C", "#27B26B", "#E0524D"
        self.assertEqual(r, [amber, green, amber, amber, red, red],
                         "<50 琥珀、≥50 绿；**显示成 0 的**才标红（剩 0.4% 时环上写着 0，颜色必须跟着它）")
        for f in (TSX, SEGS):
            self.assertNotIn("quotaLevel", code_only(f), "别换成卡片那套 ≤10 红 —— 会和托盘标题说法不一")

    def test_the_ring_number_and_the_colour_agree_at_zero(self):
        self.assertEqual(run_segs("[0.4, 0.6, 100.4, -3].map(m.ringNum)"), [0, 1, 100, 0])


AGY_ACC = {"sub": "s1", "label": "A", "email": "a@x"}


def snap(**kw):
    base = {"schema": 1, "fetched_at": 1_800_000_000, "available": True, "reason": None, "detail": None,
            "pid": None, "last_good": None,
            "quota": {"groups": [{"name": "Gemini", "buckets": [
                {"bucket_id": "g5", "window": "5h", "remaining_percent": 72.4, "reset_at": None},
                {"bucket_id": "gw", "window": "weekly", "remaining_percent": 91.0, "reset_at": None}]}]}}
    base.update(kw)
    return base


class WhatTheStripShows(unittest.TestCase):
    """`notchSegs.ts` 在边界输入上的行为 —— 读不到 ≠ 满格，旧数要说清楚为什么旧。"""

    def test_codex_dead_and_unread_are_grey_not_full(self):
        r = run_segs('[m.codexSegs({status:"dead",windows:[{label:"5h",pct:80,reset:"1h"}]}, false),'
                     ' m.codexSegs({status:"live",windows:[]}, false),'
                     ' m.codexSegs({status:"live",windows:[{label:"5h",pct:40,reset:"2h"},{label:"周",pct:90,reset:"3d"}]}, false),'
                     ' m.codexSegs(undefined, false), m.codexSegs({status:"live",windows:[]}, true)]')
        dead, unread, two, none, off = r
        self.assertEqual([(x["pct"], x["reset"]) for x in dead], [(None, "失效")], "★★ 死号的旧窗口数字不许画出来")
        self.assertEqual([(x["pct"], x["reset"]) for x in unread], [(None, "待刷新")])
        self.assertEqual([x["pct"] for x in two], [40, 90], "每个窗口一段，原值照传")
        self.assertEqual((none, off), ([], []))

    def test_agy_fresh_reading_is_not_marked_stale(self):
        r = run_segs("m.agySegs(%s, false)" % json.dumps(snap()))
        self.assertEqual([(x["pct"], bool(x.get("stale"))) for x in r], [(72.4, False), (91.0, False)])

    def test_agy_last_good_is_stale_and_says_so(self):
        s = snap(available=False, reason="network_error", quota=None,
                 last_good={"fetched_at": 1_800_000_000, "quota": snap()["quota"]})
        r = run_segs("m.agySegs(%s, false)" % json.dumps(s))
        self.assertTrue(all(x["stale"] for x in r))
        self.assertTrue(all("上次读到的数" in x["title"] for x in r), r)
        self.assertFalse(any("没在跑" in x["title"] for x in r),
                         "★ 原来一律写「agy 现在没在跑」—— 读失败的原因多得很，那句是编的")

    def test_agy_carried_bucket_is_stale_with_its_own_reason(self):
        s = snap()
        s["quota"]["groups"][0]["buckets"][1]["seen_at"] = 1_800_000_000
        r = run_segs("m.agySegs(%s, false)" % json.dumps(s))
        five, week = r
        self.assertFalse(five.get("stale"), "现读的那一格不降级")
        self.assertTrue(week["stale"])
        self.assertIn("沿用", week["title"])

    def test_agy_installed_but_unread_is_one_grey_slot(self):
        s = snap(available=False, reason="network_error", detail="HTTP 503", quota=None)
        r = run_segs("m.agySegs(%s, false)" % json.dumps(s))
        self.assertEqual([(x["pct"], x["reset"]) for x in r], [(None, "读不到")],
                         "★ 整段消失和「没装 agy」长得一样；读不到要占一个灰槽")
        self.assertIn("HTTP 503", r[0]["title"])

    def test_agy_not_installed_or_off_draws_nothing(self):
        r = run_segs("[m.agySegs(%s, false), m.agySegs(%s, true), m.agySegs(null, false)]"
                     % (json.dumps(snap(available=False, reason="not_installed", quota=None)), json.dumps(snap())))
        self.assertEqual(r, [[], [], []])

    def test_agy_pool_without_a_known_current_account_does_not_borrow_a_number(self):
        r = run_segs("[m.agySegs(%s, false, true), m.agySegs(null, true, true)]" % json.dumps(snap()))
        self.assertEqual([(x["pct"], x["reset"]) for x in r[0]], [(None, "当前号未知")])
        self.assertEqual(r[1], [], "平台关了就什么都不画")


class TheSettingsRowTellsTheTruth(unittest.TestCase):
    """★ 原来没有刘海屏时开关照样变绿、屏幕上什么都没有、也没有任何原因（四方评审一致）。"""

    def test_on_without_a_notch_says_why_nothing_shows(self):
        on, off, err, unknown, fine = run_segs(
            '[m.notchRowDesc(true,{active:false,reason:"no_notch"},null),'
            ' m.notchRowDesc(false,{active:false,reason:"no_notch"},null),'
            ' m.notchRowDesc(true,null,"build failed"),'
            ' m.notchRowDesc(true,null,null), m.notchRowDesc(true,{active:true,reason:null},null)]')
        self.assertIn("没有检测到刘海屏", on)
        self.assertIn("自动出现", on, "开盖后会自己出来 —— 要说出来，不然用户会以为得重开一次")
        self.assertIn("没有刘海屏", off)
        self.assertIn("没能打开：build failed", err)
        self.assertNotIn("⚠", unknown, "还没问到 ⇒ 不下结论")
        self.assertNotIn("⚠", fine)

    def test_the_toggle_uses_the_answer_and_rolls_back_on_error(self):
        code = code_only(SETTINGS)
        # ★ 2026-10-19 改名「刘海屏版本」（交接包 DECISIONS）；存储键与命令沿用，见 test_settings_toggles.py。
        i = code.index('label="显示位置"')
        row = code[i:i + 1600]
        self.assertIn("warn={notchRowWarn(s.notchHud, notchSt, notchErr)}", row,
                      "原因单独一行（设置页文字不折行，跟在说明末尾会第一个被省略）")
        self.assertIn("notchRowDesc(s.notchHud, notchSt, notchErr)", row, "全文进悬浮")
        self.assertRegex(row, r'invoke<NotchStatus>\("set_notch_hud"[^)]*\)\s*\.then\(\(st\) => setNotchSt',
                         "开关要收下 Rust 的回答（显示着没有 / 为什么）")
        self.assertNotRegex(row, r"\.catch\(\(\) => \{\}\)", "★ 不许再吞错 —— 失败要回滚开关并说原因")
        self.assertIn("notchHud: !next", row, "失败时把开关拨回去")
        self.assertIn('invoke<NotchStatus>("notch_status")', code, "进设置页先问一次现在的状态")


class ReviewFindingsStayFixed(unittest.TestCase):
    """2026-10-17 四方评审抓到的每一类各一条。"""

    def setUp(self):
        self.rs = code_only(RS)
        self.hud = code_only(TSX)

    def test_agy_number_comes_from_the_pool_like_the_menubar(self):
        """★★ 本机 RPC 自 agy 1.2 起恒 csrf_required，只拿它 = 画一个几周前的 last_good（本机实测 24.5 天前）。"""
        self.assertIn("agyPool.snapshotOf(agyCur, agySnap)", self.hud)
        self.assertIn("useAgyPool(false)", self.hud, "★ 刘海窗口不做保鲜（那是菜单栏的活），只读盘 + 收广播")
        self.assertIn("const { state, agy: agySnap } = useNotchData();", self.hud,
                      "本机那份只作 snapshotOf 的归属候选，且只听推送（不用自带定时器的 useAgyQuota）")
        self.assertNotRegex(self.hud, r"useAgyPool\([^)]*background", "保鲜只能有一个 webview（菜单栏）")

    def test_the_tracking_thread_never_touches_nswindow_or_tao_cursor(self):
        """★ `cursor_position()` 按主屏 scale 换物理坐标，原来除以刘海窗口的 scale ⇒ 混合 DPI 下坐标减半。"""
        self.assertNotIn("cursor_position(", self.rs)
        self.assertNotIn("scale_factor(", self.rs)
        body = self.rs[self.rs.index("fn track("):self.rs.index("fn ensure_window(")]
        self.assertIn("mouse_desktop(&g)", body, "唤醒与跟踪必须同一套坐标算法")
        self.assertNotIn("place(&", body, "后台线程只能经 place_soon 派回主线程")

    def test_stale_threads_check_their_generation(self):
        body = self.rs[self.rs.index("fn track("):self.rs.index("fn ensure_window(")]
        self.assertIn("ENABLE_GEN.load(Ordering::SeqCst) != gen", body, "关掉之后旧跟踪线程不许再把窗口展开")
        self.assertIn("compare_exchange(me, 0", body, "只清自己那一号，不抹掉新线程的标记")
        so = self.rs[self.rs.index("fn set_open("):self.rs.index("fn track(")]
        self.assertIn("OPEN_GEN.load(Ordering::SeqCst) == gen", so, "旧的收起计时不许裁掉新一轮动画")
        se = self.rs[self.rs.index("pub fn set_enabled("):]
        self.assertIn("ENABLE_GEN.fetch_add", se)

    def test_losing_the_notch_screen_removes_the_window(self):
        """★★ 合盖后层级 26 的窗口原来留在原地，被系统挪到外接屏菜单栏正中（一块黑块）。"""
        rc = self.rs[self.rs.index("fn reconcile("):self.rs.index("fn on_mouse(")]
        self.assertRegex(rc, r"None => if app\.get_webview_window\(LABEL\)\.is_some\(\) \{ drop_window\(app\); sync_tray\(app, false\); \}",
                         "★ 刘海屏没了 ⇒ 销毁窗口，并把托盘放回来（显示位置二选一的兜底）")
        self.assertIn("ensure_window(app, &g)", rc, "开盖后要能自己建出来")
        om = self.rs[self.rs.index("fn on_mouse("):self.rs.index("fn install_monitors(")]
        self.assertIn("reconcile(app)", om)

    def test_monitors_are_installed_even_without_a_notch(self):
        se = self.rs[self.rs.index("pub fn set_enabled("):self.rs.index("pub fn status(")]
        self.assertLess(se.index("install_monitors(app)"), se.index("let Some(g) = geometry() else"),
                        "★ 没有刘海屏也要先装监听，否则合盖时打开、开盖后永远不出现")
        self.assertIn('reason: Some("no_notch")', se)

    def test_collapsed_strip_lets_clicks_through_and_never_takes_focus(self):
        self.assertIn("setIgnoresMouseEvents: true", self.rs, "建窗时先穿透")
        pl = self.rs[self.rs.index("fn place("):self.rs.index("fn place_soon(")]
        self.assertIn("pass_clicks(&win, !open)", pl, "收起穿透、展开才接点击")
        self.assertNotIn(".show()", self.rs, "★ tao 的 show = makeKeyAndOrderFront，会抢主窗口焦点（⌘1/2/3 失灵）")
        self.assertIn("orderFrontRegardless", self.rs)
        self.assertIn(".accept_first_mouse(true)", self.rs, "不在前台时第一下点击也要算数")

    def test_window_state_plugin_leaves_it_alone(self):
        lib = code_only(LIB)
        m = re.search(r"with_denylist\(&\[([^\]]*)\]\)", lib)
        self.assertIsNotNone(m)
        self.assertIn('"notch"', m.group(1), "★ 不进黑名单，插件会把展开态尺寸存下、下次建窗时恢复回来")

    def test_first_open_event_is_not_lost(self):
        self.assertIn('v["open"] = Value::Bool(notch::is_open())', code_only(LIB))
        self.assertRegex(self.hud, r"Promise\.all\(uns\)\.then\(\(\) => \{[^}]*?return invoke<[^>]*>\(\"notch_geometry\"\)",
                         "监听注册好之后再问一次当前展开态")
        self.assertIn('v["mode"]', code_only(LIB), "★ 首次问也要带展开种类，否则错过 `notch-mode` 时画成 4e 卡片")
        self.assertIn('v["near"] = Value::Bool(notch::is_near())', code_only(LIB), "★ 也要带「靠近」，否则窗口刚建好时光标已在靠近区就漏亮")
        self.assertIn("setNear(!!g.near);", self.hud)
        self.assertIn('"notch-geom"', self.hud, "改分辨率 / 换屏后前端的刘海尺寸要跟着变")



class PushNotPoll(unittest.TestCase):
    """PR #1 作者 2026-10-17：刘海网页进程改成数据变化时再推送。打开刘海条时它的 WebContent 曾 60s 平均 0.25%，
    来源是借用了主界面/菜单栏那两个自带定时器的 hook。"""

    def test_does_not_borrow_the_polling_hooks(self):
        code = _code(TSX)
        # ★ 4e 卡片多了 grok / Claude / 今日用量三路数据：对应的现成 hook 都自带定时器（grok 走 useQuotaSidecar、
        #   useTraffic 30s 心跳、useClaudeQuota / useTodayTps 60s），刘海只读盘 + 收推送 + 展开时节流补读。
        for hook in ("useStore", "useAgyQuota", "useQuotaSidecar", "useGrokQuota", "useTraffic", "useClaudeQuota", "useTodayTps"):
            self.assertNotRegex(code, rf"\b{hook}\b", f"刘海条不许用 {hook}：它自带定时器")
        self.assertRegex(code, r"useNotchData\(\)", "刘海条要走只听推送的 useNotchData")

    def test_data_hook_only_listens(self):
        code = _code(DATA)
        self.assertNotIn("setInterval", code, "取数 hook 里不许有周期定时器")
        self.assertNotIn("run_agy_quota", code, "刘海条只读 sidecar，不发起取数（会起 python）")
        self.assertNotIn("read_auth_tokens", code, "额度窗口用不到 token，别每次连全部 token 一起读")
        self.assertRegex(code, r'listen\("state-changed"', "要跟着 state.json 的推送重读")
        self.assertRegex(code, r'listen\("agy-quota-updated"', "要跟着 agy sidecar 的推送重读")

    def test_the_pool_hook_is_push_only_when_neither_enabled_nor_background(self):
        """刘海用 `useAgyPool(false)`。它的每个定时器都必须挡在 enabled / background 之后，
        否则刘海窗口会跟着跑 30s 心跳（甚至起取额度的子进程）。"""
        pool = _code(APP / "src" / "hooks" / "useAgyPool.ts")
        n = pool.count("setInterval")
        self.assertGreater(n, 0)
        for i in [j for j in range(len(pool)) if pool.startswith("setInterval", j)]:
            eff = pool[pool.rfind("useEffect(", 0, i):i]
            self.assertRegex(eff, r"if \(!(enabled|background)\) return;", "池 hook 的定时器没挡在 enabled / background 之后")
        self.assertIn("listen(POOL_EVT", pool, "池文件变了要跟着读盘")
        self.assertIn("listen<LivePayload>(LIVE_EVT", pool, "当前号变了要跟着换")

    def test_opening_the_card_asks_the_menubar_to_rescan(self):
        """刘海只读盘、不扫描；展开时请常驻的菜单栏 webview 按新鲜度代扫（2026-10-21：主窗与菜单栏都没开时，
        刘海「今日」停在 40 分钟前）。刘海自己不许直接起扫描。"""
        code = _code(TSX)
        self.assertNotIn("run_traffic", code, "刘海不许自己起扫描（会起 python）")
        i = code.index('emit("notch-shown")')
        guard = code.rfind("if (cardOpen) {", 0, i)   # v2.1.2 起变量叫 cardOpen（samchen #5）
        self.assertNotEqual(guard, -1, "`notch-shown` 只在卡片展开时发")
        self.assertLess(i - guard, 1500, "`notch-shown` 离展开分支太远，可能不在同一个分支里")
        mb = _code(APP / "src" / "MenuBar.tsx")
        self.assertRegex(mb, r'listen\("notch-shown", \(\) => \{ refreshIfStale\(',
                         "菜单栏要接住 `notch-shown`，按新鲜度代扫")

    def test_the_only_interval_runs_while_the_panel_is_open(self):
        code = _code(TSX)
        self.assertEqual(code.count("setInterval"), 1, "只允许面板展开时那一个倒计时定时器")
        i = code.index("setInterval")
        guard = code.rfind("if (!cardOpen) return;", 0, i)
        self.assertNotEqual(guard, -1, "唯一的定时器必须挂在 `if (!cardOpen) return;` 之后（只有 4e 卡片有倒计时）")
        self.assertLess(i - guard, 120, "定时器离 open 守卫太远，可能不在同一个 effect 里")



GLOW = APP / "src" / "notchGlow.ts"


def run_card(expr):
    """notchCard.ts 零 import，直接用 node 跑。"""
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                        "import('%s').then(m => console.log(JSON.stringify(%s)))" % (CARD.as_posix(), expr)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def run_glow(expr):
    """notchGlow.ts 零 import，直接用 node 跑（CI 没有 node_modules）。"""
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                        "import('%s').then(m => console.log(JSON.stringify(%s)))" % (GLOW.as_posix(), expr)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


COLS = "(k) => ({codex: '#2dd4bf', claude: '#E0784F', agy: '#4d9fff', grok: '#8b7cf6'})[k]"


class ActivityGlow(unittest.TestCase):
    """PR #1 作者 2026-10-17 提出光晕；维护者 2026-10-18 接受并改成：**空闲不亮**，四家（Codex / Claude / agy / grok）
    谁在跑亮谁的平台色，几家同时跑就几段，停下熄灭。"""

    def colors(self, act, off="[]"):
        return run_glow(f"m.glowColors({act}, (k) => {off}.includes(k), {COLS})")

    def test_idle_means_no_glow(self):
        self.assertEqual(self.colors("m.NO_ACTIVITY"), [], "没有平台在跑就不亮")
        self.assertEqual(run_glow("m.glowBackground([])"), "", "没有颜色 = 没有背景")

    def test_each_platform_lights_its_own_colour(self):
        for k, c in (("codex", "#2dd4bf"), ("claude", "#E0784F"), ("agy", "#4d9fff"), ("grok", "#8b7cf6")):
            self.assertEqual(self.colors(f"{{...m.NO_ACTIVITY, {k}: true}}"), [c], k)
        self.assertEqual(run_glow("m.glowBackground(['#4d9fff'])"), "#4d9fff", "一家 = 纯色，不是渐变")

    def test_order_is_fixed_whatever_order_the_payload_has(self):
        got = self.colors("{grok: true, agy: true, claude: true, codex: true}")
        self.assertEqual(got, ["#2dd4bf", "#E0784F", "#4d9fff", "#8b7cf6"], "颜色位置不能随推送字段顺序跳")

    def test_a_platform_turned_off_in_settings_stays_dark(self):
        got = self.colors("{codex: true, claude: true, agy: false, grok: false}", off="['claude']")
        self.assertEqual(got, ["#2dd4bf"], "设置里停用的平台不亮")

    def test_several_platforms_blend_with_stops_at_segment_midpoints(self):
        """★ 交接包 2026-10-19 DECISIONS「刘海光晕」定稿 = **加强前的原版**：平滑渐变、色标在每段中点。
        维护者 2026-10-18 那版「每家中间 60% 纯色」被用户在交接包里否决（「加强版」在否决清单里）。"""
        bg = run_glow("m.glowBackground(['#a', '#b', '#c', '#d'])")
        self.assertEqual(bg, "linear-gradient(90deg, #a 12.5%, #b 37.5%, #c 62.5%, #d 87.5%)", "色标在每段中点")
        self.assertEqual(run_glow("m.glowBackground(['#a', '#b'])"), "linear-gradient(90deg, #a 25.0%, #b 75.0%)")

    def test_bridge_is_neutral_grey_when_idle(self):
        """交接包：「空闲时光桥为中性灰」；在跑时与光晕同一条渐变（卡片顶边那条线同源）。"""
        self.assertEqual(run_glow("m.bridgeBackground([])"),
                         "linear-gradient(90deg, rgba(255,255,255,.22), rgba(255,255,255,.22))")
        self.assertEqual(run_glow("m.bridgeBackground(['#a', '#b'])"), run_glow("m.glowBackground(['#a', '#b'])"))
        self.assertEqual(run_glow("m.bridgeBackground(['#a'])"), "linear-gradient(90deg, #a, #a)",
                         "一家 = 同色渐变（光桥与顶边线都按渐变画）")
        self.assertEqual(run_glow("m.glowKeys({grok: true, agy: true, claude: false, codex: true}, (k) => k === 'grok')"),
                         ["codex", "agy"], "固定顺序、停用的不亮")

    def test_rust_and_ts_agree_on_the_payload(self):
        rs = _code(ACT)
        fields = re.search(r"pub struct Activity \{([^}]*)\}", rs).group(1)
        rs_keys = re.findall(r"pub (\w+): bool", fields)
        ts = _code(GLOW)
        ts_keys = re.findall(r"(\w+): boolean", re.search(r"interface NotchActivity \{([^}]*)\}", ts).group(1))
        self.assertEqual(rs_keys, ts_keys, "notch.rs::Activity 与 NotchActivity 字段不一致 ⇒ 有一家永远不亮")
        self.assertEqual(run_glow("m.GLOW_ORDER"), rs_keys, "GLOW_ORDER 漏了某家 ⇒ 它在跑也不亮")

    def test_hud_uses_the_pure_functions(self):
        code = _code(TSX)
        self.assertRegex(code, r"const litKeys = glowKeys\(act, isOff\);", "光晕颜色必须走 notchGlow.ts（有行为闸的那份）")
        self.assertRegex(code, r"const glow = glowBackground\(litCols\);")
        self.assertRegex(code, r"const bridge = bridgeBackground\(litCols\);")
        self.assertRegex(code, r'\["--glow" as string\]: glow', "算好的颜色没传给 --glow")
        self.assertRegex(code, r"const lit = litKeys\.length > 0;")
        self.assertRegex(code, r'lit \? "nh-active" : "nh-quiet"', "没有平台在跑就必须是 nh-quiet（不亮）")
        self.assertRegex(code, r"hot\.has\(k\) \? C\.ALERT :", "低额度那家那一段要换橙红")
        self.assertNotIn("quotaGlow", code, "空闲不再显示额度色")

    def _layer(self, g):
        return re.search(rf"(?m)^\.nh-glow \.{g} \{{([^}}]*)\}}", _code(CSS)).group(1)

    def test_glow_is_the_original_values(self):
        """★ 交接包 DECISIONS「刘海光晕」/「刘海屏版本」：贴边层下沿 10 pt / blur 7 / 2.4 s 呼吸，散开层 blur 20 / .7 / 3.1 s。
        维护者 2026-10-18 的加强版（下沿 12 / blur 5 / 14）被用户在交接包里否决 —— 回到原值。"""
        g1, g2 = self._layer("g1"), self._layer("g2")
        self.assertEqual(re.search(r"height: calc\(var\(--nh\) \+ ([\d.]+)px\)", g1).group(1), "10", "贴边层下沿 10")
        self.assertEqual(re.search(r"top: (-?[\d.]+)px", g1).group(1), "-6")
        self.assertEqual(re.search(r"blur\(([\d.]+)px\)", g1).group(1), "7")
        self.assertRegex(g1, r"animation: nh-breathe 2\.4s ease-in-out infinite;")
        self.assertEqual(re.search(r"blur\(([\d.]+)px\)", g2).group(1), "20")
        self.assertRegex(g2, r"animation: nh-breathe-wide 3\.1s ease-in-out -2\.5s infinite;")
        css = _code(CSS)
        self.assertRegex(css, r"@keyframes nh-breathe-wide \{ 0%, 100% \{ opacity: \.7; \}", "散开层峰值 .7")
        self.assertRegex(css, r"@keyframes nh-alert \{ 0%, 100% \{ opacity: 1; \} 50% \{ opacity: \.15; \} \}", "告警快闪 1→.15")
        self.assertRegex(self._layer("ga"), r"animation: nh-alert \.9s ease-in-out infinite;", "告警快闪 0.9 s")

    def test_two_layers_do_not_breathe_in_lockstep(self):
        """两层同周期同相位，看着就是一块整齐的光在一明一暗 —— 作者嫌的正是「太整齐规则」。"""
        d1 = re.search(r"animation: nh-breathe ([\d.]+)s", self._layer("g1")).group(1)
        d2 = re.search(r"animation: nh-breathe-wide ([\d.]+)s", self._layer("g2")).group(1)
        self.assertNotEqual(d1, d2, "两层呼吸周期要错开")

    def test_glow_is_dark_when_idle_and_at_sixty_percent_while_open(self):
        css = _code(CSS)
        self.assertRegex(css, r"(?m)^\.nh-quiet \.nh-glow \{ opacity: 0; \}", "没有平台在跑时光晕要收掉")
        self.assertRegex(css, r"(?m)^\.nh-quiet \.nh-glow i \{ animation: none; \}", "收掉后不能还在跑动画（白耗 CPU）")
        # AICoop 阶段 2：任一种展开（含空闲格子）都降到 60%，所以判 `open` 不判 4e 的 `isOpen`
        # 空闲格子开着时平台色光晕让位（展开种类在展开那一刻定）
        self.assertRegex(_code(TSX), r"opacity: !lit \|\| idleOpen \? 0 : open \? 0\.6 : 0\.9",
                         "交接包：卡片展开时光晕降到 60% 保留（不是收掉）")

    def test_holds_still_under_reduce_motion(self):
        css = _code(CSS)
        m = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*)\}\s*$", css, re.S | re.M)
        self.assertIsNotNone(m)
        self.assertRegex(m.group(1), r"\.nh-glow i \{ animation: none;", "开了「减弱动态效果」光晕就不该再动")
        # ★ 组件读到系统设置后挂 `nh-reduce`（JS 读 matchMedia；harness 也只能改到 JS 这一侧）—— 告警橙红常亮不闪
        self.assertRegex(_code(CSS), r"(?m)^\.nh-reduce \.nh-glow i \{ animation: none; \}", "减弱动态效果：告警常亮不闪")
        self.assertRegex(_code(TSX), r'reduce && "nh-reduce"')

    def test_activity_is_pushed_by_rust(self):
        code = _code(TSX)
        self.assertRegex(code, r'listen<[^>]+>\("notch-activity"', "要跟着 Rust 的活动推送")
        self.assertRegex(code, r'invoke<[^>]+>\("notch_activity"\)', "首次挂载要取一次当前状态")
        self.assertNotIn("last_proxy_ts", code, "codex 会定时 GET /models，代理照样刷新 last_proxy_ts —— 停手后仍会亮")
        lib = LIB.read_text(encoding="utf-8")
        block = re.search(r"generate_handler!\[(.*?)\]\)", lib, re.S).group(1)
        self.assertRegex(block, r"\bnotch_activity\b")

    def test_rust_watches_instead_of_polling(self):
        """维护者 2026-10-18：Claude Code 加子 agent 约 8000 个会话文件，每 2s stat 一遍约 50 ms ⇒ 改 FSEvents 推送。
        判哪家在写的规则由 `cargo test` 的 `each_platform_is_told_apart_by_its_own_session_files` 守。"""
        rs = _code(ACT)
        watch = rs[rs.index("fn watch_activity("):rs.index("fn run_live_soon(")]
        self.assertIn("notify::recommended_watcher(", watch, "活动检测要靠文件系统推送")
        self.assertIn("RecursiveMode::Recursive", watch)
        # ★ 2026-10-22 例外：FSEvents 只在**关闭**写过的文件时报（实测），一直开着写的 agy WAL / Codex rollout 收不到 ⇒
        #   只对这两家的**平目录**补 mtime 轮询（agy ~500 个 -wal 1.3 ms；Codex 最近两个日期目录）。Claude 的 8000 个文件仍只靠推送。
        poll = rs[rs.index("fn poll_open_writers("):rs.index("impl Roots {", rs.index("fn recent_day_dirs("))]
        self.assertNotIn("self.claude", poll, "Claude 的会话文件不许轮询（每 2s 50 ms 那次）")
        self.assertNotIn("self.grok", poll)
        for f in (ACT, RS):
            code = _code(f).replace(poll, "") if f == ACT else _code(f)
            self.assertNotIn("read_dir", code, "不许回到逐个目录扫文件（只许 `poll_open_writers` 那两家）")
            self.assertNotIn("last_proxy_ts", _code(f))
        cls = rs[rs.index("fn classify("):rs.index("fn is_write(")]
        self.assertRegex(cls, r'n\.starts_with\("rollout-"\) && n\.ends_with\("\.jsonl"\)', "Codex 看 rollout 写入")
        self.assertRegex(cls, r'n\.ends_with\("\.db-wal"\)', "agy 是 WAL 库，生成时写的是 -wal，只看主库会永远判成空闲")
        self.assertRegex(watch, r"if changed \{ let _ = app\.emit_to\(crate::notch::LABEL, \"notch-activity\", a\); \}", "只在变了才推")



class ActivityWatcher(unittest.TestCase):
    """评审 2026-10-17（PR #1 退回意见）：检测线程快速开关后会丢；没有刘海屏时也在每 2s 扫文件。
    ★ 2026-10-19 检测线程搬进 activity.rs、改成订阅制（刘海 `NOTCH` + 托盘胶囊 `TPS`）：「开关换代后旧线程退出」
      与「窗口没了就别扫」两条，现在由「没有订阅者就退出」+「刘海窗口建 = 订阅、拆 = 退订」守。"""

    def setUp(self):
        act = code_only(ACT)
        self.watch = act[act.index("fn watch_activity("):act.index("fn run_live_soon(")]
        self.sub = act[act.index("pub fn subscribe("):act.index("pub fn unsubscribe(")]
        rs = code_only(RS)
        self.ensure = rs[rs.index("fn ensure_window("):rs.index("fn drop_window(")]
        self.drop = rs[rs.index("fn drop_window("):rs.index("fn reconcile(")]

    def test_a_new_watcher_takes_over_instead_of_bailing_out(self):
        for f in (ACT, RS):
            self.assertNotIn("WATCHING", code_only(f), "布尔标记：快速关了再开时新线程起不来、旧线程随后退出 ⇒ 一条都没有")
        self.assertIn("WATCHER.store(me", self.watch, "新起的一条直接接管")
        self.assertIn("WATCHER.load(Ordering::SeqCst) == me", self.watch, "旧的看到不是自己就退")
        self.assertIn("WATCHER.compare_exchange(me, 0", self.watch, "退出时只清自己那一号")
        head = self.watch[:self.watch.index("std::thread::spawn")]
        self.assertNotIn("return", head, "起线程前不许因为「已经有一条」就退出 —— 那条可能正要因换代退出")
        self.assertIn("prev == 0 || WATCHER.load(Ordering::SeqCst) == 0", self.sub,
                      "第一个订阅者（或线程已退出）时必须起一条新的")

    def test_the_glow_is_judged_by_live_and_published_when_live_returns(self):
        """用户 2026-10-19「改用轮次结束标记」：光晕与托盘同一个裁判（live），同时熄。纯判定 `glow` 由 cargo test 守，
        这里守接线：每 tick 和 live 一回来都走 `publish`，`publish` 用 live 那一份。"""
        act = code_only(ACT)
        pub = act[act.index("fn publish("):act.index("fn run_live_soon(")]
        live = act[act.index("fn run_live_soon("):act.index("pub fn live_activity(")]
        self.assertIn("glow(fs, *LIVE_ACT.lock().unwrap(), LIVE_SINCE.load(Ordering::SeqCst), now)", pub,
                      "光晕要用 live 的判断（live 不可用才退回 FSEvents）")
        self.assertIn("let fs = publish(&app);", self.watch, "每 tick 走 publish")
        self.assertIn("run_live_soon(&app, fs)", self.watch, "live 失败时托盘退回的是 FSEvents 那一份")
        # 阶段 E/F 评审：写回改在核代次那把锁里（`*g = act;`），发布锁 `LIVE_PUB` 罩住整段
        i, j = live.index("*g = act;"), live.index("publish(&app);")
        self.assertLess(live.index("let _pub = LIVE_PUB.lock().unwrap();"), live.index("if LIVE_GEN.load(Ordering::SeqCst) != gen"),
                        "发布锁先于核代次拿：退订插不进核代次与 emit／on_live 之间")
        self.assertLess(i, j, "live 一回来先记下、再立刻推光晕（不等下一 tick）")
        self.assertIn("let mut was_live = true;", self.watch, "订阅那一刻先跑一次 live（长工具调用中途打开时没有写入来叫醒）")

    def test_runs_only_while_someone_is_subscribed(self):
        self.assertIn("CONSUMERS.load(Ordering::SeqCst) != 0", self.watch, "没有订阅者（刘海窗口没了、t/s 关了）就别再扫文件")
        self.assertEqual(self.ensure.count("crate::activity::subscribe(app, crate::activity::NOTCH)"), 2,
                         "建窗和「窗口已在、只是重新打开」两条路都要订阅")
        self.assertIn("crate::activity::unsubscribe(crate::activity::NOTCH)", self.drop,
                      "窗口没了（合盖 / 外接屏 / 关掉）就退订")
        se = code_only(RS)
        se = se[se.index("pub fn set_enabled("):se.index("pub fn status(")]
        self.assertNotIn("subscribe", se, "不能在 set_enabled 里无条件订阅 —— 没有刘海屏时也会跑")



class OnlyOneOfMenuBarAndNotch(unittest.TestCase):
    """设置「显示位置」菜单栏 / 刘海屏二选一（用户 2026-10-24：不能同时出现两个；选刘海屏 =「整个托盘图标都藏起来」）。
    ★ 兜底：没有刘海屏 / 建窗失败时托盘必须还在，否则 app 一个入口都没有 —— 判据是「刘海窗口真的在」，不是开关。"""

    def setUp(self):
        self.rs = code_only(RS)

    def test_the_rule_hides_the_tray_only_while_the_notch_window_is_up(self):
        self.assertRegex(self.rs, r"fn tray_visible\(notch_chosen: bool, notch_window: bool\) -> bool \{ !\(notch_chosen && notch_window\) \}")
        st = self.rs[self.rs.index("fn sync_tray("):]
        st = st[:st.index("\n}")]
        self.assertIn("tray_visible(ENABLED.load(Ordering::SeqCst), notch_window)", st)
        self.assertRegex(st, r'app\.tray_by_id\("main"\)[^\n]*set_visible\(v\)')

    def test_every_place_the_window_appears_or_goes_resyncs_the_tray(self):
        se = self.rs[self.rs.index("pub fn set_enabled("):self.rs.index("fn set_enabled_inner(")]
        self.assertRegex(se, r"let st = set_enabled_inner\(app, on\);\s*sync_tray\(app, matches!\(st, Ok\(Status \{ active: true, \.\. \}\)\)\);",
                         "开 / 关都按结果同步：没刘海屏时 active=false ⇒ 托盘留着")
        rc = self.rs[self.rs.index("fn reconcile("):self.rs.index("fn on_mouse(")]
        self.assertIn("drop_window(app); sync_tray(app, false);", rc, "合盖 / 拔屏 ⇒ 托盘回来")
        self.assertRegex(rc, r"let ok = ensure_window\(app, &g\)\.is_ok\(\);\s*sync_tray\(app, ok\);", "开盖 ⇒ 建窗成功才藏托盘")


if __name__ == "__main__":
    unittest.main()
