import unittest
from datetime import datetime, timedelta
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.scraper import _dedupe_by_url, _extract_deadline_from_text, is_opportunity_active
from app.core.time import utc_now


class DummyOpportunity:
    def __init__(self, deadline):
        self.deadline = deadline


class TestScraperIngestionHelpers(unittest.TestCase):
    def test_dedupe_by_url_keeps_first_unique_url(self) -> None:
        rows = [
            {"url": "https://example.com/one", "title": "One"},
            {"url": "https://example.com/one", "title": "Duplicate"},
            {"url": "https://example.com/two", "title": "Two"},
        ]
        deduped = _dedupe_by_url(rows)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["title"], "One")

    def test_extract_deadline_from_text_parses_named_date(self) -> None:
        deadline = _extract_deadline_from_text("Applications close: March 14, 2026 for the program.")
        self.assertIsNotNone(deadline)
        assert deadline is not None
        self.assertEqual(deadline.year, 2026)
        self.assertEqual(deadline.month, 3)
        self.assertEqual(deadline.day, 14)

    def test_is_opportunity_active_rejects_expired_deadline(self) -> None:
        now = utc_now()
        active = is_opportunity_active(DummyOpportunity(deadline=now + timedelta(days=3)), now=now)
        expired = is_opportunity_active(DummyOpportunity(deadline=now - timedelta(days=1)), now=now)
        self.assertTrue(active)
        self.assertFalse(expired)


if __name__ == "__main__":
    unittest.main()
