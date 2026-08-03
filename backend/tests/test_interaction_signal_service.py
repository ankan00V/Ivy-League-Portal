import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from beanie import PydanticObjectId  # noqa: E402

from app.services.interaction_service import (  # noqa: E402
    InteractionService,
    SignalStrengthCalculator,
    funnel_event_type,
    object_id_or_none,
)


class TestSignalStrengthCalculator(unittest.TestCase):
    def test_reward_map_matches_training_signal_contract(self) -> None:
        calculator = SignalStrengthCalculator()

        self.assertEqual(calculator.reward(event_type="impression"), 0.0)
        self.assertEqual(calculator.reward(event_type="click"), 0.2)
        self.assertEqual(calculator.reward(event_type="expand"), 0.35)
        self.assertEqual(calculator.reward(event_type="save"), 0.6)
        self.assertEqual(calculator.reward(event_type="apply_start"), 0.75)
        self.assertEqual(calculator.reward(event_type="apply_complete"), 1.0)
        self.assertEqual(calculator.reward(event_type="skip"), -0.1)
        self.assertEqual(calculator.reward(event_type="dismiss"), -0.1)

    def test_dwell_and_legacy_aliases_raise_signal_strength(self) -> None:
        calculator = SignalStrengthCalculator()

        self.assertEqual(calculator.normalize_event_type("view"), "expand")
        self.assertEqual(calculator.normalize_event_type("apply"), "apply_complete")
        self.assertEqual(calculator.reward(event_type="click", dwell_time_ms=31_000), 0.45)
        self.assertEqual(calculator.reward(event_type="expand", scroll_depth=95), 0.45)

    def test_funnel_event_type_maps_canonical_apply_signals(self) -> None:
        self.assertEqual(funnel_event_type(interaction_type="impression"), "impression")
        self.assertEqual(funnel_event_type(interaction_type="view", event_type="expand"), "view")
        self.assertEqual(funnel_event_type(interaction_type="view", event_type="apply_complete"), "apply")
        self.assertEqual(funnel_event_type(interaction_type="apply"), "apply")
        self.assertEqual(funnel_event_type(interaction_type="apply_complete"), "apply")
        self.assertEqual(funnel_event_type(interaction_type="shortlisted"), "apply")
        self.assertEqual(funnel_event_type(interaction_type="interview"), "apply")
        self.assertIsNone(funnel_event_type(interaction_type="dismiss"))

    def test_service_normalization_helpers_are_strict_for_ml_contract(self) -> None:
        service = InteractionService()

        self.assertEqual(service.normalize_ranking_mode("ML"), "ml")
        self.assertIsNone(service.normalize_ranking_mode("unsupported"))
        self.assertEqual(service.normalize_traffic_type("simulated"), "simulated")
        self.assertEqual(service.normalize_traffic_type("bad-value"), "real")

    def test_object_id_or_none_rejects_invalid_ids(self) -> None:
        valid = "64f0c85f9f1b2c3d4e5f6789"

        self.assertIsInstance(object_id_or_none(valid), PydanticObjectId)
        self.assertIsNone(object_id_or_none("not-an-object-id"))


class TestInteractionMetrics(unittest.IsolatedAsyncioTestCase):
    async def test_log_event_uses_metrics_initialized_after_service_import(self) -> None:
        service = InteractionService()
        counter = Mock()
        counter.labels.return_value = Mock()
        event = SimpleNamespace(insert=AsyncMock())

        with (
            patch("app.services.interaction_service.metrics_module.INTERACTION_EVENTS_TOTAL", counter),
            patch("app.services.interaction_service.OpportunityInteraction", return_value=event),
            patch.object(service, "_update_journey", new=AsyncMock()),
            patch("app.services.interaction_service.cache_manager.invalidate_after_user_interaction", new=AsyncMock()),
        ):
            await service.log_event(
                user_id=PydanticObjectId("64f0c85f9f1b2c3d4e5f6789"),
                opportunity_id=PydanticObjectId("64f0c85f9f1b2c3d4e5f6790"),
                interaction_type="dismiss",
                ranking_mode="semantic",
                experiment_key="ranking_mode",
                experiment_variant="semantic",
            )

        counter.labels.assert_called_once_with(
            interaction_type="dismiss",
            ranking_mode="semantic",
            experiment_key="ranking_mode",
            experiment_variant="semantic",
            traffic_type="real",
        )
        counter.labels.return_value.inc.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
