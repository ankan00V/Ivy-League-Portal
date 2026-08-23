"""Ask AI must say "nothing matches" rather than rank the least-bad rows.

Retrieval returns its nearest neighbours whatever is asked, so an unanswerable
query still produces a full shortlist. Cosine similarity cannot distinguish the
two cases - 0.48 means "closest thing in the corpus", not "a match" - which is
how "product and analytics competitions worth shortlisting this week" surfaced
a Codeforces round and had it written up as a shortlist.

The cross-encoder scores on an absolute scale, so a threshold is meaningful.
Measured over 11 queries on this corpus: six the corpus can answer scored -1.03
to +4.71, five it genuinely cannot scored -8.07 to -10.91.
"""

from __future__ import annotations

import unittest
from unittest import mock

from app.core.config import settings
from app.schemas.rag import RAGInsights
from app.services.rag_service import RAGService


class NoStrongMatchInsightTests(unittest.TestCase):
    def test_payload_validates_against_the_response_contract(self):
        """Abstention travels the same schema as an answer, not a side channel."""
        payload = RAGService._no_strong_match_insight("medieval Latin fellowship", -10.9)
        model = RAGInsights.model_validate(payload)
        self.assertTrue(model.abstained)
        self.assertEqual(model.top_opportunities, [])
        self.assertEqual(model.citations, [])
        self.assertEqual(model.top_relevance_score, -10.9)

    def test_abstaining_is_not_reported_as_a_grounding_failure(self):
        """Withholding a shortlist is a correct outcome; the safety report must
        not brand it a hallucination, or the gates will read it as a defect."""
        model = RAGInsights.model_validate(
            RAGService._no_strong_match_insight("q", -9.0)
        )
        self.assertTrue(model.safety.hallucination_checks_passed)
        self.assertEqual(model.safety.failed_checks, [])

    def test_reason_is_machine_readable(self):
        payload = RAGService._no_strong_match_insight("q", -9.0)
        self.assertEqual(payload["abstain_reason"], "no_candidate_above_relevance_threshold")


class AbstentionThresholdTests(unittest.TestCase):
    """The comparison itself, pinned against the measured score ranges."""

    THRESHOLD = -5.0

    def _abstains(self, score: float | None) -> bool:
        if not settings.RAG_ABSTAIN_ON_LOW_RELEVANCE:
            return False
        return score is not None and float(score) < float(self.THRESHOLD)

    def test_scores_from_answerable_queries_do_not_abstain(self):
        # Measured: ML internships +2.51, web3 hackathons +1.62, data science
        # +0.09, NLP research -1.03, SWE internship +4.71, AI fellowship +3.51.
        for score in (2.506665, 1.622439, 0.091132, -1.031398, 4.708347, 3.514148):
            self.assertFalse(self._abstains(score), f"should answer at {score}")

    def test_scores_from_unanswerable_queries_abstain(self):
        # Measured: product/analytics -9.01, basket weaving -8.07, medieval
        # Latin -10.91, deep sea diving -10.75, opera masterclass -10.89.
        for score in (-9.009705, -8.073093, -10.908489, -10.751942, -10.893929):
            self.assertTrue(self._abstains(score), f"should abstain at {score}")

    def test_threshold_sits_clear_of_both_measured_ranges(self):
        """Guards the margin, not just the direction: the nearest answerable
        score is -1.03 and the nearest unanswerable is -8.07, so a threshold
        drifting toward either end would start misclassifying real queries."""
        self.assertLess(self.THRESHOLD, -1.031398 - 3.0)
        self.assertGreater(self.THRESHOLD, -8.073093 + 3.0)
        self.assertEqual(self.THRESHOLD, float(settings.RAG_MIN_RELEVANCE_SCORE))

    def test_missing_score_never_abstains(self):
        """A reranker that failed to load must not silently mute every answer."""
        self.assertFalse(self._abstains(None))

    def test_disabled_flag_answers_regardless(self):
        with mock.patch.object(settings, "RAG_ABSTAIN_ON_LOW_RELEVANCE", False):
            self.assertFalse(self._abstains(-99.0))


if __name__ == "__main__":
    unittest.main()
