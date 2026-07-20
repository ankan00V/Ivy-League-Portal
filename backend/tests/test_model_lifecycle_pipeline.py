import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.run_model_lifecycle_pipeline import _insufficient_training_rows


class TestModelLifecyclePipeline(unittest.TestCase):
    def test_parses_expected_insufficient_training_data_error(self) -> None:
        self.assertEqual(
            _insufficient_training_rows(ValueError("insufficient_training_data: 0 < 200")),
            (0, 200),
        )

    def test_rejects_unrelated_value_error(self) -> None:
        self.assertIsNone(_insufficient_training_rows(ValueError("model artifact checksum mismatch")))


if __name__ == "__main__":
    unittest.main()
