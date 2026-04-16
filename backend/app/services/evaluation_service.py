from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from openai import AsyncOpenAI

from app.core.config import settings
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.services.embedding_service import embedding_service
from app.services.recommendation_service import recommendation_service
from app.services.ranking_metrics import (
    mrr,
    ndcg_at_k,
    normalize_relevant_ids,
    precision_at_k,
    recall_at_k,
)


class EvaluationService:
    def __init__(self) -> None:
        self._judge_client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY or "dummy_key_to_prevent_boot_crash",
        )

    def _extract_json(self, content: str) -> dict[str, Any]:
        raw = (content or "").strip()
        if not raw:
            return {}

        try:
            return json.loads(raw)
        except Exception:
            pass

        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            candidate = raw[start : end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                return {}

        return {}

    async def _llm_judge(
        self,
        *,
        generated_text: str,
        expected_output: Optional[str],
        expected_keywords: list[str],
        rubric: Optional[str],
    ) -> Optional[dict[str, Any]]:
        if not settings.OPENROUTER_API_KEY:
            return None

        model = (settings.LLM_JUDGE_MODEL or settings.OPENROUTER_MODEL).strip()
        judge_prompt = {
            "generated_text": generated_text,
            "expected_keywords": expected_keywords,
            "expected_output": expected_output or "",
            "rubric": rubric
            or (
                "Score 0..1 for: correctness, completeness, groundedness, clarity. "
                "Penalize unsupported claims and missing required details."
            ),
        }

        response = await self._judge_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict evaluator. Return JSON only with keys: "
                        "score (number 0..1), rationale (string), flags (array of strings)."
                    ),
                },
                {"role": "user", "content": json.dumps(judge_prompt)},
            ],
            extra_headers={
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "VidyaVerse LLM Judge",
            },
        )

        content = ""
        if response.choices and response.choices[0].message:
            content = response.choices[0].message.content or ""

        parsed = self._extract_json(content)
        if not parsed:
            return None

        try:
            score = float(parsed.get("score"))
        except Exception:
            return None

        score = max(0.0, min(1.0, score))
        return {
            "score": round(score, 6),
            "rationale": str(parsed.get("rationale") or "").strip()[:1000],
            "flags": [str(flag) for flag in (parsed.get("flags") or []) if str(flag).strip()][:20],
            "model": model,
        }

    async def judge_rag_response(
        self,
        *,
        query: str,
        candidates: list[dict[str, Any]],
        insights: dict[str, Any],
        rubric: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Optional LLM-as-judge for RAG outputs.
        Returns {score:0..1, rationale, flags, model} or None if judge unavailable.
        """
        if not settings.OPENROUTER_API_KEY:
            return None

        model = (settings.LLM_JUDGE_MODEL or settings.OPENROUTER_MODEL).strip()
        judge_prompt = {
            "query": query,
            "candidates": [
                {
                    "id": c.get("id"),
                    "title": c.get("title"),
                    "url": c.get("url"),
                    "deadline": str(c.get("deadline") or ""),
                    "similarity": c.get("similarity"),
                }
                for c in (candidates or [])[:8]
            ],
            "insights": insights,
            "rubric": rubric
            or (
                "Score 0..1 for: groundedness to candidates (no invented facts), "
                "usefulness for shortlisting, and clarity. "
                "Return low score if insights mention opportunities not in candidates "
                "or if citations do not match candidate ids/urls."
            ),
        }

        response = await self._judge_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict RAG judge. Return JSON only with keys: "
                        "score (number 0..1), rationale (string), flags (array of strings)."
                    ),
                },
                {"role": "user", "content": json.dumps(judge_prompt)},
            ],
            extra_headers={
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "VidyaVerse RAG Judge",
            },
        )

        content = ""
        if response.choices and response.choices[0].message:
            content = response.choices[0].message.content or ""

        parsed = self._extract_json(content)
        if not parsed:
            return None

        try:
            score = float(parsed.get("score"))
        except Exception:
            return None

        score = max(0.0, min(1.0, score))
        return {
            "score": round(score, 6),
            "rationale": str(parsed.get("rationale") or "").strip()[:1000],
            "flags": [str(flag) for flag in (parsed.get("flags") or []) if str(flag).strip()][:20],
            "model": model,
        }

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
        relevant_set = normalize_relevant_ids(relevant_ids)

        baseline_ranked, _meta = await recommendation_service.rank(
            user_id=user_id,
            profile=profile,
            opportunities=opportunities,
            limit=max(150, safe_k * 5),
            ranking_mode="baseline",
            query=query,
        )
        semantic_ranked, _meta2 = await recommendation_service.rank(
            user_id=user_id,
            profile=profile,
            opportunities=opportunities,
            limit=max(150, safe_k * 5),
            ranking_mode="semantic",
            query=query,
        )
        ml_ranked, _meta3 = await recommendation_service.rank(
            user_id=user_id,
            profile=profile,
            opportunities=opportunities,
            limit=max(150, safe_k * 5),
            ranking_mode="ml",
            query=query,
        )

        baseline_ids = [str(item["opportunity"].id) for item in baseline_ranked]
        semantic_ids = [str(item["opportunity"].id) for item in semantic_ranked]
        ml_ids = [str(item["opportunity"].id) for item in ml_ranked]

        return {
            "k": safe_k,
            "relevant_count": len(relevant_set),
            "baseline": {
                "precision_at_k": round(precision_at_k(baseline_ids, relevant_set, safe_k), 6),
                "recall_at_k": round(recall_at_k(baseline_ids, relevant_set, safe_k), 6),
                "ndcg_at_k": round(ndcg_at_k(baseline_ids, relevant_set, safe_k), 6),
                "mrr": round(mrr(baseline_ids, relevant_set, safe_k), 6),
            },
            "semantic": {
                "precision_at_k": round(precision_at_k(semantic_ids, relevant_set, safe_k), 6),
                "recall_at_k": round(recall_at_k(semantic_ids, relevant_set, safe_k), 6),
                "ndcg_at_k": round(ndcg_at_k(semantic_ids, relevant_set, safe_k), 6),
                "mrr": round(mrr(semantic_ids, relevant_set, safe_k), 6),
            },
            "ml": {
                "precision_at_k": round(precision_at_k(ml_ids, relevant_set, safe_k), 6),
                "recall_at_k": round(recall_at_k(ml_ids, relevant_set, safe_k), 6),
                "ndcg_at_k": round(ndcg_at_k(ml_ids, relevant_set, safe_k), 6),
                "mrr": round(mrr(ml_ids, relevant_set, safe_k), 6),
            },
        }

    async def evaluate_llm_response(
        self,
        *,
        generated_text: str,
        expected_keywords: list[str],
        expected_output: Optional[str] = None,
        include_judge: bool = False,
        rubric: Optional[str] = None,
    ) -> dict[str, Any]:
        generated_lower = (generated_text or "").lower()
        keyword_hits = [keyword for keyword in expected_keywords if keyword.lower() in generated_lower]
        expected_count = len(expected_keywords or [])
        hit_count = len(keyword_hits)
        keyword_coverage = (hit_count / expected_count) if expected_count else 0.0
        # Keyword matching here is a "required coverage" metric; treat it as recall-like.
        keyword_precision = keyword_coverage
        keyword_recall = keyword_coverage
        keyword_f1 = keyword_coverage

        semantic_similarity = None
        if expected_output:
            vectors = await embedding_service.embed_texts([generated_text, expected_output])
            if len(vectors) == 2:
                semantic_similarity = float((vectors[0] * vectors[1]).sum())

        judge = None
        if include_judge or settings.LLM_JUDGE_ENABLED:
            judge = await self._llm_judge(
                generated_text=generated_text,
                expected_output=expected_output,
                expected_keywords=expected_keywords,
                rubric=rubric,
            )

        return {
            "keyword_coverage": round(keyword_coverage, 6),
            "keyword_precision": round(float(keyword_precision), 6),
            "keyword_recall": round(float(keyword_recall), 6),
            "keyword_f1": round(float(keyword_f1), 6),
            "keyword_hits": keyword_hits,
            "semantic_similarity": round(float(semantic_similarity), 6) if semantic_similarity is not None else None,
            "llm_judge": judge,
        }


evaluation_service = EvaluationService()
