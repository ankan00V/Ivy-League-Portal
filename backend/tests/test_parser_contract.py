import json
import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.scraper import (  # noqa: E402
    FreshersworldScraper,
    GenericOpportunityPortalScraper,
    InternshalaScraper,
    IvyLeagueRSSConnector,
    UnstopScraper,
    parse_result_from_record,
    parse_results_from_records,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "parsers"


def _fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class DummyJsonSession:
    def __init__(self, payload):
        self.payload = payload
        self.urls: list[str] = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return DummyResponse(self.payload)


class TestParserContract(unittest.TestCase):
    def test_parse_result_enriches_canonical_url_and_confidence(self) -> None:
        result = parse_result_from_record(
            {
                "title": "Software Engineer Intern",
                "description": (
                    "Hybrid internship in Bengaluru with stipend Rs. 30,000 / month, "
                    "duration 8 weeks, and eligibility for 2026 batch students."
                ),
                "url": "https://www.linkedin.com/jobs/view/software-engineer-intern-1234567890?trk=public_jobs",
                "opportunity_type": "Internship",
                "university": "LinkedIn",
                "deadline": "2026-08-01",
                "created_at": "2026-06-01",
                "tags": ["software", "internship"],
                "source": "linkedin",
            }
        )

        self.assertIsNotNone(result.item)
        assert result.item is not None
        self.assertEqual(result.item["url"], "https://www.linkedin.com/jobs/view/1234567890")
        self.assertEqual(result.item["work_mode"], "Hybrid")
        self.assertEqual(result.item["stipend"], "Rs. 30,000 / month")
        self.assertGreaterEqual(result.confidence, 0.8)
        self.assertNotIn("apply_url", result.missing_fields)
        self.assertNotIn("source_id", result.missing_fields)

    def test_internshala_fixture_extracts_complete_parse_result(self) -> None:
        soup = BeautifulSoup(_fixture_text("internshala_card.html"), "html.parser")
        rows = InternshalaScraper()._extract_cards(
            soup,
            "https://internshala.com/internships/data-science-internship/",
            "Internship",
        )

        self.assertEqual(len(rows), 1)
        result = parse_result_from_record(rows[0])
        self.assertIsNotNone(result.item)
        assert result.item is not None
        self.assertEqual(result.item["source"], "internshala")
        self.assertEqual(result.item["university"], "Acme Labs Pvt Ltd")
        self.assertEqual(
            result.item["url"],
            "https://internshala.com/internship/data-science-internship-at-acme-labs-172001",
        )
        self.assertNotIn("company", result.missing_fields)
        self.assertNotIn("apply_url", result.missing_fields)

    def test_freshersworld_fixture_extracts_job_metadata(self) -> None:
        soup = BeautifulSoup(_fixture_text("freshersworld_card.html"), "html.parser")
        rows = FreshersworldScraper()._extract_cards(soup)

        self.assertEqual(len(rows), 1)
        result = parse_result_from_record(rows[0])
        self.assertIsNotNone(result.item)
        assert result.item is not None
        self.assertEqual(result.item["source"], "freshersworld")
        self.assertEqual(result.item["title"], "Software Engineer Trainee")
        self.assertEqual(result.item["location"], "Bengaluru")
        self.assertEqual(result.item["stipend"], "Rs. 4,00,000 / year")
        self.assertIn(2026, result.item["batch_years"])

    def test_generic_priority_cards_extract_linkedin_and_hackerearth(self) -> None:
        soup = BeautifulSoup(_fixture_text("generic_priority_cards.html"), "html.parser")
        scraper = GenericOpportunityPortalScraper()

        linkedin_rows = scraper._extract_from_source_cards(
            soup=soup,
            listing_url="https://www.linkedin.com/jobs/search/",
            source_name="linkedin",
            default_type="Job",
            default_university="LinkedIn Recruiters",
        )
        hackerearth_rows = scraper._extract_from_source_cards(
            soup=soup,
            listing_url="https://www.hackerearth.com/challenges/hackathon/",
            source_name="hackerearth",
            default_type="Competition",
            default_university="HackerEarth",
        )

        linkedin_results = parse_results_from_records(linkedin_rows)
        hackerearth_results = parse_results_from_records(hackerearth_rows)
        self.assertEqual(linkedin_results[0].item["url"], "https://www.linkedin.com/jobs/view/1234567890")
        self.assertEqual(linkedin_results[0].item["location"], "Bengaluru")
        self.assertEqual(hackerearth_results[0].item["source"], "hackerearth")
        self.assertIsNotNone(hackerearth_results[0].item["deadline"])

    def test_ycombinator_and_promilo_card_profiles_extract_metadata(self) -> None:
        scraper = GenericOpportunityPortalScraper()
        yc_rows = scraper._extract_from_source_cards(
            soup=BeautifulSoup(_fixture_text("ycombinator_jobs_card.html"), "html.parser"),
            listing_url="https://www.ycombinator.com/jobs",
            source_name="ycombinator_jobs",
            default_type="Job",
            default_university="Y Combinator Startups",
        )
        promilo_rows = scraper._extract_from_source_cards(
            soup=BeautifulSoup(_fixture_text("promilo_card.html"), "html.parser"),
            listing_url="https://promilo.com/",
            source_name="promilo",
            default_type="Job",
            default_university="Promilo",
        )

        yc_result = parse_result_from_record(yc_rows[0])
        promilo_result = parse_result_from_record(promilo_rows[0])

        self.assertEqual(yc_result.item["source"], "ycombinator_jobs")
        self.assertEqual(yc_result.item["university"], "Acme AI")
        self.assertEqual(yc_result.item["location"], "Remote")
        self.assertIn(2026, yc_result.item["batch_years"])
        self.assertEqual(promilo_result.item["source"], "promilo")
        self.assertEqual(promilo_result.item["university"], "Promilo Partner")
        self.assertEqual(promilo_result.item["location"], "Mumbai")
        self.assertEqual(promilo_result.item["stipend"], "Rs. 20,000 / month")

    def test_unstop_json_fixture_and_ivy_rss_parse(self) -> None:
        payload = json.loads(_fixture_text("unstop_search.json"))
        unstop_rows = UnstopScraper(session=DummyJsonSession(payload)).fetch_unstop_opportunities(max_items=1)
        self.assertEqual(len(unstop_rows), 1)
        unstop_result = parse_result_from_record(unstop_rows[0])
        self.assertEqual(unstop_result.item["source"], "unstop")
        self.assertEqual(unstop_result.item["university"], "Unstop")
        self.assertTrue(unstop_result.item["url"].startswith("https://unstop.com/hackathons/"))

        feed_entries = IvyLeagueRSSConnector()._parse_feed(_fixture_text("ivy_rss.xml"))
        self.assertEqual(len(feed_entries), 1)
        rss_result = parse_result_from_record(
            {
                "title": feed_entries[0]["title"],
                "description": feed_entries[0]["description"],
                "url": feed_entries[0]["link"],
                "opportunity_type": "Research",
                "university": "Example University",
                "deadline": "2026-06-30",
                "created_at": feed_entries[0]["published_at"],
                "tags": ["research", "fellowship"],
                "source": "ivy_rss",
            }
        )
        self.assertNotIn("posted_date", rss_result.missing_fields)
        self.assertEqual(rss_result.item["source"], "ivy_rss")


if __name__ == "__main__":
    unittest.main()
