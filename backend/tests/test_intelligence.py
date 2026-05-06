import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now
from app.services.intelligence import score_opportunity_match


class TestIntelligence(unittest.TestCase):
    def test_cold_start_profile_uses_onboarding_signals(self) -> None:
        profile = SimpleNamespace(
            skills="",
            interests="",
            education="",
            achievements="",
            bio="",
            domain="Frontend Engineering",
            course="BTech Computer Science",
            course_specialization="Web Development",
            current_job_role="",
            experience_summary="",
            preferred_roles="Frontend Developer",
            preferred_locations="Remote",
            user_type="college_student",
            account_type="candidate",
            goals=["internships", "open source"],
        )
        opportunity = SimpleNamespace(
            title="Frontend Internship Program",
            description="Build React interfaces and work on UI performance.",
            domain="Frontend Engineering",
            opportunity_type="Internship",
            university="Example Org",
            deadline=utc_now() + timedelta(days=12),
        )

        score, reasons = score_opportunity_match(profile, opportunity)

        self.assertGreater(score, 0.0)
        self.assertTrue(any("onboarding profile signals" in reason.lower() for reason in reasons))

    def test_empty_profile_still_surfaces_evergreen_programs(self) -> None:
        profile = SimpleNamespace(
            skills="",
            interests="",
            education="",
            achievements="",
            bio="",
            domain="",
            course="",
            course_specialization="",
            current_job_role="",
            experience_summary="",
            preferred_roles="",
            preferred_locations="",
            user_type="",
            account_type="candidate",
            goals=[],
        )
        opportunity = SimpleNamespace(
            title="Google Summer of Code 2026",
            description="Open source mentorship program for contributors worldwide.",
            domain="Open Source",
            opportunity_type="Program",
            university="Google",
            deadline=utc_now() + timedelta(days=30),
        )

        score, reasons = score_opportunity_match(profile, opportunity)

        self.assertGreaterEqual(score, 30.0)
        self.assertTrue(any("evergreen" in reason.lower() for reason in reasons))


if __name__ == "__main__":
    unittest.main()
