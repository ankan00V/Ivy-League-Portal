from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.recommendation_quality_gate import (
    PersonaSpec,
    aggregate_persona_results,
    is_relevant_for_persona,
    summarize_ranked_results,
)


class TestRecommendationQualityGate(unittest.TestCase):
    def test_relevance_uses_opportunity_metadata(self) -> None:
        persona = PersonaSpec(
            name="frontend",
            profile={},
            positive_terms=("react", "frontend", "typescript"),
        )
        opportunity = SimpleNamespace(
            title="Junior Product Engineer",
            description="Build React and TypeScript dashboards.",
            domain="Software",
            opportunity_type="Internship",
            tags=["web", "ui"],
        )

        self.assertTrue(is_relevant_for_persona(opportunity, persona))

    def test_short_terms_require_word_boundaries(self) -> None:
        persona = PersonaSpec(
            name="ai",
            profile={},
            positive_terms=("ai", "ml"),
        )
        false_positive = SimpleNamespace(
            title="Entry Level Administrative Assistant",
            description="Coordinate office workflows.",
            domain="Operations",
            opportunity_type="Job",
            tags=[],
        )
        true_positive = SimpleNamespace(
            title="AI Intern",
            description="Build ML experiments.",
            domain="AI/ML",
            opportunity_type="Internship",
            tags=[],
        )

        self.assertFalse(is_relevant_for_persona(false_positive, persona))
        self.assertTrue(is_relevant_for_persona(true_positive, persona))

    def test_persona_summary_tracks_first_relevant_rank_and_precision(self) -> None:
        persona = PersonaSpec(
            name="ai_ml",
            profile={},
            positive_terms=("machine learning", "python"),
            top_k=3,
            min_relevant_in_top_k=1,
            min_mrr=0.2,
        )
        ranked = [
            {
                "opportunity": SimpleNamespace(
                    id="opp-1",
                    title="General Operations Role",
                    description="Non-technical coordination.",
                    source="example",
                    domain="Operations",
                    opportunity_type="Job",
                ),
                "match_score": 80.0,
                "ranking_mode": "semantic",
            },
            {
                "opportunity": SimpleNamespace(
                    id="opp-2",
                    title="Machine Learning Internship",
                    description="Python ranking models.",
                    source="example",
                    domain="AI/ML",
                    opportunity_type="Internship",
                ),
                "match_score": 75.0,
                "ranking_mode": "semantic",
            },
        ]

        result = summarize_ranked_results(
            persona=persona,
            ranked=ranked,
            latency_ms=42.42,
            candidate_count=100,
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.first_relevant_rank, 2)
        self.assertEqual(result.relevant_in_top_k, 1)
        self.assertAlmostEqual(result.reciprocal_rank, 0.5)
        self.assertEqual(result.precision_at_k, 0.333333)
        self.assertEqual(result.top_results[1]["id"], "opp-2")
        self.assertTrue(result.top_results[1]["relevant"])

    def test_aggregate_gate_fails_empty_results(self) -> None:
        summary = aggregate_persona_results(results=[])

        self.assertFalse(summary["ready"])
        self.assertEqual(summary["persona_count"], 0)
        self.assertFalse(summary["gates"][0]["pass"])

    def test_aggregate_gate_combines_quality_and_latency(self) -> None:
        persona = PersonaSpec(name="any", profile={}, positive_terms=("python",))
        passing = summarize_ranked_results(
            persona=persona,
            ranked=[
                {
                    "opportunity": SimpleNamespace(
                        id="opp",
                        title="Python Internship",
                        description="Build APIs.",
                        source="example",
                        domain="Software",
                        opportunity_type="Internship",
                    ),
                    "match_score": 91.0,
                    "ranking_mode": "semantic",
                }
            ],
            latency_ms=100.0,
            candidate_count=10,
        )

        summary = aggregate_persona_results(
            results=[passing],
            min_persona_pass_rate=1.0,
            min_mean_mrr=1.0,
            max_p95_latency_ms=150.0,
        )

        self.assertTrue(summary["ready"])
        self.assertEqual(summary["pass_rate"], 1.0)
        self.assertEqual(summary["mean_mrr"], 1.0)


if __name__ == "__main__":
    unittest.main()
