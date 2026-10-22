"""「使用重置卡」—— 全 app **唯一不可逆**的花费动作（2026-10-01 用户要求：用最近到期的那张）。

一张卡用掉就没了，所以这份闸守的是「**什么时候绝不能发请求**」与「**什么才算成功**」：

| 不变量 | 为什么 |
|---|---|
| 选**最近到期**、且**有到期日**的那张 | 用户要求；没有到期日的卡「不知道多久过期」≠「最近过期」，不能当最近 |
| ~~没有可重置窗口 ⇒ 不发~~ **2026-10-01 撤销** | 用户实测额度没见底也能用卡并要求放开；服务端是最终裁判，成败只认 `windows_reset`，前后张数核对 |
| 成功**只认** `windows_reset > 0` | 200 + `windows_reset: 0`（实测 `no_credit`）是「没生效」，不能报成「已使用」 |
| 请求号（`redeem_request_id`）先落盘；没确认成功就复用 | 网络在发出去之后断了，重试若换新号就可能再用掉第二张 |
| 请求结果未知 ⇒ 既不报成功也不清掉请求号 | 「这一枪没打中」与「确实没生效」不能是同一个值 |

端点与请求体是 2026-10-01 实测的（见 `codex-rotate` 里 `CREDIT_CONSUME_PATH` 上的注释）；
这里**一次真实请求都不发** —— 网络函数全部打桩。
"""
try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401
import contextlib
import importlib.machinery
import io
import importlib.util
import json
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    loader = importlib.machinery.SourceFileLoader("codex_rotate_uc", str(ROOT / "codex-rotate"))
    spec = importlib.util.spec_from_loader("codex_rotate_uc", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


CR = load()
NOW = time.time()


def _load_proxy():
    """代理的 `cooling()` / `_win_used()` 只读传进去的 slot，不碰盘；模块顶层只有常量。"""
    spec = importlib.util.spec_from_file_location("proxy_uc", ROOT / "proxy" / "proxy.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PX = _load_proxy()


def iso(days):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime(NOW + days * 86400))


def card(cid, days, status="available"):
    return {"id": cid, "status": status, "expires_at": None if days is None else iso(days)}


class PickSoonest(unittest.TestCase):
    def test_nearest_expiry_wins(self):
        c = CR._pick_soonest_credit([card("far", 20), card("near", 3), card("mid", 9)])
        self.assertEqual(c["id"], "near")

    def test_unusable_cards_are_never_picked(self):
        cs = [card("gone", 1, "redeemed"), card("expired", -1), card("nodate", None),
              {"status": "available", "expires_at": iso(2)}, card("ok", 8)]
        self.assertEqual(CR._pick_soonest_credit(cs)["id"], "ok",
                         "★★ 选到了已用掉 / 已过期 / 没到期日 / 没 id 的卡")

    def test_nothing_usable_is_none(self):
        self.assertIsNone(CR._pick_soonest_credit([card("n", None), card("r", 2, "redeemed")]))
        self.assertIsNone(CR._pick_soonest_credit(None))


class Outcome(unittest.TestCase):
    def test_only_windows_reset_counts_as_success(self):
        j = lambda **k: json.dumps(k).encode()
        self.assertEqual(CR._consume_outcome(200, j(code="ok", credit={"id": "x"}, windows_reset=2))[0], "reset")
        # 实测：不存在的卡 → 200 + no_credit + windows_reset 0
        self.assertEqual(CR._consume_outcome(200, j(code="no_credit", credit=None, windows_reset=0))[0], "no_effect")
        # 只有 credit 非空、没重置窗口 —— 也不是成功
        self.assertEqual(CR._consume_outcome(200, j(code="x", credit={"id": "x"}, windows_reset=0))[0], "no_effect")
        self.assertEqual(CR._consume_outcome(200, j(windows_reset=True))[0], "no_effect", "★ bool 不是数字")

    def test_unknown_is_not_failure_and_not_success(self):
        self.assertEqual(CR._consume_outcome(None, b"timeout")[0], "unknown")
        self.assertEqual(CR._consume_outcome(200, b"<html>")[0], "unknown")
        self.assertEqual(CR._consume_outcome(500, b"")[0], "http_error")
        self.assertEqual(CR._consume_outcome(429, b"")[0], "http_error")


class Flow(unittest.TestCase):
    """真跑 `cmd_use_credit`，网络与状态全打桩。"""

    def setUp(self):
        self.aid = "acct-1"
        self.state = {"active": "other", "slots": {
            self.aid: {"label": "Egan", "file": "egan.json",
                       "credits": {"available": 3, "applicable": 1, "at": NOW}}}}
        self.detail = [card("far", 20), card("near", 3), card("mid", 9)]
        self.posts = []
        self.post_result = (200, json.dumps({"code": "ok", "credit": {"id": "near"}, "windows_reset": 1}).encode())
        self.after_available = 2
        self.orig = {k: getattr(CR, k) for k in ("_state", "_mutate_state", "_probe_quota", "_fetch_credit_detail",
                                                 "_load_json", "_account_id", "_access_exp", "_api_post")}
        CR._state = lambda: self.state
        CR._mutate_state = lambda fn: fn(self.state)
        CR._load_json = lambda p: {"tokens": {"access_token": "t", "account_id": self.aid}}
        CR._account_id = lambda auth: self.aid
        CR._access_exp = lambda tok: NOW + 3600

        def probe(aid, slot, is_active):
            c = self.state["slots"][aid].get("credits") or {}
            if self.posts:                       # 发完之后的核对读数
                c["available"] = self.after_available
                c["at"] = time.time()
            return {}, "ok"
        CR._probe_quota = probe
        CR._fetch_credit_detail = lambda aid, slot, act: (self.detail, "HTTP 200")

        def post(tok, path, body, timeout=25):
            self.posts.append((path, dict(body)))
            return self.post_result
        CR._api_post = post
        self.orig["CREDIT_READ_DELAYS"] = CR.CREDIT_READ_DELAYS
        CR.CREDIT_READ_DELAYS = (0, 0, 0, 0)        # 不真睡
        self.addCleanup(lambda: [setattr(CR, k, v) for k, v in self.orig.items()])

    def run_cmd(self, *extra):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()):
            CR.cmd_use_credit(["Egan", *extra])
            raise SystemExit(0)                  # 成功路径是正常 return
        return cm.exception.code

    def test_success_spends_the_nearest_card_and_records_it(self):
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertEqual(len(self.posts), 1, "★★ 一次调用只许发一次请求")
        path, body = self.posts[0]
        self.assertEqual(path, CR.CREDIT_CONSUME_PATH)
        self.assertEqual(body["credit_id"], "near", "★★ 没用最近到期的那张")
        self.assertTrue(body["redeem_request_id"])
        sl = self.state["slots"][self.aid]
        self.assertNotIn("credit_redeem", sl, "成功后请求号应清掉")

    def test_it_still_sends_when_the_quota_is_not_exhausted(self):
        """用户 2026-10-01 拍板：额度没见底（`applicable == 0`）也要能用卡。反向对照：旧闸会在这里拒绝。"""
        self.state["slots"][self.aid]["credits"]["applicable"] = 0
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertEqual(len(self.posts), 1, "★★ 没有可重置窗口就被客户端拦下了 —— 用户明确要求放开")

    def test_a_stale_or_unreadable_reading_does_not_block_either(self):
        self.state["slots"][self.aid]["credits"]["at"] = NOW - 3600
        CR._probe_quota = lambda *a: (None, "HTTP 403")     # 刷不新
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertEqual(len(self.posts), 1)

    def test_without_an_applicable_window_the_outcome_is_still_judged_by_the_server(self):
        """放开闸之后，成败判据更要硬：服务端说没重置任何窗口 ⇒ 失败，不能因为「是我们发的」就报成功。"""
        self.state["slots"][self.aid]["credits"]["applicable"] = 0
        self.post_result = (200, json.dumps({"code": "not_applicable", "credit": None, "windows_reset": 0}).encode())
        self.assertEqual(self.run_cmd("--json"), 1)

    def test_refuses_dead_expired_or_mismatched_accounts(self):
        self.state["slots"][self.aid]["auth_dead"] = True
        self.assertEqual(self.run_cmd("--json"), 1)
        del self.state["slots"][self.aid]["auth_dead"]
        CR._access_exp = lambda tok: NOW - 5
        self.assertEqual(self.run_cmd("--json"), 1)
        CR._access_exp = lambda tok: NOW + 3600
        CR._account_id = lambda auth: "someone-else"
        self.assertEqual(self.run_cmd("--json"), 1)
        self.assertEqual(self.posts, [])

    def test_no_dated_card_means_no_request(self):
        self.detail = [card("a", None)]
        self.assertEqual(self.run_cmd("--json"), 1)
        self.assertEqual(self.posts, [])

    def test_a_confirmed_reset_clears_the_cooling(self):
        """★ 阶段 E 评审 codex：冷却现在能按周窗口拉到几天后；重置卡成功却不清，额度回来了代理照样不挑它。"""
        self.state["slots"][self.aid]["cooling_until"] = NOW + 3 * 86400
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertNotIn("cooling_until", self.state["slots"][self.aid])

    def test_after_a_confirmed_reset_the_proxy_no_longer_cools_it(self):
        """★★ 用户 2026-10-23 实报：某个号用了重置卡之后仍在冷却。判据打在**代理的** `cooling()` 上（选号就看它），
        且 GET /usage 没读到时也成立：旧的 100% 不能把它判回冷却。"""
        now = time.time()
        sl = self.state["slots"][self.aid]
        sl["cooling_until"] = now + 3 * 86400
        sl["quota"] = {"captured_at": now - 600,
                       "primary": {"window_minutes": 300, "used_percent": 100, "resets_at": now + 3600},
                       "secondary": {"window_minutes": 10080, "used_percent": 100, "resets_at": now + 3 * 86400}}
        self.assertTrue(PX.cooling(sl, now), "前提：用卡之前它确实在冷却")
        self.post_result = (200, json.dumps({"code": "ok", "credit": {"id": "near"}, "windows_reset": 2}).encode())
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertFalse(PX.cooling(sl, time.time()), "★★ 用卡成功之后代理仍判它冷却")
        self.assertIsNone(PX._win_used(sl, "primary"), "★ 旧的 100% 属于上一个窗口 ⇒ 未知，不是仍见底")
        self.assertIsNone(PX._win_used(sl, "secondary"))

    def test_the_fresh_reading_replaces_the_old_quota(self):
        """★ `_probe_quota` 的读数要写回 —— 原来回值被丢掉，旧额度一直留着。"""
        fresh = {"captured_at": time.time(), "primary": {"window_minutes": 300, "used_percent": 0, "resets_at": NOW + 18000}}
        orig = CR._probe_quota
        CR._probe_quota = lambda aid, slot, act: (fresh, "ok") if self.posts else orig(aid, slot, act)
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertEqual(self.state["slots"][self.aid]["quota"], fresh)

    def _spent_both(self):
        now = time.time()
        q = {"captured_at": now - 600,
             "primary": {"window_minutes": 300, "used_percent": 100, "resets_at": now + 3600},
             "secondary": {"window_minutes": 10080, "used_percent": 40, "resets_at": now + 3 * 86400}}
        self.state["slots"][self.aid]["quota"] = json.loads(json.dumps(q))
        return q

    def test_an_echo_of_the_pre_reset_reading_is_not_written(self):
        """★★ 用户 2026-10-23「用完重置卡，没有立马刷新恢复全额度」：重置刚确认时 `/usage` 还回重置前那份
        （5h 仍 100%、`resets_at` 没变）。照写 ⇒ 旧的 100% 回来，要等 quotad 下一轮。回声不写，接着读，读到新的才写。"""
        q = self._spent_both()
        echo = dict(q, captured_at=time.time())
        fresh = {"captured_at": time.time(), "primary": {"window_minutes": 300, "used_percent": 0, "resets_at": NOW + 18000}}
        seq = [echo, echo, fresh]
        CR._probe_quota = lambda aid, slot, act: ((seq.pop(0) if seq else fresh), "ok") if self.posts else ({}, "ok")
        self.assertEqual(self.run_cmd("--json"), 0)
        sl = self.state["slots"][self.aid]
        self.assertEqual(sl["quota"], fresh, "★ 回声之后读到的新读数要写进去")
        self.assertEqual([r["echo"] for r in sl["last_credit_use"]["reads"]], [True, True, False])

    def test_if_it_only_ever_echoes_the_window_stays_unknown(self):
        """一直是回声 ⇒ 不写；见底窗口留着「此刻已重置 ⇒ 未知」（—），不回到 100%、也不编满额。"""
        q = self._spent_both()
        echo = dict(q, captured_at=time.time())
        CR._probe_quota = lambda aid, slot, act: (json.loads(json.dumps(echo)), "ok") if self.posts else ({}, "ok")
        self.assertEqual(self.run_cmd("--json"), 0)
        sl = self.state["slots"][self.aid]
        self.assertIsNone(PX._win_used(sl, "primary"), "★ 回声把旧的 100% 写回去了")
        self.assertEqual(len(sl["last_credit_use"]["reads"]), len(CR.CREDIT_READ_DELAYS))

    def test_a_window_that_was_not_spent_is_not_an_echo(self):
        """周 40% 原样读回来不算回声（它本来就没见底，不该因此一直重读）。"""
        q = self._spent_both()
        fresh = {"captured_at": time.time(), "primary": {"window_minutes": 300, "used_percent": 0, "resets_at": NOW + 18000},
                 "secondary": q["secondary"]}
        CR._probe_quota = lambda aid, slot, act: (fresh, "ok") if self.posts else ({}, "ok")
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertEqual(len(self.state["slots"][self.aid]["last_credit_use"]["reads"]), 1)

    def test_a_spent_window_read_back_with_room_is_fresh_even_with_the_same_reset(self):
        """回声的判据是「仍见底且 reset 没变」，不是「reset 没变」：服务端可能只清用量不挪重置点。"""
        q = self._spent_both()
        fresh = json.loads(json.dumps(q)); fresh["captured_at"] = time.time(); fresh["primary"]["used_percent"] = 0
        CR._probe_quota = lambda aid, slot, act: (fresh, "ok") if self.posts else ({}, "ok")
        self.assertEqual(self.run_cmd("--json"), 0)
        sl = self.state["slots"][self.aid]
        self.assertEqual(sl["quota"], fresh)
        self.assertEqual(len(sl["last_credit_use"]["reads"]), 1)

    def test_one_reset_window_does_not_vouch_for_two_spent_ones(self):
        """★ 阶段 F 评审 codex：服务端只说重置了 1 个窗口，而两个都见底 ⇒ 不猜是哪个，旧读数原样留着等新 GET。"""
        now = time.time()
        sl = self.state["slots"][self.aid]
        q = {"captured_at": now - 600,
             "primary": {"window_minutes": 300, "used_percent": 100, "resets_at": now + 3600},
             "secondary": {"window_minutes": 10080, "used_percent": 100, "resets_at": now + 3 * 86400}}
        sl["quota"] = json.loads(json.dumps(q))
        self.assertEqual(self.run_cmd("--json"), 0)
        self.assertEqual(sl["quota"]["primary"]["resets_at"], q["primary"]["resets_at"])
        self.assertEqual(sl["quota"]["secondary"]["resets_at"], q["secondary"]["resets_at"])
        self.assertNotIn("cooling_until", sl, "冷却照样清：服务端确认重置过")

    def test_a_late_reading_never_resurrects_a_removed_account(self):
        """★ 阶段 F 评审 codex：请求期间号被 remove，迟到的 GET 读数用 `setdefault` 建回一个残缺槽位。"""
        fresh = {"captured_at": time.time(), "primary": {"window_minutes": 300, "used_percent": 0}}

        def probe(aid, slot, act):
            if self.posts:
                self.state["slots"].pop(aid, None)      # 发完之后、读数回来之前，号被删了
                return fresh, "ok"
            return {}, "ok"
        orig = CR._probe_quota
        CR._probe_quota = probe
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.suppress(SystemExit):
                CR.cmd_use_credit(["Egan", "--json"])
        finally:
            CR._probe_quota = orig
        self.assertNotIn(self.aid, self.state["slots"], "★ 删掉的号被迟到的读数复活了")

    def test_no_effect_keeps_the_cooling(self):
        """反向：服务端没重置任何窗口 ⇒ 冷却照旧（别把「没生效」也当成回满）。"""
        self.state["slots"][self.aid]["cooling_until"] = NOW + 3600
        self.post_result = (200, json.dumps({"code": "no_credit", "credit": None, "windows_reset": 0}).encode())
        self.run_cmd("--json")
        self.assertEqual(self.state["slots"][self.aid].get("cooling_until"), NOW + 3600)

    def test_no_effect_is_failure_and_keeps_the_request_id_for_retry(self):
        self.post_result = (200, json.dumps({"code": "no_credit", "credit": None, "windows_reset": 0}).encode())
        self.assertEqual(self.run_cmd("--json"), 1, "★★ 没重置任何窗口却报成功")
        rid1 = self.posts[0][1]["redeem_request_id"]
        self.assertEqual(self.state["slots"][self.aid]["credit_redeem"]["redeem_request_id"], rid1)
        self.run_cmd("--json")                    # 重试
        self.assertEqual(self.posts[1][1]["redeem_request_id"], rid1,
                         "★★★ 重试换了新请求号 —— 网络断过的那一次若其实生效了，这里会再用掉第二张")

    def test_unknown_result_keeps_the_request_id_and_is_not_success(self):
        self.post_result = (None, b"timed out")
        self.assertEqual(self.run_cmd("--json"), 1)
        self.assertIn("credit_redeem", self.state["slots"][self.aid])

    def test_card_flag_spends_exactly_the_chosen_card(self):
        """弹窗里让人挑的那张：CLI 必须用它，不能退回去用「最近」。"""
        self.assertEqual(self.run_cmd("--card", "far", "--json"), 0)
        self.assertEqual(self.posts[0][1]["credit_id"], "far", "★★★ 用户挑了 far，却发了别的卡")

    def test_a_chosen_card_that_is_gone_sends_nothing_and_never_falls_back(self):
        for bad in ("nope", "ghost"):
            self.assertEqual(self.run_cmd("--card", bad, "--json"), 1)
        self.detail = [card("far", 20), card("near", 3, "redeemed"), card("old", -2)]
        self.assertEqual(self.run_cmd("--card", "near", "--json"), 1, "已用掉的卡也被发了")
        self.assertEqual(self.run_cmd("--card", "old", "--json"), 1, "已过期的卡也被发了")
        self.assertEqual(self.posts, [], "★★★ 选的那张不可用时发了请求 —— 退回去用了另一张")

    def test_card_flag_without_a_value_is_an_error(self):
        self.assertNotIn(self.run_cmd("--card"), (0, None), "★ `--card` 后面没跟 id 却退出 0")
        self.assertEqual(self.posts, [])

    def test_a_different_card_gets_a_fresh_request_id(self):
        """反向对照：请求号只在**同一张卡**上复用，否则永远发同一个 id。"""
        self.post_result = (200, json.dumps({"code": "x", "credit": None, "windows_reset": 0}).encode())
        self.run_cmd("--json")
        self.detail = [card("another", 1)] + self.detail
        self.run_cmd("--json")
        self.assertNotEqual(self.posts[0][1]["redeem_request_id"], self.posts[1][1]["redeem_request_id"])


import re
import tempfile  # noqa: F401  (保持与其它测试同形)

SRC = ROOT / "codexbar" / "src"
BASE = "http://127.0.0.1:3304/harness.html?nav=home"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class Wiring(unittest.TestCase):
    def test_the_command_is_registered(self):
        self.assertIn("use-credit", CR.CMDS)

    def test_the_gui_may_call_it(self):
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("const ALLOWED_CMDS")
        self.assertIn('"use-credit"', rs[i:rs.index("];", i)], "★★ 白名单没放行 —— 按钮点了只会报 disallowed command")

    def test_there_is_no_use_button_in_the_action_bar(self):
        """用户 2026-10-01：「很容易误触」—— 动作条里的「用卡」按钮取消，入口只剩页脚角标 + 确认弹窗。"""
        code = re.sub(r"\{/\*[\s\S]*?\*/\}", "", (SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8"))
        self.assertNotIn("用卡 ", code, "★★ 动作条里又出现了「用卡」按钮")
        self.assertNotIn("data-use-credit-disabled", code)

    def test_the_cli_is_only_reachable_through_the_confirm_dialog(self):
        """✗ 2026-10-19 版（App 里的 `<UseCreditDialog>` 弹窗）已被 AICoop P5（2026-10-21）取代：
        入口是底栏的重置卡 chip，点开**卡内单选弹层**（`ov/CreditChip.tsx`），只有「确认使用」才回调。
        判据不变：`use-credit` 全前端只出现在一处，且那一处只能经由弹层的确认到达。"""
        strip = lambda t: re.sub(r"//[^\n]*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", t))
        ov = strip((SRC / "components" / "ov" / "Overview.tsx").read_text(encoding="utf-8"))
        app = strip((SRC / "App.tsx").read_text(encoding="utf-8"))
        self.assertEqual(app.count('"use-credit"'), 0, "★★ App 里又有一处 use-credit")
        self.assertEqual(ov.count('"use-credit"'), 1, "★★ `use-credit` 出现在不止一处 —— 有别的入口绕过了确认")
        # P5 评审修复 2026-10-22：外层加了计费在途锁 `withBilled`（同一号用卡不会并发两次）
        self.assertIn('credit: (a: Account, cardId: string) => withBilled(`credit:${a.aid}`, () =>\n      p.run(`usecredit-${a.aid}`, ["use-credit", a.node, "--card", cardId]', ov,
                      "★★★ 发出去的不是弹层里选中的那张（没带 --card）")
        self.assertEqual(ov.count("cx.credit("), 1, "★★ cx.credit 有不止一个调用方")
        self.assertIn("onUseCredit={(id) => cx.credit(a, id)}", ov, "★★ 卡上的入口不是经由 onUseCredit")
        self.assertFalse((SRC / "components" / "UseCreditDialog.tsx").exists(), "★ 旧弹窗组件该随 P5 删除（不留骨架）")

    def test_the_badge_does_not_confirm_by_itself(self):
        """卡片自己不发命令：chip 只开关弹层，弹层只有「确认使用」才调 `onConfirm(选中那张的 id)`。"""
        strip = lambda t: re.sub(r"//[^\n]*", "", re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", t))
        card = strip((SRC / "components" / "AccountCard.tsx").read_text(encoding="utf-8"))
        self.assertIn("<CreditChip a={a} busy={usingCredit} open={creditOpen} onOpenChange={setCreditOpen} onConfirm={onUseCredit} />", card,
                      "★★ 卡上的重置卡入口不是 CreditChip，或者它的确认不是只回调 onUseCredit")
        self.assertEqual(card.count("onUseCredit"), 3, "★★ onUseCredit 被别处调用了（应只有：解构 · 类型 · 传给 chip）")
        chip = strip((SRC / "components" / "ov" / "CreditChip.tsx").read_text(encoding="utf-8"))
        for f, code in (("AccountCard", card), ("CreditChip", chip)):
            for bad in ("invoke(", "run_rotate", '"use-credit"'):
                with self.subTest(f=f, bad=bad):
                    self.assertNotIn(bad, code, "★★★ 卡片自己发了命令 —— 绕过了确认")
        self.assertEqual(chip.count("onConfirm("), 1, "★★★ 弹层里不止一处会确认")
        i = chip.index("onConfirm(")
        btn = chip.rfind("<span", 0, i)
        self.assertIn("data-use-credit-confirm", chip[btn:i], "★★★ 确认不在「确认使用」按钮上")
        self.assertNotRegex(chip, r'e\.key === "Enter"[^\n]*onConfirm', "★★★ 回车会确认 —— 连按回车会花掉一张卡")


def _render():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    import urllib.request
    try:
        urllib.request.urlopen(BASE, timeout=2).read(1)
    except Exception:
        return None
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = br.new_page(viewport={"width": 1300, "height": 900})
        pg.goto(BASE, timeout=30000); pg.wait_for_timeout(3000)
        n = pg.evaluate("document.querySelectorAll('[data-aid]').length")
        out = []
        for i in range(n):
            pg.evaluate(f"document.querySelectorAll('[data-aid]')[{i}].click()"); pg.wait_for_timeout(450)
            out.append(pg.evaluate("""() => { const c = document.querySelector('[data-aid][style*="border-color"], [data-aid]');
              const bar = document.querySelector('[data-actions]'); if (!bar) return null;
              const t = bar.innerText.replace(/\\n/g, ' ');
              return {text: t, disabled: bar.querySelectorAll('[data-use-credit-disabled]').length,
                      overflow: bar.scrollWidth > bar.clientWidth + 1}; }"""))
        br.close()
    return [o for o in out if o]


def _dialog_probe():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    import urllib.request
    try:
        urllib.request.urlopen(BASE, timeout=2).read(1)
    except Exception:
        return None
    R = "(window.__RUN_ROTATE__ || []).filter(a => a[0] === 'use-credit')"
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=True)
        pg = br.new_page(viewport={"width": 1300, "height": 900})
        pg.goto(BASE, timeout=30000); pg.wait_for_timeout(3000)
        # ★ P5（2026-10-21）：入口是底栏的重置卡 chip（`data-card-chip=N`），点开卡内单选弹层。
        #   每张卡的弹层都常驻 DOM（CSS 显隐）⇒ 判「开着」一律看 `[data-open]`，选行也只在开着的那份里找。
        out = {"n_badges": pg.locator('[data-card-chip]:not([data-card-chip="0"])').count()}
        bars = pg.evaluate("[...document.querySelectorAll('[data-ov-actions]')].map(e => e.textContent)")
        out["bar_has_use"] = any("用卡" in b for b in bars)

        class _Entry:   # 每次都点 Egan 那张卡的 chip
            @staticmethod
            def click():
                ok = pg.evaluate("""() => { const c = [...document.querySelectorAll('[data-ov-card]')]
                    .find(c => (c.querySelector('[data-card-name]') || {}).textContent === 'Egan');
                  const it = c && c.querySelector('[data-card-chip]'); if (it) it.click(); return !!it; }""")
                if not ok:
                    raise AssertionError("★★ Egan 那张卡没有重置卡 chip")
        b = _Entry
        dlg = "[data-use-credit-dialog][data-open]"
        rowsel = dlg + " [data-use-credit-row]"
        b.click(); pg.wait_for_timeout(300)
        out["opened"] = pg.locator(dlg).count()
        out["sent_on_open"] = pg.evaluate(R + ".length")
        out["title"] = pg.locator(dlg + " b").first.inner_text()
        pg.keyboard.press("Enter"); pg.wait_for_timeout(200)
        out["enter_confirms"] = pg.evaluate(R + ".length")
        if pg.locator(dlg).count() == 0:
            b.click(); pg.wait_for_timeout(200)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
        out["esc_closes"] = pg.locator(dlg).count() == 0
        b.click(); pg.wait_for_timeout(200)
        pg.mouse.click(5, 5); pg.wait_for_timeout(200)           # 点外面
        out["overlay_closes"] = pg.locator(dlg).count() == 0
        b.click(); pg.wait_for_timeout(200)
        pg.locator(dlg + " [data-use-credit-cancel]").click(); pg.wait_for_timeout(200)
        out["cancel_closes"] = pg.locator(dlg).count() == 0
        out["sent_before_confirm"] = pg.evaluate(R + ".length")
        # 列出每一张、默认选最先过期、可改选
        b.click(); pg.wait_for_timeout(200)
        rows = pg.evaluate("""(s) => [...document.querySelectorAll(s)].map(r => ({id: r.getAttribute('data-use-credit-row'), sel: r.hasAttribute('data-selected'), text: r.innerText}))""", rowsel)
        out["rows"] = rows
        if len(rows) >= 2:
            pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(150)
            out["arrow_moves"] = pg.evaluate("(s) => [...document.querySelectorAll(s)].findIndex(r => r.hasAttribute('data-selected'))", rowsel)
            pg.locator(f"{dlg} [data-use-credit-row='{rows[0]['id']}']").click(); pg.wait_for_timeout(100)
            pg.locator(f"{dlg} [data-use-credit-row='{rows[1]['id']}']").click(); pg.wait_for_timeout(100)
            out["click_selects_second"] = pg.evaluate("(s) => [...document.querySelectorAll(s)].findIndex(r => r.hasAttribute('data-selected'))", rowsel)
        pg.locator(dlg + " [data-use-credit-confirm]").click(); pg.wait_for_timeout(600)
        out["sent_after_confirm"] = pg.evaluate(R)
        out["closed_after_confirm"] = pg.locator(dlg).count() == 0
        # 数据里的顺序被打乱（明细接口不保证按到期排）⇒ 弹层仍必须按到期先后排，最先过期的在最前
        pg.evaluate("""() => { for (const sl of Object.values(window.__HSTATE.slots)) if (sl.label === 'Egan') sl.credits_detail.credits.reverse(); }""")
        pg.get_by_text("刷新全池").first.click(); pg.wait_for_timeout(2500)
        b.click(); pg.wait_for_timeout(300)
        out["rows_shuffled"] = pg.evaluate("(s) => [...document.querySelectorAll(s)].map(r => r.innerText.match(/\\d\\d-\\d\\d/)[0])", rowsel)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
        # 不改选直接确认 ⇒ 发最先过期那张
        b.click(); pg.wait_for_timeout(200)
        pg.locator(dlg + " [data-use-credit-confirm]").click(); pg.wait_for_timeout(500)
        out["sent_default"] = pg.evaluate(R)[-1]
        br.close()
    return out


class TheConfirmDialog(unittest.TestCase):
    def test_flow(self):
        r = _dialog_probe()
        if r is None:
            self.skipTest("没有 playwright 或 harness 静态服务（3304）没在跑")
        self.assertGreaterEqual(r["n_badges"], 2, "★★ 底栏没有可点的重置卡 chip —— 闸此刻没有判别力")
        self.assertFalse(r["bar_has_use"], "★★ 动作条里还有「用卡」按钮（用户要求取消，因为容易误触）")
        self.assertEqual(r["opened"], 1, "★★ 点 chip 没有弹出确认弹层")
        self.assertEqual(r["sent_on_open"], 0, "★★★ 弹层一出来就已经发了 use-credit")
        # ✗「共 N 张，用掉后剩 M 张」与「默认焦点在取消」随旧弹窗一起被 P5 取代：弹层标题点名是哪个号，
        #   副标题写「用掉不能撤回」；张数在 chip 上（×N），选中的是哪一张由单选行写明。
        self.assertEqual(r["title"], "给 Egan 用一张重置卡？", "★★ 弹层没点名是哪个号")
        self.assertEqual(r["enter_confirms"], 0, "★★★ 回车就确认了 —— 连按回车会花掉一张卡")
        self.assertTrue(r["esc_closes"] and r["overlay_closes"] and r["cancel_closes"], f"★★ 取消路径没都关掉弹窗: {r}")
        self.assertEqual(r["sent_before_confirm"], 0, "★★★ 没点确认就发出了 use-credit")
        rows = r["rows"]
        self.assertGreaterEqual(len(rows), 3, f"★★ 这个号有 3 张卡，弹窗只列了 {len(rows)} 张")
        dates = [re.search(r"\d\d-\d\d", x["text"]).group() for x in rows]
        self.assertEqual(dates, sorted(dates), "★★ 卡没有按到期先后排")
        self.assertEqual(len(set(dates)), len(dates), "夹具里三张的到期日应各不相同，否则这条闸判别不了排序")
        self.assertEqual([x["sel"] for x in rows], [True] + [False] * (len(rows) - 1), "★★★ 默认没选中最近到期的那张")
        self.assertIn("最先过期", rows[0]["text"])
        self.assertEqual(r["arrow_moves"], 1, "★ 下方向键没有把选中移到下一张")
        self.assertEqual(r["click_selects_second"], 1, "★★ 点第二行没选中它")
        self.assertEqual(r["sent_after_confirm"][0][:3], ["use-credit", "Egan", "--card"], "★★ 没带 --card")
        self.assertEqual(r["sent_after_confirm"][0][3], rows[1]["id"], "★★★ 选了第二张，发出去的却不是它")
        self.assertEqual(len(r["sent_after_confirm"]), 1, "★★ 点确认后应恰好发一次")
        self.assertTrue(r["closed_after_confirm"])
        self.assertEqual(r["rows_shuffled"], sorted(r["rows_shuffled"]), "★★ 明细顺序被打乱后弹窗没重新按到期排（不能依赖接口返回顺序）")
        self.assertEqual(len(r["rows_shuffled"]), 3)
        self.assertEqual(r["sent_default"][3], rows[0]["id"], "★★★ 不改选直接确认，应发最近到期的那张")


if __name__ == "__main__":
    unittest.main(verbosity=2)
