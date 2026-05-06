import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints.opportunities import _diversify_by_source, _feed_priority
from app.core.time import utc_now


class TestFeedCuration(unittest.TestCase):
    def test_diversify_by_source_limits_early_source_repetition(self) -> None:
        now = utc_now()
        rows = [
            SimpleNamespace(source="linkedin", trust_status="verified", trust_score=95, risk_score=5, last_seen_at=now, updated_at=now, created_at=now),
            SimpleNamespace(source="linkedin", trust_status="verified", trust_score=94, risk_score=6, last_seen_at=now, updated_at=now, created_at=now),
            SimpleNamespace(source="linkedin", trust_status="verified", trust_score=93, risk_score=7, last_seen_at=now, updated_at=now, created_at=now),
            SimpleNamespace(source="devfolio", trust_status="verified", trust_score=92, risk_score=8, last_seen_at=now, updated_at=now, created_at=now),
            SimpleNamespace(source="wellfound", trust_status="verified", trust_score=91, risk_score=9, last_seen_at=now, updated_at=now, created_at=now),
        ]

        ordered = sorted(rows, key=_feed_priority, reverse=True)
        diversified = _diversify_by_source(ordered, source_getter=lambda item: item.source, per_source_cap=2)

        self.assertEqual(diversified[0].source, "linkedin")
        self.assertEqual(diversified[1].source, "linkedin")
        self.assertNotEqual(diversified[2].source, "linkedin")

    def test_feed_priority_prefers_verified_and_trusted_rows(self) -> None:
        now = utc_now()
        verified = SimpleNamespace(
            source="linkedin",
            trust_status="verified",
            trust_score=90,
            risk_score=10,
            last_seen_at=now,
            updated_at=now,
            created_at=now - timedelta(hours=1),
        )
        pending = SimpleNamespace(
            source="unknown",
            trust_status="unreviewed",
            trust_score=50,
            risk_score=50,
            last_seen_at=now,
            updated_at=now,
            created_at=now - timedelta(hours=1),
        )

        self.assertGreater(_feed_priority(verified), _feed_priority(pending))


if __name__ == "__main__":
    unittest.main()
