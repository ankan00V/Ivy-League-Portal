from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import numpy as np
from beanie import PydanticObjectId

from app.core.time import utc_now
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.services.embedding_pipeline import embedding_pipeline
from app.services.embedding_service import embedding_service

ColdStartStrategy = Literal["diversity", "semantic", "ml"]
PersonalizationLevel = Literal["low", "medium", "high"]


def _split_terms(value: Any, *, limit: int = 24) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        parts = [str(item).strip() for item in value]
    else:
        raw = str(value)
        for separator in (";", "\n", "/", "|"):
            raw = raw.replace(separator, ",")
        parts = [chunk.strip() for chunk in raw.split(",")]

    output: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = part.lower()
        if not part or key in seen:
            continue
        seen.add(key)
        output.append(part)
    return output[:limit]


def _text_present(value: Any) -> bool:
    return bool(str(value or "").strip())


def _vector_to_list(vector: np.ndarray) -> list[float]:
    values = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(values))
    if norm > 1e-12:
        values = values / norm
    return [float(item) for item in values.tolist()]


@dataclass(frozen=True)
class UserPreferenceFilter:
    domains: list[str] = field(default_factory=list)
    preferred_work_mode: Optional[str] = None
    locations: list[str] = field(default_factory=list)
    expected_stipend_min: Optional[int] = None
    expected_stipend_max: Optional[int] = None
    graduation_year: Optional[int] = None
    opportunity_types: list[str] = field(default_factory=list)

    def vector_filters(self, *, quality_min: float = 30.0) -> dict[str, Any]:
        filters: dict[str, Any] = {"quality_min": float(quality_min)}
        if self.preferred_work_mode:
            filters["work_mode"] = self.preferred_work_mode
        if self.locations:
            filters["locations"] = list(self.locations)
        if self.expected_stipend_min is not None:
            filters["stipend_min"] = int(self.expected_stipend_min)
        if self.opportunity_types:
            filters["opportunity_types"] = list(self.opportunity_types)
        return filters


@dataclass(frozen=True)
class ColdStartProfileResult:
    quality_score: float
    preference_text: str
    preference_filter: UserPreferenceFilter
    embedding: list[float]
    model_version: Optional[str]
    persona_cluster_id: Optional[int]


@dataclass(frozen=True)
class ColdStartDecision:
    strategy: ColdStartStrategy
    ranking_mode: str
    personalization_level: PersonalizationLevel
    quality_score: float
    interaction_count: int
    persona_cluster_id: Optional[int]


class ColdStartProfileBuilder:
    persona_cluster_count = 8

    def preference_filter(self, profile: Profile) -> UserPreferenceFilter:
        domains = _split_terms(getattr(profile, "domains_of_interest", None))
        if not domains and _text_present(getattr(profile, "domain", None)):
            domains = _split_terms(getattr(profile, "domain", None), limit=4)
        locations = _split_terms(getattr(profile, "preferred_locations", None), limit=12)
        work_mode = str(getattr(profile, "preferred_work_mode", "") or "").strip() or None
        if not work_mode:
            for value in _split_terms(getattr(profile, "work_preferences", None), limit=8):
                lowered = value.lower()
                if lowered in {"remote", "hybrid", "onsite", "on-site", "in-office"}:
                    work_mode = "onsite" if lowered in {"on-site", "in-office"} else lowered
                    break
        return UserPreferenceFilter(
            domains=domains,
            preferred_work_mode=work_mode,
            locations=locations,
            expected_stipend_min=getattr(profile, "expected_stipend_min", None),
            expected_stipend_max=getattr(profile, "expected_stipend_max", None),
            graduation_year=getattr(profile, "graduation_year", None) or getattr(profile, "passout_year", None),
            opportunity_types=_split_terms(getattr(profile, "opportunity_types", None), limit=10),
        )

    def preference_text(self, profile: Profile) -> str:
        filters = self.preference_filter(profile)
        sections = [
            f"[DOMAINS] {', '.join(filters.domains)}",
            f"[DOMAIN] {getattr(profile, 'domain', '') or ''}",
            f"[COURSE] {getattr(profile, 'course', '') or ''} {getattr(profile, 'course_specialization', '') or ''}",
            f"[SKILLS] {getattr(profile, 'skills', '') or ''}",
            f"[INTERESTS] {getattr(profile, 'interests', '') or ''} {', '.join(getattr(profile, 'interest_graph', []) or [])}",
            f"[CAREER_INTENT] {', '.join(getattr(profile, 'career_intent', []) or [])}",
            f"[GOALS] {', '.join(getattr(profile, 'goals', []) or [])}",
            f"[OPPORTUNITY_TYPES] {', '.join(filters.opportunity_types)}",
            f"[PREFERRED_ROLES] {getattr(profile, 'preferred_roles', '') or ''}",
            f"[WORK_MODE] {filters.preferred_work_mode or ''} {', '.join(getattr(profile, 'work_preferences', []) or [])}",
            f"[LOCATIONS] {', '.join(filters.locations)}",
            f"[STIPEND] {getattr(profile, 'expected_stipend_range', '') or ''}",
            f"[BIO] {getattr(profile, 'bio', '') or ''}",
            f"[PROJECTS] {getattr(profile, 'projects', '') or ''}",
        ]
        return " ".join(section for section in sections if section.strip()).strip()

    def quality_score(self, profile: Profile) -> float:
        filters = self.preference_filter(profile)
        weights = {
            "domains": 0.16,
            "skills": 0.18,
            "intent": 0.15,
            "work_mode": 0.10,
            "locations": 0.09,
            "stipend": 0.08,
            "graduation": 0.07,
            "context": 0.17,
        }
        score = 0.0
        if filters.domains:
            score += weights["domains"]
        if _split_terms(getattr(profile, "skills", None), limit=40):
            score += weights["skills"]
        if filters.opportunity_types or getattr(profile, "career_intent", None) or getattr(profile, "goals", None):
            score += weights["intent"]
        if filters.preferred_work_mode or getattr(profile, "work_preferences", None):
            score += weights["work_mode"]
        if filters.locations:
            score += weights["locations"]
        if (
            _text_present(getattr(profile, "expected_stipend_range", None))
            or filters.expected_stipend_min is not None
            or filters.expected_stipend_max is not None
        ):
            score += weights["stipend"]
        if filters.graduation_year is not None:
            score += weights["graduation"]

        context_signals = [
            getattr(profile, "bio", None),
            getattr(profile, "interests", None),
            getattr(profile, "interest_graph", None),
            getattr(profile, "course", None),
            getattr(profile, "course_specialization", None),
            getattr(profile, "projects", None),
            getattr(profile, "education", None),
        ]
        context_count = sum(1 for value in context_signals if bool(_split_terms(value) if isinstance(value, list) else _text_present(value)))
        score += weights["context"] * min(1.0, context_count / 3.0)
        return round(max(0.0, min(1.0, score)), 4)

    def choose_strategy(self, *, quality_score: float, interaction_count: int) -> ColdStartDecision:
        safe_quality = max(0.0, min(1.0, float(quality_score)))
        safe_interactions = max(0, int(interaction_count))
        if safe_interactions >= 10 or safe_quality > 0.7:
            return ColdStartDecision(
                strategy="ml",
                ranking_mode="ml",
                personalization_level="high",
                quality_score=safe_quality,
                interaction_count=safe_interactions,
                persona_cluster_id=None,
            )
        if safe_quality >= 0.3:
            return ColdStartDecision(
                strategy="semantic",
                ranking_mode="semantic",
                personalization_level="medium",
                quality_score=safe_quality,
                interaction_count=safe_interactions,
                persona_cluster_id=None,
            )
        return ColdStartDecision(
            strategy="diversity",
            ranking_mode="diversity",
            personalization_level="low",
            quality_score=safe_quality,
            interaction_count=safe_interactions,
            persona_cluster_id=None,
        )

    def assign_persona_cluster(self, *, embedding: list[float], preference_text: str) -> Optional[int]:
        if not embedding and not preference_text:
            return None
        if embedding:
            rounded = ",".join(f"{value:.4f}" for value in embedding[:64])
            digest = hashlib.sha256(rounded.encode("utf-8")).hexdigest()
        else:
            digest = hashlib.sha256(preference_text.lower().encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % self.persona_cluster_count

    async def interaction_count(self, user_id: PydanticObjectId) -> int:
        try:
            return int(
                await OpportunityInteraction.find_many(
                    {
                        "user_id": user_id,
                        "event_type": {"$ne": "impression"},
                        "traffic_type": "real",
                    }
                ).count()
            )
        except Exception:
            return 0

    async def build(self, profile: Profile, *, force: bool = False) -> ColdStartProfileResult:
        text = self.preference_text(profile)
        quality = self.quality_score(profile)
        model_version = embedding_pipeline.model_version
        embedding = list(getattr(profile, "preference_embedding", []) or [])

        needs_embedding = bool(text) and (
            force
            or not embedding
            or (getattr(profile, "preference_embedding_model_version", None) or "") != model_version
        )
        if needs_embedding:
            embedding = _vector_to_list(await embedding_service.embed_query(text))

        persona_cluster_id = self.assign_persona_cluster(embedding=embedding, preference_text=text)
        return ColdStartProfileResult(
            quality_score=quality,
            preference_text=text,
            preference_filter=self.preference_filter(profile),
            embedding=embedding,
            model_version=model_version if embedding else None,
            persona_cluster_id=persona_cluster_id,
        )

    async def refresh_profile(
        self,
        profile: Profile,
        *,
        interaction_count: Optional[int] = None,
        force: bool = False,
        save: bool = True,
    ) -> tuple[ColdStartProfileResult, ColdStartDecision]:
        result = await self.build(profile, force=force)
        resolved_interaction_count = (
            int(interaction_count)
            if interaction_count is not None
            else await self.interaction_count(profile.user_id)
        )
        decision = self.choose_strategy(
            quality_score=result.quality_score,
            interaction_count=resolved_interaction_count,
        )
        decision = ColdStartDecision(
            strategy=decision.strategy,
            ranking_mode=decision.ranking_mode,
            personalization_level=decision.personalization_level,
            quality_score=decision.quality_score,
            interaction_count=decision.interaction_count,
            persona_cluster_id=result.persona_cluster_id,
        )

        profile.cold_start_quality_score = result.quality_score
        profile.cold_start_strategy = decision.strategy
        profile.preference_embedding = result.embedding
        profile.preference_embedding_model_version = result.model_version
        profile.preference_embedding_updated_at = utc_now() if result.embedding else None
        profile.persona_cluster_id = result.persona_cluster_id
        if save:
            await profile.save()
        return result, decision

    def calibration_weight(self, feedback: str) -> tuple[str, float]:
        normalized = (feedback or "").strip().lower()
        if normalized == "up":
            return "save", 1.0
        if normalized == "down":
            return "dismiss", -0.5
        return "skip", -0.1


cold_start_profile_builder = ColdStartProfileBuilder()
