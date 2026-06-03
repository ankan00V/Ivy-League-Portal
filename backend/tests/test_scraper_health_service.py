import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now
from app.models.scraper_run_log import ScraperRunLog
from app.services.scraper_health_service import ScraperHealthService


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args, **_kwargs):
        return self

    async def to_list(self):
        return self.rows


class TestScraperHealthService(unittest.IsolatedAsyncioTestCase):
    async def test_source_health_flags_silent_failure_red(self) -> None:
        now = utc_now()
        rows = [
            ScraperRunLog.model_construct(
                source_name="linkedin",
                run_start=now - timedelta(hours=2),
                run_end=now - timedelta(hours=2),
                status="failed",
                items_fetched=10,
                items_parsed=10,
                items_inserted=0,
                items_updated=0,
                items_deduplicated=0,
                parse_error_count=0,
                error_samples=[],
                silent_failure=True,
            ),
            ScraperRunLog.model_construct(
                source_name="linkedin",
                run_start=now - timedelta(hours=1),
                run_end=now - timedelta(hours=1),
                status="failed",
                items_fetched=8,
                items_parsed=8,
                items_inserted=0,
                items_updated=0,
                items_deduplicated=0,
                parse_error_count=2,
                error_samples=[{"message": "blocked"}],
                silent_failure=False,
            ),
        ]

        with patch.object(ScraperRunLog, "find_many", return_value=FakeQuery(rows)):
            payload = await ScraperHealthService().source_health()

        self.assertEqual(payload["summary"]["red_count"], 1)
        self.assertEqual(payload["sources"][0]["source"], "linkedin")
        self.assertEqual(payload["sources"][0]["health_status"], "RED")
        self.assertEqual(payload["sources"][0]["consecutive_failures"], 2)


if __name__ == "__main__":
    unittest.main()
