from __future__ import annotations

import time
from typing import Any, Optional
from uuid import uuid4

from openai import AsyncOpenAI

from app.core.config import settings
from app.models.assistant_conversation_turn import AssistantConversationTurn
from app.models.profile import Profile
from app.models.user import User
from app.services.rag_service import rag_service
from app.services.ranking_request_telemetry_service import ranking_request_telemetry_service


def _looks_like_rag_query(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    keywords = {
        "internship",
        "internships",
        "job",
        "jobs",
        "opportunity",
        "opportunities",
        "scholarship",
        "scholarships",
        "research",
        "hackathon",
        "fellowship",
        "deadline",
        "apply",
    }
    return any(token in normalized for token in keywords)


class AssistantService:
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
        self._client = AsyncOpenAI(
            base_url=self._api_base_url,
            api_key=self._api_key or "dummy_key_to_prevent_boot_crash",
        )

    async def _load_memory(self, *, user_id, surface: str) -> list[dict[str, str]]:
        if not settings.ASSISTANT_CHAT_MEMORY_ENABLED:
            return []
        safe_limit = max(2, min(int(settings.ASSISTANT_CHAT_MEMORY_MAX_TURNS), 30))
        rows = (
            await AssistantConversationTurn.find(
                AssistantConversationTurn.user_id == user_id,
                AssistantConversationTurn.surface == surface,
            )
            .sort("-created_at")
            .limit(safe_limit)
            .to_list()
        )
        rows.reverse()
        return [
            {"role": str(row.role or "user"), "content": str(row.content or "")}
            for row in rows
            if str(row.content or "").strip()
        ]

    async def _persist_turns(
        self,
        *,
        user_id,
        surface: str,
        request_id: str,
        user_text: str,
        assistant_text: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        if not settings.ASSISTANT_CHAT_MEMORY_ENABLED:
            return
        rows = [
            AssistantConversationTurn(
                user_id=user_id,
                surface=surface,
                role="user",
                content=user_text,
                request_id=request_id,
                metadata=dict(metadata or {}),
            ),
            AssistantConversationTurn(
                user_id=user_id,
                surface=surface,
                role="assistant",
                content=assistant_text,
                request_id=request_id,
                metadata=dict(metadata or {}),
            ),
        ]
        await AssistantConversationTurn.insert_many(rows)

    def _extra_headers(self) -> dict[str, str] | None:
        if "openrouter.ai" not in self._api_base_url.lower():
            return None
        return {
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "VidyaVerse Assistant",
        }

    async def chat(
        self,
        *,
        user: User,
        messages: list[dict[str, str]],
        surface: str,
        profile: Optional[Profile] = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        request_id = uuid4().hex
        request_kind = "assistant_chat"
        latest_user_message = next(
            (str(item.get("content") or "").strip() for item in reversed(messages) if str(item.get("role") or "") == "user"),
            "",
        )

        try:
            if not self._api_key:
                raise RuntimeError("Underlying AI service is not configured (Missing API Key).")

            if settings.ASSISTANT_CHAT_RAG_AUTO_ROUTE_ENABLED and _looks_like_rag_query(latest_user_message):
                rag_result = await rag_service.ask(
                    query=latest_user_message,
                    top_k=8,
                    profile=profile,
                    user_id=user.id,
                )
                insights = dict(rag_result.get("insights") or {})
                message = str(insights.get("summary") or "").strip() or "No grounded answer generated."
                citations = list(insights.get("citations") or [])
                await self._persist_turns(
                    user_id=user.id,
                    surface=surface,
                    request_id=request_id,
                    user_text=latest_user_message,
                    assistant_text=message,
                    metadata={"mode": "rag", "citations": citations},
                )
                await ranking_request_telemetry_service.log(
                    request_kind=request_kind,
                    surface=surface,
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    success=True,
                    user_id=user.id,
                    ranking_mode="assistant_rag",
                    experiment_key="assistant_router",
                    experiment_variant="rag",
                    rag_template_label=str((rag_result.get("governance") or {}).get("template_label") or ""),
                    rag_template_version_id=str((rag_result.get("governance") or {}).get("template_version_id") or ""),
                    results_count=len(rag_result.get("results") or []),
                    traffic_type="real",
                )
                return {
                    "request_id": request_id,
                    "message": message,
                    "mode": "rag",
                    "citations": citations,
                    "results": rag_result.get("results") or [],
                }

            memory = await self._load_memory(user_id=user.id, surface=surface)
            system_prompt = (
                "You are Vidya, the official AI assistant for VidyaVerse. "
                "Be practical, concise, grounded, and useful. "
                "When the user asks for opportunities, direct them toward grounded search results instead of inventing listings."
            )
            api_messages = [{"role": "system", "content": system_prompt}]
            api_messages.append(
                {
                    "role": "system",
                    "content": f"[User context: {user.full_name or user.email} <{user.email}>]",
                }
            )
            api_messages.extend(memory[-max(0, len(memory)):])
            for item in messages[-10:]:
                role = str(item.get("role") or "").strip()
                content = str(item.get("content") or "").strip()
                if role in {"user", "assistant"} and content:
                    api_messages.append({"role": role, "content": content})

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=api_messages,
                extra_headers=self._extra_headers(),
            )
            message = str(response.choices[0].message.content or "").strip()
            if not message:
                raise RuntimeError("Empty response received from AI Model")

            await self._persist_turns(
                user_id=user.id,
                surface=surface,
                request_id=request_id,
                user_text=latest_user_message,
                assistant_text=message,
                metadata={"mode": "general"},
            )
            await ranking_request_telemetry_service.log(
                request_kind=request_kind,
                surface=surface,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                success=True,
                user_id=user.id,
                ranking_mode="assistant_general",
                experiment_key="assistant_router",
                experiment_variant="general",
                traffic_type="real",
            )
            return {
                "request_id": request_id,
                "message": message,
                "mode": "general",
                "citations": [],
                "results": [],
            }
        except Exception as exc:
            await ranking_request_telemetry_service.log(
                request_kind=request_kind,
                surface=surface,
                latency_ms=(time.perf_counter() - started_at) * 1000.0,
                success=False,
                user_id=user.id,
                ranking_mode="assistant_error",
                experiment_key="assistant_router",
                experiment_variant="error",
                error_code=exc.__class__.__name__,
                traffic_type="real",
            )
            raise


assistant_service = AssistantService()
