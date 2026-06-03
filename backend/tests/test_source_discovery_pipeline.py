import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.source_discovery import (  # noqa: E402
    AdaptiveExtractionService,
    LocalMemoryQueue,
    SourceQualificationService,
    _extract_json_object,
    normalize_domain,
    normalize_url,
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

    def test_bootstrap_seed_dataset_has_200_unique_domains(self) -> None:
        script = BACKEND_ROOT / "scripts" / "bootstrap_company_seeds.py"
        spec = importlib.util.spec_from_file_location("bootstrap_company_seeds", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        rows = module.initial_company_seeds()
        domains = [row["domain"] for row in rows]
        self.assertEqual(len(rows), 200)
        self.assertEqual(len(set(domains)), 200)


if __name__ == "__main__":
    unittest.main()
