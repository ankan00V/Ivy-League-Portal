"""The listings that need verifying are the ones this loop never reached.

A listing leaves the feed one of two ways: its deadline passes, or its link
stops resolving. Measured on the live corpus, 81% of active listings carry no
deadline at all, and 1,347 of 2,587 had not been seen by any scraper in over 30
days - mostly one-off company career-page scrapes that will never run again. For
those rows the link check is the only thing that can ever retire them, and it
had never run once: 0 of 2,587 had a `url_last_checked_at`.

Two reasons, both here. The scheduled job passed `check_liveness: False` as a
literal, and the loop spends its budget in `-updated_at` order, which is the
freshest rows first - the ones a scraper has just confirmed. Even switched on,
the budget would have been spent re-checking what was already known and the
stale tail would never have been reached.
"""

from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now
from app.services.opportunity_status_service import OpportunityStatusService


class FakeRow:
    """Only the attributes refresh() touches."""

    def __init__(self, name, *, checked_days_ago=None, url="https://example.com/x"):
        self.name = name
        self.url = url
        self.deadline = None
        self.lifecycle_status = "published"
        self.opportunity_status = "active"
        self.freshness_score = 0.0
        self.last_seen_at = utc_now() - timedelta(days=60)
        self.url_liveness_status = "unknown"
        self.url_last_checked_at = (
            None if checked_days_ago is None else utc_now() - timedelta(days=checked_days_ago)
        )
        self.lifecycle_updated_at = None
        self.saved = 0

    async def save(self):
        self.saved += 1


class LivenessQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = OpportunityStatusService()

    async def _refresh(self, rows, *, liveness_limit=2, check_liveness=True, verdict="alive"):
        checked: list[str] = []

        async def _check(row, **kwargs):
            checked.append(row.name)
            return verdict

        with (
            patch(
                "app.services.opportunity_status_service.Opportunity.find_many"
            ) as find_many,
            patch.object(self.service, "check_url_liveness", new=AsyncMock(side_effect=_check)),
        ):
            find_many.return_value.sort.return_value.limit.return_value.to_list = AsyncMock(
                return_value=rows
            )
            report = await self.service.refresh(
                limit=100, check_liveness=check_liveness, liveness_limit=liveness_limit
            )
        return checked, report

    async def test_never_checked_rows_go_first(self):
        """They are the 2,587 that had never been verified at all."""
        rows = [
            FakeRow("checked-yesterday", checked_days_ago=2),
            FakeRow("never-checked"),
            FakeRow("checked-long-ago", checked_days_ago=40),
        ]
        checked, _ = await self._refresh(rows, liveness_limit=1)
        self.assertEqual(checked, ["never-checked"])

    async def test_then_the_least_recently_checked(self):
        """Every row is verified once before any row is verified twice."""
        rows = [
            FakeRow("recent", checked_days_ago=2),
            FakeRow("oldest", checked_days_ago=90),
            FakeRow("middle", checked_days_ago=30),
        ]
        checked, _ = await self._refresh(rows, liveness_limit=2)
        self.assertEqual(checked, ["oldest", "middle"])

    async def test_order_in_the_page_does_not_decide(self):
        """The page arrives in -updated_at order, which is the freshest first.
        Taking that order is what spent the budget on rows that needed it least."""
        rows = [FakeRow(f"fresh-{i}", checked_days_ago=1.5) for i in range(5)]
        rows.append(FakeRow("stale-tail", checked_days_ago=60))
        checked, _ = await self._refresh(rows, liveness_limit=1)
        self.assertEqual(checked, ["stale-tail"])

    async def test_the_budget_is_respected(self):
        rows = [FakeRow(f"row-{i}") for i in range(10)]
        checked, report = await self._refresh(rows, liveness_limit=3)
        self.assertEqual(len(checked), 3)
        self.assertEqual(report.liveness_checked, 3)

    async def test_a_row_checked_today_is_not_rechecked(self):
        rows = [FakeRow("checked-today", checked_days_ago=0)]
        checked, _ = await self._refresh(rows, liveness_limit=5)
        self.assertEqual(checked, [])

    async def test_nothing_is_checked_when_the_job_asks_for_nothing(self):
        rows = [FakeRow("a"), FakeRow("b")]
        checked, _ = await self._refresh(rows, check_liveness=False, liveness_limit=5)
        self.assertEqual(checked, [])

    async def test_a_dead_link_retires_the_listing(self):
        """Retirement is a status change, never a delete."""
        rows = [FakeRow("gone")]
        await self._refresh(rows, liveness_limit=1, verdict="dead")
        self.assertEqual(rows[0].opportunity_status, "removed")
        self.assertEqual(rows[0].url_liveness_status, "dead")

    async def test_an_unreachable_link_changes_nothing(self):
        """A bot-block or timeout is not evidence the listing is gone, and most
        of this corpus sits behind boards that refuse automated requests."""
        rows = [FakeRow("blocked")]
        await self._refresh(rows, liveness_limit=1, verdict="error")
        self.assertEqual(rows[0].opportunity_status, "active")


class ScheduledJobTests(unittest.TestCase):
    def test_the_setting_exists_and_defaults_on(self):
        """The call site passed False as a literal, so the feature shipped and
        never ran. A setting at least makes that visible and reversible."""
        from app.core.config import settings

        self.assertTrue(hasattr(settings, "OPPORTUNITY_LIVENESS_CHECK_ENABLED"))
        self.assertTrue(settings.OPPORTUNITY_LIVENESS_CHECK_ENABLED)
        self.assertGreater(settings.OPPORTUNITY_LIVENESS_PER_RUN, 0)

    def test_the_scheduler_no_longer_hardcodes_it_off(self):
        source = (BACKEND_ROOT / "app" / "main.py").read_text()
        self.assertNotIn('"check_liveness": False', source)
        self.assertIn("OPPORTUNITY_LIVENESS_CHECK_ENABLED", source)


if __name__ == "__main__":
    unittest.main()
