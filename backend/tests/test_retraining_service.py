import unittest
from datetime import timedelta
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

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


if __name__ == "__main__":
    unittest.main()
