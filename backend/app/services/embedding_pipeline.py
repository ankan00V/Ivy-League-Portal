from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import math
from typing import Any, Iterable, Optional

import numpy as np
from beanie import PydanticObjectId

from app.core.config import settings
from app.core.time import as_utc_aware, utc_now
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.models.user import User
from app.services.embedding_service import embedding_service


@dataclass
class EmbeddingBatchReport:
    status: str
    model_version: str
    processed: int
    updated: int
    skipped: int

    def model_dump(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model_version": self.model_version,
            "processed": self.processed,
            "updated": self.updated,
            "skipped": self.skipped,
        }


def _hash_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _vector_to_list(vector: np.ndarray) -> list[float]:
    return [float(item) for item in np.asarray(vector, dtype=np.float32).tolist()]


def _normalize_vector(vector: np.ndarray) -> np.ndarray:
    values = np.asarray(vector, dtype=np.float32)
    if values.ndim != 1:
        values = values.reshape(-1)
    norm = float(np.linalg.norm(values))
    if norm <= 1e-12:
        return values
    return values / norm


def _split_terms(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


class EmbeddingPipeline:
    @property
    def model_version(self) -> str:
        return (settings.EMBEDDING_MODEL_VERSION or settings.EMBEDDING_MODEL).strip()

    def opportunity_text(self, opportunity: Opportunity | dict[str, Any]) -> str:
        def field(name: str, default: Any = "") -> Any:
            if isinstance(opportunity, dict):
                return opportunity.get(name, default)
            return getattr(opportunity, name, default)

        tags = _split_terms(field("tags"))
        company = field("university") or field("normalized_organization") or ""
        description = str(field("description") or "")[:300]
        parts = [
            f"[TITLE] {field('title') or ''}",
            f"[COMPANY] {company}",
            f"[TYPE] {field('opportunity_type') or ''}",
            f"[LOCATION] {field('location') or ''}",
            f"[WORK_MODE] {field('work_mode') or ''}",
            f"[SKILLS] {', '.join(tags)}",
            f"[DESC] {description}",
        ]
        return " ".join(part for part in parts if part.strip()).strip()

    def needs_opportunity_embedding(self, opportunity: Opportunity) -> bool:
        if not getattr(opportunity, "embedding", None):
            return True
        if (opportunity.embedding_model_version or "") != self.model_version:
            return True
        return (opportunity.embedding_text_hash or "") != _hash_text(self.opportunity_text(opportunity))

    async def embed_opportunities(
        self,
        *,
        limit: Optional[int] = None,
        force: bool = False,
    ) -> EmbeddingBatchReport:
        rows = await Opportunity.find_many().sort("-updated_at").limit(max(1, int(limit or 10_000))).to_list()
        candidates = [row for row in rows if force or self.needs_opportunity_embedding(row)]
        if not candidates:
            return EmbeddingBatchReport(
                status="skipped",
                model_version=self.model_version,
                processed=len(rows),
                updated=0,
                skipped=len(rows),
            )

        batch_size = max(1, min(int(settings.EMBEDDING_BATCH_SIZE), 512))
        updated = 0
        now = utc_now()
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            texts = [self.opportunity_text(row) for row in batch]
            vectors = await embedding_service.embed_texts(texts)
            for row, text, vector in zip(batch, texts, vectors):
                row.embedding = _vector_to_list(_normalize_vector(vector))
                row.embedding_text_hash = _hash_text(text)
                row.embedding_model_version = self.model_version
                row.embedding_updated_at = now
                row.updated_at = now
                await row.save()
                updated += 1

        return EmbeddingBatchReport(
            status="updated",
            model_version=self.model_version,
            processed=len(rows),
            updated=updated,
            skipped=max(0, len(rows) - updated),
        )

    async def user_profile_text(self, user_id: PydanticObjectId) -> str:
        profile = await Profile.find_one(Profile.user_id == user_id)
        fragments: list[str] = []
        if profile is not None:
            fragments.extend(
                [
                    f"[DOMAIN] {profile.domain or ''}",
                    f"[DOMAINS_OF_INTEREST] {', '.join(profile.domains_of_interest or [])}",
                    f"[COURSE] {profile.course or ''} {profile.course_specialization or ''}",
                    f"[ROLES] {profile.preferred_roles or ''}",
                    f"[LOCATIONS] {profile.preferred_locations or ''}",
                    f"[WORK] {profile.preferred_work_mode or ''} {', '.join(profile.work_preferences or [])}",
                    f"[OPPORTUNITY_TYPES] {', '.join(profile.opportunity_types or [])}",
                    f"[SKILLS] {profile.skills or ''}",
                    f"[INTERESTS] {profile.interests or ''} {', '.join(profile.interest_graph or [])}",
                    f"[GOALS] {', '.join(profile.goals or [])} {', '.join(profile.career_intent or [])}",
                ]
            )

        recent = (
            await OpportunityInteraction.find_many(OpportunityInteraction.user_id == user_id)
            .sort("-created_at")
            .limit(100)
            .to_list()
        )
        opportunity_ids = list({item.opportunity_id for item in recent if float(item.reward or 0.0) > 0.0})
        if opportunity_ids:
            opportunities = await Opportunity.find_many({"_id": {"$in": opportunity_ids}}).to_list()
            opportunity_by_id = {str(item.id): item for item in opportunities}
            half_life = max(1, int(settings.USER_EMBEDDING_HALF_LIFE_DAYS))
            weighted_titles: list[str] = []
            now = utc_now()
            for event in recent:
                opportunity = opportunity_by_id.get(str(event.opportunity_id))
                if opportunity is None:
                    continue
                created_at = as_utc_aware(event.created_at) or now
                age_days = max(0.0, (now - created_at).total_seconds() / 86_400.0)
                recency_weight = math.exp(-math.log(2.0) * age_days / half_life)
                reward_weight = max(0.0, float(event.reward or 0.0))
                repeats = max(1, min(5, int(round((recency_weight * reward_weight) * 5))))
                weighted_titles.extend([self.opportunity_text(opportunity)] * repeats)
            if weighted_titles:
                fragments.append("[RECENT_INTERACTIONS] " + " ".join(weighted_titles[:40]))

        return " ".join(fragment for fragment in fragments if fragment.strip()).strip()

    async def recompute_user_embedding(
        self,
        *,
        user_id: PydanticObjectId,
        force: bool = False,
    ) -> dict[str, Any]:
        user = await User.get(user_id)
        if user is None:
            return {"status": "not_found", "user_id": str(user_id)}

        interaction_count = await OpportunityInteraction.find_many(
            OpportunityInteraction.user_id == user_id,
        ).count()
        if (
            not force
            and user.profile_embedding
            and user.profile_embedding_model_version == self.model_version
            and interaction_count - int(user.profile_embedding_interaction_count or 0)
            < int(settings.USER_EMBEDDING_INTERACTION_THRESHOLD)
        ):
            return {"status": "skipped", "user_id": str(user_id), "interaction_count": interaction_count}

        text = await self.user_profile_text(user_id)
        if not text:
            return {"status": "skipped", "user_id": str(user_id), "reason": "empty_profile_text"}

        vector = await embedding_service.embed_text(text)
        user.profile_embedding = _vector_to_list(_normalize_vector(vector))
        user.profile_embedding_model_version = self.model_version
        user.profile_embedding_updated_at = utc_now()
        user.profile_embedding_interaction_count = int(interaction_count)
        await user.save()
        return {
            "status": "updated",
            "user_id": str(user_id),
            "interaction_count": interaction_count,
            "dimension": len(user.profile_embedding),
        }

    async def rebuild_vector_index_if_stale(self, *, force: bool = False) -> dict[str, Any]:
        from app.services.vector_service import opportunity_vector_service

        embedding_report = await self.embed_opportunities(force=force)
        await opportunity_vector_service.rebuild(force=bool(force or embedding_report.updated > 0))
        return {
            "status": "rebuilt",
            "force": bool(force),
            "embedding_report": embedding_report.model_dump(),
            "provider": opportunity_vector_service.provider_name(),
            "model_version": self.model_version,
        }


embedding_pipeline = EmbeddingPipeline()
