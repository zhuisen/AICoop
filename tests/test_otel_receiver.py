"""OTel 接收端：白名单之外的属性绝不落盘；只收 llm_request；非 JSON 看得见。

不碰真实 `traffic/otel-ledger/`：账本目录用临时目录，端口用 0（系统分配）。
"""
import http.client
import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("otel_receiver", ROOT / "traffic" / "otel_receiver.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def _attr(k, v):
    if isinstance(v, bool):
        return {"key": k, "value": {"boolValue": v}}
    if isinstance(v, int):
        return {"key": k, "value": {"intValue": str(v)}}
    return {"key": k, "value": {"stringValue": v}}


def _payload():
    llm = {"name": "claude_code.llm_request", "startTimeUnixNano": "1792333000000000000",
           "endTimeUnixNano": "1792333005861000000",
           "attributes": [_attr("request_id", "req_x"), _attr("ttft_ms", 5362),
                          _attr("duration_ms", 5861), _attr("output_tokens", 60),
                          _attr("success", True), _attr("user.email", "a@b.c"),
                          _attr("user.account_uuid", "uuid-1"), _attr("organization.id", "org-1")]}
    inter = {"name": "claude_code.interaction",
             "attributes": [_attr("user_prompt", "SECRET PROMPT")]}
    return {"resourceSpans": [{"scopeSpans": [{"spans": [llm, inter]}]}]}


class ExtractKeepsOnlyTheWhitelist(unittest.TestCase):
    def test_identity_and_prompt_never_kept(self):
        recs, ignored = R.extract(_payload())
        self.assertEqual(len(recs), 1)
        self.assertEqual(ignored, 1)
        blob = json.dumps(recs)
        for bad in ("a@b.c", "uuid-1", "org-1", "SECRET PROMPT", "user.email", "user_prompt"):
            self.assertNotIn(bad, blob)

    def test_timing_fields_are_ints(self):
        r = R.extract(_payload())[0][0]
        self.assertEqual((r["ttft_ms"], r["duration_ms"], r["output_tokens"]), (5362, 5861, 60))
        self.assertEqual(r["request_id"], "req_x")
        self.assertAlmostEqual(r["t_end"] - r["t_start"], 5.861, places=3)


class ServerWritesLedgerAndRejectsVisibly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = R.Ledger(self.tmp.name)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), R.make_handler(self.ledger))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def _post(self, body, ctype):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=3)
        c.request("POST", "/v1/traces", body, {"Content-Type": ctype})
        return c.getresponse().status

    def test_json_span_lands_on_disk_without_identity(self):
        self.assertEqual(self._post(json.dumps(_payload()), "application/json"), 200)
        files = list(Path(self.tmp.name).glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text()
        self.assertIn("req_x", text)
        self.assertNotIn("a@b.c", text)
        st = json.loads((Path(self.tmp.name) / ".status.json").read_text())
        self.assertEqual((st["posts"], st["spans_kept"], st["rejected"]), (1, 1, 0))

    def test_protobuf_is_rejected_and_recorded(self):
        self.assertEqual(self._post(b"\x0a\x00", "application/x-protobuf"), 415)
        st = json.loads((Path(self.tmp.name) / ".status.json").read_text())
        self.assertEqual(st["rejected"], 1)
        self.assertIn("not json", st["last_error"])
        self.assertEqual(list(Path(self.tmp.name).glob("*.jsonl")), [])



class APortConflictIsVisibleNotSilent(unittest.TestCase):
    """★★ 4318 是 OTLP/HTTP 的标准端口，用户自己的收集器很可能占着它。起不来要说出来，不许静默。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.squatter = ThreadingHTTPServer(("127.0.0.1", 0), R.make_handler(R.Ledger(self.tmp.name + "/other")))
        self.port = self.squatter.server_address[1]

    def tearDown(self):
        self.squatter.server_close()
        self.tmp.cleanup()

    def test_the_reason_lands_in_the_status_file_and_the_exit_code(self):
        (self.root / ".status.json").write_text(json.dumps({"last_post_at": 1792384243.1, "posts": 9}))
        rc = R.main(["--port", str(self.port), "--dir", str(self.root)])
        self.assertNotEqual(rc, 0, "起不来却退出 0 —— launchd 会当它正常结束")
        st = json.loads((self.root / ".status.json").read_text())
        self.assertIs(st["listening"], False)
        self.assertIn(str(self.port), st["last_error"])
        self.assertIn("占用", st["last_error"])
        # ★ 合并而不是整份重写：占着端口的可能正是另一份接收端，它的「收到过」不能被抹掉。
        self.assertEqual((st["last_post_at"], st["posts"]), (1792384243.1, 9))

    def test_a_restart_keeps_the_last_post_time(self):
        (self.root / ".status.json").write_text(json.dumps({"last_post_at": 1792384243.1, "posts": 9}))
        led = R.Ledger(self.root)
        led.note(listening=True)
        st = json.loads((self.root / ".status.json").read_text())
        self.assertEqual(st["last_post_at"], 1792384243.1, "重启把「收到过数据」清空了 —— 设置页会误报「还没收到」")


if __name__ == "__main__":
    unittest.main()
