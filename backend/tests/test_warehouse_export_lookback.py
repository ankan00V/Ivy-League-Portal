"""The export must honour lookback_days when it queries.

It used to accept the parameter and ignore it, so every export re-read the whole
of opportunity_interactions and feature_store_rows regardless of the window the
caller asked for. On a 300MB database that was ~218MB of egress per run - 4.4% of
a 5GB monthly allowance - for data nobody requested, immediately after the
rebuild had carefully filtered the same tables to `since`.

Nothing failed. The export produced correct output, just at many times the cost,
which is exactly why it survived: an unused parameter has no symptom until
someone reads a bandwidth bill. These tests assert the filter reaches the query.
"""

import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now
from app.services import warehouse_export_service as export_mod


class _RecordingQuery:
    """Captures the filters a find_many() call received."""

    def __init__(self, sink, model_name):
        self._sink = sink
        self._model_name = model_name

    async def to_list(self):
        return []


class _RecordingModel:
    def __init__(self, sink, name):
        self._sink = sink
        self._name = name

    def find_many(self, *filters):
        self._sink[self._name] = filters
        return _RecordingQuery(self._sink, self._name)

    # Attribute access returns a marker so `Model.field >= value` is expressible.
    def __getattr__(self, item):
        return _Field(f"{self._name}.{item}")


class _Field:
    def __init__(self, path):
        self.path = path

    def __ge__(self, other):
        return ("ge", self.path, other)

    def __eq__(self, other):  # noqa: D105
        return ("eq", self.path, other)

    def __hash__(self):
        return hash(self.path)


class TestExportHonoursLookback(unittest.IsolatedAsyncioTestCase):
    async def test_lookback_filter_is_applied_to_the_heavy_tables(self) -> None:
        sink: dict = {}
        names = [
            "OpportunityInteraction",
            "RankingRequestTelemetry",
            "FeatureStoreRow",
            "AnalyticsDailyAggregate",
            "AnalyticsFunnelAggregate",
            "AnalyticsCohortAggregate",
        ]
        patches = [
            patch.object(export_mod, name, _RecordingModel(sink, name)) for name in names
        ]
        with patch.object(export_mod.settings, "ANALYTICS_WAREHOUSE_EXPORT_ENABLED", True):
            for p in patches:
                p.start()
            try:
                # The export does far more than query; we only care that the
                # queries carried the filter, so let it fail afterwards.
                try:
                    await export_mod.warehouse_export_service.export(
                        lookback_days=7, traffic_type="real"
                    )
                except Exception:
                    pass
            finally:
                for p in patches:
                    p.stop()

        cutoff = utc_now() - timedelta(days=7)

        # The two tables that dominate egress must be bounded.
        for model in ("OpportunityInteraction", "RankingRequestTelemetry"):
            self.assertIn(model, sink, f"{model} was never queried")
            ge_filters = [f for f in sink[model] if f[0] == "ge"]
            self.assertTrue(
                ge_filters, f"{model} was queried with no lower bound - full table read"
            )
            _, path, value = ge_filters[0]
            self.assertTrue(path.endswith(".created_at"))
            # Allow a little slack for clock movement during the test.
            self.assertLess(abs((value - cutoff).total_seconds()), 60)

        for model in ("FeatureStoreRow", "AnalyticsDailyAggregate", "AnalyticsFunnelAggregate"):
            self.assertIn(model, sink, f"{model} was never queried")
            ge_filters = [f for f in sink[model] if f[0] == "ge"]
            self.assertTrue(
                ge_filters, f"{model} was queried with no lower bound - full table read"
            )
            _, path, value = ge_filters[0]
            self.assertTrue(path.endswith(".date"))
            self.assertEqual(value, cutoff.date().isoformat())

    async def test_lookback_is_clamped_to_a_sane_range(self) -> None:
        # A caller passing 0 or something enormous must not turn back into a
        # full-table read by accident.
        sink: dict = {}
        names = [
            "OpportunityInteraction", "RankingRequestTelemetry", "FeatureStoreRow",
            "AnalyticsDailyAggregate", "AnalyticsFunnelAggregate", "AnalyticsCohortAggregate",
        ]
        for requested, expected_days in ((0, 30), (100000, 365)):
            with self.subTest(requested=requested):
                sink.clear()
                patches = [patch.object(export_mod, n, _RecordingModel(sink, n)) for n in names]
                with patch.object(export_mod.settings, "ANALYTICS_WAREHOUSE_EXPORT_ENABLED", True):
                    for p in patches:
                        p.start()
                    try:
                        try:
                            await export_mod.warehouse_export_service.export(
                                lookback_days=requested, traffic_type="real"
                            )
                        except Exception:
                            pass
                    finally:
                        for p in patches:
                            p.stop()

                ge = [f for f in sink["OpportunityInteraction"] if f[0] == "ge"][0]
                expected = utc_now() - timedelta(days=expected_days)
                self.assertLess(abs((ge[2] - expected).total_seconds()), 60)


    async def test_prefetched_rows_are_not_requeried(self) -> None:
        """Passing rows in must skip the query entirely, not merely ignore it.

        The rebuild selects these rows and then calls export, which selected them
        again. Same rows, twice, on a metered connection. If this regresses the
        symptom is only a bandwidth bill, so it gets a test.
        """
        sink: dict = {}
        names = [
            "OpportunityInteraction", "RankingRequestTelemetry", "FeatureStoreRow",
            "AnalyticsDailyAggregate", "AnalyticsFunnelAggregate", "AnalyticsCohortAggregate",
        ]
        patches = [patch.object(export_mod, n, _RecordingModel(sink, n)) for n in names]
        with patch.object(export_mod.settings, "ANALYTICS_WAREHOUSE_EXPORT_ENABLED", True):
            for p in patches:
                p.start()
            try:
                try:
                    await export_mod.warehouse_export_service.export(
                        lookback_days=14,
                        traffic_type="real",
                        interactions_prefetched=[],
                        telemetry_prefetched=[],
                    )
                except Exception:
                    pass
            finally:
                for p in patches:
                    p.stop()

        self.assertNotIn(
            "OpportunityInteraction", sink,
            "interactions were re-queried despite being passed in",
        )
        self.assertNotIn(
            "RankingRequestTelemetry", sink,
            "telemetry was re-queried despite being passed in",
        )
        # Feature rows are written by the rebuild, not held by it, so they are
        # still fetched - and still bounded by the lookback window.
        self.assertIn("FeatureStoreRow", sink)


if __name__ == "__main__":
    unittest.main()
