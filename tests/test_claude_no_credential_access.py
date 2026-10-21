"""★★★ 红线（P3b 设计第 0 层闸 G1，2026-10-22）：仓库代码不碰 Claude 的凭证。

Claude Code 的条款写明不得「collect, store, or intermediate Claude.ai credentials」，Consumer Terms §3
另禁自动化访问。所以 Claude 档只读（额度走状态栏转写，`traffic/statusline_quota.py`），**不照 agy 的做法
改写钥匙串单槽切号**：那会让本机所有常驻 `claude` 进程在下次刷新 token 时换身份（与 agy 常驻进程抢槽同族）。
设计与风险全文：`scratch/aicoop_20261021/P3b_claude_pool_design.md`（gitignored）。

判据打在代码形态上：扫描所有受版本控制的非文档文件（本文件除外），任何一条命中即红。
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

#: (名字, 正则, 只在同一行还出现 claude/anthropic 时才算)
RULES = (
    ("钥匙串条目名", re.compile(r"Claude Code-credentials"), False),
    ("钥匙串读写", re.compile(r"(find|add|delete)-generic-password"), True),
    ("凭证文件", re.compile(r"\.credentials\.json"), False),
    ("OAuth 端点", re.compile(r"api/oauth"), False),
    ("令牌变量赋值", re.compile(r"\b(ANTHROPIC_AUTH_TOKEN|CLAUDE_CODE_OAUTH_TOKEN)\b\s*[:=]|"
                          r"\[\s*[\"'](ANTHROPIC_AUTH_TOKEN|CLAUDE_CODE_OAUTH_TOKEN)[\"']\s*\]\s*="), False),
    ("回环 BASE_URL", re.compile(r"ANTHROPIC_BASE_URL[\"']?\s*[:=,]\s*[\"']?https?://(127\.0\.0\.1|localhost|\[::1\])"), False),
    # ★ 阶段 4 评审补的四条（codex 实测漏检）：拼接出来的条目名 / 文件名、整串导出钥匙串、令牌变量的任何引用。
    ("钥匙串条目名（拼接）", re.compile(r"[\"']Claude Code-[\"']|[\"']Code-credentials[\"']"), False),
    ("凭证文件（拼接）", re.compile(r"[\"']\.credentials[\"']"), False),
    ("钥匙串导出", re.compile(r"(dump|export)-keychain"), False),
    # 这两个令牌在本仓没有任何合法用途 ⇒ 出现即红（含 env.update / os.putenv / 字典初始化）。
    ("令牌变量引用", re.compile(r"\b(ANTHROPIC_AUTH_TOKEN|CLAUDE_CODE_OAUTH_TOKEN)\b"), False),
)
CLAUDE = re.compile(r"claude|anthropic", re.I)
SKIP_SUFFIX = (".md", ".png", ".svg", ".icns", ".jpg", ".woff2", ".lock")


def hits(text):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for name, rx, need in RULES:
            if rx.search(line) and (not need or CLAUDE.search(line)):
                out.append((name, n, line.strip()[:120]))
    return out


def tracked():
    r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    for rel in r.stdout.splitlines():
        p = ROOT / rel
        if p.resolve() == SELF or rel.endswith(SKIP_SUFFIX) or not p.is_file():
            continue
        yield rel, p


class NoClaudeCredentialAccess(unittest.TestCase):
    def test_the_repo_never_touches_claude_credentials(self):
        bad = []
        n = 0
        for rel, p in tracked():
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            n += 1
            bad += [(rel, *h) for h in hits(text)]
        self.assertGreater(n, 100, "扫到的文件太少 —— 闸没在扫仓库")
        self.assertEqual(bad, [], "★★★ 仓库代码碰了 Claude 凭证（条款红线，见模块 docstring）")

    def test_every_rule_fires_on_a_known_positive(self):
        """已知阳性：每条规则各自能响（防「正则写错、一次都没命中过」）。"""
        cases = {
            "钥匙串条目名": 'svc = "Claude Code-credentials"',
            "钥匙串读写": 'run(["security", "find-generic-password", "-s", "claude"])',
            "凭证文件": "p = home / '.claude' / '.credentials.json'",
            "OAuth 端点": 'url = "https://api.anthropic.com/api/oauth/usage"',
            "令牌变量赋值": 'env["CLAUDE_CODE_OAUTH_TOKEN"] = tok',
            "回环 BASE_URL": 'ANTHROPIC_BASE_URL="http://127.0.0.1:8012"',
            "钥匙串条目名（拼接）": 'svc = "Claude Code-" + "credentials"',
            "凭证文件（拼接）": 'p = home / ".claude" / (".credentials" + ".json")',
            "钥匙串导出": 'run(["security", "dump-keychain", "-d"])',
            "令牌变量引用": 'env.update({"CLAUDE_CODE_OAUTH_TOKEN": tok})',
        }
        for name, line in cases.items():
            with self.subTest(rule=name):
                self.assertIn(name, [h[0] for h in hits(line)])

    def test_agys_own_keychain_access_is_not_flagged(self):
        """反向：agy 自己的钥匙串读写（`agy/pool.py`）不是 Claude 的，不能假红。"""
        self.assertEqual(hits('["security", "find-generic-password", "-s", KEYRING_SVC, "-a", KEYRING_ACCT, "-w"]'), [])


if __name__ == "__main__":
    unittest.main()
