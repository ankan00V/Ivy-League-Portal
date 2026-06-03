import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from beanie import PydanticObjectId  # noqa: E402

from app.core.time import utc_now  # noqa: E402
from app.models.experiment import ExperimentVariant  # noqa: E402
from app.services.experiment_service import ExperimentService, _allocate_units  # noqa: E402


class TestExperimentService(unittest.IsolatedAsyncioTestCase):
    def test_allocate_units_prefers_traffic_fraction_when_present(self) -> None:
        variants = [
            ExperimentVariant(name="control", traffic_fraction=0.8, weight=1.0, is_control=True),
            ExperimentVariant(name="ml", traffic_fraction=0.2, weight=9.0, ranking_mode="ml"),
        ]

        self.assertEqual(_allocate_units(variants), [8000, 2000])

    async def test_cold_start_user_is_excluded_from_ml_variant(self) -> None:
        service = ExperimentService()
        variants = [
            ExperimentVariant(name="baseline", ranking_mode="baseline", is_control=True),
            ExperimentVariant(name="ml", ranking_mode="ml", exclude_cold_start=True),
        ]

        variant, is_control, reason = await service._apply_exclusion_rules(
            variants=variants,
            selected_variant="ml",
            cold_start=True,
            user_id=PydanticObjectId(),
        )

        self.assertEqual(variant, "baseline")
        self.assertTrue(is_control)
        self.assertEqual(reason, "cold_start_excluded_from_ml")

    async def test_assign_stores_exclusion_metadata_for_new_assignments(self) -> None:
        service = ExperimentService()
        experiment = type(
            "FakeExperiment",
            (),
            {
                "key": "ranking_mode",
                "status": "running",
                "salt": "fixed",
                "variants": [
                    ExperimentVariant(name="baseline", traffic_fraction=0.0, ranking_mode="baseline", is_control=True),
                    ExperimentVariant(name="ml", traffic_fraction=1.0, ranking_mode="ml", exclude_cold_start=True),
                ],
            },
        )()
        inserted = {}

        def fake_assignment(**kwargs):
            inserted.update(kwargs)

            async def insert():
                return None

            return SimpleNamespace(**kwargs, assigned_at=utc_now(), insert=insert)

        with patch.object(service, "get", AsyncMock(return_value=experiment)), patch.object(
            service,
            "_find_assignment",
            AsyncMock(return_value=None),
        ), patch.object(service, "_make_assignment", side_effect=fake_assignment):
            decision = await service.assign(user_id=PydanticObjectId(), experiment_key="ranking_mode", cold_start=True)

        self.assertIsNotNone(decision)
        self.assertEqual(decision.variant, "baseline")
        self.assertTrue(inserted["assigned_via_exclusion"])
        self.assertEqual(inserted["exclusion_reason"], "cold_start_excluded_from_ml")


if __name__ == "__main__":
    unittest.main()
