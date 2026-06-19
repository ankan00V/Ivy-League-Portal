import unittest
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.scraper import (
    GreenhouseScraper,
    _dedupe_by_url,
    _extract_batch_years,
    _extract_deadline_from_text,
    _extract_stipend,
    _extract_work_mode,
    _parse_datetime,
    is_valid_apply_url,
    is_early_career_opportunity,
    is_opportunity_active,
)
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


class DummyResponse:
    def __init__(self, payload, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class DummySession:
    def __init__(self, payload):
        self.payload = payload
        self.urls: list[str] = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return DummyResponse(self.payload)


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

    def test_valid_apply_url_rejects_non_http_destinations(self) -> None:
        self.assertTrue(is_valid_apply_url("https://example.com/apply"))
        self.assertTrue(is_valid_apply_url("http://example.com/apply"))
        self.assertFalse(is_valid_apply_url("mailto:internship@example.com"))
        self.assertFalse(is_valid_apply_url("javascript:alert(1)"))
        self.assertFalse(is_valid_apply_url(""))

    def test_dedupe_by_url_normalizes_tracking_params_and_canonical_keys(self) -> None:
        rows = [
            {
                "url": "https://example.com/jobs/123?utm_source=test",
                "title": "Software Engineer Intern",
                "university": "Acme",
                "opportunity_type": "Internship",
                "description": "Remote stipend INR 25000 / month for batch 2026",
            },
            {
                "url": "https://example.com/jobs/123?ref=linkedin",
                "title": "Software Engineer Intern",
                "university": "Acme",
                "opportunity_type": "Internship",
                "description": "Remote stipend INR 25000 / month for batch 2026",
            },
        ]
        deduped = _dedupe_by_url(rows)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["url"], "https://example.com/jobs/123")
        self.assertEqual(deduped[0]["work_mode"], "Remote")
        self.assertEqual(deduped[0]["stipend"], "INR 25000 / month")
        self.assertEqual(deduped[0]["batch_years"], [2026])

    def test_metadata_extractors_parse_recruiter_style_fields(self) -> None:
        text = "Hybrid internship with stipend Rs. 30,000 / month open for batches 2025, 2026 and 2027."
        self.assertEqual(_extract_work_mode(text), "Hybrid")
        self.assertEqual(_extract_stipend(text), "Rs. 30,000 / month")
        self.assertEqual(_extract_batch_years(text), [2025, 2026, 2027])

    def test_extract_deadline_from_text_parses_named_date(self) -> None:
        deadline = _extract_deadline_from_text("Applications close: March 14, 2026 for the program.")
        self.assertIsNotNone(deadline)
        assert deadline is not None
        self.assertEqual(deadline.year, 2026)
        self.assertEqual(deadline.month, 3)
        self.assertEqual(deadline.day, 14)

    def test_parse_datetime_accepts_existing_datetime(self) -> None:
        parsed = _parse_datetime(datetime(2026, 3, 14, 12, 30, tzinfo=timezone.utc))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.isoformat(), "2026-03-14T12:30:00+00:00")

    def test_is_opportunity_active_rejects_expired_deadline(self) -> None:
        now = utc_now()
        active = is_opportunity_active(DummyOpportunity(deadline=now + timedelta(days=3)), now=now)
        expired = is_opportunity_active(DummyOpportunity(deadline=now - timedelta(days=1)), now=now)
        self.assertTrue(active)
        self.assertFalse(expired)

    def test_early_career_gate_allows_internships_and_zero_to_one_year_jobs(self) -> None:
        self.assertTrue(
            is_early_career_opportunity(
                {
                    "title": "Machine Learning Internship",
                    "description": "Student internship building recommendation systems.",
                    "opportunity_type": "Internship",
                }
            )
        )
        self.assertTrue(
            is_early_career_opportunity(
                {
                    "title": "Junior Data Analyst",
                    "description": "Entry-level opening for candidates with 0-1 years of experience.",
                    "opportunity_type": "Job",
                }
            )
        )

    def test_early_career_gate_rejects_senior_and_two_plus_year_jobs(self) -> None:
        self.assertFalse(
            is_early_career_opportunity(
                {
                    "title": "Senior Backend Engineer",
                    "description": "Requires 5+ years of production experience.",
                    "opportunity_type": "Job",
                }
            )
        )
        self.assertFalse(
            is_early_career_opportunity(
                {
                    "title": "Software Engineer",
                    "description": "Minimum 2 years of experience required.",
                    "opportunity_type": "Job",
                }
            )
        )

    def test_greenhouse_scraper_parses_public_jobs_api(self) -> None:
        session = DummySession(
            {
                "jobs": [
                    {
                        "title": "Software Engineering Intern",
                        "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123",
                        "content": "<p>Build student-facing systems. Remote internship.</p>",
                        "location": {"name": "Remote"},
                        "departments": [{"name": "Engineering"}],
                        "updated_at": "2026-05-01T00:00:00Z",
                    }
                ]
            }
        )
        scraper = GreenhouseScraper(session=session)
        rows = scraper.fetch_live_opportunities(max_items=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "greenhouse")
        self.assertEqual(rows[0]["title"], "Software Engineering Intern")
        self.assertEqual(rows[0]["location"], "Remote")
        self.assertEqual(rows[0]["opportunity_type"], "Internship")
        self.assertIn("boards-api.greenhouse.io", session.urls[0])

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

    def test_assess_opportunity_trust_verifies_long_tail_platform_source_match(self) -> None:
        assessment = assess_opportunity_trust(
            {
                "title": "Research Internship",
                "description": "Official research internship listing with eligibility, role details, and application instructions for students.",
                "url": "https://www.zintellect.com/Opportunity/Details/example",
                "source": "zintellect",
                "university": "Zintellect",
            }
        )
        self.assertEqual(assessment.trust_status, TRUST_STATUS_VERIFIED)
        self.assertIn("allowlisted platform", " ".join(assessment.verification_evidence))
        self.assertLess(assessment.risk_score, 45)

    def test_assess_opportunity_trust_verifies_greenhouse_source(self) -> None:
        assessment = assess_opportunity_trust(
            {
                "title": "Software Engineering Intern",
                "description": "Published role with clear responsibilities, location, and application path for candidates.",
                "url": "https://job-boards.greenhouse.io/acme/jobs/123",
                "source": "greenhouse",
                "university": "Acme",
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
