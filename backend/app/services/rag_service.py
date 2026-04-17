from __future__ import annotations

import json
from typing import Any, Optional
from uuid import uuid4

from openai import AsyncOpenAI

from app.core.config import settings
from app.models.profile import Profile
from app.schemas.rag import (
    RAGAskResponse,
    RAGCitation,
    RAGInsights,
    RAGSafetyReport,
    RAGTopOpportunity,
)
from app.services.evaluation_service import evaluation_service
from app.services.nlp_service import nlp_service
from app.services.vector_service import opportunity_vector_service


class RAGService:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY or "dummy_key_to_prevent_boot_crash",
        )

    def _profile_context(self, profile: Optional[Profile]) -> str:
        if not profile:
            return ""
        sections = [
            f"skills={profile.skills or ''}",
            f"interests={profile.interests or ''}",
            f"education={profile.education or ''}",
            f"achievements={profile.achievements or ''}",
        ]
        return " | ".join(section for section in sections if section.strip())

    async def retrieve(self, query: str, top_k: int = 8) -> dict[str, Any]:
        intent = await nlp_service.classify_intent(query)
        entities = await nlp_service.extract_entities_with_model(query)

        filters = {
            "intent": intent.get("intent"),
            "locations": entities.get("locations", []),
            "companies": entities.get("companies", []),
        }

        results = await opportunity_vector_service.search(
            query,
            top_k=max(1, min(top_k, 30)),
            filters=filters,
        )

        return {
            "intent": intent,
            "entities": entities,
            "results": results,
            "filters": filters,
        }

    def _heuristic_insight(self, query: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        top = results[:3]
        top_opportunities: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        for item in top:
            opportunity_id = str(item.get("id") or "")
            url = str(item.get("url") or "")
            if not opportunity_id.strip() or not url.strip():
                continue
            citation = {
                "opportunity_id": opportunity_id,
                "url": url,
                "title": item.get("title"),
                "source": item.get("source"),
            }
            citations.append(citation)
            top_opportunities.append(
                {
                    "opportunity_id": opportunity_id,
                    "title": str(item.get("title") or "Opportunity"),
                    "why_fit": "Strong semantic relevance to your query.",
                    "urgency": "high" if item.get("deadline") else "medium",
                    "match_score": round(max(0.0, float(item.get("similarity") or 0.0)) * 100.0, 2),
                    "citations": [citation],
                }
            )

        failed_checks: list[str] = []
        checks_passed = True
        if not results:
            checks_passed = False
            failed_checks.append("no_retrieval_results")
        elif not citations:
            checks_passed = False
            failed_checks.append("no_retrieved_sources_to_cite")

        return {
            "summary": f"Top {len(top_opportunities)} opportunities retrieved for: {query}",
            "top_opportunities": top_opportunities,
            "deadline_urgency": "Prioritize items with nearest deadline first.",
            "recommended_action": "Shortlist the top matches and apply in priority order.",
            "citations": citations,
            "safety": {"hallucination_checks_passed": checks_passed, "failed_checks": failed_checks},
            "contract_version": "rag_insights.v1",
        }

    def _allowed_sources(self, results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        allowed: dict[str, dict[str, Any]] = {}
        for item in results or []:
            opportunity_id = str(item.get("id") or "").strip()
            url = str(item.get("url") or "").strip()
            if not opportunity_id or not url:
                continue
            allowed[opportunity_id] = {
                "opportunity_id": opportunity_id,
                "url": url,
                "title": item.get("title"),
                "source": item.get("source"),
            }
        return allowed

    def _apply_hallucination_checks(self, insights: RAGInsights, results: list[dict[str, Any]]) -> RAGInsights:
        allowed = self._allowed_sources(results)
        failed_checks: list[str] = []
        if not results:
            failed_checks.append("no_retrieval_results")

        safe_top: list[RAGTopOpportunity] = []
        for item in insights.top_opportunities:
            if item.opportunity_id not in allowed:
                failed_checks.append(f"top_opportunity_id_not_retrieved:{item.opportunity_id}")
                continue

            canonical = allowed[item.opportunity_id]
            safe_citation = RAGCitation.model_validate(canonical)
            safe_top.append(
                item.model_copy(
                    update={
                        "citations": [safe_citation],
                        "title": item.title or str(canonical.get("title") or "Opportunity"),
                    }
                )
            )

        if insights.top_opportunities and not safe_top:
            failed_checks.append("all_top_opportunities_invalid")

        merged_citations: list[RAGCitation] = []
        seen: set[tuple[str, str]] = set()
        for item in safe_top:
            for citation in item.citations:
                key = (citation.opportunity_id, citation.url)
                if key in seen:
                    continue
                seen.add(key)
                merged_citations.append(citation)

        if results and not merged_citations:
            first = next(iter(allowed.values()), None)
            if first:
                merged_citations = [RAGCitation.model_validate(first)]
            else:
                failed_checks.append("missing_citations")

        safety = insights.safety
        updated_safety = RAGSafetyReport.model_validate(
            {
                "hallucination_checks_passed": len(failed_checks) == 0,
                "failed_checks": failed_checks,
                "quality_checks_passed": safety.quality_checks_passed,
                "quality_failed_checks": safety.quality_failed_checks,
                "judge_score": safety.judge_score,
                "judge_rationale": safety.judge_rationale,
            }
        )

        return insights.model_copy(
            update={
                "top_opportunities": safe_top,
                "citations": merged_citations,
                "safety": updated_safety,
            }
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

    async def _llm_insight(
        self,
        *,
        query: str,
        retrieval_payload: dict[str, Any],
        profile: Optional[Profile],
    ) -> dict[str, Any]:
        if not settings.OPENROUTER_API_KEY:
            return self._heuristic_insight(query, retrieval_payload.get("results", []))

        top_candidates = retrieval_payload.get("results", [])[:6]
        prompt = {
            "query": query,
            "intent": retrieval_payload.get("intent", {}),
            "entities": retrieval_payload.get("entities", {}),
            "profile": self._profile_context(profile),
            "candidates": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "description": item.get("description"),
                    "domain": item.get("domain"),
                    "opportunity_type": item.get("opportunity_type"),
                    "university": item.get("university"),
                    "deadline": str(item.get("deadline") or ""),
                    "similarity": item.get("similarity"),
                }
                for item in top_candidates
            ],
        }

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an opportunity-shortlisting assistant. "
                    "Return STRICT JSON only (no markdown). "
                    "Schema:\n"
                    "- summary: string\n"
                    "- top_opportunities: array (max 3) of {opportunity_id, title, why_fit, urgency(low|medium|high), match_score(0-100), citations}\n"
                    "- deadline_urgency: string\n"
                    "- recommended_action: string\n"
                    "- citations: array of {opportunity_id, url}\n"
                    "- safety: {hallucination_checks_passed, failed_checks}\n"
                    "Rules:\n"
                    "- Only use opportunity_id values from candidates.\n"
                    "- Every top_opportunity MUST include citations with the matching opportunity_id and url.\n"
                    "- citations must reference retrieved candidates (id + url)."
                ),
            },
            {"role": "user", "content": json.dumps(prompt)},
        ]

        response = await self._client.chat.completions.create(
            model=settings.OPENROUTER_MODEL,
            messages=messages,
            extra_headers={
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "VidyaVerse RAG",
            },
        )

        content = ""
        if response.choices and response.choices[0].message:
            content = response.choices[0].message.content or ""

        parsed = self._extract_json(content)
        if parsed:
            try:
                insights = RAGInsights.model_validate(parsed)
                insights = self._apply_hallucination_checks(insights, retrieval_payload.get("results", []))
                if insights.safety.hallucination_checks_passed:
                    return insights.model_dump()
            except Exception:
                pass
        return self._heuristic_insight(query, retrieval_payload.get("results", []))

    async def ask(self, *, query: str, top_k: int = 8, profile: Optional[Profile] = None) -> dict[str, Any]:
        retrieval_payload = await self.retrieve(query=query, top_k=top_k)
        insights = await self._llm_insight(
            query=query,
            retrieval_payload=retrieval_payload,
            profile=profile,
        )

        results = retrieval_payload.get("results", []) or []
        allowed = self._allowed_sources(results)
        insights_model = RAGInsights.model_validate(insights)
        insights_model = self._apply_hallucination_checks(insights_model, results)

        # Optional LLM-as-judge quality gate (disabled by default).
        if settings.LLM_JUDGE_ENABLED and settings.OPENROUTER_API_KEY:
            judge = await evaluation_service.judge_rag_response(
                query=query,
                candidates=results,
                insights=insights_model.model_dump(),
            )
            if judge:
                quality_failed: list[str] = []
                quality_passed = True
                judge_score = float(judge.get("score")) if judge.get("score") is not None else None
                if judge_score is not None and judge_score < float(settings.LLM_JUDGE_MIN_SCORE):
                    quality_passed = False
                    quality_failed.append("judge_below_threshold")
                    insights_model = RAGInsights.model_validate(self._heuristic_insight(query, results))
                    insights_model = self._apply_hallucination_checks(insights_model, results)

                insights_model = insights_model.model_copy(
                    update={
                        "safety": insights_model.safety.model_copy(
                            update={
                                "quality_checks_passed": quality_passed,
                                "quality_failed_checks": quality_failed,
                                "judge_score": judge_score,
                                "judge_rationale": str(judge.get("rationale") or "").strip()[:1000] or None,
                            }
                        )
                    }
                )

        # If retrieval succeeded but citations are still missing, ensure at least one safe citation.
        if results and not insights_model.citations:
            first = next(iter(allowed.values()), None)
            if first:
                insights_model = insights_model.model_copy(
                    update={"citations": [RAGCitation.model_validate(first)]}
                )

        response = RAGAskResponse.model_validate(
            {
                "request_id": uuid4().hex,
                "query": query,
                "intent": retrieval_payload.get("intent", {}) or {},
                "entities": retrieval_payload.get("entities", {}) or {},
                "results": [
                    {
                        "id": str(item.get("id") or ""),
                        "title": item.get("title"),
                        "description": item.get("description"),
                        "url": str(item.get("url") or ""),
                        "domain": item.get("domain"),
                        "opportunity_type": item.get("opportunity_type"),
                        "university": item.get("university"),
                        "deadline": item.get("deadline"),
                        "similarity": item.get("similarity"),
                        "source": item.get("source"),
                    }
                    for item in results
                    if item.get("id") and item.get("url")
                ],
                "insights": insights_model.model_dump(),
            }
        )
        return response.model_dump()


rag_service = RAGService()
