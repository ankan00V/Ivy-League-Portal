from __future__ import annotations

import json
import re
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
        self._api_base_url = (
            (settings.LLM_API_BASE_URL or "").strip()
            or (settings.OPENROUTER_BASE_URL or "").strip()
            or "https://openrouter.ai/api/v1"
        )
        self._api_key = (settings.LLM_API_KEY or settings.OPENROUTER_API_KEY or "").strip() or None
        self._default_model = (
            (settings.LLM_MODEL or "").strip()
            or (settings.OPENROUTER_MODEL or "").strip()
            or "meta-llama/llama-3-8b-instruct:free"
        )
        self._judge_api_base_url = (
            (settings.LLM_JUDGE_API_BASE_URL or "").strip()
            or self._api_base_url
        )
        self._judge_api_key = (settings.LLM_JUDGE_API_KEY or self._api_key or "").strip() or None
        self._judge_client = AsyncOpenAI(
            base_url=self._judge_api_base_url,
            api_key=self._judge_api_key or "dummy_key_to_prevent_boot_crash",
        )

    def _judge_headers(self, *, title: str) -> dict[str, str] | None:
        if "openrouter.ai" not in self._judge_api_base_url.lower():
            return None
        return {
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": title,
        }

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

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", (text or "").lower())

    def _token_level_prf(
        self,
        *,
        generated_text: str,
        reference_text: str,
    ) -> dict[str, float]:
        generated_tokens = self._tokenize(generated_text)
        reference_tokens = self._tokenize(reference_text)
        generated_counts: dict[str, int] = {}
        reference_counts: dict[str, int] = {}
        for token in generated_tokens:
            generated_counts[token] = generated_counts.get(token, 0) + 1
        for token in reference_tokens:
            reference_counts[token] = reference_counts.get(token, 0) + 1

        overlap = 0
        for token, count in generated_counts.items():
            overlap += min(count, reference_counts.get(token, 0))

        precision = float(overlap / max(1, len(generated_tokens)))
        recall = float(overlap / max(1, len(reference_tokens)))
        f1_score = 0.0 if (precision <= 0.0 or recall <= 0.0) else (2.0 * precision * recall / (precision + recall))
        return {
            "precision": precision,
            "recall": recall,
            "f1": f1_score,
            "overlap_tokens": overlap,
            "generated_tokens": len(generated_tokens),
            "reference_tokens": len(reference_tokens),
        }

    def _phrase_level_prf(
        self,
        *,
        generated_text: str,
        expected_phrases: list[str],
    ) -> dict[str, Any]:
        normalized_expected: list[str] = []
        seen_expected: set[str] = set()
        for phrase in expected_phrases:
            normalized = " ".join(self._tokenize(phrase))
            if not normalized or normalized in seen_expected:
                continue
            seen_expected.add(normalized)
            normalized_expected.append(normalized)

        generated_tokens = self._tokenize(generated_text)
        token_lengths = sorted({max(1, len(phrase.split())) for phrase in normalized_expected})
        predicted_candidates: set[str] = set()
        for length in token_lengths:
            if length <= 0 or len(generated_tokens) < length:
                continue
            for idx in range(len(generated_tokens) - length + 1):
                predicted_candidates.add(" ".join(generated_tokens[idx : idx + length]))

        expected_set = set(normalized_expected)
        matched = sorted(expected_set.intersection(predicted_candidates))
        precision = float(len(matched) / max(1, len(predicted_candidates))) if predicted_candidates else 0.0
        recall = float(len(matched) / max(1, len(expected_set))) if expected_set else 0.0
        f1_score = 0.0 if (precision <= 0.0 or recall <= 0.0) else (2.0 * precision * recall / (precision + recall))
        return {
            "precision": precision,
            "recall": recall,
            "f1": f1_score,
            "matched_phrases": matched,
            "expected_phrases": sorted(expected_set),
            "predicted_phrase_candidates": int(len(predicted_candidates)),
        }

    def _citation_grounding(
        self,
        *,
        generated_text: str,
        required_citations: list[str],
        allowed_citations: list[str],
    ) -> dict[str, Any]:
        extracted = re.findall(r"https?://[^\s\])>,]+", generated_text or "", flags=re.IGNORECASE)
        normalized_extracted: list[str] = []
        seen: set[str] = set()
        for value in extracted:
            norm = value.strip().rstrip(".;,")
            if not norm:
                continue
            lowered = norm.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized_extracted.append(norm)

        required_set = {item.strip().lower() for item in required_citations if str(item).strip()}
        allowed_set = {item.strip().lower() for item in allowed_citations if str(item).strip()}
        hits_required = [cite for cite in normalized_extracted if cite.lower() in required_set]
        hits_allowed = [cite for cite in normalized_extracted if cite.lower() in allowed_set] if allowed_set else list(hits_required)
        ungrounded = [cite for cite in normalized_extracted if allowed_set and cite.lower() not in allowed_set]

        precision = float(len(hits_allowed) / max(1, len(normalized_extracted))) if normalized_extracted else 0.0
        recall = float(len(hits_required) / max(1, len(required_set))) if required_set else 0.0
        coverage = float(len(hits_required) / max(1, len(required_set))) if required_set else 0.0
        return {
            "extracted_citations": normalized_extracted,
            "required_hits": hits_required,
            "allowed_hits": hits_allowed,
            "ungrounded_citations": ungrounded,
            "precision": precision,
            "recall": recall,
            "required_coverage": coverage,
            "has_ungrounded_citations": bool(ungrounded),
        }

    def _rubric_score(
        self,
        *,
        weights: dict[str, float] | None,
        features: dict[str, float | None],
    ) -> tuple[float, dict[str, float]]:
        default_weights = {
            "token_f1": 0.25,
            "phrase_f1": 0.25,
            "keyword_recall": 0.2,
            "citation_precision": 0.15,
            "citation_recall": 0.15,
        }
        provided = weights or {}
        normalized_weights: dict[str, float] = {}
        for key, value in default_weights.items():
            raw = float(provided.get(key, value))
            if raw < 0:
                raw = 0.0
            normalized_weights[key] = raw

        score_total = 0.0
        weight_total = 0.0
        for key, weight in normalized_weights.items():
            metric_value = features.get(key)
            if metric_value is None:
                continue
            score_total += float(metric_value) * weight
            weight_total += weight
        if weight_total <= 0:
            return 0.0, normalized_weights
        return float(score_total / weight_total), normalized_weights

    async def _llm_judge(
        self,
        *,
        generated_text: str,
        expected_output: Optional[str],
        expected_keywords: list[str],
        rubric: Optional[str],
    ) -> Optional[dict[str, Any]]:
        if not self._judge_api_key:
            return None

        model = (
            (settings.RAG_JUDGE_MODEL or "").strip()
            or (settings.LLM_JUDGE_MODEL or "").strip()
            or self._default_model
        ).strip()
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
            extra_headers=self._judge_headers(title="VidyaVerse LLM Judge"),
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=220,
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
        if not self._judge_api_key:
            return None

        model = (
            (settings.RAG_JUDGE_MODEL or "").strip()
            or (settings.LLM_JUDGE_MODEL or "").strip()
            or self._default_model
        ).strip()
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
            extra_headers=self._judge_headers(title="VidyaVerse RAG Judge"),
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=220,
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
        expected_phrases: Optional[list[str]] = None,
        expected_output: Optional[str] = None,
        required_citations: Optional[list[str]] = None,
        allowed_citations: Optional[list[str]] = None,
        rubric_weights: Optional[dict[str, float]] = None,
        include_judge: bool = False,
        rubric: Optional[str] = None,
    ) -> dict[str, Any]:
        generated_lower = (generated_text or "").lower()
        keyword_hits = [keyword for keyword in expected_keywords if keyword.lower() in generated_lower]
        expected_count = len(expected_keywords or [])
        hit_count = len(keyword_hits)
        keyword_coverage = (hit_count / expected_count) if expected_count else 0.0
        expected_phrases_merged = list(expected_keywords or []) + list(expected_phrases or [])

        reference_text = expected_output or " ".join(expected_phrases_merged)
        token_metrics = self._token_level_prf(generated_text=generated_text, reference_text=reference_text)
        phrase_metrics = self._phrase_level_prf(generated_text=generated_text, expected_phrases=expected_phrases_merged)

        keyword_predicted_count = len(re.findall(r"[a-z0-9]+", generated_lower))
        keyword_precision = float(hit_count / max(1, keyword_predicted_count)) if keyword_predicted_count else 0.0
        keyword_recall = float(hit_count / max(1, expected_count)) if expected_count else 0.0
        keyword_f1 = 0.0 if (keyword_precision <= 0.0 or keyword_recall <= 0.0) else (
            2.0 * keyword_precision * keyword_recall / (keyword_precision + keyword_recall)
        )

        semantic_similarity = None
        if expected_output:
            vectors = await embedding_service.embed_texts([generated_text, expected_output])
            if len(vectors) == 2:
                semantic_similarity = float((vectors[0] * vectors[1]).sum())

        citation_metrics = self._citation_grounding(
            generated_text=generated_text,
            required_citations=list(required_citations or []),
            allowed_citations=list(allowed_citations or []),
        )

        rubric_score_value, normalized_rubric_weights = self._rubric_score(
            weights=rubric_weights,
            features={
                "token_f1": float(token_metrics["f1"]),
                "phrase_f1": float(phrase_metrics["f1"]),
                "keyword_recall": float(keyword_recall),
                "citation_precision": float(citation_metrics["precision"]),
                "citation_recall": float(citation_metrics["recall"]),
            },
        )

        judge = None
        if include_judge or settings.LLM_JUDGE_ENABLED:
            judge = await self._llm_judge(
                generated_text=generated_text,
                expected_output=expected_output,
                expected_keywords=expected_keywords,
                rubric=rubric,
            )

        judge_agreement = None
        if judge is not None and judge.get("score") is not None:
            judge_score = float(judge["score"])
            score_delta = abs(judge_score - rubric_score_value)
            threshold = float(max(0.0, min(1.0, settings.LLM_JUDGE_MIN_SCORE)))
            rubric_pass = bool(rubric_score_value >= threshold)
            judge_pass = bool(judge_score >= threshold)
            judge_agreement = {
                "judge_score": round(judge_score, 6),
                "rubric_score": round(rubric_score_value, 6),
                "score_delta": round(score_delta, 6),
                "score_agreement": round(float(max(0.0, 1.0 - score_delta)), 6),
                "judge_pass": judge_pass,
                "rubric_pass": rubric_pass,
                "verdict_agreement": bool(judge_pass == rubric_pass),
                "threshold": round(threshold, 6),
            }

        return {
            "keyword_coverage": round(keyword_coverage, 6),
            "keyword_precision": round(float(keyword_precision), 6),
            "keyword_recall": round(float(keyword_recall), 6),
            "keyword_f1": round(float(keyword_f1), 6),
            "keyword_hits": keyword_hits,
            "token_metrics": {
                "precision": round(float(token_metrics["precision"]), 6),
                "recall": round(float(token_metrics["recall"]), 6),
                "f1": round(float(token_metrics["f1"]), 6),
                "overlap_tokens": int(token_metrics["overlap_tokens"]),
                "generated_tokens": int(token_metrics["generated_tokens"]),
                "reference_tokens": int(token_metrics["reference_tokens"]),
            },
            "phrase_metrics": {
                "precision": round(float(phrase_metrics["precision"]), 6),
                "recall": round(float(phrase_metrics["recall"]), 6),
                "f1": round(float(phrase_metrics["f1"]), 6),
                "matched_phrases": phrase_metrics["matched_phrases"],
                "expected_phrases": phrase_metrics["expected_phrases"],
                "predicted_phrase_candidates": int(phrase_metrics["predicted_phrase_candidates"]),
            },
            "citation_metrics": {
                "extracted_citations": citation_metrics["extracted_citations"],
                "required_hits": citation_metrics["required_hits"],
                "allowed_hits": citation_metrics["allowed_hits"],
                "ungrounded_citations": citation_metrics["ungrounded_citations"],
                "precision": round(float(citation_metrics["precision"]), 6),
                "recall": round(float(citation_metrics["recall"]), 6),
                "required_coverage": round(float(citation_metrics["required_coverage"]), 6),
                "has_ungrounded_citations": bool(citation_metrics["has_ungrounded_citations"]),
            },
            "rubric": {
                "score": round(float(rubric_score_value), 6),
                "weights": {str(key): round(float(value), 6) for key, value in normalized_rubric_weights.items()},
            },
            "semantic_similarity": round(float(semantic_similarity), 6) if semantic_similarity is not None else None,
            "llm_judge": judge,
            "judge_agreement": judge_agreement,
        }


evaluation_service = EvaluationService()
