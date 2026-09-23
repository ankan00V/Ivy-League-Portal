"""A failed bookkeeping write must not destroy an answer that already exists.

Ask AI does three writes after the shortlist is computed: the saved-query
upsert, the analytics snapshot, and the telemetry row. None of them changes the
response. All three used to be able to turn a completed answer into a 500 - hit
locally on "data science internships in Bangalore", where the pool release timed
out inside the saved-query upsert and the caller got a 500 at 107 seconds for a
shortlist the server was holding.

The failure path had the mirror-image bug: its telemetry insert goes to the same
database that most failures come from, so it is the likeliest thing to fail
second, and it would have replaced the original error with a database error.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from beanie import PydanticObjectId

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints import opportunities as opportunities_endpoint


class DummyUser:
    def __init__(self) -> None:
        self.id = PydanticObjectId("64b64b64b64b64b64b64b64b")


def _answer() -> dict:
    return {
        "request_id": "req-bookkeeping",
        "query": "data science internships in Bangalore",
        "intent": {},
        "entities": {},
        "results": [],
        "insights": {
            "summary": "summary",
            "top_opportunities": [],
            "deadline_urgency": "soon",
            "recommended_action": "apply",
            "citations": [],
            "safety": {
                "hallucination_checks_passed": True,
                "failed_checks": [],
                "quality_checks_passed": True,
                "quality_failed_checks": [],
                "judge_score": None,
                "judge_rationale": None,
            },
            "contract_version": "rag_insights.v1",
        },
    }


class BookkeepingFailureTests(unittest.IsolatedAsyncioTestCase):
    async def _ask(self, **extra_patches) -> dict:
        request = opportunities_endpoint.AskAIRequest(query="data science internships in Bangalore")
        with (
            patch.object(opportunities_endpoint, "_get_or_create_profile", new=AsyncMock(return_value=object())),
            patch.object(opportunities_endpoint.rag_service, "ask", new=AsyncMock(return_value=_answer())),
        ):
            with patch.multiple(opportunities_endpoint, **extra_patches):
                return await opportunities_endpoint.ask_ai_shortlist(
                    request=request, current_user=DummyUser()
                )

    async def test_saved_query_timeout_still_returns_the_shortlist(self):
        """The exact failure observed: a pool release timing out mid-upsert."""
        upsert = AsyncMock(side_effect=TimeoutError())
        payload = await self._ask(_upsert_saved_query=upsert)
        upsert.assert_awaited()
        self.assertEqual(payload["request_id"], "req-bookkeeping")

    async def test_snapshot_failure_still_returns_the_shortlist(self):
        """The snapshot is an analytics record, not part of the response."""
        snapshot = patch.object(
            opportunities_endpoint.AskAIQuerySnapshot,
            "find_one",
            new=AsyncMock(side_effect=TimeoutError()),
        )
        with snapshot:
            payload = await self._ask(_upsert_saved_query=AsyncMock())
        self.assertEqual(payload["request_id"], "req-bookkeeping")

    async def test_telemetry_failure_still_returns_the_shortlist(self):
        with patch.object(
            opportunities_endpoint.ranking_request_telemetry_service,
            "log",
            new=AsyncMock(side_effect=TimeoutError()),
        ):
            payload = await self._ask(_upsert_saved_query=AsyncMock())
        self.assertEqual(payload["request_id"], "req-bookkeeping")


class FailurePathTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_original_error_survives_a_failing_telemetry_insert(self):
        """Losing the real error here sends the diagnosis to the wrong layer:
        an embedding failure would be reported as a database timeout."""
        request = opportunities_endpoint.AskAIRequest(query="anything")
        with (
            patch.object(opportunities_endpoint, "_get_or_create_profile", new=AsyncMock(return_value=object())),
            patch.object(
                opportunities_endpoint.rag_service,
                "ask",
                new=AsyncMock(side_effect=ValueError("embedding backend down")),
            ),
            patch.object(
                opportunities_endpoint.ranking_request_telemetry_service,
                "log",
                new=AsyncMock(side_effect=TimeoutError()),
            ),
        ):
            with self.assertRaises(ValueError) as caught:
                await opportunities_endpoint.ask_ai_shortlist(
                    request=request, current_user=DummyUser()
                )

        self.assertIn("embedding backend down", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
