"""grok：429 单列 + 退避，套餐名一天读一次（2026-10-15，用户点名做的 2、3）。

## 守的
1. 429 ⇒ `rate_limited`（不是 `http_error`），带 `retry_at`；失败态 `quota` 仍恒 None。
2. Retry-After 两种写法都认（秒 / HTTP 日期）、夹在 [1, 3600]；没带就默认退避。
3. ★★ 退避期内**不发请求**（经 `--prev` 带过来的 `retry_at`）—— 把 429 单列的全部意义。
4. 套餐名取 `/v1/settings` 的 `subscription_tier_display`（实测 "SuperGrok"）；
   24h 内不重读；读不到 / 额度失败时**留上次的**（读不到 ≠ 没有）。
5. 前端：`grokBadgePlan` 免费档不画；卡与菜单栏行都接上了。

假上游：自签 CA + `SSL_CERT_FILE`（同 `test_grok_degrade_contract.py`），**不碰真实 `~/.grok`**。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import http.server
import importlib.machinery
import importlib.util
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from email.utils import formatdate
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "grok-quota"
SRC = ROOT / "codexbar" / "src"
BILL = "/v1/billing?format=credits"
GOOD = {"config": {"currentPeriod": {"type": "W", "start": "2026-10-10T00:00:00+00:00",
                                     "end": "2026-10-17T00:00:00+00:00"},
                   "creditUsagePercent": 12.0}}


def make_cert(tmp):
    key, crt = tmp / "k.pem", tmp / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                    "-out", str(crt), "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1"], check=True, capture_output=True)
    return key, crt


class Up:
    def __init__(self, key, crt):
        self.routes = {}      # path -> (status, body, extra_headers)
        self.paths = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.paths.append(self.path)
                st, body, hdr = outer.routes.get(self.path, (404, b"{}", {}))
                self.send_response(st)
                for k, v in hdr.items():
                    self.send_header(k, v)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(crt), str(key))
        self.srv.socket = ctx.wrap_socket(self.srv.socket, server_side=True)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


class GrokRateLimitAndPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.key, cls.crt = make_cert(cls.tmp)
        cls.up = Up(cls.key, cls.crt)

    @classmethod
    def tearDownClass(cls):
        cls.up.srv.shutdown()
        cls._tmp.cleanup()

    def setUp(self):
        self.up.routes = {BILL: (200, json.dumps(GOOD).encode(), {}),
                          "/v1/settings": (200, json.dumps({"subscription_tier_display": "SuperGrok"}).encode(), {})}
        self.auth = self.tmp / "auth.json"
        exp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + 3600)) + ".0Z"
        self.auth.write_text(json.dumps({"k1": {"key": "tok", "user_id": "u", "email": "g@example.com",
                                                "expires_at": exp}}), encoding="utf-8")
        self.prev = self.tmp / "prev.json"
        if self.prev.exists():
            self.prev.unlink()

    def run_tool(self, use_prev=True):
        env = dict(os.environ, GROK_AUTH_PATH=str(self.auth), SSL_CERT_FILE=str(self.crt),
                   GROK_BILLING_HOST="127.0.0.1:%d" % self.up.port)
        cmd = [sys.executable, str(SCRIPT)] + (["--prev", str(self.prev)] if use_prev and self.prev.exists() else [])
        n = len(self.up.paths)
        out = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.prev.write_text(out.stdout, encoding="utf-8")
        return json.loads(out.stdout)["accounts"][0], self.up.paths[n:]

    # ── 429 ─────────────────────────────────────────────────────────────
    def test_429_is_its_own_reason_and_backs_off(self):
        self.up.routes[BILL] = (429, b'{"error":"slow down"}', {"Retry-After": "90"})
        a, hit = self.run_tool()
        self.assertEqual(a["reason"], "rate_limited", "★★ 429 还混在 http_error 里")
        self.assertIsNone(a["quota"], "失败态 quota 恒 None")
        self.assertAlmostEqual(a["retry_at"] - time.time(), 90, delta=5)
        self.assertEqual(hit, [BILL])
        a2, hit2 = self.run_tool()
        self.assertEqual(hit2, [], "★★★ 退避期内又打了一次 —— 把 429 单列的意义就没了")
        self.assertEqual(a2["reason"], "rate_limited")
        self.assertEqual(a2["retry_at"], a["retry_at"], "退避截止要原样带下去，不能每次顺延")

    def test_after_the_deadline_it_asks_again(self):
        self.up.routes[BILL] = (429, b"{}", {"Retry-After": "1"})
        self.run_tool()
        time.sleep(1.2)
        self.up.routes[BILL] = (200, json.dumps(GOOD).encode(), {})
        a, hit = self.run_tool()
        self.assertTrue(a["available"])
        self.assertIn(BILL, hit)
        self.assertIsNone(a["retry_at"])

    def test_retry_after_forms(self):
        loader = importlib.machinery.SourceFileLoader("gq_t", str(SCRIPT))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        gq = importlib.util.module_from_spec(spec)
        loader.exec_module(gq)
        now = time.time()
        self.assertEqual(gq.retry_after_secs("30", now), 30)
        self.assertAlmostEqual(gq.retry_after_secs(formatdate(now + 600, usegmt=True), now), 600, delta=2)
        self.assertEqual(gq.retry_after_secs("999999", now), gq.MAX_BACKOFF)
        self.assertEqual(gq.retry_after_secs(None, now), gq.DEFAULT_BACKOFF, "没带头也要退避")
        self.assertEqual(gq.retry_after_secs("garbage", now), gq.DEFAULT_BACKOFF)
        self.assertEqual(gq.retry_after_secs("0", now), 1)

    def test_500_is_still_http_error(self):
        self.up.routes[BILL] = (500, b"boom", {})
        a, _ = self.run_tool()
        self.assertEqual(a["reason"], "http_error")
        self.assertIsNone(a["retry_at"], "★ 只有 429 才退避；500 下次照常重试")

    # ── 套餐名 ──────────────────────────────────────────────────────────
    def test_plan_is_read_once_a_day(self):
        a, hit = self.run_tool()
        self.assertEqual(a["plan"]["name"], "SuperGrok")
        self.assertEqual(hit, [BILL, "/v1/settings"])
        a2, hit2 = self.run_tool()
        self.assertEqual(hit2, [BILL], "★ 每 60s 采样都去读一次套餐 —— 一天一次就够")
        self.assertEqual(a2["plan"], a["plan"])

    def test_plan_survives_failures(self):
        self.run_tool()
        self.up.routes[BILL] = (500, b"x", {})
        a, _ = self.run_tool()
        self.assertEqual((a["plan"] or {}).get("name"), "SuperGrok", "★★ 额度读失败把套餐名也丢了（读不到 ≠ 没有）")

    def test_settings_failure_keeps_old_and_never_breaks_quota(self):
        data = json.loads(self.run_tool()[0] and self.prev.read_text())
        data["accounts"][0]["plan"]["at"] = 0           # 推到 TTL 之外，逼它重读
        self.prev.write_text(json.dumps(data), encoding="utf-8")
        # ★ 两种坏法都要试：500 走状态码分支，200 + 坏 JSON 才会真的抛进 except。
        for bad in ((500, b"x", {}), (200, b"<html>not json", {})):
            self.up.routes["/v1/settings"] = bad
            a, hit = self.run_tool()
            self.assertTrue(a["available"], "★ 套餐名读失败绝不能拖垮额度：%r" % (bad[:2],))
            self.assertEqual(a["plan"]["name"], "SuperGrok")
            self.assertIn("/v1/settings", hit)


def ts_eval(expr):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "grok.ts"
        src = (SRC / "grok.ts").read_text(encoding="utf-8")
        src = re.sub(r'from "\./(\w+)"', lambda m: 'from "%s"' % (SRC / (m.group(1) + ".ts")).as_posix(), src)
        f.write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                            "import('%s').then(m => console.log(JSON.stringify(%s)))" % (f.as_posix(), expr)],
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class TheUi(unittest.TestCase):
    def test_badge_text(self):
        self.assertEqual(ts_eval('[{plan:{name:"SuperGrok",at:1}},{plan:{name:"Free",at:1}},{},null].map(m.grokBadgePlan)'),
                         ["SuperGrok", "", "", ""])

    def test_card_and_row_render_it(self):
        card = (SRC / "components" / "GrokCard.tsx").read_text(encoding="utf-8")
        # 2026-10-19：PlanBadge 随总览重做删除，套餐用卡片外壳的同一个标签（`OvTag` kind "ultra"，紫底）。
        self.assertIn("const plan = grokBadgePlan(a);", card, "GrokCard.tsx 没从 grokBadgePlan 取套餐")
        self.assertRegex(card, r'\{plan && <OvTag tag=\{\{ text: plan, kind: "ultra" \}\}', "GrokCard.tsx 拿到套餐却没画出来")
        # 菜单栏行（2026-10-19 交接包 4f）：套餐名进行名下的小状态行 `Sub`，不再是独立 PlanBadge。
        row = (SRC / "components" / "GrokRow.tsx").read_text(encoding="utf-8")
        self.assertEqual(row.count("plan={grokBadgePlan(a)}"), 2, "菜单栏行两种形态（有读数 / 降级）都要带")
        self.assertRegex(row, r"\{plan \? <span[^>]*>\{plan\}</span> : null\}", "Sub 拿到套餐名却没画出来")

    def test_rate_limited_note_says_when(self):
        note = ts_eval('m.grokReasonNote({reason:"rate_limited",retry_at:%d,token_expires_at:null})' % (time.time() + 600))
        self.assertIn("429", note)
        self.assertIn("之后再取", note, "★ 要说出什么时候恢复")


if __name__ == "__main__":
    unittest.main()
