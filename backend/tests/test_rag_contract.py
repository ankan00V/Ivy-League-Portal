import unittest

from app.schemas.rag import RAGInsights
from app.services.rag_service import RAGService


class TestRAGContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RAGService()

    def test_apply_hallucination_checks_adds_citations(self) -> None:
        results = [
            {"id": "a1", "url": "https://example.com/a1", "title": "Opp A", "source": "unit-test"},
            {"id": "b2", "url": "https://example.com/b2", "title": "Opp B", "source": "unit-test"},
        ]

        insights = RAGInsights.model_validate(
            {
                "summary": "Summary",
                "top_opportunities": [
                    {
                        "opportunity_id": "a1",
                        "title": "Opp A",
                        "why_fit": "Because relevant",
                        "urgency": "medium",
                        "match_score": 88.0,
                        # citations intentionally missing
                    }
                ],
                "deadline_urgency": "Sooner is better",
                "recommended_action": "Apply",
            }
        )

        checked = self.service._apply_hallucination_checks(insights, results)
        self.assertTrue(checked.citations)
        self.assertTrue(checked.top_opportunities[0].citations)
        self.assertEqual(checked.top_opportunities[0].citations[0].opportunity_id, "a1")
        self.assertEqual(checked.top_opportunities[0].citations[0].url, "https://example.com/a1")

    def test_apply_hallucination_checks_rejects_non_retrieved_ids(self) -> None:
        results = [{"id": "a1", "url": "https://example.com/a1", "title": "Opp A"}]
        insights = RAGInsights.model_validate(
            {
                "summary": "Summary",
                "top_opportunities": [
                    {
                        "opportunity_id": "not-real",
                        "title": "Invented",
                        "why_fit": "Invented",
                        "urgency": "low",
                        "match_score": 50.0,
                        "citations": [{"opportunity_id": "not-real", "url": "https://evil.com"}],
                    }
                ],
                "deadline_urgency": "Sooner is better",
                "recommended_action": "Apply",
            }
        )
        checked = self.service._apply_hallucination_checks(insights, results)
        self.assertFalse(checked.safety.hallucination_checks_passed)
        self.assertEqual(len(checked.top_opportunities), 0)

    def test_apply_hallucination_checks_reports_no_results(self) -> None:
        insights = RAGInsights.model_validate(
            {
                "summary": "No results",
                "top_opportunities": [],
                "deadline_urgency": "N/A",
                "recommended_action": "Try a broader query",
            }
        )
        checked = self.service._apply_hallucination_checks(insights, [])
        self.assertFalse(checked.safety.hallucination_checks_passed)
        self.assertIn("no_retrieval_results", checked.safety.failed_checks)


if __name__ == "__main__":
    unittest.main()

