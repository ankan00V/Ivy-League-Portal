import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now
from app.services.opportunity_status_service import opportunity_status_service


class TestOpportunityStatusService(unittest.TestCase):
    def test_resolve_status_from_deadline_and_lifecycle(self) -> None:
        now = utc_now()

        self.assertEqual(
            opportunity_status_service.resolve_status(
                SimpleNamespace(lifecycle_status="published", deadline=now + timedelta(days=30))
            ),
            "active",
        )
        self.assertEqual(
            opportunity_status_service.resolve_status(
                SimpleNamespace(lifecycle_status="published", deadline=now + timedelta(days=2))
            ),
            "closing_soon",
        )
        self.assertEqual(
            opportunity_status_service.resolve_status(
                SimpleNamespace(lifecycle_status="published", deadline=now - timedelta(minutes=1))
            ),
            "expired",
        )
        self.assertEqual(
            opportunity_status_service.resolve_status(SimpleNamespace(lifecycle_status="closed", deadline=None)),
            "filled",
        )

    def test_freshness_score_decays_with_age(self) -> None:
        now = utc_now()
        fresh = SimpleNamespace(last_seen_at=now, updated_at=None, created_at=now, deadline=None)
        stale = SimpleNamespace(
            last_seen_at=now - timedelta(days=60),
            updated_at=None,
            created_at=now - timedelta(days=60),
            deadline=None,
        )

        self.assertGreater(opportunity_status_service.freshness_score(fresh), 0.9)
        self.assertLess(opportunity_status_service.freshness_score(stale), 0.1)


if __name__ == "__main__":
    unittest.main()
