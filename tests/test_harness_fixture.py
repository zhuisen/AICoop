"""harness 固定夹具（`codexbar/uishot/fixture/` + `fixture_tool.py`，2026-10-23）。

用户「CI 跑 UI 闸」+ 本机 UI 闸随真实数据漂（一轮里 3 条红与代码无关）。守四件事：
① 夹具里没有能认人的东西（入库、会公开）；② 日期平移到「现在」，过多久都不冻；
③ 平移不碰 token 计数（用量快照里有落在 epoch 量级的计数）；④ harness 默认读夹具，不读本机真实数据。
"""
import datetime
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UISHOT = ROOT / "codexbar" / "uishot"
sys.path.insert(0, str(UISHOT))
import fixture_tool as FT  # noqa: E402

TEN_DAYS = 10 * 86400


def _raw(p):
    return json.loads(p.read_text())


class TheFixtureCarriesNoIdentity(unittest.TestCase):
    def test_no_real_ids_emails_or_paths(self):
        body = FT.STATE.read_text() + FT.TRAFFIC.read_text()
        self.assertIsNone(FT._UUID.search(body), "真实 account_id（UUID）进了夹具")
        self.assertIsNone(FT._CARD.search(body), "服务端的卡片 id 进了夹具")
        self.assertEqual(set(re.findall(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", body)) - {"example.com"}, set(), "真实邮箱域名")
        self.assertNotIn("/Users/", body)
        for k in FT.DROP_KEYS:
            self.assertNotIn('"%s":' % k, FT.STATE.read_text(), "state 里不该再有 %s" % k)

    def test_the_anonymizer_catches_what_it_claims(self):
        """反向：已知阳性必须被换掉（扫描器 0 命中 ≠ 干净）。"""
        real = "1db43c75-40f5-4572-89d6-8c5926fe2711"
        out = FT._anonymize({real: {"email": "a.b@gmail.com", "id": "RateLimitResetCredit_" + "ab" * 16,
                                    "name": "X", "pinned": [real]}}, {}, FT.DROP_KEYS)
        s = json.dumps(out)
        self.assertNotIn(real, s)
        self.assertNotIn("gmail", s)
        self.assertNotIn("abababab", s)
        self.assertNotIn('"name"', s)
        k = next(iter(out))
        self.assertEqual(out[k]["pinned"], [k], "同一个真值必须映射到同一个假值（键与值对得上）")


class DatesFollowTheClock(unittest.TestCase):
    def setUp(self):
        self.s0, self.t0 = _raw(FT.STATE), _raw(FT.TRAFFIC)
        self.now = self.s0["_anchor"] + TEN_DAYS

    def test_state_times_move_with_now(self):
        st = FT.load_state(self.now)
        a, b = self.s0["slots"], st["slots"]
        self.assertEqual(set(a), set(b))
        moved = 0
        for aid in a:
            qa, qb = a[aid].get("quota") or {}, b[aid].get("quota") or {}
            if qa.get("captured_at"):
                self.assertAlmostEqual(qb["captured_at"] - qa["captured_at"], TEN_DAYS, delta=1)
                self.assertEqual(qa.get("primary", {}).get("used_percent"), qb.get("primary", {}).get("used_percent"))
                moved += 1
            for ca, cb in zip((a[aid].get("credits_detail") or {}).get("credits") or [],
                              (b[aid].get("credits_detail") or {}).get("credits") or []):
                ta = datetime.datetime.fromisoformat(ca["expires_at"].replace("Z", "+00:00"))
                tb = datetime.datetime.fromisoformat(cb["expires_at"].replace("Z", "+00:00"))
                self.assertAlmostEqual((tb - ta).total_seconds(), TEN_DAYS, delta=1)
        self.assertGreater(moved, 0, "★ 夹具里没有带 captured_at 的额度 —— 闸没有判别力")

    def test_traffic_days_end_today_and_tokens_are_untouched(self):
        tr = FT.load_traffic(self.now)
        today = datetime.date.fromtimestamp(self.now).isoformat()
        for k, p in tr["platforms"].items():
            days = sorted((p.get("days") or {}).keys())
            if days:
                self.assertLessEqual(days[-1], today, k)
        old = sorted(self.t0["platforms"]["claude"]["days"].items())
        new = sorted(tr["platforms"]["claude"]["days"].items())
        self.assertEqual([v["total"] for _, v in old], [v["total"] for _, v in new],
                         "★ token 计数被当成时刻挪了（cache_read 实测落在 epoch 量级）")
        last_old = datetime.date.fromisoformat(old[-1][0])
        self.assertEqual(datetime.date.fromisoformat(new[-1][0]) - last_old, datetime.timedelta(days=10))
        self.assertEqual(tr["generated_at"], int(self.now), "快照按「刚生成」算")


class TheHarnessReadsTheFixtureByDefault(unittest.TestCase):
    def test_wiring(self):
        src = (UISHOT / "make_harness.py").read_text()
        self.assertIn('REAL = os.environ.get("CODEXBAR_HARNESS_REAL") == "1"', src)
        self.assertIn('json.loads((REPO / "state.json").read_text()) if REAL else fixture_tool.load_state()', src)
        self.assertIn("SNAP.read_text() if SNAP else json.dumps(fixture_tool.load_traffic())", src)


if __name__ == "__main__":
    unittest.main()
