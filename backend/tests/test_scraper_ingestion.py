import unittest
from datetime import datetime, timedelta
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.scraper import _dedupe_by_url, _extract_deadline_from_text, is_opportunity_active
from app.core.time import utc_now
from app.services.opportunity_trust import (
    TRUST_STATUS_BLOCKED,
    TRUST_STATUS_NEEDS_REVIEW,
    TRUST_STATUS_VERIFIED,
    assess_opportunity_trust,
)


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

    def test_assess_opportunity_trust_blocks_fee_based_opportunities(self) -> None:
        assessment = assess_opportunity_trust(
            {
                "title": "Internship with registration fee",
                "description": "Pay Rs 999 application fee via UPI to secure your internship slot today.",
                "url": "https://random-opportunity-example.com/apply",
                "source": "manual",
                "university": "Unknown",
            }
        )
        self.assertEqual(assessment.trust_status, TRUST_STATUS_BLOCKED)
        self.assertGreaterEqual(assessment.risk_score, 75)

    def test_assess_opportunity_trust_verifies_established_sources(self) -> None:
        assessment = assess_opportunity_trust(
            {
                "title": "Official Hackathon",
                "description": "Established public hackathon with published dates, organizer info, and eligibility details for students.",
                "url": "https://devfolio.co/hackathons/example",
                "source": "devfolio",
                "university": "Devfolio",
            }
        )
        self.assertEqual(assessment.trust_status, TRUST_STATUS_VERIFIED)
        self.assertLess(assessment.risk_score, 45)

    def test_assess_opportunity_trust_verifies_new_allowlisted_sources(self) -> None:
        assessment = assess_opportunity_trust(
            {
                "title": "Startup internship listing",
                "description": "Published startup internship with role details, published host identity, and a clear application path for students.",
                "url": "https://www.instahyre.com/job/example-role/",
                "source": "instahyre",
                "university": "Instahyre",
            }
        )
        self.assertEqual(assessment.trust_status, TRUST_STATUS_VERIFIED)
        self.assertLess(assessment.risk_score, 45)

    def test_assess_opportunity_trust_flags_source_host_mismatch(self) -> None:
        assessment = assess_opportunity_trust(
            {
                "title": "Devfolio hackathon clone",
                "description": "Hackathon listing with copied branding and enough text to avoid thin-description penalties for this check.",
                "url": "https://fake-devfolio-event.xyz/register",
                "source": "devfolio",
                "university": "Devfolio",
            }
        )
        self.assertIn(assessment.trust_status, {TRUST_STATUS_NEEDS_REVIEW, TRUST_STATUS_BLOCKED})
        self.assertGreaterEqual(assessment.risk_score, 45)


if __name__ == "__main__":
    unittest.main()
