"""每个已注册源都报一条状态，「读不到」一路传到给人看的那句话（B85 · 四方评审 P1）。

## 现场
少了一家时平台键从 `platforms` 里消失，「根目录不存在 / 有压缩文件没解析 / 读失败 / 被停用」
在页面上一模一样（B84 当天：看见 1712 个文件、解析 37 个，界面上只是数字小）。

## 守的（全是合成夹具，单元素 SOURCES，不碰真实 `~/.codex` 与缓存）
1. 六种状态各自判得出：not_found / empty / ok / partial / read_failed / disabled。
2. 普查只认压缩后缀：`.lock` 不算漏；同名 `.jsonl` 已收时 `.jsonl.zst` 不算漏（那是去重）。
3. 「没有解压器」与「文件坏了」分开计（`no_decoder`）。
4. `scanHealth.ts` 把它们说成人话：漏算是 warn、没找到是 info，warn 排前；没问题不出声。
"""
try:
    from . import _isolation  # noqa: F401
except ImportError:
    import _isolation  # noqa: F401
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "traffic"))
import scan  # noqa: E402

HEALTH = ROOT / "codexbar" / "src" / "scanHealth.ts"


def _rollout(t0):
    tc = {"type": "event_msg", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t0)),
          "payload": {"type": "token_count", "info": {
              "total_token_usage": {"total_tokens": 100},
              "last_token_usage": {"total_tokens": 100, "input_tokens": 80, "cached_input_tokens": 30,
                                   "output_tokens": 20}}}}
    ev = [{"type": "session_meta", "payload": {"id": "s", "model_provider": "openai"}},
          {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}}, tc]
    return "".join(json.dumps(e) + "\n" for e in ev)


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.root = self.d / "sessions"
        self.t0 = int(time.time()) - 86400
        self._orig = (scan.SOURCES, scan.CACHE, scan.LOCAL_CFG, scan._ZSTD)
        self.codex = next(x for x in scan.SOURCES if x["key"] == "codex")
        scan.SOURCES = (dict(self.codex, root=self.root),)
        scan.CACHE = self.d / "cache.json"
        scan.LOCAL_CFG = self.d / "sources.local.json"
        self.addCleanup(self._restore)

    def _restore(self):
        scan.SOURCES, scan.CACHE, scan.LOCAL_CFG, scan._ZSTD = self._orig

    def put(self, name, text=None):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_rollout(self.t0) if text is None else text, encoding="utf-8")
        return p

    def src(self, key="codex", **kw):
        _, stat = scan.scan(days=7, use_cache=False, **kw)
        return stat["sources"][key]


class EachStateIsDistinguishable(_Fixture):
    def test_not_found(self):
        s = self.src()
        self.assertEqual(s["state"], "not_found")
        self.assertEqual(s["name"], "Codex")

    def test_empty(self):
        self.root.mkdir(parents=True)
        self.assertEqual(self.src()["state"], "empty")

    def test_ok(self):
        self.put("rollout-a.jsonl")
        s = self.src()
        self.assertEqual((s["state"], s["files"], s["unparsed"]), ("ok", 1, {}))

    def test_partial_when_a_compressed_file_is_not_parsed(self):
        self.put("rollout-a.jsonl")
        self.put("rollout-b.jsonl.gz", "x")
        s = self.src()
        self.assertEqual(s["state"], "partial", s)
        self.assertEqual(s["unparsed"], {".gz": 1})

    def test_partial_for_a_glob_that_does_not_end_in_a_star(self):
        """另一条候选路径：`**/*.jsonl` 这类 glob 看不见 `.jsonl.gz`，要靠 `<glob>.*` 补看。"""
        claude = next(x for x in self._orig[0] if x["key"] == "claude")
        scan.SOURCES = (dict(claude, root=self.root),)
        self.put("p/a.jsonl", "")
        self.put("p/b.jsonl.zst", "x")
        s = self.src("claude")
        self.assertEqual((s["state"], s["unparsed"]), ("partial", {".zst": 1}), s)

    def test_disabled(self):
        self.put("rollout-a.jsonl")
        self.assertEqual(self.src(exclude=["codex"])["state"], "disabled")


class TheCensusDoesNotCryWolf(_Fixture):
    def test_lock_files_are_not_a_gap(self):
        claude = next(x for x in self._orig[0] if x["key"] == "claude")
        scan.SOURCES = (dict(claude, root=self.root),)
        self.put("p/a.jsonl", "")
        self.put("p/b.jsonl.lock", "")    # ★ 孤儿：旁边没有 b.jsonl，否则被「同名已收」那条兜住，测不到后缀过滤
        s = self.src("claude")
        self.assertEqual((s["state"], s["unparsed"]), ("ok", {}), "★★ 一盏永远亮着的灯（grok 根下 127 个 .lock）")

    @unittest.skipUnless(shutil.which("zstd"), "需要 zstd")
    def test_a_zst_beside_its_jsonl_is_dedup_not_a_gap(self):
        self.put("rollout-a.jsonl")
        z = self.root / "rollout-a.jsonl.zst"
        subprocess.run(["zstd", "-q", "-f", str(self.root / "rollout-a.jsonl"), "-o", str(z)], check=True)
        s = self.src()
        self.assertEqual((s["state"], s["unparsed"], s["files"]), ("ok", {}, 1), s)


class NoDecoderIsNotACorruptFile(_Fixture):
    def setUp(self):
        super().setUp()
        self.put("rollout-a.jsonl")
        self.put("rollout-b.jsonl.zst", "not zstd at all")

    def test_no_decoder_on_this_machine(self):
        scan._ZSTD = str(self.d / "no-such-zstd")
        saved = {k: sys.modules.get(k) for k in ("compression", "compression.zstd")}
        sys.modules["compression.zstd"] = None          # ⇒ `from compression import zstd` 抛 ImportError
        sys.modules["compression"] = None
        try:
            s = self.src()
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.assertEqual((s["state"], s["read_failed"], s["no_decoder"]), ("read_failed", 1, 1), s)

    @unittest.skipUnless(shutil.which("zstd"), "需要 zstd")
    def test_a_corrupt_file_with_a_real_decoder(self):
        scan._ZSTD = shutil.which("zstd")
        s = self.src()
        self.assertEqual((s["state"], s["read_failed"], s["no_decoder"]), ("read_failed", 1, 0), s)


def _node(expr):
    script = "import('file://%s').then(m => console.log(JSON.stringify(%s)));" % (HEALTH.as_posix(), expr)
    r = subprocess.run(["node", "--experimental-strip-types", "-e", script],
                       capture_output=True, text=True, timeout=60, cwd=ROOT)
    out = [l for l in r.stdout.splitlines() if l.strip().startswith(("[", "{"))]
    if not out:
        raise AssertionError(f"node 没有产出：{r.stderr[-500:]}")
    return json.loads(out[-1])


#: ★ info 级（openclaw）故意排第一个：否则插入顺序本来就是 warn 在前，「排序」被删了也照样绿。
FIX = {
    "openclaw": {"state": "not_found", "name": "OpenClaw", "root": "~/.openclaw/agents", "files": 0},
    "codex": {"state": "read_failed", "name": "Codex", "root": "~/.codex/sessions", "files": 40,
              "read_failed": 3, "no_decoder": 2, "unparsed": {}},
    "claude": {"state": "partial", "name": "Claude", "root": "~/.claude/projects", "files": 9,
               "read_failed": 0, "no_decoder": 0, "unparsed": {".gz": 5}},
    "kimi": {"state": "ok", "name": "Kimi", "root": "~/.kimi-code/sessions", "files": 100,
             "read_failed": 0, "no_decoder": 0, "unparsed": {}},
    "grok": {"state": "empty", "name": "Grok", "root": "~/.grok/sessions", "files": 0},
}


@unittest.skipIf(shutil.which("node") is None, "没有 node")
class TheCopySaysWhatHappened(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notes = _node("m.sourceNotes(%s)" % json.dumps(FIX, ensure_ascii=False))
        cls.by = {}
        for n in cls.notes:
            cls.by.setdefault(n["key"], []).append(n)

    def test_no_decoder_says_install_one(self):
        t = [n["text"] for n in self.by["codex"]]
        self.assertTrue(any("未计入 2 个压缩会话" in x and "brew install zstd" in x for x in t), t)
        self.assertEqual({n["level"] for n in self.by["codex"]}, {"warn"}, "★★ 少算了是告警，不是附注")

    def test_the_rest_of_the_failures_say_read_failed(self):
        t = [n["text"] for n in self.by["codex"]]
        self.assertTrue(any("1 个文件读失败" in x for x in t), t)

    def test_unparsed_says_how_many_and_which_suffix(self):
        self.assertEqual([n["text"] for n in self.by["claude"]],
                         ["Claude：未计入 5 个 .gz 文件（还不支持这种压缩格式）"])

    def test_missing_and_empty_are_info_not_warn(self):
        self.assertEqual([n["level"] for n in self.by["openclaw"] + self.by["grok"]], ["info", "info"])
        self.assertIn("~/.openclaw/agents", self.by["openclaw"][0]["text"])

    def test_a_healthy_source_is_silent(self):
        self.assertNotIn("kimi", self.by)

    def test_warnings_come_first(self):
        lv = [n["level"] for n in self.notes]
        self.assertEqual(lv, sorted(lv, key=lambda x: x != "warn"), lv)
        self.assertGreater(lv.count("warn"), 0)

    def test_the_card_line_only_carries_that_platforms_warnings(self):
        got = _node("[m.warnNotesFor(%s, 'claude'), m.warnNotesFor(%s, 'openclaw'), m.warnNotesFor(undefined, 'codex')]"
                    % (json.dumps(FIX), json.dumps(FIX)))
        self.assertEqual([len(g) for g in got], [1, 0, 0], "★ 没装 OpenClaw 不该在卡上告警")


if __name__ == "__main__":
    unittest.main()
