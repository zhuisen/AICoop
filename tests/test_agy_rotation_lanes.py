"""日志页「代理轮换」的 Gemini 版块（用户 2026-09-24：「改成 codex 和 gemini 两个版块」）。

数据：`traffic/agy_rotation.py`（纯模块，与 `rotation.collect` 同形）。判据：
① 会话按 agy 自己日志的 `applyAuthResult` 归属，**认不出就不归属**（计数，不猜）；
② 一场会话中途身份变了要切段，不把整场记在第一个号头上；
③ 「在岗」是区间**并集**（本机常有多个 agy 同号并发，实测求和一天出 139633s）；
④ 有换号记录的是「切换」，没有的是「钥匙串被写回」（drift）—— 两者不许混；
⑤ 输出与前端 `Rotation` 接口同形（从 TS 源现解析）；
⑤' 按号 token（2026-10-14）：会话 id 写在哪份日志里、那份日志此刻是谁 —— 精确 join，对不上就不归属；
⑥ 前端：Gemini 版不把 `rot.log` 再并进运行日志（那份就是 agy.log，会每行两遍且错标 proxy）；
   IPC 只读不 emit；模块进了安装包 resources。
"""
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "traffic"))
import agy_rotation as AR  # noqa: E402

NOW = time.time()


def _stamp(t):
    return time.strftime("%m%d %H:%M:%S.000000", time.localtime(t))


class Fixture:
    def __init__(self):
        self.d = Path(tempfile.mkdtemp(prefix="agyrot-"))
        self.logs = self.d / "log"
        self.logs.mkdir()
        (self.d / ".agy-pool.json").write_text(json.dumps({"accounts": {
            "s0": {"label": "A", "email": "a@x.y"}, "s1": {"label": "B", "email": "b@x.y"}}}))
        self.n = 0

    def run(self, a_h, b_h, *auths, convs=()):
        """一场会话：`auths` = [(相对小时, email), …]；空 = 认不出身份。`convs` = 这场写进日志的会话 id。"""
        t0 = NOW + a_h * 3600
        self.n += 1
        f = self.logs / time.strftime("cli-%Y%m%d_%H%M%S.log", time.localtime(t0 + self.n))
        body = "I%s 1 x.go:1] start\n" % _stamp(t0)
        for c in convs:
            body += "I%s 3 conv.go:1] conversation_id=%s\n" % (_stamp(t0), c)
        for (h, email) in auths:
            body += "I%s 2 server_oauth.go:196] applyAuthResult: email=%s, authMethod=consumer\n" % (
                _stamp(NOW + h * 3600), email)
        f.write_text(body)
        os.utime(f, (NOW + b_h * 3600, NOW + b_h * 3600))

    def switch(self, h, label):
        with open(self.d / "agy.log", "a") as fh:
            fh.write("[agy %s] auto 自动切到 [%s]（剩余 90%%，new，落点 keyring）\n"
                     % (time.strftime("%m-%d %H:%M:%S", time.localtime(NOW + h * 3600)), label))

    def collect(self, hours=24, gens=()):
        return AR.collect(hours, now=NOW, log_dir=self.logs, store=self.d, gens=list(gens))


class SessionsAreAttributedByAgysOwnLog(unittest.TestCase):
    def test_an_unreadable_identity_is_counted_not_guessed(self):
        f = Fixture()
        f.run(-3, -2)
        r = f.collect()
        self.assertEqual(r["segments"], [])
        self.assertEqual(r["coverage"]["responses_unplaced"], 1, "★★ 认不出身份的会话被悄悄丢了")

    def test_an_identity_change_mid_session_splits_it(self):
        """★★ 长会话中途被钥匙串写回 → 同一份日志第二条 applyAuthResult。"""
        f = Fixture()
        f.run(-5, -1, (-5, "a@x.y"), (-3, "b@x.y"))
        segs = [(s["acc"], round((s["end"] - s["start"]) / 3600)) for s in f.collect()["segments"]]
        self.assertEqual(segs, [("A", 2), ("B", 2)])

    def test_on_duty_is_a_union_not_a_sum(self):
        """★★★ 两场同号并发会话：在岗 = 并集（2h），不是求和（3h）。"""
        f = Fixture()
        f.run(-4, -2, (-4, "a@x.y"))
        f.run(-3, -2, (-3, "a@x.y"))
        row = next(r for r in f.collect()["daily"]["rows"] if r["acc"] == "A")
        secs = sum(c["secs"] for c in row["cells"] if isinstance(c, dict))
        self.assertAlmostEqual(secs / 3600, 2, delta=0.05)


class SwitchAndDriftAreDifferentThings(unittest.TestCase):
    def test_a_logged_switch_is_a_switch(self):
        f = Fixture()
        f.run(-6, -5, (-6, "a@x.y"))
        f.switch(-4.01, "B")
        f.run(-4, -3, (-4, "b@x.y"))
        r = f.collect()
        self.assertEqual(r["segments"][1]["enter_reason"], "switch")
        self.assertFalse(any(e["reason"] == "drift" for e in r["events"]))

    def test_an_unlogged_change_is_drift(self):
        """★★ 没有换号记录却换了身份 = 某个常驻 agy 把钥匙串写回了 —— 必须单独说出来。"""
        f = Fixture()
        f.run(-6, -5, (-6, "a@x.y"))
        f.run(-4, -3, (-4, "b@x.y"))
        r = f.collect()
        self.assertEqual(r["segments"][1]["enter_reason"], "drift")
        self.assertTrue(any(e["reason"] == "drift" for e in r["events"]))


class TheOutputMatchesTheRotationInterface(unittest.TestCase):
    def test_keys_parsed_from_the_ts_source(self):
        ts = (ROOT / "codexbar" / "src" / "pages" / "LogsPage.tsx").read_text(encoding="utf-8")

        def fields(name):
            body = re.search(r"interface %s \{([\s\S]*?)\n\}" % name, ts).group(1)
            body = re.sub(r"/\*\*[\s\S]*?\*/", "", body)
            return {k for k in re.findall(r"^\s{2}(\w+):", body, re.M)}   # 只核必填键（`reason?`/`detail?` 是失败态专用）
        f = Fixture()
        f.run(-3, -1, (-3, "a@x.y"))
        r = f.collect()
        self.assertTrue(fields("Rotation") <= set(r), fields("Rotation") - set(r))
        self.assertTrue(fields("Seg0") <= set(r["segments"][0]), fields("Seg0") - set(r["segments"][0]))
        self.assertTrue(fields("Acct") - {"retired"} <= set(r["accounts"][0]))

    def test_no_generations_means_unknown_not_zero_percent(self):
        """没有一条生成时覆盖率是 None —— 「没有可归属的」≠「0% 归属」。"""
        f = Fixture()
        f.run(-3, -1, (-3, "a@x.y"))
        r = f.collect()
        self.assertIsNone(r["coverage"]["attributed_pct"])
        self.assertEqual(r["platform"], "agy")


C1, C2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def _g(h, conv, i=100, cr=1000, o=10, model="gemini-4-argon"):
    return (NOW + h * 3600, conv, model, i, cr, o)


class TokensAreJoinedByConversationId(unittest.TestCase):
    """★★ 2026-10-14：会话 id 出现在启动它的那份日志里 ⇒ 按 id 精确归属，与 codex 的 response_id 同纪律。"""

    def test_a_logged_conversation_goes_to_that_logs_account(self):
        f = Fixture()
        f.run(-6, -4, (-6, "a@x.y"), convs=[C1])
        f.run(-3, -1, (-3, "b@x.y"), convs=[C2])
        r = f.collect(gens=[_g(-5, C1), _g(-2, C2, i=1, cr=2, o=3)])
        tok = {a["acc"]: a["tokens"] for a in r["accounts"]}
        self.assertEqual(tok, {"A": 1110, "B": 6}, "★★ token 没按会话 id 落到写它的那份日志的号上")
        self.assertEqual(r["kpi"]["tokens"], 1116)
        self.assertEqual(r["coverage"]["attributed_pct"], 1.0)
        self.assertEqual(r["segments"][0]["by_model"], [{"model": "gemini-4-argon", "tokens": 1110}])

    def test_time_alone_never_attributes(self):
        """★★★ 会话 id 不在任何日志里 ⇒ 不归属，哪怕时间正好落在 A 的段里。按时间拼就是猜。"""
        f = Fixture()
        f.run(-6, -1, (-6, "a@x.y"), convs=[C1])
        r = f.collect(gens=[_g(-3, C2)])
        self.assertEqual({a["acc"]: a["tokens"] for a in r["accounts"]}, {"A": 0, "B": 0})
        self.assertEqual(r["coverage"]["responses_seen"], 1)
        self.assertEqual(r["coverage"]["attributed_pct"], 0.0)

    def test_a_mid_session_identity_change_splits_the_tokens(self):
        f = Fixture()
        f.run(-6, -1, (-6, "a@x.y"), (-3, "b@x.y"), convs=[C1])
        r = f.collect(gens=[_g(-5, C1), _g(-2, C1, i=1, cr=0, o=0)])
        self.assertEqual({a["acc"]: a["tokens"] for a in r["accounts"]}, {"A": 1110, "B": 1})

    def test_two_logs_that_disagree_attribute_nothing(self):
        """同一会话 id 在两份日志里、此刻对出两个号 ⇒ 宁可不并，也不并错。"""
        f = Fixture()
        f.run(-6, -1, (-6, "a@x.y"), convs=[C1])
        f.run(-6, -1, (-6, "b@x.y"), convs=[C1])
        r = f.collect(gens=[_g(-3, C1)])
        self.assertEqual(r["kpi"]["tokens"], 0)
        self.assertEqual(r["coverage"]["responses_with_tokens"], 0)

    def test_daily_cells_carry_the_tokens(self):
        f = Fixture()
        f.run(-6, -4, (-6, "a@x.y"), convs=[C1])
        r = f.collect(gens=[_g(-5, C1)])
        row = next(x for x in r["daily"]["rows"] if x["acc"] == "A")
        self.assertEqual(sum(c["tokens"] for c in row["cells"] if isinstance(c, dict)), 1110)


class TheLogsPageWiring(unittest.TestCase):
    SRC = (ROOT / "codexbar" / "src" / "pages" / "LogsPage.tsx").read_text(encoding="utf-8")

    def test_the_gemini_tab_uses_its_own_ipc(self):
        self.assertIn('invoke<Rotation>("read_agy_rotation"', self.SRC)
        self.assertIn('<Seg opts={["codex", "agy"] as const}', self.SRC)

    def test_gemini_shows_tokens_only_when_attribution_ran(self):
        """★ 2026-10-14 起 Gemini 也显示 token —— 但只在后端真的做过归属时（`attributed_pct` 非 None）；
        否则仍是「—」，不把「没有可归属的」画成 0。"""
        self.assertIn("const agyTok = !isAgy || rot?.coverage.attributed_pct != null;", self.SRC)
        self.assertIn('v={rot && agyTok ? fmtTok(rot.kpi.tokens) : "—"}', self.SRC)
        self.assertIn('{agyTok ? fmtTok(l.tokens) : "—"}', self.SRC)

    def test_the_run_log_is_not_merged_twice(self):
        """★ Gemini 版的 rot.log 就是 agy.log 的换号行 —— 服务日志里已经整份含着。"""
        self.assertIn("const proxy = isAgy ? [] :", self.SRC)

    def test_the_ipc_is_read_only_and_the_module_ships(self):
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("async fn read_agy_rotation")
        self.assertNotIn("emit(", rs[i:rs.index("\n}", i)])
        conf = (ROOT / "codexbar" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
        self.assertIn('"../../traffic/agy_rotation.py"', conf, "★★ 模块没进安装包 —— 装机版这一版整块读不出")


if __name__ == "__main__":
    unittest.main(verbosity=2)
