import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.duplicate_detector import (  # noqa: E402
    EXACT_URL_STAGE,
    FUZZY_STAGE,
    DuplicateDetector,
)


def _row(**kwargs):
    defaults = {
        "description": "Detailed student opportunity with role scope, eligibility, and application instructions.",
        "university": "Acme Labs",
        "location": "Bengaluru",
        "opportunity_type": "Internship",
        "source": "unknown",
        "source_id": "",
        "source_ids": {},
        "seen_on": [],
        "trust_score": 50,
        "trust_status": "unreviewed",
        "quality_score": 70.0,
        "source_count": 1,
        "duplicate_count": 0,
        "dedup_score": 0.0,
        "tags": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestDuplicateDetector(unittest.IsolatedAsyncioTestCase):
    def test_exact_url_hash_match_canonicalizes_tracking_params(self) -> None:
        detector = DuplicateDetector()
        candidate = _row(
            id="candidate",
            title="Software Engineer Intern",
            url="https://example.com/jobs/123?utm_source=linkedin",
            source="linkedin",
        )
        existing = _row(
            id="existing",
            title="Software Engineer Intern",
            url="https://example.com/jobs/123",
            source="internshala",
        )

        match = detector.find_best_match(candidate, [existing])

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.stage, EXACT_URL_STAGE)
        self.assertEqual(match.score, 1.0)

    def test_fuzzy_match_selects_higher_trust_source_as_canonical(self) -> None:
        detector = DuplicateDetector()
        candidate = _row(
            id="candidate",
            title="Data Science Internship",
            url="https://www.linkedin.com/jobs/view/1234567890",
            source="linkedin",
            source_id="linkedin-123",
            trust_score=85,
            trust_status="verified",
            quality_score=92.0,
        )
        existing = _row(
            id="existing",
            title="Data Science Intern",
            url="https://example.org/jobs/ds-intern",
            source="unknown",
            source_id="manual-1",
            trust_score=45,
            trust_status="unreviewed",
            quality_score=65.0,
        )

        match = detector.find_best_match(candidate, [existing])

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.stage, FUZZY_STAGE)
        self.assertIs(match.canonical, candidate)
        self.assertIs(match.duplicate, existing)

    async def test_merge_duplicate_rolls_up_source_metadata_without_event(self) -> None:
        detector = DuplicateDetector()
        canonical = _row(
            id="canonical",
            title="AI Product Hackathon",
            url="https://unstop.com/hackathons/ai-product-hackathon-1001",
            source="unstop",
            source_id="unstop-1001",
            source_ids={"unstop": ["unstop-1001"]},
            seen_on=["unstop"],
            tags=["ai"],
            duplicate_count=1,
        )
        duplicate = _row(
            id="duplicate",
            title="AI Product Hackathon",
            url="https://www.hackerearth.com/challenges/hackathon/ai-product-hackathon/",
            source="hackerearth",
            source_id="he-2002",
            source_ids={"hackerearth": ["he-2002"]},
            seen_on=["hackerearth"],
            tags=["hackathon"],
        )

        result = await detector.merge_duplicate(
            canonical,
            duplicate,
            stage=FUZZY_STAGE,
            score=0.91,
            persist_event=False,
        )

        self.assertEqual(result["status"], "merged")
        self.assertEqual(canonical.source_count, 2)
        self.assertEqual(canonical.duplicate_count, 2)
        self.assertEqual(canonical.source_ids["unstop"], ["unstop-1001"])
        self.assertEqual(canonical.source_ids["hackerearth"], ["he-2002"])
        self.assertIn("ai", canonical.tags)
        self.assertIn("hackathon", canonical.tags)
        self.assertEqual(canonical.dedup_score, 0.91)


if __name__ == "__main__":
    unittest.main()
