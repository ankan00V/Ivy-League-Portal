import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now  # noqa: E402
from app.services.personalization.feature_builder import (  # noqa: E402
    DEFAULT_LEARNED_RANKER_FEATURES,
    RANKER_FEATURE_SCHEMA_VERSION,
    build_ranker_features,
)


class TestRankerFeatureBuilder(unittest.TestCase):
    def test_phase_2_3_features_are_explicit_and_schema_backed(self) -> None:
        now = utc_now()
        profile = SimpleNamespace(
            domain="Data Science",
            course="B.Tech",
            preferred_roles="ML engineer, data scientist",
            preferred_locations="Bengaluru",
            work_preferences=["remote"],
            career_intent=["machine learning"],
            skills="python, sql, machine learning",
            interests="ranking systems",
            bio="Building applied ML products.",
            passout_year=2026,
            prefer_wfh=True,
            onboarding_completed_at=now - timedelta(days=10),
        )
        opportunity = SimpleNamespace(
            title="Machine Learning Intern",
            description="Python ranking systems internship in Bengaluru.",
            url="https://example.com/ml-intern",
            domain="Data Science",
            opportunity_type="internship",
            university=None,
            source="wellfound",
            location="Bengaluru",
            work_mode="remote",
            stipend_min=20_000,
            stipend_max=25_000,
            quality_score=0.0,
            dedup_score=0.8,
            source_count=4,
            last_seen_at=now - timedelta(days=1),
            deadline=None,
        )

        features = build_ranker_features(
            profile=profile,
            opportunity=opportunity,
            semantic_score=82.0,
            skills_overlap_score=0.5,
            baseline_score=70.0,
            behavior_score=30.0,
            behavior_domain_pref=64.0,
            behavior_type_pref=40.0,
            behavior_source_pref=55.0,
            user_recent_interactions_30d=12.0,
            source_diversity_bonus=0.5,
            ctr_for_source=0.42,
            ctr_for_domain=0.31,
            now=now,
        )

        values = features.values
        self.assertEqual(RANKER_FEATURE_SCHEMA_VERSION, "ranker-features-v3")
        self.assertFalse(set(DEFAULT_LEARNED_RANKER_FEATURES) - set(values))
        self.assertEqual(values["opportunity_quality_score"], 0.0)
        self.assertEqual(values["opportunity_quality_low"], 1.0)
        self.assertAlmostEqual(values["opportunity_dedup_score"], 0.8)
        self.assertAlmostEqual(values["source_diversity_bonus"], 0.5)
        self.assertAlmostEqual(values["ctr_for_source"], 0.42)
        self.assertAlmostEqual(values["ctr_for_domain"], 0.31)
        self.assertEqual(values["pref_work_mode"], 1.0)
        self.assertEqual(values["pref_location"], 1.0)
        self.assertGreater(values["profile_completeness"], 0.8)
        self.assertEqual(values["stipend_fit_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
