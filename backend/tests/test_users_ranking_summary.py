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

    def test_onboarding_requires_resume_for_college_student(self) -> None:
        profile = SimpleNamespace(
            account_type="candidate",
            first_name="A",
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
            resume_url=None,
            company_name=None,
            hiring_for=None,
        )
        completed, _progress, missing, _next = users_endpoint._compute_onboarding_status(profile)
        self.assertFalse(completed)
        self.assertIn("resume", missing)

    def test_profile_update_normalizes_educator_to_professional(self) -> None:
        payload = users_endpoint.ProfileUpdate(user_type="educator")
        self.assertEqual(payload.user_type, "professional")

    def test_profile_strength_includes_missing_signal_details(self) -> None:
        profile = SimpleNamespace(
            account_type="candidate",
            first_name="Ankan",
            last_name="",
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
            bio="",
            skills="python",
            interests="",
            education="",
            resume_url=None,
            company_name=None,
            hiring_for=None,
            company_website=None,
            company_description=None,
        )
        summary = users_endpoint._build_profile_strength_summary(profile)
        self.assertTrue(any(item.key == "resume" for item in summary.missing_signal_details))
        self.assertTrue(any(item.key == "last_name" for item in summary.missing_signal_details))

    def test_apply_parsed_resume_signals_autofills_profile(self) -> None:
        profile = SimpleNamespace(
            account_type="candidate",
            user_type=None,
            domain=None,
            course=None,
            passout_year=None,
            college_name=None,
            current_job_role=None,
            total_work_experience=None,
            skills="Python",
            education=None,
            company_name=None,
        )
        parsed = {
            "skills": ["SQL", "Python", "Machine Learning"],
            "education": "B.Tech in CSE | Lovely Professional University",
            "inferred_domain": "Data Science",
            "course": "B.Tech",
            "college_name": "Lovely Professional University",
            "passout_year": 2027,
            "current_job_role": "Data Scientist",
            "years_of_experience": 1.5,
            "user_type_hint": "educator",
        }

        users_endpoint._apply_parsed_resume_signals(profile=profile, parsed_data=parsed)
        self.assertEqual(profile.user_type, "professional")
        self.assertEqual(profile.domain, "Data Science")
        self.assertEqual(profile.course, "B.Tech")
        self.assertEqual(profile.passout_year, 2027)
        self.assertEqual(profile.college_name, "Lovely Professional University")
        self.assertEqual(profile.current_job_role, "Data Scientist")
        self.assertEqual(profile.total_work_experience, "1.5 years")
        self.assertIn("Machine Learning", profile.skills)
        self.assertIn("Lovely Professional University", profile.education)


if __name__ == "__main__":
    unittest.main()
