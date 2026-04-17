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
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                last_seen_at=datetime.utcnow(),
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
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                last_seen_at=datetime.utcnow(),
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


if __name__ == "__main__":
    unittest.main()
