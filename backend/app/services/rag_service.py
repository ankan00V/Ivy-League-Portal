from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional
from uuid import uuid4

from beanie import PydanticObjectId
from app.core.config import settings
from app.models.profile import Profile
from app.schemas.rag import (
    RAGAskResponse,
    RAGCitation,
    RAGInsights,
    RAGSafetyReport,
    RAGTopOpportunity,
)
from app.services.bedrock_llm_client import BedrockLLMClient, BedrockLLMConfig
from app.services.evaluation_service import evaluation_service
from app.services.nlp_service import nlp_service
from app.services.grounded_ai import live_model
from app.services.openai_client import create_async_openai_client
from app.services.rag_template_registry_service import (
    _default_system_prompt,
    rag_template_registry_service,
)
from app.services.vector_service import opportunity_vector_service
from app.services.reranker_service import reranker_service

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(self) -> None:
        self._provider = str(settings.LLM_PROVIDER or "openai_compatible").strip().lower()
        self._api_base_url = (
            (settings.LLM_API_BASE_URL or "").strip()
            or (settings.OPENROUTER_BASE_URL or "").strip()
            or "https://openrouter.ai/api/v1"
        )
        self._api_key = (settings.LLM_API_KEY or settings.OPENROUTER_API_KEY or "").strip() or None
        self._bedrock_api_key = (settings.AWS_BEARER_TOKEN_BEDROCK or "").strip() or None
        self._model = (
            (settings.LLM_MODEL or "").strip()
            or (settings.OPENROUTER_MODEL or "").strip()
            or "meta-llama/llama-3-8b-instruct:free"
        )
        configured_rag_model = (settings.RAG_LLM_MODEL or "").strip()
        if configured_rag_model:
            self._rag_model = configured_rag_model
        elif "integrate.api.nvidia.com" in self._api_base_url.lower() and "deepseek-ai/deepseek-v3" in self._model:
            # NVIDIA-hosted deepseek-v3 variants are high-latency for an
            # interactive Ask AI flow, so this swaps to a faster one.
            #
            # The model it swapped to used to be named here as a literal, and
            # the endpoint retired that model on 2026-08-26. From that date the
            # call returned HTTP 410 Gone, the exception handler below caught it
            # and served the heuristic answer, and Ask AI looked like it was
            # working: a well-formed response with no sign anywhere that the
            # grounded one had never been generated. Naming a settings value
            # means the substitute is reviewed and replaced with everything else
            # that points at a model, rather than aging quietly inside a branch
            # nobody reads.
            self._rag_model = (
                (settings.BRIEFING_LLM_MODEL or "").strip()
                or "nvidia/nemotron-3-super-120b-a12b"
            )
            logger.warning(
                "RAG model auto-switched from %s to %s for lower interactive latency.",
                self._model,
                self._rag_model,
            )
        else:
            self._rag_model = self._model
        # Last word on the model, after the configured value and the latency
        # auto-switch have both had theirs. A retired model reaches here from a
        # deployment's .env just as easily as from a hardcoded literal.
        self._rag_model = live_model(
            self._rag_model,
            fallback=(settings.BRIEFING_LLM_MODEL or "").strip() or "nvidia/nemotron-3-super-120b-a12b",
            context="Ask AI",
        )
        self._bedrock_model = (
            configured_rag_model
            or (settings.LLM_MODEL or "").strip()
            or (settings.BEDROCK_MODEL_ID or "").strip()
            or "us.anthropic.claude-3-5-haiku-20241022-v1:0"
        )
        self._bedrock_client = BedrockLLMClient(
            BedrockLLMConfig(
                api_key=self._bedrock_api_key,
                region=(
                    (settings.AWS_REGION or "").strip()
                    or (settings.AWS_DEFAULT_REGION or "").strip()
                    or "us-east-1"
                ),
                model_id=self._bedrock_model,
            )
        )
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = create_async_openai_client(
                base_url=self._api_base_url,
                api_key=self._api_key or "dummy_key_to_prevent_boot_crash",
            )
        return self._client

    def _extra_body(self) -> dict[str, Any] | None:
        """Suppress the model's reasoning preamble where the host accepts it.

        Reasoning-tuned models on NVIDIA's endpoint narrate their working before
        answering. Ask AI never shows that, and generating it costs most of the
        latency budget - measured on the briefing prompt, the same flag took one
        model from 37.4 seconds to 7.0 and another from 8.9 to 2.1. Sent only to
        hosts known to accept it, since an unknown body field is a 400 on some
        gateways and that would take Ask AI down rather than speed it up.
        """
        if "integrate.api.nvidia.com" not in self._api_base_url.lower():
            return None
        return {"chat_template_kwargs": {"thinking": False}}

    def _llm_configured(self) -> bool:
        if self._provider == "bedrock":
            return self._bedrock_client.is_configured
        return bool(self._api_key)

    def _extra_headers(self, *, title: str) -> dict[str, str] | None:
        # OpenRouter supports optional ranking headers; other OpenAI-compatible hosts may ignore/reject them.
        if "openrouter.ai" not in self._api_base_url.lower():
            return None
        return {
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": title,
        }

    def _profile_context(self, profile: Optional[Profile]) -> str:
        """Everything about the student that should shape a shortlist.

        This used to carry only skills, interests, education and achievements,
        so the copilot could not tell a final-year student from a fresher, did
        not know which roles or cities they wanted, and ignored their stipend
        expectation and availability - all of which the ordinary matcher already
        uses. Empty fields are dropped rather than sent as "field=", which would
        spend context on nothing and invite the model to invent a value.
        """
        if not profile:
            return ""
        fields = (
            ("skills", profile.skills),
            ("interests", profile.interests),
            ("education", profile.education),
            ("achievements", profile.achievements),
            ("course", getattr(profile, "course", None)),
            ("specialization", getattr(profile, "course_specialization", None)),
            ("domain", getattr(profile, "domain", None)),
            ("graduation_year", getattr(profile, "passout_year", None)),
            ("current_role", getattr(profile, "current_job_role", None)),
            ("experience", getattr(profile, "total_work_experience", None)),
            ("preferred_roles", getattr(profile, "preferred_roles", None)),
            ("preferred_locations", getattr(profile, "preferred_locations", None)),
            ("work_mode", getattr(profile, "preferred_work_mode", None)),
            ("expected_stipend", getattr(profile, "expected_stipend_range", None)),
            ("availability", getattr(profile, "availability", None)),
            ("bio", getattr(profile, "bio", None)),
        )
        sections = [
            f"{name}={str(value).strip()}"
            for name, value in fields
            if value is not None and str(value).strip()
        ]
        return " | ".join(sections)

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

        # Over-fetch, then rerank, then truncate. Asking the bi-encoder for exactly
        # top_k means a candidate the cross-encoder would have promoted is never
        # scored by it - the reranker can only reorder what retrieval hands it, so
        # the shortlist has to be deeper than the answer.
        candidate_k = max(search_top_k, int(getattr(settings, "RAG_RERANK_CANDIDATES", 40)))
        candidates = await opportunity_vector_service.search(
            query,
            top_k=candidate_k,
            filters=filters,
        )

        results = await reranker_service.rerank(
            query=query,
            candidates=candidates,
            top_k=search_top_k,
        )

        return {
            "intent": intent,
            "entities": entities,
            "results": results,
            "filters": filters,
            "retrieval_debug": {
                "candidates_retrieved": len(candidates),
                "returned": len(results),
                "reranked": bool(results and "rerank_score" in results[0]),
                # Best cross-encoder score among the rows actually returned.
                #
                # This is the question cosine similarity structurally cannot answer.
                # Similarity is relative - the nearest vector is always returned, so
                # 0.48 means "closest thing in the corpus", not "a match". That is
                # how "product and analytics competitions worth shortlisting this
                # week" returned a Codeforces round and had it described as a
                # shortlist. The cross-encoder scores on an absolute scale, and on
                # that query every candidate lands near -10: the corpus correctly
                # reporting it holds no product or analytics competition at all.
                #
                # Callers can use this to say so, rather than presenting the
                # least-bad rows as though they answered the question.
                "top_rerank_score": max(
                    (float(r["rerank_score"]) for r in results if "rerank_score" in r),
                    default=None,
                ),
            },
        }

    @staticmethod
    def _no_strong_match_insight(query: str, top_score: Optional[float]) -> dict[str, Any]:
        """Say the corpus has nothing, rather than ranking the least-bad rows.

        Retrieval always returns its nearest neighbours, so an unanswerable
        query still produces a full shortlist - and every layer above it then
        treats that shortlist as an answer. Presenting a Codeforces round as a
        "product and analytics competition" is worse than returning nothing:
        it spends the reader's attention and teaches them the shortlist cannot
        be trusted.

        Deliberately carries no top_opportunities and no citations. Grounding
        checks pass because abstaining is a correct outcome, not a failure.
        """
        return {
            "summary": (
                "No strong match. Nothing currently listed answers this closely enough "
                "to shortlist, so the results have been withheld rather than ranked by "
                "how near they happen to fall."
            ),
            "top_opportunities": [],
            "deadline_urgency": "Not applicable - nothing was shortlisted.",
            "recommended_action": (
                "Try a broader phrasing, a different domain, or check back once more "
                "sources have been ingested."
            ),
            "citations": [],
            "safety": {"hallucination_checks_passed": True, "failed_checks": []},
            "abstained": True,
            "abstain_reason": "no_candidate_above_relevance_threshold",
            "top_relevance_score": top_score,
            "contract_version": "rag_insights.v1",
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

    @staticmethod
    def _resolve_refs(parsed: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """Turn the model's `ref` integers back into canonical ids, urls and citations.

        Grounding is enforced here rather than requested in the prompt. A ref is
        either a valid index into the candidate list - in which case the id, url
        and title come from the retrieved row and are correct by construction -
        or it is not, in which case the entry is dropped. There is no third
        outcome, so the model cannot cite an opportunity that was never
        retrieved no matter what it emits.

        Citations are rebuilt from the surviving entries for the same reason:
        anything the model wrote in that field is discarded.
        """
        resolved: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []

        for entry in parsed.get("top_opportunities") or []:
            if not isinstance(entry, dict):
                continue
            try:
                ref = int(entry.get("ref"))
            except (TypeError, ValueError):
                continue
            if ref < 0 or ref >= len(candidates):
                continue

            source = candidates[ref]
            opportunity_id = str(source.get("id") or "").strip()
            url = str(source.get("url") or "").strip()
            if not opportunity_id or not url:
                continue

            citation = {"opportunity_id": opportunity_id, "url": url}
            item = dict(entry)
            item.pop("ref", None)
            item["opportunity_id"] = opportunity_id
            item["title"] = source.get("title")
            item["citations"] = [citation]
            resolved.append(item)
            if citation not in citations:
                citations.append(citation)

        out = dict(parsed)
        out["top_opportunities"] = resolved
        out["citations"] = citations
        return out

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
                # The model produced no citable opportunity, so this attaches
                # the top retrieval result instead. That keeps the response
                # shape intact, but the answer is NOT grounded in this source -
                # the model never referenced it. Recording the substitution
                # keeps hallucination_checks_passed honest; previously the
                # answer was silently presented as fully grounded.
                merged_citations = [RAGCitation.model_validate(first)]
                failed_checks.append("citations_substituted_from_retrieval")
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
        if not self._llm_configured():
            return self._heuristic_insight(query, retrieval_payload.get("results", []))

        # If nothing was retrieved, skip expensive LLM invocation and return deterministic fallback.
        if not (retrieval_payload.get("results") or []):
            return self._heuristic_insight(query, retrieval_payload.get("results", []))

        # Nothing retrieved is rare; nothing *relevant* retrieved is common, and
        # until now looked identical to a good answer. Checked before the LLM
        # call because there is no answer worth paying for here - the model
        # would only be asked to justify rows the reranker already rejected.
        if bool(getattr(settings, "RAG_ABSTAIN_ON_LOW_RELEVANCE", True)):
            top_score = (retrieval_payload.get("retrieval_debug") or {}).get("top_rerank_score")
            threshold = float(getattr(settings, "RAG_MIN_RELEVANCE_SCORE", -5.0))
            if top_score is not None and float(top_score) < threshold:
                logger.info(
                    "Ask AI abstaining: best candidate scored %.3f, below %.3f, for query %r",
                    float(top_score), threshold, query[:120],
                )
                return self._no_strong_match_insight(query, float(top_score))

        top_candidates = retrieval_payload.get("results", [])[:6]
        prompt = {
            "query": query,
            "intent": retrieval_payload.get("intent", {}),
            "entities": retrieval_payload.get("entities", {}),
            "profile": self._profile_context(profile),
            # Candidates are addressed by `ref`, a small integer index into
            # top_candidates. The model is deliberately not shown opportunity ids
            # or urls: it cannot cite what it has never been given, and it no
            # longer has to transcribe a 24-hex ObjectId character by character -
            # which is how llama-3.1-8b produced
            # top_opportunity_id_not_retrieved:6a734a20c87526767b68e1cb and lost a
            # whole answer to the hallucination gate. The server resolves ref back
            # to the canonical id, url and title below.
            "candidates": [
                {
                    "ref": index,
                    "title": item.get("title"),
                    "description": str(item.get("description") or "")[:480],
                    "domain": item.get("domain"),
                    "opportunity_type": item.get("opportunity_type"),
                    "university": item.get("university"),
                    "deadline": str(item.get("deadline") or ""),
                    "similarity": item.get("similarity"),
                }
                for index, item in enumerate(top_candidates)
            ],
        }

        messages = [
            {
                "role": "system",
                "content": (
                    # One definition of the output contract, imported rather
                    # than restated. The copy that used to live here drifted from
                    # the stored template and silently broke every answer.
                    (system_prompt or "").strip() or _default_system_prompt()
                ),
            },
            {"role": "user", "content": json.dumps(prompt)},
        ]

        try:
            if self._provider == "bedrock":
                content = await asyncio.wait_for(
                    self._bedrock_client.complete(
                        model_id=self._bedrock_model,
                        messages=messages,
                        temperature=0,
                        max_tokens=max(700, int(getattr(settings, "RAG_LLM_MAX_TOKENS", 2000))),
                    ),
                    timeout=max(3.0, float(getattr(settings, "RAG_LLM_TIMEOUT_SECONDS", 15.0))),
                )
            else:
                response = await asyncio.wait_for(
                    self._get_client().chat.completions.create(
                        model=self._rag_model,
                        messages=messages,
                        extra_headers=self._extra_headers(title="VidyaVerse RAG"),
                        response_format={"type": "json_object"},
                        extra_body=self._extra_body(),
                        temperature=0,
                        max_tokens=max(700, int(getattr(settings, "RAG_LLM_MAX_TOKENS", 2000))),
                    ),
                    timeout=max(3.0, float(getattr(settings, "RAG_LLM_TIMEOUT_SECONDS", 15.0))),
                )
                content = ""
                if response.choices and response.choices[0].message:
                    content = response.choices[0].message.content or ""
        except asyncio.TimeoutError:
            logger.warning("RAG LLM generation timed out; serving heuristic fallback.")
            return self._heuristic_insight(query, retrieval_payload.get("results", []))
        except Exception as exc:
            logger.warning("RAG LLM generation failed; serving heuristic fallback: %s", exc)
            return self._heuristic_insight(query, retrieval_payload.get("results", []))

        # Every fallback below is logged with its reason. This block previously
        # swallowed all three failure modes in silence, so a truncated completion
        # was indistinguishable from a model that had never been called: the API
        # returned a well-formed heuristic answer and nothing anywhere recorded
        # that the LLM's grounded output had been discarded.
        parsed = self._extract_json(content)
        if not parsed:
            logger.warning(
                "RAG LLM returned unparseable content (%d chars); serving heuristic fallback. "
                "A truncated tail usually means RAG_LLM_MAX_TOKENS is too low for the schema.",
                len(content or ""),
            )
            return self._heuristic_insight(query, retrieval_payload.get("results", []))

        parsed = self._resolve_refs(parsed, top_candidates)
        if not parsed.get("top_opportunities"):
            logger.warning(
                "RAG LLM returned no resolvable candidate refs; serving heuristic fallback."
            )
            return self._heuristic_insight(query, retrieval_payload.get("results", []))

        try:
            insights = RAGInsights.model_validate(parsed)
        except Exception as exc:
            logger.warning("RAG LLM JSON failed schema validation; serving heuristic fallback: %s", exc)
            return self._heuristic_insight(query, retrieval_payload.get("results", []))

        insights = self._apply_hallucination_checks(insights, retrieval_payload.get("results", []))
        if insights.safety.hallucination_checks_passed:
            return insights.model_dump()

        logger.warning(
            "RAG LLM answer failed hallucination checks %s; serving heuristic fallback.",
            list(insights.safety.failed_checks or []),
        )
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
        if settings.LLM_JUDGE_ENABLED and self._llm_configured():
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
