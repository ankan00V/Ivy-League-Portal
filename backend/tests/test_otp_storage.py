import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.redis_client import _as_utc_aware


class TestOtpTimestampNormalization(unittest.TestCase):
    def test_naive_datetimes_are_treated_as_utc(self) -> None:
        normalized = _as_utc_aware(datetime(2026, 5, 5, 19, 30, 0))

        self.assertEqual(normalized.tzinfo, timezone.utc)
        self.assertEqual(normalized.isoformat(), "2026-05-05T19:30:00+00:00")

    def test_aware_datetimes_are_converted_to_utc(self) -> None:
        normalized = _as_utc_aware(datetime(2026, 5, 5, 19, 30, 0, tzinfo=timezone.utc))

        self.assertEqual(normalized.tzinfo, timezone.utc)
        self.assertEqual(normalized.isoformat(), "2026-05-05T19:30:00+00:00")


if __name__ == "__main__":
    unittest.main()
