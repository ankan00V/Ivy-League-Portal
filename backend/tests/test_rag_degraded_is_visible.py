"""A fallback answer must not look like a generated one.

When the model call fails, retrieval has still produced a shortlist and the
service returns a deterministic summary over those rows. Showing rows beats an
error page. What it must not do is look identical to a real answer.

It did. Same shape, same fields, and a confident "Top 3 opportunities retrieved
for: <your query>" with nothing saying the AI had not run. Measured against a
real provider outage - every model on the account returning 404 - Ask AI
appeared to be working for as long as the outage lasted, and only a WARNING in
the log said otherwise.
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

ROWS = [
    {"id": "a1", "url": "https://e.com/1", "title": "Backend Intern", "description": "python", "similarity": 0.7},
    {"id": "a2", "url": "https://e.com/2", "title": "Data Intern", "description": "sql", "similarity": 0.6},
]


class DegradedFlagTests(unittest.TestCase):
    def setUp(self):
        self.service = RAGService()

    def test_a_healthy_fallback_is_not_marked_degraded(self):
        payload = self.service._heuristic_insight("internships", ROWS)
        self.assertFalse(payload["degraded"])
        self.assertIsNone(payload["degraded_reason"])

    def test_an_outage_is_marked_and_named(self):
        payload = self.service._heuristic_insight("internships", ROWS, degraded_reason="llm_unavailable")
        self.assertTrue(payload["degraded"])
        self.assertEqual(payload["degraded_reason"], "llm_unavailable")

    def test_the_summary_says_the_ai_did_not_run(self):
        payload = self.service._heuristic_insight("internships", ROWS, degraded_reason="llm_unavailable")
        self.assertIn("AI summary is unavailable", payload["summary"])

    def test_the_degraded_summary_does_not_echo_the_query_as_a_finding(self):
        """"Top 3 opportunities retrieved for: <query>" was the sentence that
        made an outage look like an answer."""
        payload = self.service._heuristic_insight(
            "data science internships in Bangalore", ROWS, degraded_reason="llm_unavailable"
        )
        self.assertNotIn("data science internships in Bangalore", payload["summary"])
        self.assertNotIn("Top 2 opportunities retrieved for", payload["summary"])

    def test_the_rows_are_still_served(self):
        """Degraded is not empty. Retrieval worked; those rows are useful."""
        payload = self.service._heuristic_insight("internships", ROWS, degraded_reason="llm_timeout")
        self.assertEqual(len(payload["top_opportunities"]), 2)
        self.assertEqual(len(payload["citations"]), 2)

    def test_it_validates_against_the_response_contract(self):
        model = RAGInsights.model_validate(
            self.service._heuristic_insight("q", ROWS, degraded_reason="llm_unavailable")
        )
        self.assertTrue(model.degraded)
        self.assertEqual(model.degraded_reason, "llm_unavailable")

    def test_every_fallback_path_names_a_reason(self):
        """Six ways the model answer can be discarded. A flag that only some of
        them set is worse than none, because the unset ones look healthy."""
        source = (BACKEND_ROOT / "app" / "services" / "rag_service.py").read_text()
        for reason in (
            "llm_timeout",
            "llm_unavailable",
            "llm_unparseable_response",
            "llm_no_resolvable_refs",
            "llm_schema_invalid",
            "llm_failed_grounding_checks",
            "llm_not_configured",
        ):
            self.assertIn(f'degraded_reason="{reason}"', source, reason)


if __name__ == "__main__":
    unittest.main()
