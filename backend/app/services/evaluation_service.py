from __future__ import annotations

from typing import Any, Iterable, Optional

from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.services.embedding_service import embedding_service
from app.services.recommendation_service import recommendation_service

def _precision_at_k(predicted_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    topk = predicted_ids[:k]
    if not topk:
        return 0.0
    hits = sum(1 for item in topk if item in relevant_ids)
    return hits / float(k)


def _recall_at_k(predicted_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    topk = predicted_ids[:k]
    hits = sum(1 for item in topk if item in relevant_ids)
    return hits / float(len(relevant_ids))


class EvaluationService:
    async def evaluate_ranking(
        self,
        *,
        user_id,
        profile: Profile,
        query: str,
        relevant_ids: Iterable[str],
        k: int,
    ) -> dict[str, Any]:
        opportunities = await Opportunity.find_many().to_list()
        safe_k = max(1, min(k, 50))
        relevant_set = {str(value) for value in relevant_ids if value}

        baseline_ranked, _ = await recommendation_service.rank(
            user_id=user_id,
            profile=profile,
            opportunities=opportunities,
            limit=max(150, safe_k * 5),
            ranking_mode="baseline",
            query=query,
        )
        semantic_ranked, _ = await recommendation_service.rank(
            user_id=user_id,
            profile=profile,
            opportunities=opportunities,
            limit=max(150, safe_k * 5),
            ranking_mode="semantic",
            query=query,
        )

        baseline_ids = [str(item["opportunity"].id) for item in baseline_ranked]
        semantic_ids = [str(item["opportunity"].id) for item in semantic_ranked]

        return {
            "k": safe_k,
            "relevant_count": len(relevant_set),
            "baseline": {
                "precision_at_k": round(_precision_at_k(baseline_ids, relevant_set, safe_k), 6),
                "recall_at_k": round(_recall_at_k(baseline_ids, relevant_set, safe_k), 6),
            },
            "semantic": {
                "precision_at_k": round(_precision_at_k(semantic_ids, relevant_set, safe_k), 6),
                "recall_at_k": round(_recall_at_k(semantic_ids, relevant_set, safe_k), 6),
            },
        }

    async def evaluate_llm_response(
        self,
        *,
        generated_text: str,
        expected_keywords: list[str],
        expected_output: Optional[str] = None,
    ) -> dict[str, Any]:
        generated_lower = (generated_text or "").lower()
        keyword_hits = [keyword for keyword in expected_keywords if keyword.lower() in generated_lower]
        keyword_coverage = (len(keyword_hits) / len(expected_keywords)) if expected_keywords else 0.0

        semantic_similarity = None
        if expected_output:
            vectors = await embedding_service.embed_texts([generated_text, expected_output])
            if len(vectors) == 2:
                semantic_similarity = float((vectors[0] * vectors[1]).sum())

        return {
            "keyword_coverage": round(keyword_coverage, 6),
            "keyword_hits": keyword_hits,
            "semantic_similarity": round(float(semantic_similarity), 6) if semantic_similarity is not None else None,
        }


evaluation_service = EvaluationService()
