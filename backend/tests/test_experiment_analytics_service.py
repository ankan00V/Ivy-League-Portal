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
from app.services.experiment_analytics_service import ExperimentAnalyticsService, VariantCounts, VariantMetricCounts
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

    async def test_results_returns_dashboard_metrics_and_graduation_recommendation(self) -> None:
        experiment = SimpleNamespace(
            key="ranking_mode",
            name="Ranking Mode",
            description="Ranking experiment",
            status="running",
            primary_metric="ctr",
            min_sample_size=100,
            guardrail_metrics=["apply_rate"],
            variants=[
                ExperimentVariant(name="baseline", weight=1.0, ranking_mode="baseline", is_control=True),
                ExperimentVariant(name="ml", weight=1.0, ranking_mode="ml", is_control=False),
            ],
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        service = ExperimentAnalyticsService()

        with patch.object(
            service,
            "report",
            new=AsyncMock(
                return_value={
                    "status": "running",
                    "comparisons": [
                        {
                            "control": "baseline",
                            "variant": "ml",
                            "p_value": 0.01,
                            "lift": 0.08,
                        }
                    ],
                    "diagnostics": {"guardrails": {"triggered_reasons": []}},
                }
            ),
        ), patch.object(
            service,
            "_metrics_by_variant",
            new=AsyncMock(
                return_value={
                    "baseline": VariantMetricCounts(
                        impressions=200,
                        clicks=20,
                        saves=6,
                        applies=4,
                        dwell_time_ms_total=100_000,
                        dwell_count=10,
                        event_count=260,
                        session_count=50,
                    ),
                    "ml": VariantMetricCounts(
                        impressions=200,
                        clicks=28,
                        saves=8,
                        applies=5,
                        dwell_time_ms_total=120_000,
                        dwell_count=12,
                        event_count=290,
                        session_count=55,
                    ),
                }
            ),
        ):
            result = await service.results(experiment=experiment, days=14, traffic_type="real")

        self.assertEqual(result["experiment_id"], "ranking_mode")
        self.assertEqual(result["variants"][0]["ctr"], 0.1)
        self.assertEqual(result["variants"][1]["ctr"], 0.14)
        self.assertEqual(result["traffic_allocation"]["total_impressions"], 400)
        self.assertEqual(result["recommendation"]["winning_variant"], "ml")
        self.assertTrue(result["recommendation"]["ready_for_graduation"])

    async def test_maybe_graduate_persists_winner_when_guardrails_pass(self) -> None:
        saved = {"called": False}

        async def save() -> None:
            saved["called"] = True

        experiment = SimpleNamespace(
            key="ranking_mode",
            name="Ranking Mode",
            description="Ranking experiment",
            status="running",
            primary_metric="ctr",
            min_sample_size=100,
            guardrail_metrics=[],
            variants=[
                ExperimentVariant(name="baseline", weight=1.0, ranking_mode="baseline", is_control=True),
                ExperimentVariant(name="ml", weight=1.0, ranking_mode="ml", is_control=False),
            ],
            graduation_history=[],
            created_at=utc_now(),
            updated_at=utc_now(),
            save=save,
        )
        service = ExperimentAnalyticsService()

        with patch.object(
            service,
            "results",
            new=AsyncMock(
                return_value={
                    "primary_metric": "ctr",
                    "recommendation": {
                        "code": "significant_lift_consider_graduating",
                        "winning_variant": "ml",
                        "ready_for_graduation": True,
                    },
                }
            ),
        ):
            result = await service.maybe_graduate(experiment=experiment, days=14, traffic_type="real")

        self.assertTrue(result["graduated"])
        self.assertEqual(experiment.status, "concluded")
        self.assertEqual(experiment.default_variant, "ml")
        self.assertEqual(experiment.winning_variant, "ml")
        self.assertTrue(saved["called"])

    async def test_session_depth_primary_metric_requires_manual_graduation(self) -> None:
        experiment = SimpleNamespace(
            key="session_depth_exp",
            status="running",
            primary_metric="session_depth",
            min_sample_size=100,
            variants=[
                ExperimentVariant(name="baseline", weight=1.0, is_control=True),
                ExperimentVariant(name="treatment", weight=1.0, is_control=False),
            ],
        )
        service = ExperimentAnalyticsService()
        recommendation = service._recommendation(
            experiment=experiment,
            report={
                "comparisons": [{"variant": "treatment", "p_value": 0.01, "lift": 0.2}],
                "diagnostics": {"guardrails": {"triggered_reasons": []}},
            },
            variant_metrics=[
                {"name": "baseline", "sample_size": 200},
                {"name": "treatment", "sample_size": 200},
            ],
        )

        self.assertEqual(recommendation["code"], "manual_review_required_non_proportion_metric")
        self.assertFalse(recommendation["ready_for_graduation"])


if __name__ == "__main__":
    unittest.main()
