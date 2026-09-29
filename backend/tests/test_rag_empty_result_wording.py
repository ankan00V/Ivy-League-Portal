"""Zero rows has two causes, and only one of them is a statement about the corpus.

The answer for an empty shortlist used to be "Top 0 opportunities retrieved for:
<query>", which reads as though the question itself were the finding, and was
produced identically whether the search matched nothing or never ran at all.

Those need different words. "Nothing currently listed matches this" is a claim
about the corpus; making it after a retrieval timeout asserts something that was
never checked, and this repo has shipped that mistake before.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.rag import RAGInsights
from app.services.rag_service import RAGService


class EmptyResultWordingTests(unittest.TestCase):
    def setUp(self):
        self.service = RAGService()

    def test_the_query_is_not_echoed_back_as_the_answer(self):
        payload = self.service._heuristic_insight("data science internships in Bangalore", [])
        self.assertNotIn("data science internships in Bangalore", payload["summary"])
        self.assertNotIn("Top 0", payload["summary"])

    def test_a_search_that_matched_nothing_says_so(self):
        payload = self.service._heuristic_insight("medieval Latin fellowship", [])
        self.assertIn("Nothing currently listed matches", payload["summary"])
        self.assertEqual(payload["top_opportunities"], [])
        self.assertEqual(payload["citations"], [])

    def test_a_search_that_never_ran_makes_no_claim_about_the_corpus(self):
        """After a timeout the corpus was never consulted, so "nothing is listed"
        would be an assertion the server has no basis for."""
        payload = self.service._heuristic_insight(
            "data science internships in Bangalore", [], retrieval_error="retrieval_timed_out"
        )
        self.assertNotIn("Nothing currently listed", payload["summary"])
        self.assertIn("could not be searched", payload["summary"])
        self.assertIn("retrieval_timed_out", payload["safety"]["failed_checks"])

    def test_both_shapes_validate_against_the_response_contract(self):
        """An empty answer travels the same schema as a full one, not a side channel."""
        for error in (None, "retrieval_timed_out"):
            model = RAGInsights.model_validate(
                self.service._heuristic_insight("q", [], retrieval_error=error)
            )
            self.assertEqual(model.top_opportunities, [])
            self.assertFalse(model.safety.hallucination_checks_passed)

    def test_a_populated_shortlist_is_unchanged(self):
        """The empty branch must not swallow the normal fallback path."""
        results = [
            {
                "id": "a1",
                "url": "https://example.com/a1",
                "title": "Opp A",
                "source": "unit-test",
                "similarity": 0.7,
            }
        ]
        payload = self.service._heuristic_insight("q", results)
        self.assertEqual(len(payload["top_opportunities"]), 1)
        self.assertTrue(payload["safety"]["hallucination_checks_passed"])


if __name__ == "__main__":
    unittest.main()
