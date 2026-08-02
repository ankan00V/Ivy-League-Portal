import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.opportunity_quality_service import OpportunityQualityScorer


class DummyOpportunity:
    title = "Python Data Science Internship"
    description = "Build pandas and scikit-learn workflows for a remote internship. Duration 8 weeks."
    url = "https://example.com/apply"
    university = "Acme Labs"
    location = "WFH"
    work_mode = None
    stipend = "10k pm"
    deadline = "2026-07-01"
    eligibility = "2026 and 2027 batch students"
    tags = []
    duration_months = None
    duplicate_count = 0
    duplicate_cluster_key = None


class TestOpportunityQualityService(unittest.TestCase):
    def test_normalization_extracts_remote_stipend_duration_and_tags(self) -> None:
        scorer = OpportunityQualityScorer()
        normalized = scorer.normalize_payload(DummyOpportunity())

        self.assertEqual(normalized["location"], "India")
        self.assertEqual(normalized["work_mode"], "remote")
        self.assertEqual(normalized["stipend_min"], 10000)
        self.assertEqual(normalized["stipend_max"], 10000)
        self.assertEqual(normalized["stipend_currency"], "INR")
        self.assertEqual(normalized["stipend_period"], "monthly")
        self.assertEqual(normalized["duration_months"], 2.0)
        self.assertIn("python", normalized["tags"])
        self.assertIn("data science", normalized["tags"])

    def test_quality_score_penalizes_missing_apply_url_and_description(self) -> None:
        scorer = OpportunityQualityScorer()
        row = type(
            "OpportunityStub",
            (),
            {
                "title": "Thin row",
                "description": "short",
                "url": "",
                "university": "",
                "location": None,
                "work_mode": None,
                "stipend": None,
                "deadline": None,
                "eligibility": None,
                "tags": [],
                "duplicate_count": 0,
                "duplicate_cluster_key": None,
            },
        )()

        score, missing = scorer.score_payload(row, {})

        self.assertLess(score, 40)
        self.assertIn("apply_url", missing)
        self.assertIn("description", missing)
        self.assertIn("company", missing)
        self.assertIn("eligibility", missing)

    def test_quality_review_routes_missing_student_critical_fields_to_admin_queue(self) -> None:
        scorer = OpportunityQualityScorer()
        row = type(
            "OpportunityStub",
            (),
            {
                "title": "Incomplete internship",
                "description": "A complete enough description to avoid a thin-description-only review decision.",
                "url": "https://example.com/apply",
                "university": "Example Labs",
                "location": None,
                "work_mode": None,
                "stipend": None,
                "deadline": None,
                "eligibility": None,
                "batch_years": [],
                "tags": ["python"],
                "duplicate_count": 0,
                "duplicate_cluster_key": None,
            },
        )()

        score, missing = scorer.score_payload(row)
        required, reasons = scorer.review_status(row, score=score, missing=missing)

        self.assertTrue(required)
        self.assertIn("deadline", missing)
        self.assertIn("location", missing)
        self.assertIn("eligibility", missing)
        self.assertIn("Application deadline is unavailable.", reasons)
        self.assertIn("Candidate eligibility is unavailable.", reasons)

    def test_quality_review_routes_duplicate_signals_even_when_fields_are_complete(self) -> None:
        scorer = OpportunityQualityScorer()
        row = DummyOpportunity()
        row.duplicate_count = 1

        score, missing = scorer.score_payload(row)
        required, reasons = scorer.review_status(row, score=score, missing=missing)

        self.assertTrue(required)
        self.assertIn("Potential duplicate listing requires a source and canonical-record check.", reasons)


if __name__ == "__main__":
    unittest.main()
