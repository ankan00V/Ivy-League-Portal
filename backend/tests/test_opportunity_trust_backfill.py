import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.opportunity_trust_backfill import backfill_opportunity_trust


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, *_args, **_kwargs):
        return self

    def skip(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    async def to_list(self):
        return self._rows


class TestOpportunityTrustBackfill(unittest.IsolatedAsyncioTestCase):
    async def test_backfill_preserves_manual_review_status(self) -> None:
        reviewed_row = SimpleNamespace(
            title="Manual reviewed listing",
            description="Official listing with detailed description.",
            url="https://devfolio.co/hackathons/example",
            source="devfolio",
            university="Devfolio",
            trust_status="blocked",
            trust_score=10,
            risk_score=90,
            risk_reasons=["manual review"],
            verification_evidence=["moderator note"],
            reviewed_by_user_id="admin-1",
            reviewed_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            save=AsyncMock(),
        )

        with patch(
            "app.services.opportunity_trust_backfill.Opportunity.find_many",
            side_effect=[_FakeQuery([reviewed_row]), _FakeQuery([])],
        ):
            payload = await backfill_opportunity_trust(batch_size=1)

        self.assertEqual(payload["scanned"], 1)
        self.assertEqual(reviewed_row.trust_status, "blocked")
        self.assertEqual(reviewed_row.verification_evidence, ["moderator note"])


if __name__ == "__main__":
    unittest.main()
