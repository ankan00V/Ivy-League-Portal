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
from app.core.time import utc_now


class TestExperimentAnalyticsService(unittest.IsolatedAsyncioTestCase):
    async def test_report_builds_variant_comparison_payload(self) -> None:
        experiment = SimpleNamespace(
            key="ranking_mode",
            status="active",
            variants=[
                ExperimentVariant(name="baseline", weight=1.0, is_control=True),
                ExperimentVariant(name="ml", weight=1.0, is_control=False),
            ],
            created_at=utc_now(),
            updated_at=utc_now(),
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
        self.assertIn("diagnostics", report)
        self.assertIn("srm", report["diagnostics"])
        self.assertTrue(report["diagnostics"]["srm"]["eligible"])
        self.assertIn("power", report["comparisons"][0])
        self.assertTrue(report["comparisons"][0]["power"]["eligible"])
        self.assertIn("sample_size_gate", report["comparisons"][0])
        self.assertIn("lift_label", report["comparisons"][0])

    async def test_report_srm_handles_no_impressions(self) -> None:
        experiment = SimpleNamespace(
            key="ranking_mode",
            status="active",
            variants=[
                ExperimentVariant(name="baseline", weight=1.0, is_control=True),
                ExperimentVariant(name="semantic", weight=1.0, is_control=False),
            ],
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        service = ExperimentAnalyticsService()

        with patch.object(
            service,
            "_counts_by_variant",
            new=AsyncMock(
                return_value={
                    "baseline": VariantCounts(impressions=0, conversions=0),
                    "semantic": VariantCounts(impressions=0, conversions=0),
                }
            ),
        ):
            report = await service.report(experiment=experiment, days=14, conversion_types=("click",))

        self.assertFalse(report["diagnostics"]["srm"]["eligible"])
        self.assertEqual(report["diagnostics"]["srm"]["reason"], "no_impressions")

    async def test_report_guardrails_flag_significant_regression(self) -> None:
        experiment = SimpleNamespace(
            key="ranking_mode",
            status="active",
            variants=[
                ExperimentVariant(name="baseline", weight=1.0, is_control=True),
                ExperimentVariant(name="ml", weight=1.0, is_control=False),
            ],
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        service = ExperimentAnalyticsService()

        with patch.object(
            service,
            "_counts_by_variant",
            new=AsyncMock(
                return_value={
                    "baseline": VariantCounts(impressions=400, conversions=120),
                    "ml": VariantCounts(impressions=400, conversions=70),
                }
            ),
        ):
            report = await service.report(experiment=experiment, days=14, conversion_types=("click",))

        self.assertIn("guardrails", report["diagnostics"])
        self.assertTrue(report["diagnostics"]["guardrails"]["should_pause"])
        self.assertIn("significant_regression", report["diagnostics"]["guardrails"]["triggered_reasons"])

    async def test_report_labels_insufficient_power_when_sample_size_gate_fails(self) -> None:
        experiment = SimpleNamespace(
            key="ranking_mode",
            status="active",
            variants=[
                ExperimentVariant(name="baseline", weight=1.0, is_control=True),
                ExperimentVariant(name="ml", weight=1.0, is_control=False),
            ],
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        service = ExperimentAnalyticsService()

        with patch.object(
            service,
            "_counts_by_variant",
            new=AsyncMock(
                return_value={
                    "baseline": VariantCounts(impressions=40, conversions=8),
                    "ml": VariantCounts(impressions=45, conversions=12),
                }
            ),
        ):
            report = await service.report(experiment=experiment, days=14, conversion_types=("click",))

        comparison = report["comparisons"][0]
        self.assertFalse(comparison["sample_size_gate"]["eligible"])
        self.assertEqual(comparison["lift_label"], "insufficient_power")
        self.assertFalse(comparison["lift_declared"])


if __name__ == "__main__":
    unittest.main()
