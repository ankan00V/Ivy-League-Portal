import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import users as users_endpoint


class TestUserRankingSummary(unittest.TestCase):
    def test_compute_rank_stats_top_user(self) -> None:
        top_percent, percentile = users_endpoint._compute_rank_stats(rank=1, total_users=250)
        self.assertEqual(top_percent, 0.4)
        self.assertEqual(percentile, 99.6)

    def test_compute_rank_stats_tail_user(self) -> None:
        top_percent, percentile = users_endpoint._compute_rank_stats(rank=250, total_users=250)
        self.assertEqual(top_percent, 100.0)
        self.assertEqual(percentile, 0.0)

    def test_normalize_account_scope_defaults_to_candidate(self) -> None:
        self.assertEqual(users_endpoint._normalize_account_scope(None), "candidate")
        self.assertEqual(users_endpoint._normalize_account_scope("candidate"), "candidate")
        self.assertEqual(users_endpoint._normalize_account_scope("anything"), "candidate")
        self.assertEqual(users_endpoint._normalize_account_scope("employer"), "employer")


if __name__ == "__main__":
    unittest.main()
