"""Listing applications must cost one query, not one per application.

The handler used to call Opportunity.get inside its loop. A round trip to the
pooled database costs ~350ms, so a student with fifty applications waited
roughly seventeen seconds for a page showing fifty rows - and the wait grew with
how much they had used the product, which is the worst direction for it to grow.

Nothing failed. The page was correct, just slower for the users who had engaged
most, which is why it survived: the developer testing it has three applications
and sees a second, and the student it punishes never files a bug.

This counts queries rather than measuring time, because the cost is round trips
and a fast local database would hide it completely.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import applications as applications_module


class _StubField:
    """Stands in for a Beanie field so `Model.field == value` is expressible.

    The ODM patches these onto the document classes at startup, which unit tests
    do not run, so touching Application.user_id raises AttributeError long
    before the handler under test is reached.
    """

    def __eq__(self, other):  # noqa: D105
        return ("eq", other)

    def __hash__(self):  # noqa: D105
        return id(self)

    def __neg__(self):
        # `sort(-Application.created_at)` needs this.
        return self


class _Query:
    def __init__(self, rows, counter, key):
        self._rows = rows
        self._counter = counter
        self._key = key

    def sort(self, *_args):
        return self

    async def to_list(self):
        self._counter[self._key] += 1
        return self._rows


class TestApplicationsListIsBatched(unittest.IsolatedAsyncioTestCase):
    async def _run(self, count: int):
        counter = {"applications": 0, "opportunities": 0, "per_row_get": 0}
        apps = [
            SimpleNamespace(opportunity_id=f"opp{i}", id=f"app{i}", user_id="u1")
            for i in range(count)
        ]
        opps = [SimpleNamespace(id=f"opp{i}", title=f"Role {i}") for i in range(count)]

        async def fail_on_get(*_a, **_k):
            counter["per_row_get"] += 1
            return None

        class _StubApplication:
            user_id = _StubField()
            created_at = _StubField()

            @staticmethod
            def find(*_a, **_k):
                return _Query(apps, counter, "applications")

        class _StubOpportunity:
            id = _StubField()

            @staticmethod
            def find_many(*_a, **_k):
                return _Query(opps, counter, "opportunities")

            @staticmethod
            async def get(*_a, **_k):
                return await fail_on_get()

        with (
            patch.object(applications_module, "Application", _StubApplication),
            patch.object(applications_module, "Opportunity", _StubOpportunity),
            patch.object(applications_module, "In", lambda *_a, **_k: ("in", None)),
            patch.object(
                applications_module,
                "_serialize_application_response",
                lambda application, opportunity: {"id": str(application.id)},
            ),
        ):
            rows = await applications_module.list_my_applications(
                current_user=SimpleNamespace(id="u1")
            )
        return rows, counter

    async def test_fifty_applications_still_cost_two_queries(self) -> None:
        rows, counter = await self._run(50)
        self.assertEqual(len(rows), 50)
        self.assertEqual(counter["applications"], 1)
        self.assertEqual(counter["opportunities"], 1)
        self.assertEqual(
            counter["per_row_get"],
            0,
            "Opportunity.get was called per application; the N+1 is back",
        )

    async def test_query_count_does_not_grow_with_applications(self) -> None:
        # The property that matters: cost is flat in the number of applications.
        _rows, small = await self._run(3)
        _rows, large = await self._run(80)
        self.assertEqual(small["opportunities"], large["opportunities"])

    async def test_no_applications_makes_no_opportunity_query(self) -> None:
        _rows, counter = await self._run(0)
        self.assertEqual(counter["opportunities"], 0)


if __name__ == "__main__":
    unittest.main()
