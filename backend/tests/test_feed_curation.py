import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.api_v1.endpoints.opportunities import (
    _decode_page_token,
    _diversify_by_source,
    _diversify_feed_page,
    _encode_page_token,
    _feed_priority,
)
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

    def test_feed_page_token_round_trips_offset(self) -> None:
        token = _encode_page_token(40)

        self.assertEqual(_decode_page_token(token), 40)
        self.assertEqual(_decode_page_token(None), 0)

    def test_diversify_feed_page_limits_source_and_domain_repetition(self) -> None:
        now = utc_now()
        ranked = [
            {
                "opportunity": SimpleNamespace(
                    source="linkedin",
                    domain="software",
                    last_seen_at=now,
                    updated_at=now,
                    created_at=now,
                ),
                "match_score": 100 - idx,
            }
            for idx in range(5)
        ]
        ranked.extend(
            [
                {
                    "opportunity": SimpleNamespace(
                        source="devfolio",
                        domain="design",
                        last_seen_at=now,
                        updated_at=now,
                        created_at=now,
                    ),
                    "match_score": 90,
                },
                {
                    "opportunity": SimpleNamespace(
                        source="wellfound",
                        domain="data",
                        last_seen_at=now,
                        updated_at=now,
                        created_at=now,
                    ),
                    "match_score": 89,
                },
            ]
        )

        page = _diversify_feed_page(ranked, offset=0, limit=5)
        sources = [item["opportunity"].source for item in page]

        self.assertEqual(len(set(sources[:3])), 3)
        self.assertEqual(len(page), 5)


if __name__ == "__main__":
    unittest.main()
