import unittest
from datetime import datetime
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.recommendation_service import RecommendationService
from app.core.time import utc_now


class TestRecommendationService(unittest.IsolatedAsyncioTestCase):
    async def test_semantic_ranking_prefers_top_vector_match(self) -> None:
        service = RecommendationService()
        user_id = "user-1"
        profile = SimpleNamespace(
            user_id=user_id,
            bio="",
            skills="react typescript accessibility",
            interests="frontend performance",
            education="",
            achievements="",
        )
        opportunities = [
            SimpleNamespace(
                id="opp-frontend",
                title="Accessibility Performance Residency",
                description="Improve core web vitals and accessibility systems.",
                url="https://example.com/frontend",
                domain="Software",
                opportunity_type="Residency",
                university="Lab",
                deadline=None,
                created_at=utc_now(),
                updated_at=utc_now(),
                last_seen_at=utc_now(),
            ),
            SimpleNamespace(
                id="opp-backend",
                title="Generic Backend Internship",
                description="Forms and dashboards for internal tools.",
                url="https://example.com/backend",
                domain="Software",
                opportunity_type="Internship",
                university="Company",
                deadline=None,
                created_at=utc_now(),
                updated_at=utc_now(),
                last_seen_at=utc_now(),
            ),
        ]

        with (
            patch("app.services.recommendation_service.ranking_model_service.get_active", new=AsyncMock(return_value=type("ActiveModel", (), {
                "model_version_id": "model-123",
                "weights": {"semantic": 0.6, "baseline": 0.25, "behavior": 0.15},
            })())),
            patch("app.services.recommendation_service.opportunity_vector_service.search", new=AsyncMock(return_value=[
                {"id": opportunities[0].id, "similarity": 0.94},
                {"id": opportunities[1].id, "similarity": 0.12},
            ])),
            patch.object(service, "_build_behavior_map", new=AsyncMock(return_value={"domain": {}, "type": {}})),
        ):
            ranked, meta = await service.rank(
                user_id=user_id,
                profile=profile,
                opportunities=opportunities,
                limit=2,
                ranking_mode="semantic",
                query="web performance accessibility",
            )

        self.assertEqual(ranked[0]["opportunity"].id, opportunities[0].id)
        self.assertEqual(meta["model_version_id"], "model-123")
        self.assertGreater(ranked[0]["semantic_score"], ranked[1]["semantic_score"])

    async def test_ml_mode_falls_back_for_entire_request_on_ranker_failure(self) -> None:
        service = RecommendationService()
        user_id = "user-ml-fallback"
        profile = SimpleNamespace(
            user_id=user_id,
            bio="",
            skills="python ml ranking",
            interests="recommenders",
            education="",
            achievements="",
        )
        opportunities = [
            SimpleNamespace(
                id="opp-1",
                title="Ranking Internship",
                description="Build ranking models and offline evals.",
                url="https://example.com/1",
                domain="AI/ML",
                opportunity_type="Internship",
                university="Lab",
                source="example_source",
                deadline=None,
                created_at=utc_now(),
                updated_at=utc_now(),
                last_seen_at=utc_now(),
            ),
            SimpleNamespace(
                id="opp-2",
                title="General Analytics Internship",
                description="Dashboards and KPI tracking.",
                url="https://example.com/2",
                domain="Analytics",
                opportunity_type="Internship",
                university="Org",
                source="example_source",
                deadline=None,
                created_at=utc_now(),
                updated_at=utc_now(),
                last_seen_at=utc_now(),
            ),
        ]

        with (
            patch(
                "app.services.recommendation_service.ranking_model_service.get_active",
                new=AsyncMock(
                    return_value=type(
                        "ActiveModel",
                        (),
                        {"model_version_id": "model-ml", "weights": {"semantic": 0.6, "baseline": 0.25, "behavior": 0.15}},
                    )()
                ),
            ),
            patch(
                "app.services.recommendation_service.opportunity_vector_service.search",
                new=AsyncMock(
                    return_value=[
                        {"id": opportunities[0].id, "similarity": 0.95},
                        {"id": opportunities[1].id, "similarity": 0.11},
                    ]
                ),
            ),
            patch.object(service, "_build_behavior_map", new=AsyncMock(return_value={"domain": {}, "type": {}})),
            patch("app.services.recommendation_service.learned_ranker.feature_importance", return_value=[], create=True),
            patch("app.services.recommendation_service.learned_ranker.score", return_value=None),
        ):
            ranked, meta = await service.rank(
                user_id=user_id,
                profile=profile,
                opportunities=opportunities,
                limit=2,
                ranking_mode="ml",
                query="ranking ml intern",
            )

        self.assertEqual(meta.get("fallback_reason"), "ml_model_failure")
        self.assertEqual(meta.get("mode"), "semantic")
        self.assertTrue(all(item["ranking_mode"] == "semantic" for item in ranked))
        self.assertTrue(
            all(
                any("heuristic blend fallback" in reason.lower() for reason in item["match_reasons"])
                for item in ranked
            )
        )

    async def test_semantic_mode_applies_user_trained_adaptive_filter(self) -> None:
        service = RecommendationService()
        user_id = "user-adaptive-filter"
        profile = SimpleNamespace(
            user_id=user_id,
            bio="",
            skills="python ml ranking",
            interests="recommenders",
            education="",
            achievements="",
        )
        opportunities = [
            SimpleNamespace(
                id="opp-high",
                title="High Match Internship",
                description="Build ranking systems with Python and ML.",
                url="https://example.com/high",
                domain="AI/ML",
                opportunity_type="Internship",
                university="Lab",
                source="example_source",
                deadline=None,
                created_at=utc_now(),
                updated_at=utc_now(),
                last_seen_at=utc_now(),
            ),
            SimpleNamespace(
                id="opp-low",
                title="Low Match Internship",
                description="General office internship role.",
                url="https://example.com/low",
                domain="General",
                opportunity_type="Internship",
                university="Org",
                source="example_source",
                deadline=None,
                created_at=utc_now(),
                updated_at=utc_now(),
                last_seen_at=utc_now(),
            ),
        ]

        def _mock_baseline_score(profile_arg, opportunity_arg):  # noqa: ANN001
            if opportunity_arg.id == "opp-high":
                return 92.0, ["Strong profile fit."]
            return 12.0, ["Weak fit."]

        with (
            patch(
                "app.services.recommendation_service.ranking_model_service.get_active",
                new=AsyncMock(
                    return_value=type(
                        "ActiveModel",
                        (),
                        {"model_version_id": "model-adaptive", "weights": {"semantic": 0.6, "baseline": 0.25, "behavior": 0.15}},
                    )()
                ),
            ),
            patch(
                "app.services.recommendation_service.opportunity_vector_service.search",
                new=AsyncMock(
                    return_value=[
                        {"id": opportunities[0].id, "similarity": 0.95},
                        {"id": opportunities[1].id, "similarity": 0.11},
                    ]
                ),
            ),
            patch("app.services.recommendation_service.score_opportunity_match", side_effect=_mock_baseline_score),
            patch.object(service, "_build_behavior_map", new=AsyncMock(return_value={"domain": {}, "type": {}})),
            patch.object(
                service,
                "_learn_user_filter_threshold",
                new=AsyncMock(
                    return_value={
                        "enabled": True,
                        "threshold": 70.0,
                        "trained_on_impressions": 120,
                        "positives": 18,
                        "negatives": 102,
                        "lookback_days": 120,
                        "label_window_hours": 72,
                    }
                ),
            ),
        ):
            ranked, meta = await service.rank(
                user_id=user_id,
                profile=profile,
                opportunities=opportunities,
                limit=5,
                ranking_mode="semantic",
                min_score=0.0,
                query="ml ranking systems",
            )

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["opportunity"].id, "opp-high")
        self.assertEqual(meta.get("adaptive_filter", {}).get("enabled"), True)
        self.assertEqual(meta.get("adaptive_filter", {}).get("applied"), True)
        self.assertEqual(meta.get("adaptive_filter", {}).get("effective_min_score"), 70.0)

    async def test_ml_rollout_control_cohort_serves_semantic_and_shadows_top_candidates(self) -> None:
        service = RecommendationService()
        user_id = "user-rollout-control"
        profile = SimpleNamespace(
            user_id=user_id,
            bio="",
            skills="python ml ranking",
            interests="recommenders",
            education="",
            achievements="",
        )
        opportunities = [
            SimpleNamespace(
                id="opp-1",
                title="Ranking Internship",
                description="Build ranking models and offline evals.",
                url="https://example.com/1",
                domain="AI/ML",
                opportunity_type="Internship",
                university="Lab",
                source="example_source",
                deadline=None,
                created_at=utc_now(),
                updated_at=utc_now(),
                last_seen_at=utc_now(),
            ),
            SimpleNamespace(
                id="opp-2",
                title="General Analytics Internship",
                description="Dashboards and KPI tracking.",
                url="https://example.com/2",
                domain="Analytics",
                opportunity_type="Internship",
                university="Org",
                source="example_source",
                deadline=None,
                created_at=utc_now(),
                updated_at=utc_now(),
                last_seen_at=utc_now(),
            ),
        ]
        rollout_decision = SimpleNamespace(
            requested_mode="ml",
            primary_mode="semantic",
            baseline_mode="semantic",
            rollout_key="learned_ranker_rollout",
            rollout_variant="semantic",
            rollout_bucket=4242,
            rollout_percent=25,
            in_cohort=False,
        )
        ranker_result = SimpleNamespace(score=0.93, model="ranker-v2")

        with (
            patch(
                "app.services.recommendation_service.ranking_model_service.get_active",
                new=AsyncMock(
                    return_value=type(
                        "ActiveModel",
                        (),
                        {"model_version_id": "model-rollout", "weights": {"semantic": 0.6, "baseline": 0.25, "behavior": 0.15}},
                    )()
                ),
            ),
            patch(
                "app.services.recommendation_service.opportunity_vector_service.search",
                new=AsyncMock(
                    return_value=[
                        {"id": opportunities[0].id, "similarity": 0.91},
                        {"id": opportunities[1].id, "similarity": 0.33},
                    ]
                ),
            ),
            patch.object(service, "_build_behavior_map", new=AsyncMock(return_value={"domain": {}, "type": {}, "stats": {}})),
            patch.object(service, "_learn_user_filter_threshold", new=AsyncMock(return_value=None)),
            patch("app.services.recommendation_service.learned_ranker_rollout_service.resolve", return_value=rollout_decision),
            patch("app.services.recommendation_service.learned_ranker_rollout_service.should_shadow", return_value=True),
            patch("app.services.recommendation_service.learned_ranker.feature_importance", return_value=[], create=True),
            patch("app.services.recommendation_service.learned_ranker.score", return_value=ranker_result),
            patch("app.services.recommendation_service.settings.LEARNED_RANKER_SHADOW_MAX_CANDIDATES", 1),
        ):
            ranked, meta = await service.rank(
                user_id=user_id,
                profile=profile,
                opportunities=opportunities,
                limit=2,
                ranking_mode="ml",
                query="ranking ml intern",
            )

        self.assertEqual(meta.get("mode"), "semantic")
        self.assertEqual(meta.get("requested_mode"), "ml")
        self.assertEqual(meta.get("rollout", {}).get("variant"), "semantic")
        self.assertEqual(meta.get("shadow", {}).get("candidate_limit"), 1)
        self.assertEqual(meta.get("shadow", {}).get("candidate_count"), 1)
        self.assertTrue(all(item["ranking_mode"] == "semantic" for item in ranked))
        self.assertTrue(
            any(
                "control cohort served heuristic ranking" in reason.lower()
                for item in ranked
                for reason in item["match_reasons"]
            )
        )


if __name__ == "__main__":
    unittest.main()
