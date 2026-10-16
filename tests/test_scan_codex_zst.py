"""codex 的 `rollout-*.jsonl.zst` 必须计入（2026-10-16，外部用户实报 + 交接说明 `交接说明.md`）。

## 现场（外部用户机器，本机 0 个 `.zst`，所以这里全是合成夹具）
Codex 把旧会话压成 `rollout-*.jsonl.zst`：`~/.codex/sessions` 下 1,675 个 `.zst` 对 37 个 `.jsonl`。
扫描器只认 `**/rollout-*.jsonl` ⇒ 30 天窗口少 35%、90 天少 96%（125.9M vs 193.4M、143.4M vs 4.03B）。

## 守的
1. 同一份内容，`.jsonl` 与 `.jsonl.zst` 解析出的 rows 完全相同（跨行状态一个字不改）。
2. `rollout-*.jsonl.bak-namespace*` 不收（外部用户机器上 20 个，SQLite 无对应会话，收了凭空多 841M）。
3. `X.jsonl` 与 `X.jsonl.zst` 并存只计一次（压缩中途 `.zst` 可能没写完；codex 源 `dedup: False`）。
4. 解压失败 ⇒ `read_failed` 有记录，且缓存里**没有**该文件的条目（否则 0 token 被签名钉死）。
5. `.jsonl` 打不开 ⇒ 抛 `ScanReadError`，不返回 `[]`。
6. dsh（另一个 zstd 源）解压失败同样抛错，不再静默 0 行。
"""
import json
import os
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

HAVE_ZSTD = bool(shutil.which("zstd"))


def _iso(ep):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ep))


def _rollout_text(t0, n=3, model="gpt-5.6-sol"):
    """两条 session_meta + 中途换模型 + 成对重复的 token_count —— 跨行状态全用上。"""
    ev = [{"type": "session_meta", "payload": {"id": "s", "model_provider": "openai"}},
          {"type": "turn_context", "payload": {"model": model}}]
    cum = 0
    for i in range(n):
        cum += 100 + i
        tc = {"type": "event_msg", "timestamp": _iso(t0 + i * 60), "payload": {"type": "token_count", "info": {
            "total_token_usage": {"total_tokens": cum},
            "last_token_usage": {"total_tokens": 100 + i, "input_tokens": 80 + i,
                                 "cached_input_tokens": 30, "output_tokens": 20}}}}
        ev += [tc, tc]                              # 成对重复写入（真实形态）
        if i == 0:
            ev.append({"type": "turn_context", "payload": {"model": "gpt-5.6-luna"}})
            ev.append({"type": "session_meta", "payload": {"id": "s", "model_provider": "rotateproxy"}})
    return "".join(json.dumps(e) + "\n" for e in ev)


def _write(path, text, compress=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not compress:
        path.write_text(text, encoding="utf-8")
        return path
    raw = path.with_name(path.name[:-4] + ".src")
    raw.write_text(text, encoding="utf-8")
    subprocess.run(["zstd", "-q", "-f", str(raw), "-o", str(path)], check=True)
    raw.unlink()
    return path


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.sessions = self.d / "sessions" / "2026" / "10" / "16"
        self.t0 = int(time.time()) - 3 * 86400
        self._orig = (scan.SOURCES, scan.CACHE, scan.LOCAL_CFG, scan._ZSTD)
        codex = next(x for x in scan.SOURCES if x["key"] == "codex")
        scan.SOURCES = (dict(codex, root=self.d / "sessions"),)      # 单元素：其余源根本不存在
        scan.CACHE = self.d / "cache.json"                            # 不碰真实缓存
        scan.LOCAL_CFG = self.d / "sources.local.json"
        self.addCleanup(self._restore)

    def _restore(self):
        scan.SOURCES, scan.CACHE, scan.LOCAL_CFG, scan._ZSTD = self._orig

    def total(self, **kw):
        out, st = scan.scan(days=30, **kw)
        self.assertLessEqual(set(out), {"codex"}, "隔离没生效")
        return sum(b["total"] for b in out.get("codex", {}).get("days", {}).values()), st


@unittest.skipUnless(HAVE_ZSTD, "需要 zstd 命令行")
class TheZstParsesExactlyLikeThePlainFile(_Fixture):
    def test_same_rows(self):
        text = _rollout_text(self.t0)
        a = _write(self.sessions / "rollout-a.jsonl", text)
        b = _write(self.d / "other" / "rollout-a.jsonl.zst", text, compress=True)
        ra, rb = scan._scan_codex_file(a), scan._scan_codex_file(b)
        self.assertTrue(ra, "夹具没解析出任何行 —— 这条断言没在验东西")
        self.assertEqual(ra, rb, "★★★ .zst 与 .jsonl 解析结果不同")
        self.assertEqual({r[1] for r in ra}, {"gpt-5.6-sol", "gpt-5.6-luna"}, "跨行的模型状态没用上")
        self.assertEqual({r[7] for r in ra}, {"openai", "rotateproxy"}, "跨行的 provider 状态没用上")


@unittest.skipUnless(HAVE_ZSTD, "需要 zstd 命令行")
class OnlyTheTwoSuffixesAreCounted(_Fixture):
    def test_zst_is_counted(self):
        _write(self.sessions / "rollout-a.jsonl", _rollout_text(self.t0))
        plain, _ = self.total(use_cache=False)
        _write(self.sessions / "rollout-b.jsonl.zst", _rollout_text(self.t0), compress=True)
        both, _ = self.total(use_cache=False)
        self.assertGreater(plain, 0)
        self.assertEqual(both, 2 * plain, "★★★ 压缩过的会话没被计入")

    def test_backups_are_not_counted(self):
        _write(self.sessions / "rollout-a.jsonl", _rollout_text(self.t0))
        base, _ = self.total(use_cache=False)
        _write(self.sessions / "rollout-c.jsonl.bak-namespace", _rollout_text(self.t0))
        _write(self.sessions / "rollout-d.jsonl.bak-namespace2", _rollout_text(self.t0))
        after, _ = self.total(use_cache=False)
        self.assertEqual(after, base, "★★ .bak-namespace* 备份被扫进来了")

    def test_a_pair_counts_once(self):
        text = _rollout_text(self.t0)
        _write(self.sessions / "rollout-a.jsonl", text)
        once, _ = self.total(use_cache=False)
        _write(self.sessions / "rollout-a.jsonl.zst", text, compress=True)
        pair, _ = self.total(use_cache=False)
        self.assertEqual(pair, once, "★★ 同名 .jsonl 与 .jsonl.zst 都算了一遍")


class AReadFailureIsNotZero(_Fixture):
    def test_broken_zst_is_reported_and_not_cached(self):
        bad = self.sessions / "rollout-bad.jsonl.zst"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"\x28\xb5\x2f\xfd not really zstd")
        scan._ZSTD = str(self.d / "no-such-zstd")
        _, st = self.total(use_cache=True)
        self.assertGreaterEqual(st["read_failed"], 1, "★★★ 解压失败没进 read_failed —— 少算一个会话却零报错")
        cached = json.loads(scan.CACHE.read_text(encoding="utf-8")).get("files", {}) if scan.CACHE.exists() else {}
        self.assertNotIn(str(bad), cached, "★★★ 读失败的文件进了缓存 —— 0 token 被签名钉死")

    @unittest.skipUnless(HAVE_ZSTD, "需要 zstd 命令行")
    def test_corrupt_zst_with_a_real_zstd_raises(self):
        bad = self.d / "rollout-bad.jsonl.zst"
        bad.write_bytes(b"\x28\xb5\x2f\xfd not really zstd")
        with self.assertRaises(scan.ScanReadError, msg="★★ zstd 退出码非 0 被当成了空文件"):
            scan._scan_codex_file(bad)

    def test_unopenable_jsonl_raises(self):
        with self.assertRaises(scan.ScanReadError):
            scan._scan_codex_file(self.d / "missing" / "rollout-x.jsonl")

    def test_dsh_decompress_failure_raises(self):
        scan._ZSTD = str(self.d / "no-such-zstd")
        f = self.d / "session.jsonl.zstd"
        f.write_bytes(b"junk")
        with self.assertRaises(scan.ScanReadError, msg="★★ dsh 解压失败又变回静默 0 行"):
            scan._scan_dsh_file(f)


if __name__ == "__main__":
    unittest.main()
