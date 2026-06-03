import unittest
from datetime import timedelta
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from beanie import PydanticObjectId

from app.services.mlops.retraining_service import RetrainingService, TrainingExample
from app.core.time import utc_now


class TestRetrainingService(unittest.TestCase):
    def test_split_examples_prefers_time_split_when_valid(self) -> None:
        service = RetrainingService()
        now = utc_now()
        examples = []
        for index in range(12):
            examples.append(
                TrainingExample(
                    user_id=f"user-{index % 4}",
                    created_at=now + timedelta(minutes=index),
                    query=f"query-{index}",
                    features=(0.7 if index % 2 == 0 else 0.2, 0.3, 0.1),
                    label=1 if index % 2 == 0 else 0,
                )
            )

        splits = service._split_examples(examples)
        self.assertEqual(splits.strategy, "time")
        self.assertEqual(int(splits.train_idx.size), 7)
        self.assertGreater(splits.summary["counts"]["test"]["rows"], 0)

    def test_build_model_card_contains_auc_and_activation_sections(self) -> None:
        service = RetrainingService()
        card = service._build_model_card(
            metrics={
                "auc_default_train": 0.51,
                "auc_learned_train": 0.62,
                "auc_gain_train": 0.11,
                "auc_default_validation": 0.5,
                "auc_learned_validation": 0.6,
                "auc_gain_validation": 0.1,
                "auc_default_test": 0.49,
                "auc_learned_test": 0.59,
                "auc_gain_test": 0.1,
            },
            baselines={"features": {"semantic_score": {"mean": 0.5}}, "query_length": {}, "query_buckets": {}},
            lifecycle={"activated": False, "activation_reason": "guardrail_data_missing", "activation_policy": "guarded", "diagnostics": {}},
            training_metadata={"window_start": "2026-01-01T00:00:00", "window_end": "2026-01-31T00:00:00", "label_window_hours": 72, "rows": 100, "split_strategy": "time"},
            drift_snapshot={"alert": False},
            weights={"semantic": 0.6, "baseline": 0.25, "behavior": 0.15},
        )
        self.assertIn("auc", card)
        self.assertIn("activation", card)
        self.assertEqual(card["activation"]["reason"], "guardrail_data_missing")


class TestRetrainingServiceAsync(unittest.IsolatedAsyncioTestCase):
    async def test_training_examples_use_canonical_events_and_outcomes(self) -> None:
        service = RetrainingService()
        now = utc_now()
        user_id = PydanticObjectId()
        opportunity_a = PydanticObjectId()
        opportunity_b = PydanticObjectId()

        impressions = [
            SimpleNamespace(
                user_id=user_id,
                opportunity_id=opportunity_a,
                interaction_type="impression",
                event_type="impression",
                features={"semantic_score": 80.0, "baseline_score": 60.0, "behavior_score": 20.0},
                query="ml internship",
                created_at=now,
            ),
            SimpleNamespace(
                user_id=user_id,
                opportunity_id=opportunity_b,
                interaction_type="impression",
                event_type="impression",
                features={"semantic_score": 40.0, "baseline_score": 50.0, "behavior_score": 10.0},
                query="analytics",
                created_at=now + timedelta(minutes=10),
            ),
        ]
        positives = [
            SimpleNamespace(
                user_id=user_id,
                opportunity_id=opportunity_a,
                interaction_type="view",
                event_type="apply_complete",
                features=None,
                query=None,
                created_at=now + timedelta(hours=2),
            )
        ]
        outcomes = [
            SimpleNamespace(
                user_id=user_id,
                opportunity_id=opportunity_b,
                response="yes",
                created_at=now + timedelta(hours=3),
            )
        ]

        with patch.object(
            service,
            "_load_impression_candidates",
            AsyncMock(return_value=impressions),
        ), patch.object(
            service,
            "_load_positive_candidates",
            AsyncMock(return_value=positives),
        ), patch.object(
            service,
            "_load_positive_outcomes",
            AsyncMock(return_value=outcomes),
        ):
            examples, baselines = await service.build_training_examples(
                window_start=now - timedelta(hours=1),
                window_end=now + timedelta(hours=1),
                label_window_hours=8,
            )

        self.assertEqual(len(examples), 2)
        self.assertEqual([example.label for example in examples], [1, 1])
        self.assertEqual(examples[0].features, (0.8, 0.6, 0.2))
        self.assertEqual(baselines["labels"]["positive_interactions"], 1.0)
        self.assertEqual(baselines["labels"]["positive_outcomes"], 1.0)
        self.assertEqual(baselines["labels"]["positive_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
