"""agy 取额度被 403 时，**说出是哪一种 403、下一步做什么**（2026-10-15）。

旧实现：`额度 HTTP 403: {"error": {...` 截前 120 字节 —— 「要先去验证账号」「没有许可」
「别的禁止」三种下一步完全不同的状态折成同一串，验证链接被截掉，用户只看得到「403」。

现在：`parse_google_error` 读 Google 标准错误体（`error.details[].reason` + 链接），
`fetch_quota` 返回的错误仍是 `str`（调用方不变），但带 `.reason` / `.url`；
`agy-rotate quota` 把它落成兄弟键 `quota_err_reason` / `quota_err_url`（成功时清空）；
卡片与菜单栏行显示「需验证 →」，点开走 `open_url`。

⚠️ 链接在错误体里的**确切位置没有实测样本**（来源是读 cockpit-tools 的 `validation_url`），
所以解析按 ErrorInfo.metadata → Help.links → message 三处找。哪天真撞上一次 403，
拿那份响应体补一个夹具到这里。
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

try:
    from . import _isolation  # noqa: F401  ★ 见 tests/_isolation.py —— 必须在任何被测模块之前
except ImportError:
    import _isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agy import pool as P  # noqa: E402

SRC = ROOT / "codexbar" / "src"
VURL = "https://accounts.google.com/signin/continue?sarp=1&flowName=GlifWebSignIn"


def body(reason="VALIDATION_REQUIRED", meta=None, links=None, msg="Verify your account to continue."):
    d = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason,
          "domain": "cloudcode-pa.googleapis.com", "metadata": meta or {}}]
    if links is not None:
        d.append({"@type": "type.googleapis.com/google.rpc.Help", "links": links})
    return json.dumps({"error": {"code": 403, "message": msg, "status": "PERMISSION_DENIED",
                                 "details": d}}).encode()


class TheErrorBodyIsParsed(unittest.TestCase):
    def test_reason_and_url_from_errorinfo_metadata(self):
        r, m, u = P.parse_google_error(body(meta={"validation_url": VURL}))
        self.assertEqual((r, u), ("VALIDATION_REQUIRED", VURL))
        self.assertIn("Verify", m)

    def test_url_from_help_links(self):
        self.assertEqual(P.parse_google_error(body(links=[{"url": VURL}]))[2], VURL)

    def test_url_from_the_message(self):
        self.assertEqual(P.parse_google_error(body(msg="Verify at %s now" % VURL))[2], VURL)

    def test_a_non_google_url_is_never_returned(self):
        """★ 这个字符串会交给系统 `open` —— 只收 `https://*.google.com`。"""
        for bad in ("https://evil.example/x", "http://accounts.google.com/x",
                    "https://accounts.google.com.evil.example/x", "javascript:alert(1)"):
            with self.subTest(url=bad):
                self.assertIsNone(P.parse_google_error(body(meta={"validation_url": bad}))[2])

    def test_garbage_is_three_nones(self):
        self.assertEqual(P.parse_google_error(b"<html>403</html>"), (None, None, None))


def _fake_conn(status, raw):
    class FakeConn:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return types.SimpleNamespace(status=status, read=lambda: raw)

        def close(self):
            pass
    return FakeConn


class FetchQuotaCarriesTheStructure(unittest.TestCase):
    def fetch(self, status, raw):
        orig = P.HTTPSConnection
        P.HTTPSConnection = _fake_conn(status, raw)
        try:
            return P.fetch_quota("tok")
        finally:
            P.HTTPSConnection = orig

    def test_403_validation_required(self):
        groups, err = self.fetch(403, body(meta={"validation_url": VURL}))
        self.assertIsNone(groups)
        self.assertIsInstance(err, str, "★ 调用方把它当 str 用（拼接 / JSON / `in`），不许变类型")
        self.assertIn("VALIDATION_REQUIRED", err)
        self.assertEqual((err.reason, err.url), ("VALIDATION_REQUIRED", VURL))
        self.assertEqual(json.loads(json.dumps({"e": err}))["e"], str(err), "★ 落盘仍是普通字符串")

    def test_an_unparsable_403_keeps_the_old_text(self):
        groups, err = self.fetch(403, b"<html>nope</html>")
        self.assertIn("HTTP 403", err)
        self.assertIsNone(err.reason)
        self.assertIsNone(err.url)


def _load_cli():
    loader = importlib.machinery.SourceFileLoader("agy_rotate_403", str(ROOT / "agy-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TheQuotaCommandPersistsAndClearsIt(unittest.TestCase):
    """行为闸：真调 `cmd_quota`，碰盘 / 碰网 / 碰钥匙串的地方全部打桩（同 test_agy_quota_timely）。"""

    def run_quota(self, result):
        cli = _load_cli()
        pool = self.pool
        cli.P = types.SimpleNamespace(
            load=lambda: pool, fetch_quota=lambda tok: result,
            quota_by_group=P.quota_by_group, carry_missing_groups=P.carry_missing_groups, save=lambda p: None,
            _lock=lambda path: open(os.devnull), POOL=None)
        cli._refresh_one = lambda sub, a, pool: ({"token": {"access_token": "t"}}, "")
        cli._mark_live = lambda pool: None
        cli._log = lambda msg: None
        with redirect_stdout(io.StringIO()):
            cli.cmd_quota(["--json"])
        return pool["accounts"]["s"]

    def setUp(self):
        self.pool = {"accounts": {"s": {"label": "S"}}}

    def test_a_validation_403_is_written_and_a_success_clears_it(self):
        e = P.QuotaErr("额度 HTTP 403 VALIDATION_REQUIRED: Verify")
        e.reason, e.url = "VALIDATION_REQUIRED", VURL
        a = self.run_quota((None, e))
        self.assertEqual((a["quota_err_reason"], a["quota_err_url"]), ("VALIDATION_REQUIRED", VURL))
        ok = [{"displayName": "Gemini Models", "buckets": [
            {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 0.5, "resetTime": None}]}]
        a = self.run_quota((ok, ""))
        self.assertIsNone(a["quota_err_reason"], "★★ 验证过的号还挂着「需验证」")
        self.assertIsNone(a["quota_err_url"])


def ts_code(p):
    s = (SRC / p).read_text(encoding="utf-8")
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//[^\n]*", "", s)


def run_agy_ts(expr):
    src = (SRC / "agy.ts").read_text(encoding="utf-8")
    src, n = re.subn(r'from "\./helpers"', 'from "%s"' % (SRC / "helpers.ts").as_posix(), src)
    assert n == 1
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "agy.ts"
        f.write_text(src, encoding="utf-8")
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "-e",
                            "import('%s').then(m => console.log(JSON.stringify(%s)))" % (f.as_posix(), expr)],
                           capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-600:]
    return json.loads(r.stdout.strip().splitlines()[-1])


class TheUiSaysWhatToDo(unittest.TestCase):
    def test_validation_required_gets_a_link_and_an_honest_note(self):
        a = run_agy_ts('m.agyAction("VALIDATION_REQUIRED", %s)' % json.dumps(VURL))
        self.assertEqual((a["label"], a["url"]), ("需验证", VURL))
        self.assertIn("不是「额度耗尽」", a["note"])
        self.assertIn("重试也不会好", a["note"], "★ 这一种重试修不好 —— 不能说「会自动重试」")

    def test_subscription_required_says_retry_will_not_help(self):
        a = run_agy_ts('m.agyAction("SUBSCRIPTION_REQUIRED", null)')
        self.assertEqual(a["label"], "无许可")
        self.assertIn("重试不会好", a["note"])

    def test_nothing_to_say_is_null(self):
        self.assertIsNone(run_agy_ts('m.agyAction(null, null)'))
        self.assertIsNone(run_agy_ts('m.agyAction("SOMETHING_ELSE", null)'))

    def test_both_surfaces_are_wired(self):
        for f in ("App.tsx", "MenuBar.tsx"):
            with self.subTest(f=f):
                self.assertIn("action={agyAction(a.quota_err_reason, a.quota_err_url)}", ts_code(f))
        for f in ("components/AgyCard.tsx", "components/AgyRow.tsx"):
            with self.subTest(f=f):
                c = ts_code(f)
                self.assertIn("<AgyActionLink t={t} action={action}", c)
                self.assertIn("note={action ? action.note : agyReasonNote(snap)}", c)

    def test_the_link_opens_through_open_url(self):
        c = ts_code("components/AgyActionLink.tsx")
        self.assertIn('invoke("open_url", { url })', c)
        self.assertIn("e.stopPropagation()", c, "★ 点链接不能顺带触发卡片/行的点击")


if __name__ == "__main__":
    unittest.main()
