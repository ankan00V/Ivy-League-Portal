import unittest
from datetime import datetime
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.experiment import ExperimentVariant
from app.services.experiment_analytics_service import ExperimentAnalyticsService, VariantCounts


class TestExperimentAnalyticsService(unittest.IsolatedAsyncioTestCase):
    async def test_report_builds_variant_comparison_payload(self) -> None:
        experiment = SimpleNamespace(
            key="ranking_mode",
            status="active",
            variants=[
                ExperimentVariant(name="baseline", weight=1.0, is_control=True),
                ExperimentVariant(name="ml", weight=1.0, is_control=False),
            ],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        service = ExperimentAnalyticsService()

        with patch.object(
            service,
            "_counts_by_variant",
            new=AsyncMock(
                return_value={
                    "baseline": VariantCounts(impressions=100, conversions=10),
                    "ml": VariantCounts(impressions=100, conversions=16),
                }
            ),
        ):
            report = await service.report(experiment=experiment, days=14, conversion_types=("click",))

        self.assertEqual(report["experiment_key"], "ranking_mode")
        self.assertEqual(len(report["variants"]), 2)
        self.assertEqual(report["comparisons"][0]["control"], "baseline")
        self.assertEqual(report["comparisons"][0]["variant"], "ml")
        self.assertGreater(report["comparisons"][0]["lift"], 0.0)


if __name__ == "__main__":
    unittest.main()
