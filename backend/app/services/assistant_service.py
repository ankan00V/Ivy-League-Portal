from __future__ import annotations

import time
from typing import Any, Optional
from uuid import uuid4

from beanie.odm.operators.find.comparison import In
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.time import utc_now
from app.models.assistant_audit_event import AssistantAuditEvent
from app.models.assistant_conversation_turn import AssistantConversationTurn
from app.models.assistant_memory_state import AssistantMemoryState
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.user import User
from app.services.rag_service import rag_service
from app.services.ranking_model_service import ranking_model_service
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

    def _prompt_version(self) -> str:
        return str(settings.ASSISTANT_CHAT_PROMPT_VERSION or "assistant.v2").strip() or "assistant.v2"

    def _extra_headers(self) -> dict[str, str] | None:
        if "openrouter.ai" not in self._api_base_url.lower():
            return None
        return {
            "HTTP-Referer": "http://localhost:3000",
            "X-Title": "VidyaVerse Assistant",
        }

    def _memory_limits(self) -> tuple[int, int]:
        trigger = max(8, int(settings.ASSISTANT_CHAT_SUMMARY_TRIGGER_TURNS))
        retain = max(4, min(trigger - 2, int(settings.ASSISTANT_CHAT_SUMMARY_RETAIN_TURNS)))
        return trigger, retain

    async def _load_memory(self, *, user_id, surface: str) -> tuple[list[dict[str, str]], bool]:
        if not settings.ASSISTANT_CHAT_MEMORY_ENABLED:
            return [], False
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
        memory = [
            {"role": str(row.role or "user"), "content": str(row.content or "")}
            for row in rows
            if str(row.content or "").strip()
        ]
        summary_state = await AssistantMemoryState.find_one(
            AssistantMemoryState.user_id == user_id,
            AssistantMemoryState.surface == surface,
        )
        summary_used = bool(summary_state and str(summary_state.summary or "").strip())
        if summary_used:
            memory.insert(
                0,
                {
                    "role": "system",
                    "content": f"[Conversation summary] {summary_state.summary.strip()}",
                },
            )
        return memory, summary_used

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
                created_at=utc_now(),
            ),
            AssistantConversationTurn(
                user_id=user_id,
                surface=surface,
                role="assistant",
                content=assistant_text,
                request_id=request_id,
                metadata=dict(metadata or {}),
                created_at=utc_now(),
            ),
        ]
        await AssistantConversationTurn.insert_many(rows)
        await self._compact_memory(user_id=user_id, surface=surface)

    async def _compact_memory(self, *, user_id, surface: str) -> None:
        if not settings.ASSISTANT_CHAT_SUMMARY_ENABLED:
            return
        trigger, retain = self._memory_limits()
        rows = (
            await AssistantConversationTurn.find(
                AssistantConversationTurn.user_id == user_id,
                AssistantConversationTurn.surface == surface,
            )
            .sort("-created_at")
            .to_list()
        )
        if len(rows) <= trigger:
            return
        rows.reverse()
        archived = rows[:-retain]
        retained = rows[-retain:]
        summary_lines = []
        for row in archived[-12:]:
            role = "User" if row.role == "user" else "Assistant"
            summary_lines.append(f"{role}: {str(row.content or '').strip()[:220]}")
        summary_text = " | ".join(line for line in summary_lines if line)
        if not summary_text:
            return
        state = await AssistantMemoryState.find_one(
            AssistantMemoryState.user_id == user_id,
            AssistantMemoryState.surface == surface,
        )
        if state is None:
            state = AssistantMemoryState.model_construct(
                user_id=user_id,
                surface=surface,
                summary=summary_text,
                summarized_turns=len(archived),
                updated_at=utc_now(),
            )
            await state.insert()
        else:
            prefix = str(state.summary or "").strip()
            merged = " | ".join(part for part in [prefix, summary_text] if part)
            state.summary = merged[-4000:]
            state.summarized_turns = max(int(state.summarized_turns or 0), len(archived))
            state.updated_at = utc_now()
            await state.save()
        archived_ids = [row.id for row in archived]
        if archived_ids:
            await AssistantConversationTurn.find(In(AssistantConversationTurn.id, archived_ids)).delete()
        _ = retained

    def _tool_route(self, text: str) -> tuple[str, str | None]:
        normalized = str(text or "").strip().lower()
        if not settings.ASSISTANT_CHAT_TOOLS_ENABLED or not normalized:
            return "general", None
        if any(token in normalized for token in {"my profile", "profile summary", "skills", "resume"}):
            return "tool", "profile_lookup"
        if any(token in normalized for token in {"top opportunities", "find opportunities", "latest opportunities"}):
            return "tool", "opportunity_lookup"
        if any(token in normalized for token in {"why recommended", "ranking", "ranked", "match score"}):
            return "tool", "ranking_explanation"
        if any(token in normalized for token in {"how do i apply", "application guidance", "application checklist"}):
            return "tool", "application_guidance"
        if settings.ASSISTANT_CHAT_RAG_AUTO_ROUTE_ENABLED and _looks_like_rag_query(normalized):
            return "rag", None
        return "general", None

    async def _tool_profile_lookup(self, *, user: User, profile: Optional[Profile]) -> tuple[str, list[dict[str, Any]]]:
        if profile is None:
            return "Your profile is not set up yet. Complete onboarding and upload a resume to unlock personalized guidance.", []
        goals = ", ".join(profile.goals[:4]) if profile.goals else "not set"
        summary = (
            f"Profile summary for {user.full_name or user.email}: "
            f"user_type={profile.user_type or 'unknown'}, domain={profile.domain or 'unknown'}, "
            f"skills={profile.skills or 'not set'}, education={profile.education or 'not set'}, "
            f"goals={goals}, resume_uploaded={'yes' if profile.resume_url else 'no'}."
        )
        return summary, []

    async def _tool_opportunity_lookup(self, *, query: str) -> tuple[str, list[dict[str, Any]]]:
        keywords = [part.strip() for part in query.lower().replace(",", " ").split() if len(part.strip()) >= 3]
        rows = await Opportunity.find_many().sort("-last_seen_at").limit(100).to_list()
        matched = []
        for row in rows:
            haystack = " ".join(
                [
                    row.title or "",
                    row.description or "",
                    row.domain or "",
                    row.location or "",
                    row.opportunity_type or "",
                ]
            ).lower()
            if not keywords or any(keyword in haystack for keyword in keywords):
                matched.append(row)
            if len(matched) >= 5:
                break
        if not matched:
            return "No matching live opportunities were found for that query.", []
        citations = [
            {
                "opportunity_id": str(row.id),
                "url": row.url,
                "title": row.title,
                "source": row.source,
            }
            for row in matched
        ]
        lines = [
            f"{idx + 1}. {row.title} | {row.location or 'location unknown'} | {row.domain or 'general'}"
            for idx, row in enumerate(matched)
        ]
        return "Top live opportunities:\n" + "\n".join(lines), citations

    async def _tool_ranking_explanation(self, *, profile: Optional[Profile]) -> tuple[str, list[dict[str, Any]]]:
        active = await ranking_model_service.get_active()
        weights = active.weights
        summary = (
            "Ranking explanation: the live ranker blends semantic relevance, baseline quality, and behavior signals. "
            f"Current weights are semantic={weights.get('semantic', 0):.2f}, "
            f"baseline={weights.get('baseline', 0):.2f}, behavior={weights.get('behavior', 0):.2f}. "
        )
        if profile is not None:
            summary += (
                f"For your profile, the strongest personal signals come from skills={profile.skills or 'not set'} "
                f"and interests={profile.interests or 'not set'}."
            )
        return summary, []

    async def _tool_application_guidance(self, *, profile: Optional[Profile]) -> tuple[str, list[dict[str, Any]]]:
        missing = []
        if profile is None:
            missing.extend(["profile", "resume", "skills"])
        else:
            if not str(profile.skills or "").strip():
                missing.append("skills")
            if not str(profile.education or "").strip():
                missing.append("education")
            if not str(profile.resume_url or "").strip():
                missing.append("resume")
        guidance = [
            "1. Shortlist only opportunities that match your domain and eligibility.",
            "2. Tailor your resume bullets to the opportunity title and required skills.",
            "3. Apply to the nearest-deadline roles first and track status in the dashboard.",
        ]
        if missing:
            guidance.append("Missing profile inputs: " + ", ".join(missing) + ".")
        return "\n".join(guidance), []

    async def _execute_tool(
        self,
        *,
        tool_name: str,
        user: User,
        profile: Optional[Profile],
        latest_user_message: str,
    ) -> dict[str, Any]:
        if tool_name == "profile_lookup":
            message, citations = await self._tool_profile_lookup(user=user, profile=profile)
        elif tool_name == "opportunity_lookup":
            message, citations = await self._tool_opportunity_lookup(query=latest_user_message)
        elif tool_name == "ranking_explanation":
            message, citations = await self._tool_ranking_explanation(profile=profile)
        elif tool_name == "application_guidance":
            message, citations = await self._tool_application_guidance(profile=profile)
        else:
            raise RuntimeError(f"Unsupported assistant tool: {tool_name}")
        return {
            "message": message,
            "citations": citations,
            "mode": "tool",
            "tool_name": tool_name,
        }

    async def _audit(
        self,
        *,
        user: User,
        request_id: str,
        surface: str,
        route: str,
        tool_name: str | None,
        summary_used: bool,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        row = AssistantAuditEvent(
            user_id=user.id,
            surface=surface,
            request_id=request_id,
            route=route,
            tool_name=tool_name,
            prompt_version=self._prompt_version(),
            summary_used=summary_used,
            metadata=dict(metadata or {}),
            created_at=utc_now(),
        )
        await row.insert()

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

        route, tool_name = self._tool_route(latest_user_message)
        try:
            if route == "rag":
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
                    metadata={"mode": "rag", "citations": citations, "prompt_version": self._prompt_version()},
                )
                await self._audit(
                    user=user,
                    request_id=request_id,
                    surface=surface,
                    route="rag",
                    tool_name=None,
                    summary_used=False,
                    metadata={"citations": len(citations)},
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

            if route == "tool" and tool_name:
                tool_result = await self._execute_tool(
                    tool_name=tool_name,
                    user=user,
                    profile=profile,
                    latest_user_message=latest_user_message,
                )
                await self._persist_turns(
                    user_id=user.id,
                    surface=surface,
                    request_id=request_id,
                    user_text=latest_user_message,
                    assistant_text=str(tool_result["message"]),
                    metadata={"mode": "tool", "tool_name": tool_name, "prompt_version": self._prompt_version()},
                )
                await self._audit(
                    user=user,
                    request_id=request_id,
                    surface=surface,
                    route="tool",
                    tool_name=tool_name,
                    summary_used=False,
                    metadata={"citations": len(tool_result["citations"])},
                )
                await ranking_request_telemetry_service.log(
                    request_kind=request_kind,
                    surface=surface,
                    latency_ms=(time.perf_counter() - started_at) * 1000.0,
                    success=True,
                    user_id=user.id,
                    ranking_mode=f"assistant_tool:{tool_name}",
                    experiment_key="assistant_router",
                    experiment_variant="tool",
                    results_count=len(tool_result["citations"]),
                    traffic_type="real",
                )
                return {
                    "request_id": request_id,
                    "message": str(tool_result["message"]),
                    "mode": "tool",
                    "citations": list(tool_result["citations"]),
                    "results": [],
                }

            if not self._api_key:
                raise RuntimeError("Underlying AI service is not configured (Missing API Key).")

            memory, summary_used = await self._load_memory(user_id=user.id, surface=surface)
            system_prompt = (
                "You are Vidya, the official AI assistant for VidyaVerse. "
                "Be practical, concise, grounded, and useful. "
                "Use application facts and user profile facts when available. "
                "If the user asks for live opportunities, prefer grounded search instead of inventing listings."
            )
            api_messages = [{"role": "system", "content": system_prompt}]
            api_messages.append(
                {
                    "role": "system",
                    "content": f"[Prompt version: {self._prompt_version()} | User context: {user.full_name or user.email} <{user.email}>]",
                }
            )
            if profile is not None:
                api_messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"[Profile: user_type={profile.user_type or 'unknown'}; "
                            f"domain={profile.domain or 'unknown'}; "
                            f"skills={profile.skills or 'not set'}; "
                            f"education={profile.education or 'not set'}]"
                        ),
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
                metadata={"mode": "general", "prompt_version": self._prompt_version()},
            )
            await self._audit(
                user=user,
                request_id=request_id,
                surface=surface,
                route="general",
                tool_name=None,
                summary_used=summary_used,
                metadata={"message_length": len(message)},
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
