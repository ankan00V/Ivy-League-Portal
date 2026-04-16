from __future__ import annotations

import json
from typing import Any, Optional

from openai import AsyncOpenAI

from app.core.config import settings
from app.models.profile import Profile
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
        entities = nlp_service.extract_entities(query)

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
        return {
            "summary": f"Top {len(top)} opportunities retrieved for: {query}",
            "top_opportunities": [
                {
                    "opportunity_id": item.get("id"),
                    "title": item.get("title"),
                    "why_fit": "Strong semantic relevance to your query.",
                    "urgency": "high" if item.get("deadline") else "medium",
                    "match_score": round(max(0.0, float(item.get("similarity") or 0.0)) * 100.0, 2),
                }
                for item in top
            ],
            "deadline_urgency": "Prioritize items with nearest deadline first.",
            "recommended_action": "Shortlist the top matches and apply in priority order.",
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

        response = await self._client.chat.completions.create(
            model=settings.OPENROUTER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an opportunity-shortlisting assistant. "
                        "Return strict JSON only with keys: summary, top_opportunities, deadline_urgency, recommended_action. "
                        "top_opportunities must be an array of max 3 objects with: opportunity_id, title, why_fit, urgency, match_score."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt),
                },
            ],
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
            return parsed
        return self._heuristic_insight(query, retrieval_payload.get("results", []))

    async def ask(self, *, query: str, top_k: int = 8, profile: Optional[Profile] = None) -> dict[str, Any]:
        retrieval_payload = await self.retrieve(query=query, top_k=top_k)
        insights = await self._llm_insight(
            query=query,
            retrieval_payload=retrieval_payload,
            profile=profile,
        )

        return {
            "query": query,
            "intent": retrieval_payload.get("intent", {}),
            "entities": retrieval_payload.get("entities", {}),
            "results": retrieval_payload.get("results", []),
            "insights": insights,
        }


rag_service = RAGService()
