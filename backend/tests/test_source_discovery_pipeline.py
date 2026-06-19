import asyncio
import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.source_discovery import (  # noqa: E402
    AdaptiveExtractionService,
    DiscoveryCandidate,
    DiscoveryQueryContext,
    FetchedPage,
    LocalMemoryQueue,
    SearchQueryGenerator,
    SourcePriorityScorer,
    SourceQualificationService,
    _company_seed_due_sort_key,
    _extract_json_object,
    normalize_domain,
    normalize_url,
)
from app.models.source_discovery import DiscoveryMethod  # noqa: E402
from app.services.company_careers_intelligence import (  # noqa: E402
    CompanyCareersIntelligenceService,
    _clean_title,
    _is_early_career,
    _seed_due_sort_key,
)


class TestSourceDiscoveryPipeline(unittest.TestCase):
    def test_normalize_url_strips_tracking_and_www(self) -> None:
        self.assertEqual(
            normalize_url("https://www.example.com/jobs/123/?utm_source=x&gclid=y&role=intern"),
            "https://example.com/jobs/123?role=intern",
        )
        self.assertEqual(normalize_domain("https://www.Example.com/path"), "example.com")

    def test_spam_signal_hard_rejects_bad_tld(self) -> None:
        result = SourceQualificationService()._spam_signals_check("fake-board.xyz", "<html></html>")
        self.assertFalse(result.passed)
        self.assertTrue(result.hard_reject)
        self.assertEqual(result.score, 0)

    def test_schema_org_mapping_extracts_core_fields(self) -> None:
        service = AdaptiveExtractionService()
        row = service._map_schema_job(
            {
                "@type": "JobPosting",
                "title": "Software Engineering Intern",
                "hiringOrganization": {"name": "Acme"},
                "jobLocation": {
                    "address": {
                        "addressLocality": "Bangalore",
                        "addressRegion": "Karnataka",
                        "addressCountry": "India",
                    }
                },
                "url": "/apply/intern",
                "description": "<p>Build production systems for students.</p>",
            },
            "https://careers.acme.test/jobs",
        )
        self.assertEqual(row["title"], "Software Engineering Intern")
        self.assertEqual(row["company"], "Acme")
        self.assertEqual(row["location"], "Bangalore, Karnataka, India")
        self.assertEqual(row["apply_url"], "https://careers.acme.test/apply/intern")
        self.assertEqual(row["opportunity_type"], "internship")

    def test_overall_confidence_rewards_complete_safe_rows(self) -> None:
        service = AdaptiveExtractionService()
        score = service._overall_confidence(
            0.9,
            [
                {
                    "title": "Data Science Intern",
                    "company": "Acme",
                    "location": "Remote India",
                    "apply_url": "https://acme.test/jobs/1",
                    "description_preview": "Student internship with clear application path.",
                    "opportunity_type": "internship",
                }
            ],
        )
        self.assertGreaterEqual(score, 0.7)

    def test_llm_json_recovery_accepts_wrapped_object(self) -> None:
        parsed = _extract_json_object(
            "Here is the JSON:\n"
            '{"opportunities": [{"title": "ML Intern"}], "extraction_confidence": 0.82}\n'
            "Done."
        )
        self.assertEqual(parsed["opportunities"][0]["title"], "ML Intern")
        self.assertEqual(parsed["extraction_confidence"], 0.82)

    def test_local_memory_queue_preserves_fifo_and_daily_counts(self) -> None:
        async def run() -> None:
            queue = LocalMemoryQueue()
            await queue.push("source-q", "first")
            await queue.push("source-q", "second")
            self.assertEqual(await queue.pop_batch("source-q", max_items=1), ["first"])
            self.assertEqual(await queue.pop_batch("source-q", max_items=10), ["second"])
            self.assertEqual(await queue.increment_daily("submission-key"), 1)
            self.assertEqual(await queue.increment_daily("submission-key"), 2)

        asyncio.run(run())

    def test_bootstrap_seed_dataset_has_unique_curated_official_domains(self) -> None:
        script = BACKEND_ROOT / "scripts" / "bootstrap_company_seeds.py"
        spec = importlib.util.spec_from_file_location("bootstrap_company_seeds", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        rows = module.initial_company_seeds()
        domains = [row["domain"] for row in rows]
        self.assertGreaterEqual(len(rows), 230)
        self.assertEqual(len(set(domains)), len(domains))
        self.assertIn("cisco.com", domains)
        self.assertIn("servicenow.com", domains)
        self.assertIn("google.com", domains)
        self.assertIn("airbus.com", domains)
        self.assertIn("pepsicojobs.com", domains)

        google = next(row for row in rows if row["domain"] == "google.com")
        self.assertEqual(google["priority_tier"], "tier_1")
        self.assertEqual(google["source_category"], "global_tech")
        self.assertEqual(google["check_cadence_hours"], 24)
        self.assertNotIn("utm_", google["careers_url"])

    def test_company_seed_due_sort_prioritizes_due_tier_one_rows(self) -> None:
        now = datetime(2026, 6, 18, tzinfo=timezone.utc)
        due_tier_one = SimpleNamespace(priority_tier="tier_1", check_cadence_hours=24, last_checked_at=None)
        due_standard = SimpleNamespace(priority_tier=None, check_cadence_hours=24, last_checked_at=None)
        fresh_tier_one = SimpleNamespace(priority_tier="tier_1", check_cadence_hours=24, last_checked_at=now)

        ordered = sorted([fresh_tier_one, due_standard, due_tier_one], key=lambda row: _seed_due_sort_key(row, now))
        self.assertIs(ordered[0], due_tier_one)
        self.assertIs(ordered[1], due_standard)
        self.assertIs(ordered[2], fresh_tier_one)

    def test_discovery_seed_due_sort_prioritizes_watchlist_cadence(self) -> None:
        now = datetime(2026, 6, 18, tzinfo=timezone.utc)
        daily_watchlist = SimpleNamespace(
            priority_tier="tier_1",
            check_cadence_hours=24,
            last_checked_at=None,
            company_name="Google",
        )
        weekly_standard = SimpleNamespace(
            priority_tier=None,
            check_cadence_hours=168,
            last_checked_at=None,
            company_name="Acme",
        )
        ordered = sorted([weekly_standard, daily_watchlist], key=lambda row: _company_seed_due_sort_key(row, now))
        self.assertIs(ordered[0], daily_watchlist)

    def test_priority_scorer_rewards_official_student_careers(self) -> None:
        scorer = SourcePriorityScorer()
        context = DiscoveryQueryContext(profile_terms=["machine learning"], opportunity_terms=["software engineering"])
        seed = SimpleNamespace(
            domain="google.com",
            priority_tier="tier_1",
            source_category="global_tech",
            check_cadence_hours=24,
        )
        official = scorer.score_candidate(
            DiscoveryCandidate(
                url="https://careers.google.com/students",
                method=DiscoveryMethod.company_seed,
                discovery_query="Google",
                name="Google Students",
                source_type="company_careers",
            ),
            normalized_url="https://careers.google.com/students",
            domain="careers.google.com",
            source_type="company_careers",
            company_seed=seed,
            query_context=context,
        )
        generic = scorer.score_candidate(
            DiscoveryCandidate(
                url="https://example.com/blog/resume-tips",
                method=DiscoveryMethod.web_search,
                discovery_query="resume tips internship",
                name="Resume tips",
            ),
            normalized_url="https://example.com/blog/resume-tips",
            domain="example.com",
            source_type="job_board",
            query_context=context,
        )
        self.assertGreaterEqual(official.score, 90)
        self.assertGreater(official.score, generic.score + 25)
        self.assertIn("official_company_seed", official.reasons)
        self.assertIn("low_value_content_penalty", generic.reasons)

    def test_search_query_generator_uses_data_and_platform_queries(self) -> None:
        generator = SearchQueryGenerator(queue=LocalMemoryQueue())
        context = DiscoveryQueryContext(
            profile_terms=["robotics"],
            opportunity_terms=["machine learning"],
            platform_terms=["hackathon"],
            tech_stacks=["python"],
        )
        queries = generator.candidate_queries(context)
        self.assertTrue(any("student internship platform india" in query for query in queries))
        self.assertTrue(any("robotics internship india official careers" == query for query in queries))
        self.assertTrue(any("machine learning fresher jobs india 0-1 years" == query for query in queries))

    def test_company_careers_endpoint_detection_from_official_page(self) -> None:
        service = CompanyCareersIntelligenceService()
        page = FetchedPage(
            url="https://careers.example.com",
            final_url="https://careers.example.com",
            status_code=200,
            text='<a href="https://jobs.lever.co/acme">Open roles</a>',
            elapsed_seconds=0.1,
        )
        endpoints = service._endpoints_from_page(page)
        self.assertEqual(endpoints[0].method, "lever")
        self.assertEqual(endpoints[0].slug, "acme")
        self.assertIn("api.lever.co", endpoints[0].url)

    def test_company_careers_greenhouse_mapping_and_scope_gate(self) -> None:
        service = CompanyCareersIntelligenceService()
        seed = SimpleNamespace(
            company_name="Acme",
            domain="acme.com",
            careers_url="https://careers.acme.com",
            industry="technology",
            company_size="enterprise",
        )
        rows = service._map_greenhouse(
            seed,
            {
                "jobs": [
                    {
                        "title": "Software Engineering Intern",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                        "location": {"name": "Remote India"},
                        "content": "<p>Student internship building production systems.</p>",
                        "departments": [{"name": "Engineering"}],
                    },
                    {
                        "title": "Senior Staff Engineer",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
                        "location": {"name": "Remote"},
                        "content": "<p>Requires 8+ years of experience.</p>",
                    },
                ]
            },
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(_is_early_career(rows[0]))
        self.assertFalse(_is_early_career(rows[1]))

    def test_company_careers_official_page_heuristic_extracts_student_links(self) -> None:
        service = CompanyCareersIntelligenceService()
        seed = SimpleNamespace(
            company_name="Acme",
            domain="acme.com",
            careers_url="https://careers.acme.com",
            industry="technology",
            company_size="enterprise",
        )
        rows = service.extract_official_page_links(
            seed,
            FetchedPage(
                url="https://careers.acme.com",
                final_url="https://careers.acme.com",
                status_code=200,
                text='<a href="/students/software-intern">Software Engineering Internship Program</a>',
                elapsed_seconds=0.1,
            ),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["apply_url"], "https://careers.acme.com/students/software-intern")
        self.assertEqual(rows[0]["opportunity_type"], "Internship")

    def test_company_careers_title_cleaner_removes_noise_and_contextualizes_generic_titles(self) -> None:
        self.assertEqual(
            _clean_title("noogler_hat noogler_hat Students Students", company_name="Google"),
            "Google Student and Internship Programs",
        )
        self.assertEqual(
            _clean_title("Students", company_name="Apple"),
            "Apple Student and Internship Programs",
        )


if __name__ == "__main__":
    unittest.main()
