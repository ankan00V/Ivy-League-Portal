from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional
from uuid import uuid4

from beanie import PydanticObjectId
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
from app.services.rag_template_registry_service import rag_template_registry_service
from app.services.vector_service import opportunity_vector_service

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(self) -> None:
        self._api_base_url = (
            (settings.LLM_API_BASE_URL or "").strip()
            or (settings.OPENROUTER_BASE_URL or "").strip()
            or "https://openrouter.ai/api/v1"
        )
        self._api_key = (settings.LLM_API_KEY or settings.OPENROUTER_API_KEY or "").strip() or None
        self._model = (
            (settings.LLM_MODEL or "").strip()
            or (settings.OPENROUTER_MODEL or "").strip()
            or "meta-llama/llama-3-8b-instruct:free"
        )
        configured_rag_model = (settings.RAG_LLM_MODEL or "").strip()
        if configured_rag_model:
            self._rag_model = configured_rag_model
        elif "integrate.api.nvidia.com" in self._api_base_url.lower() and "deepseek-ai/deepseek-v3" in self._model:
            # NVIDIA-hosted deepseek-v3 variants can be high-latency for interactive Ask AI flows.
            self._rag_model = "meta/llama-3.1-8b-instruct"
            logger.warning(
                "RAG model auto-switched from %s to %s for lower interactive latency.",
                self._model,
                self._rag_model,
            )
        else:
            self._rag_model = self._model
        self._client = AsyncOpenAI(
            base_url=self._api_base_url,
            api_key=self._api_key or "dummy_key_to_prevent_boot_crash",
        )

    def _extra_headers(self, *, title: str) -> dict[str, str] | None:
        # OpenRouter supports optional ranking headers; other OpenAI-compatible hosts may ignore/reject them.
        if "openrouter.ai" not in self._api_base_url.lower():
            return None
        return {
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": title,
        }

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

    async def retrieve(self, query: str, top_k: int = 8, retrieval_settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        intent, entities = await asyncio.gather(
            nlp_service.classify_intent(query),
            nlp_service.extract_entities_with_model(query),
        )

        filters = {
            "intent": intent.get("intent"),
            "locations": entities.get("locations", []),
            "companies": entities.get("companies", []),
        }

        search_top_k = max(1, min(top_k, 30))
        if retrieval_settings and retrieval_settings.get("top_k") is not None:
            try:
                search_top_k = max(1, min(int(retrieval_settings.get("top_k")), 30))
            except Exception:
                pass

        results = await opportunity_vector_service.search(
            query,
            top_k=search_top_k,
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
        system_prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            return self._heuristic_insight(query, retrieval_payload.get("results", []))

        # If nothing was retrieved, skip expensive LLM invocation and return deterministic fallback.
        if not (retrieval_payload.get("results") or []):
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
                    "description": str(item.get("description") or "")[:480],
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
                    (system_prompt or "").strip()
                    or (
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
                    )
                ),
            },
            {"role": "user", "content": json.dumps(prompt)},
        ]

        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._rag_model,
                    messages=messages,
                    extra_headers=self._extra_headers(title="VidyaVerse RAG"),
                    response_format={"type": "json_object"},
                    temperature=0,
                    max_tokens=700,
                ),
                timeout=max(3.0, float(getattr(settings, "RAG_LLM_TIMEOUT_SECONDS", 15.0))),
            )
        except asyncio.TimeoutError:
            logger.warning("RAG LLM generation timed out; serving heuristic fallback.")
            return self._heuristic_insight(query, retrieval_payload.get("results", []))
        except Exception as exc:
            logger.warning("RAG LLM generation failed; serving heuristic fallback: %s", exc)
            return self._heuristic_insight(query, retrieval_payload.get("results", []))

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

    async def ask(
        self,
        *,
        query: str,
        top_k: Optional[int] = None,
        profile: Optional[Profile] = None,
        user_id: Optional[PydanticObjectId] = None,
    ) -> dict[str, Any]:
        template_resolution = await rag_template_registry_service.resolve_template(user_id=user_id)
        template = template_resolution.template
        requested_top_k = int(top_k) if top_k is not None else int(template.retrieval_top_k)
        effective_top_k = max(1, min(requested_top_k, 30))
        retrieval_settings = dict(template.retrieval_settings or {})
        if top_k is not None:
            retrieval_settings.pop("top_k", None)

        try:
            retrieval_payload = await asyncio.wait_for(
                self.retrieve(
                    query=query,
                    top_k=effective_top_k,
                    retrieval_settings=retrieval_settings,
                ),
                timeout=max(2.0, float(getattr(settings, "RAG_RETRIEVAL_TIMEOUT_SECONDS", 45.0))),
            )
        except asyncio.TimeoutError:
            logger.warning("RAG retrieval timed out; returning empty retrieval payload.")
            retrieval_payload = {"intent": {}, "entities": {}, "results": [], "filters": {}}
        except Exception as exc:
            logger.warning("RAG retrieval failed; returning empty retrieval payload: %s", exc)
            retrieval_payload = {"intent": {}, "entities": {}, "results": [], "filters": {}}

        insights = await self._llm_insight(
            query=query,
            retrieval_payload=retrieval_payload,
            profile=profile,
            system_prompt=template.system_prompt,
        )

        results = retrieval_payload.get("results", []) or []
        allowed = self._allowed_sources(results)
        insights_model = RAGInsights.model_validate(insights)
        insights_model = self._apply_hallucination_checks(insights_model, results)

        # Optional LLM-as-judge quality gate (disabled by default).
        if settings.LLM_JUDGE_ENABLED and self._api_key:
            try:
                judge = await asyncio.wait_for(
                    evaluation_service.judge_rag_response(
                        query=query,
                        candidates=results,
                        insights=insights_model.model_dump(),
                        rubric=template.judge_rubric,
                    ),
                    timeout=max(2.0, float(getattr(settings, "RAG_JUDGE_TIMEOUT_SECONDS", 8.0))),
                )
            except asyncio.TimeoutError:
                logger.warning("RAG judge timed out; continuing without judge signal.")
                judge = None
            except Exception as exc:
                logger.warning("RAG judge failed; continuing without judge signal: %s", exc)
                judge = None
            if judge:
                quality_failed: list[str] = []
                quality_passed = True
                judge_score = float(judge.get("score")) if judge.get("score") is not None else None
                min_judge_score = float(
                    (template.acceptance_thresholds or {}).get("min_judge_score", settings.LLM_JUDGE_MIN_SCORE)
                )
                if judge_score is not None and judge_score < min_judge_score:
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
                "governance": {
                    "template_key": template.template_key,
                    "template_label": template.label,
                    "template_version": template.version,
                    "template_version_id": str(template.id),
                    "retrieval_top_k": effective_top_k,
                    "experiment_key": template_resolution.experiment_key,
                    "experiment_variant": template_resolution.experiment_variant,
                    "assigned_via_experiment": template_resolution.assigned_via_experiment,
                    "acceptance_thresholds": dict(template.acceptance_thresholds or {}),
                },
            }
        )
        return response.model_dump()


rag_service = RAGService()
