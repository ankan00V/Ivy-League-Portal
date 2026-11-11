"""A source's run status must describe that source, not the whole run.

Per-source reports never carried a status, so each source's run log fell back
to the status of the run as a whole. The run is partial whenever any one of
roughly forty sources reports an error, and with several boards that routinely
refuse automated requests one always does. So every source was logged partial
on every run: measured on the live database, 295 partial, 47 failed and not a
single success across a day - including sources that fetched and inserted
cleanly. A health view where the broken source and the working ones look the
same cannot point at the broken one.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.scraper_health_service import _source_status


class SourceStatusTests(unittest.TestCase):
    def test_a_clean_source_is_a_success_even_when_the_run_was_partial(self):
        """The failure mode: one blocked board made every other source partial."""
        source = {"source": "unstop", "fetched": 40, "inserted": 6, "updated": 30, "errors": []}
        self.assertEqual(_source_status(source, errors=[], fetched=40, inserted=6, updated=30), "success")

    def test_errors_with_progress_are_partial(self):
        source = {"source": "glassdoor"}
        self.assertEqual(
            _source_status(source, errors=["one page 403"], fetched=12, inserted=0, updated=8), "partial"
        )

    def test_errors_with_no_progress_are_failed(self):
        source = {"source": "linkedin"}
        self.assertEqual(
            _source_status(source, errors=["HTTP 999"], fetched=0, inserted=0, updated=0), "failed"
        )

    def test_a_quiet_source_with_no_errors_is_not_a_failure(self):
        """Nothing new is a normal outcome for a board that has not changed."""
        self.assertEqual(_source_status({}, errors=[], fetched=0, inserted=0, updated=0), "success")

    def test_an_explicit_source_status_still_wins(self):
        self.assertEqual(
            _source_status({"status": "failed"}, errors=[], fetched=5, inserted=1, updated=1), "failed"
        )

    def test_the_run_status_is_no_longer_consulted(self):
        source = (BACKEND_ROOT / "app" / "services" / "scraper_health_service.py").read_text()
        self.assertNotIn('or report.get("status")', source)


class DuplicateHandlerTests(unittest.TestCase):
    """The duplicate handler was written for MongoDB and never matched the
    exception Postgres raises, so concurrent jobs reaching the same listing
    were counted as failed upserts - 55 in one worker log."""

    def test_the_postgres_unique_violation_is_handled(self):
        source = (BACKEND_ROOT / "app" / "services" / "scraper.py").read_text()
        self.assertIn(
            "except (pymongo.errors.DuplicateKeyError, asyncpg.exceptions.UniqueViolationError):",
            source,
        )

    def test_a_duplicate_refreshes_last_seen_rather_than_being_dropped(self):
        source = (BACKEND_ROOT / "app" / "services" / "scraper.py").read_text()
        start = source.index("asyncpg.exceptions.UniqueViolationError):")
        handler = source[start : source.index("except Exception as exc:", start)]
        self.assertIn("last_seen_at", handler)
        self.assertIn("updated_count += 1", handler)


if __name__ == "__main__":
    unittest.main()
