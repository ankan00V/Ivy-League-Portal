"""Contract tests for the cross-encoder reranking stage.

The model itself is not exercised here - loading ms-marco takes seconds and the
behaviour worth pinning is the fusion and the degradation, both of which are
plain Python. A fake scorer stands in for the cross-encoder so the ordering
rules are asserted deterministically.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from app.core.config import settings

from app.services.reranker_service import RerankerService


def _candidates() -> list[dict]:
    # Bi-encoder order is the list order.
    return [
        {"id": "a", "title": "Codeforces Round 1117", "description": "competitive programming contest"},
        {"id": "b", "title": "Product Analytics Case Competition", "description": "analytics case study"},
        {"id": "c", "title": "Generic Challenge", "description": "misc"},
    ]


class _FakeModel:
    """Scores by id so each test states the cross-encoder's opinion directly."""

    def __init__(self, scores: dict[str, float], explode: bool = False) -> None:
        self._scores = scores
        self._explode = explode
        self.calls = 0

    def predict(self, pairs):
        self.calls += 1
        if self._explode:
            raise RuntimeError("model exploded")
        out = []
        for _query, doc in pairs:
            for key, value in self._scores.items():
                if key in doc:
                    out.append(value)
                    break
            else:
                out.append(0.0)
        return out


class RerankerFusionTests(unittest.TestCase):
    def _service(self, model) -> RerankerService:
        service = RerankerService()
        service._model = model
        service._load_attempted = True
        return service

    def test_confident_rejection_demotes_a_top_bi_encoder_hit(self):
        """The regression this stage exists for.

        Codeforces is rank 0 for the bi-encoder. The cross-encoder puts it last.
        Fusion must not leave it first.
        """
        service = self._service(
            _FakeModel({"Codeforces": -11.0, "Product Analytics": 2.0, "Generic": -1.0})
        )
        ranked = asyncio.run(
            service.rerank(query="product and analytics competitions", candidates=_candidates())
        )
        self.assertEqual(ranked[0]["id"], "b")
        self.assertNotEqual(ranked[0]["id"], "a")

    def test_bi_encoder_ordering_survives_a_weak_cross_encoder_preference(self):
        """RRF is a fusion, not an override.

        Replacing the ordering outright regressed "machine learning internships"
        on the real corpus, so a mild cross-encoder disagreement must not be
        enough to unseat a strong bi-encoder result.
        """
        service = self._service(
            _FakeModel({"Codeforces": 0.5, "Product Analytics": 0.6, "Generic": 0.4})
        )
        ranked = asyncio.run(
            service.rerank(query="anything", candidates=_candidates())
        )
        self.assertEqual([row["id"] for row in ranked], ["a", "b", "c"])

    def test_scoring_failure_serves_bi_encoder_order(self):
        service = self._service(_FakeModel({}, explode=True))
        ranked = asyncio.run(service.rerank(query="q", candidates=_candidates()))
        self.assertEqual([row["id"] for row in ranked], ["a", "b", "c"])

    def test_unavailable_model_serves_bi_encoder_order(self):
        service = RerankerService()
        service._model = None
        service._load_attempted = True  # simulate a load that already failed
        ranked = asyncio.run(service.rerank(query="q", candidates=_candidates()))
        self.assertEqual([row["id"] for row in ranked], ["a", "b", "c"])

    def test_similarity_is_never_overwritten(self):
        """similarity is the bi-encoder's answer and is persisted in telemetry."""
        service = self._service(_FakeModel({"Codeforces": -11.0, "Product": 2.0}))
        candidates = _candidates()
        for row in candidates:
            row["similarity"] = 0.5
        ranked = asyncio.run(service.rerank(query="q", candidates=candidates))
        for row in ranked:
            self.assertEqual(row["similarity"], 0.5)
            self.assertIn("rerank_score", row)

    def test_top_k_truncates_after_fusion_not_before(self):
        service = self._service(
            _FakeModel({"Codeforces": -11.0, "Product Analytics": 2.0, "Generic": -1.0})
        )
        ranked = asyncio.run(
            service.rerank(query="q", candidates=_candidates(), top_k=1)
        )
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["id"], "b")

    def test_disabled_service_skips_the_model_entirely(self):
        # Patch the setting, not the property: assigning to
        # RerankerService.enabled replaces the real descriptor for every later
        # test in the process, and deleting it afterwards does not put it back.
        model = _FakeModel({"Codeforces": -11.0})
        service = self._service(model)
        with mock.patch.object(settings, "RAG_RERANKER_ENABLED", False):
            ranked = asyncio.run(service.rerank(query="q", candidates=_candidates()))
        self.assertEqual([row["id"] for row in ranked], ["a", "b", "c"])
        self.assertEqual(model.calls, 0)


if __name__ == "__main__":
    unittest.main()
