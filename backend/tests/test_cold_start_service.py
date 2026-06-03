import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.cold_start import cold_start_profile_builder


class TestColdStartService(unittest.TestCase):
    def test_strategy_thresholds_follow_quality_and_interaction_policy(self) -> None:
        low = cold_start_profile_builder.choose_strategy(quality_score=0.29, interaction_count=0)
        medium = cold_start_profile_builder.choose_strategy(quality_score=0.3, interaction_count=0)
        high = cold_start_profile_builder.choose_strategy(quality_score=0.71, interaction_count=0)
        mature = cold_start_profile_builder.choose_strategy(quality_score=0.1, interaction_count=10)

        self.assertEqual(low.strategy, "diversity")
        self.assertEqual(low.personalization_level, "low")
        self.assertEqual(medium.strategy, "semantic")
        self.assertEqual(medium.personalization_level, "medium")
        self.assertEqual(high.strategy, "ml")
        self.assertEqual(mature.strategy, "ml")

    def test_profile_quality_uses_enhanced_onboarding_signals(self) -> None:
        sparse = SimpleNamespace(
            domain="",
            domains_of_interest=[],
            skills="",
            career_intent=[],
            goals=[],
            opportunity_types=[],
            preferred_work_mode=None,
            work_preferences=[],
            preferred_locations="",
            expected_stipend_range=None,
            expected_stipend_min=None,
            expected_stipend_max=None,
            graduation_year=None,
            passout_year=None,
            bio="",
            interests="",
            interest_graph=[],
            course="",
            course_specialization="",
            projects="",
            education="",
        )
        rich = SimpleNamespace(
            domain="Computer Science",
            domains_of_interest=["AI", "Backend"],
            skills="Python, FastAPI, ML",
            career_intent=["internship"],
            goals=["research"],
            opportunity_types=["Internship", "Hackathon"],
            preferred_work_mode="remote",
            work_preferences=["remote"],
            preferred_locations="Bengaluru, Remote",
            expected_stipend_range="20000-40000 INR",
            expected_stipend_min=20000,
            expected_stipend_max=40000,
            graduation_year=2027,
            passout_year=None,
            bio="Builder",
            interests="AI products",
            interest_graph=["agents"],
            course="BTech",
            course_specialization="CSE",
            projects="recommendation engine",
            education="engineering",
        )

        self.assertLess(cold_start_profile_builder.quality_score(sparse), 0.3)
        self.assertGreater(cold_start_profile_builder.quality_score(rich), 0.7)


if __name__ == "__main__":
    unittest.main()
