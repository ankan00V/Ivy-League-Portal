import asyncio
import re
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.scraper import (
    GenericOpportunityPortalScraper,
    GreenhouseScraper,
    _collect_fetch_batch_results,
    _dedupe_by_url,
    _enrich_metadata,
    _expire_opportunities,
    _extract_batch_years,
    _extract_deadline_from_text,
    _extract_stipend,
    _extract_work_mode,
    _parse_datetime,
    is_valid_apply_url,
    is_early_career_opportunity,
    is_probable_opportunity_posting,
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

    def test_early_career_gate_ignores_seniority_words_in_description(self) -> None:
        """Descriptions routinely name senior colleagues without the role being senior.

        Matching seniority nouns against the description rejected the majority of
        legitimate internships, so the exclusion is scoped to title/eligibility.
        """
        for description in (
            "You will work alongside senior engineers on production services.",
            "Graduate trainee reporting to the engineering manager.",
            "Software development intern - you will lead small projects.",
            "Cloud intern working with our solution architect team.",
            "Join our staff of 200 engineers.",
        ):
            with self.subTest(description=description):
                self.assertTrue(
                    is_early_career_opportunity(
                        {
                            "title": "Software Engineering Intern",
                            "description": description,
                            "opportunity_type": "Job",
                        }
                    )
                )

    def test_early_career_gate_accepts_zero_and_one_anchored_year_ranges(self) -> None:
        """`0-2 years` is the most common fresher phrasing and must not be rejected."""
        for description in (
            "Experience: 0-2 years",
            "Looking for candidates with 0 to 3 years of experience.",
            "1-2 years experience welcome.",
            "Experience: 0 - 2 years",
        ):
            with self.subTest(description=description):
                self.assertTrue(
                    is_early_career_opportunity(
                        {
                            "title": "Software Engineer Trainee",
                            "description": description,
                            "opportunity_type": "Job",
                        }
                    )
                )

    def test_early_career_gate_still_rejects_explicit_multi_year_demands(self) -> None:
        for description in (
            "We need 5+ years of backend experience.",
            "At least 4 years building distributed systems.",
            "Guaranteed placement bootcamp with paid enrollment.",
        ):
            with self.subTest(description=description):
                self.assertFalse(
                    is_early_career_opportunity(
                        {
                            "title": "Backend Developer",
                            "description": description,
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

    def test_tensorhack_profiles_parse_hackathon_and_new_grad_rows(self) -> None:
        from bs4 import BeautifulSoup

        scraper = GenericOpportunityPortalScraper(source_configs=[])
        hackathon_soup = BeautifulSoup(
            """
            <div class="board-grid">
              <a class="hk-card" href="/hackathons/devpost-global-ai-hackathon-series-with-qwen-cloud">
                <div class="hk-meta mono">02 / online / &lt; 01d left &gt;</div>
                <div class="hk-body">
                  <h3 class="hk-name display">Global AI Hackathon Series With Qwen Cloud</h3>
                  <p class="hk-org mono">Alibaba Cloud</p>
                </div>
                <div class="hk-foot">
                  <span class="hk-prize mono">$45K prize</span>
                  <span class="hk-tags mono">MACHINE LEARNING/AI · DESIGN</span>
                </div>
              </a>
            </div>
            """,
            "html.parser",
        )
        hackathon_rows = scraper._extract_from_source_cards(
            soup=hackathon_soup,
            listing_url="https://tensorhack.com/hackathons",
            source_name="tensorhack_hackathons",
            default_type="Hackathon",
            default_university="TensorHack",
        )
        self.assertEqual(len(hackathon_rows), 1)
        self.assertEqual(hackathon_rows[0]["source"], "tensorhack_hackathons")
        self.assertEqual(hackathon_rows[0]["title"], "Global AI Hackathon Series With Qwen Cloud")
        self.assertEqual(hackathon_rows[0]["university"], "Alibaba Cloud")
        self.assertEqual(
            hackathon_rows[0]["url"],
            "https://tensorhack.com/hackathons/devpost-global-ai-hackathon-series-with-qwen-cloud",
        )

        jobs_soup = BeautifulSoup(
            """
            <a class="job-row" href="/jobs/ashby-notion-7e6dc7fe">
              <div class="job-main">
                <span class="job-role display">Software Engineer, New Grad (AI)</span>
                <span class="job-co mono">Notion · San Francisco, California · Remote</span>
              </div>
              <div class="job-right">
                <span class="job-tags mono">PRODUCTIVITY · FRONTEND · AI</span>
                <span class="job-comp mono"></span>
              </div>
            </a>
            <a class="job-row" href="/jobs/lever-fampay-manager">
              <div class="job-main">
                <span class="job-role display">IT Manager</span>
                <span class="job-co mono">FamPay · Bengaluru · On-site</span>
              </div>
              <div class="job-right">
                <span class="job-tags mono">FINTECH · CONSUMER · INDIA</span>
              </div>
            </a>
            """,
            "html.parser",
        )
        job_rows = scraper._extract_from_source_cards(
            soup=jobs_soup,
            listing_url="https://tensorhack.com/jobs",
            source_name="tensorhack_jobs",
            default_type="Job",
            default_university="TensorHack",
        )
        early_career_rows = [row for row in job_rows if is_early_career_opportunity(row)]
        self.assertEqual([row["title"] for row in early_career_rows], ["Software Engineer, New Grad (AI)"])
        self.assertTrue(early_career_rows[0]["url"].startswith("https://tensorhack.com/jobs/"))

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


class TestScraperFetchBatchTimeout(unittest.IsolatedAsyncioTestCase):
    async def test_completed_results_are_preserved_when_a_sibling_times_out(self) -> None:
        started = asyncio.Event()

        async def completed() -> list[str]:
            return ["fresh"]

        async def blocked() -> list[str]:
            started.set()
            await asyncio.Event().wait()
            return []

        results = await _collect_fetch_batch_results(
            [completed(), blocked()],
            batch_name="test_sources",
            timeout_seconds=0.01,
        )

        self.assertTrue(started.is_set())
        self.assertEqual(results[0], ["fresh"])
        self.assertIsInstance(results[1], TimeoutError)
        self.assertIn("test_sources fetch timed out", str(results[1]))


class TestPaymentPatternPrecision(unittest.TestCase):
    """Fee-scam detection must not fire on ordinary posting language.

    `\\bwallet|upi|...\\b` anchored only its first and last alternatives, so a
    bare "upi" matched inside words like "occupied"; and `pay\\s+\\d+` matched
    legitimate stipend disclosures. Both scored +55 risk and hid the posting.
    """

    def _flagged(self, text: str) -> bool:
        from app.services.opportunity_trust import PAYMENT_PATTERNS

        return any(re.search(pattern, text, re.IGNORECASE) for pattern in PAYMENT_PATTERNS)

    def test_legitimate_postings_are_not_flagged(self) -> None:
        for text in (
            "The role is currently occupied by a contractor.",
            "We pay 25000 per month stipend.",
            "Stipend: pay 15000 INR monthly.",
            "Laptop and equipment provided at no cost.",
        ):
            with self.subTest(text=text):
                self.assertFalse(self._flagged(text))

    def test_fee_scam_signals_are_still_flagged(self) -> None:
        for text in (
            "Send money to our paytm wallet.",
            "Pay Rs 500 registration fee.",
            "pay 500 to apply for this role",
            "A non-refundable deposit is required.",
            "Application fee of 200.",
            "transfer via upi to confirm your seat",
        ):
            with self.subTest(text=text):
                self.assertTrue(self._flagged(text))


class TestInternshalaListingBudget(unittest.TestCase):
    """Every configured Internshala listing must be requested.

    The two job listings are declared first; filling the item budget greedily in
    order meant the internship listings were never fetched, so India's largest
    internship board contributed zero internships.
    """

    def test_all_listings_are_requested_including_internships(self) -> None:
        import app.services.scraper as scraper_module

        requested: list[str] = []

        def fake_fetch(url: str, *, render: bool = True):
            requested.append(url)
            cards = "".join(
                f'<div class="internship_meta"><h3><a href="/x/{i}">Role {i}</a></h3>'
                f'<div class="company_name">Acme</div></div>'
                for i in range(40)
            )
            return SimpleNamespace(text=f"<html><body>{cards}</body></html>",
                                   status_code=200, final_url=url)

        original = scraper_module._fetch_listing_page
        scraper_module._fetch_listing_page = fake_fetch
        try:
            scraper_module.internshala_scraper.fetch_live_opportunities(max_items=30)
        finally:
            scraper_module._fetch_listing_page = original

        self.assertEqual(len(requested), len(scraper_module.INTERNSHALA_LISTINGS))
        internship_listings = [
            url for url, kind in scraper_module.INTERNSHALA_LISTINGS if kind == "Internship"
        ]
        self.assertTrue(internship_listings, "config should declare internship listings")
        for url in internship_listings:
            self.assertIn(url, requested)


class TestExpiryIsNonDestructive(unittest.IsolatedAsyncioTestCase):
    """Past-deadline rows must be retired by status, never hard-deleted.

    Most deadlines in the corpus are synthetic (`now + 30 days`), so deleting on
    that basis destroyed rows that had not genuinely closed.
    """

    class _FakeOpportunity:
        def __init__(self, status: str = "active") -> None:
            self.id = "fake-id"
            self.opportunity_status = status
            self.updated_at = None
            self.saved = False
            self.deleted = False

        async def save(self) -> None:
            self.saved = True

        async def delete(self) -> None:  # pragma: no cover - must never run
            self.deleted = True
            raise AssertionError("expiry must not hard-delete opportunities")

    async def test_past_deadline_row_is_marked_expired_not_deleted(self) -> None:
        record = self._FakeOpportunity()

        marked = await _expire_opportunities([record])

        self.assertEqual(marked, 1)
        self.assertEqual(record.opportunity_status, "expired")
        self.assertTrue(record.saved)
        self.assertFalse(record.deleted)

    async def test_already_retired_rows_are_not_rewritten(self) -> None:
        for status in ("expired", "filled", "removed"):
            with self.subTest(status=status):
                record = self._FakeOpportunity(status=status)
                marked = await _expire_opportunities([record])
                self.assertEqual(marked, 0)
                self.assertFalse(record.saved)

    async def test_duplicate_records_are_only_counted_once(self) -> None:
        record = self._FakeOpportunity()

        marked = await _expire_opportunities([record, record])

        self.assertEqual(marked, 1)


if __name__ == "__main__":
    unittest.main()


class TestStipendExtraction(unittest.TestCase):
    """Stipend was populated on 0 of 364 active opportunities.

    The old patterns anchored the currency with \\b, but "₹" is a non-word
    character so \\b could never match before it - excluding most Indian
    postings outright. There was also no form for amount-then-currency, a
    labelled bare amount, lakh/LPA notation, or an explicit "unpaid".
    """

    def test_extracts_common_indian_stipend_formats(self) -> None:
        for text, expected_fragment in (
            ("Stipend: Rs. 15000 per month", "15000"),
            ("₹25,000/month stipend", "25,000"),
            ("Stipend 10000 INR monthly", "10000"),
            ("Paid internship with stipend of 20000", "20000"),
            ("CTC 6 LPA for selected candidates", "6 LPA"),
            ("Salary: ₹4,00,000 - ₹6,00,000 per annum", "4,00,000"),
            ("Stipend 20k/month", "20k"),
            ("25,000 rupees per month", "25,000"),
        ):
            with self.subTest(text=text):
                extracted = _extract_stipend(text)
                self.assertIsNotNone(extracted, f"no stipend extracted from {text!r}")
                self.assertIn(expected_fragment.lower(), str(extracted).lower())

    def test_records_explicitly_unpaid_roles(self) -> None:
        for text in ("This is an unpaid internship", "No stipend will be provided"):
            with self.subTest(text=text):
                self.assertIsNotNone(_extract_stipend(text))

    def test_does_not_invent_a_stipend_from_prose(self) -> None:
        for text in (
            "competitive salary",
            "salary: 2 years experience required",
            "We offer growth and mentorship",
            "apply within 3 days",
        ):
            with self.subTest(text=text):
                self.assertIsNone(_extract_stipend(text))


class TestOpportunityTypeCanonicalisation(unittest.TestCase):
    """Plurals were stored as distinct types, splitting filters and portals.

    The corpus held Hackathon (31) and Hackathons (18) separately, so a student
    filtering hackathons saw roughly half of them.
    """

    def test_plurals_collapse_to_one_spelling(self) -> None:
        from app.services.opportunity_visibility import canonical_opportunity_type

        for raw, expected in (
            ("Hackathons", "Hackathon"),
            ("hackathon", "Hackathon"),
            ("Conferences", "Conference"),
            ("Internships", "Internship"),
            ("jobs", "Job"),
            ("Scholarships", "Scholarship"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(canonical_opportunity_type(raw), expected)

    def test_ingestion_canonicalises_the_type(self) -> None:
        enriched = _enrich_metadata(
            {
                "title": "Some Event",
                "university": "Acme",
                "url": "https://acme.example/1",
                "opportunity_type": "Hackathons",
                "description": "d",
            }
        )
        self.assertEqual(enriched["opportunity_type"], "Hackathon")

    def test_currency_token_must_not_match_inside_a_word(self) -> None:
        """"yea[rs]," previously yielded a stipend of "rs,".

        Dropping \\b to support "₹" (a non-word character) let "rs" match inside
        ordinary words, so a negative lookbehind guards the currency instead.
        """
        for text in (
            "3 years, strong communication skills",
            "Requires 2 years, a degree, and initiative",
            "Team Leader with 5 years, experience",
        ):
            with self.subTest(text=text):
                self.assertIsNone(_extract_stipend(text))


class TestNonPostingGate(unittest.TestCase):
    """About a quarter of the active corpus was not an opportunity at all.

    Generic anchor extraction harvests a listing page's chrome alongside its
    rows, so nav links, help centres, login pages, marketing and university
    newsroom articles were ingested and shown to students as opportunities.
    """

    def test_rejects_navigation_and_marketing_chrome(self) -> None:
        for title, url in (
            ("Or see all categories", "https://www.wayup.com/s/internships/all"),
            ("Careers help center", "https://support.joinhandshake.com/hc/en-us"),
            ("intern salaries in Coimbatore", "https://www.glassdoor.co.in/Salaries/x.htm"),
            ("Employer/Post Internship", "https://internship.aicte-india.org/login_new.php"),
            ("Host a public hackathon", "https://info.devpost.com/product/public-hackathons"),
            ("Register Now", "https://hack2skill.com/event/x"),
            ("Internship in Delhi", "https://internshala.com/internship/internship-in-delhi"),
            ("Students's Corner", "https://www.barc.gov.in/students/index.html"),
        ):
            with self.subTest(title=title):
                self.assertFalse(is_probable_opportunity_posting({"title": title, "url": url}))

    def test_rejects_newsroom_articles_about_past_awards(self) -> None:
        """An article about someone who already won an award is not applyable."""
        for title, url in (
            (
                "Lilia Burtonpatel and Ram Narayanan named Goldwater Scholars",
                "https://www.princeton.edu/news/2026/05/26/x",
            ),
            (
                "Cornell Atkinson announces $1.24M in joint EDF grants",
                "https://news.cornell.edu/stories/2026/04/x",
            ),
            (
                "Graduate Hooding 2026: 'Your bold scholarship'",
                "https://www.princeton.edu/news/2026/05/26/y",
            ),
        ):
            with self.subTest(title=title):
                self.assertFalse(is_probable_opportunity_posting({"title": title, "url": url}))

    def test_keeps_genuine_postings(self) -> None:
        for title, url in (
            ("Software Engineering Intern", "https://job-boards.greenhouse.io/cloudflare/jobs/8013562"),
            ("Software Engineer, New Grad", "https://jobs.lever.co/notion/abc-123"),
            ("Governance, Risk, and Compliance Intern", "https://jobs.ashbyhq.com/notion/xyz"),
            ("R&D Engineer Intern", "https://internshala.com/internship/detail/rd-intern-12345"),
            ("Agentic Commerce Hackathon", "https://devfolio.co/hackathons/agentic-commerce"),
            ("Python Internship", "https://in.indeed.com/rc/clk?jk=abc123"),
        ):
            with self.subTest(title=title):
                self.assertTrue(is_probable_opportunity_posting({"title": title, "url": url}))

    def test_rejects_bare_host_with_no_path(self) -> None:
        self.assertFalse(
            is_probable_opportunity_posting({"title": "Acme Careers", "url": "https://acme.com"})
        )
