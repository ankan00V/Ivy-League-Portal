import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

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

    def test_profile_strength_candidate_recommends_resume_when_missing(self) -> None:
        profile = SimpleNamespace(
            account_type="candidate",
            first_name="Ankan",
            last_name="Ghosh",
            mobile="9000000000",
            consent_data_processing=True,
            user_type="college_student",
            class_grade=None,
            domain="Engineering",
            course="B.Tech",
            passout_year=2027,
            college_name="LPU",
            current_job_role=None,
            total_work_experience=None,
            bio="ML builder",
            skills="python,fastapi",
            interests="ai",
            education="B.Tech",
            resume_url="",
            company_name=None,
            hiring_for=None,
            company_website=None,
            company_description=None,
        )
        summary = users_endpoint._build_profile_strength_summary(profile)
        self.assertLess(summary.strength_percent, 100)
        self.assertIn("resume", summary.missing_signals)
        self.assertIn("resume", summary.recommendation.lower())

    def test_profile_strength_employer_counts_company_fields(self) -> None:
        profile = SimpleNamespace(
            account_type="employer",
            first_name="A",
            last_name="B",
            mobile="9000000000",
            consent_data_processing=True,
            user_type=None,
            class_grade=None,
            domain=None,
            course=None,
            passout_year=None,
            college_name=None,
            current_job_role="Recruitment Manager",
            total_work_experience=None,
            bio=None,
            skills=None,
            interests=None,
            education=None,
            resume_url=None,
            company_name="Acme",
            hiring_for="myself",
            company_website="https://acme.example",
            company_description="Campus hiring",
        )
        summary = users_endpoint._build_profile_strength_summary(profile)
        self.assertEqual(summary.account_scope, "employer")
        self.assertEqual(summary.strength_percent, 100)
        self.assertEqual(summary.missing_signals, [])


if __name__ == "__main__":
    unittest.main()
