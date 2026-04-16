from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from hashlib import md5
from typing import Any, Optional

from beanie.odm.operators.find.comparison import In

from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.services.intelligence import score_opportunity_match
from app.services.vector_service import opportunity_vector_service


def _activity_sort_key(opportunity: Opportunity) -> tuple[datetime, datetime]:
    latest_touch = opportunity.last_seen_at or opportunity.updated_at or opportunity.created_at
    created_at = opportunity.created_at or latest_touch or datetime.min
    return latest_touch or datetime.min, created_at


def _profile_query(profile: Profile) -> str:
    values = [
        profile.bio or "",
        profile.skills or "",
        profile.interests or "",
        profile.education or "",
        profile.achievements or "",
    ]
    return " ".join(value for value in values if value).strip()


def _stable_mode(user_id: str) -> str:
    bucket = int(md5(user_id.encode("utf-8")).hexdigest(), 16) % 2
    return "baseline" if bucket == 0 else "semantic"


class RecommendationService:
    async def _build_behavior_map(self, user_id) -> dict[str, dict[str, float]]:
        since = datetime.utcnow() - timedelta(days=120)
        interactions = await OpportunityInteraction.find_many(
            OpportunityInteraction.user_id == user_id,
            OpportunityInteraction.created_at >= since,
        ).to_list()
        if not interactions:
            return {"domain": {}, "type": {}}

        opp_ids = list({item.opportunity_id for item in interactions})
        opportunities = await Opportunity.find_many(In(Opportunity.id, opp_ids)).to_list()
        opportunity_map = {str(opportunity.id): opportunity for opportunity in opportunities}

        action_weights = {
            "impression": 0.2,
            "view": 0.5,
            "click": 1.0,
            "apply": 1.8,
        }

        domain_score: dict[str, float] = defaultdict(float)
        type_score: dict[str, float] = defaultdict(float)

        for interaction in interactions:
            opportunity = opportunity_map.get(str(interaction.opportunity_id))
            if not opportunity:
                continue
            weight = action_weights.get(interaction.interaction_type, 0.5)
            if opportunity.domain:
                domain_score[opportunity.domain.lower()] += weight
            if opportunity.opportunity_type:
                type_score[opportunity.opportunity_type.lower()] += weight

        def _normalize(values: dict[str, float]) -> dict[str, float]:
            if not values:
                return {}
            maximum = max(values.values())
            if maximum <= 0:
                return {}
            return {key: round((score / maximum) * 100.0, 3) for key, score in values.items()}

        return {
            "domain": _normalize(domain_score),
            "type": _normalize(type_score),
        }

    def _behavior_score(self, opportunity: Opportunity, behavior_map: dict[str, dict[str, float]]) -> float:
        domain_map = behavior_map.get("domain", {})
        type_map = behavior_map.get("type", {})

        domain_key = (opportunity.domain or "").lower()
        type_key = (opportunity.opportunity_type or "").lower()

        domain_score = domain_map.get(domain_key, 0.0)
        type_score = type_map.get(type_key, 0.0)

        return round((0.65 * domain_score) + (0.35 * type_score), 3)

    async def rank(
        self,
        *,
        user_id,
        profile: Profile,
        opportunities: list[Opportunity],
        limit: int,
        min_score: float = 0.0,
        ranking_mode: str = "semantic",
        query: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], str]:
        if not opportunities:
            return [], "semantic"

        effective_mode = ranking_mode
        if ranking_mode == "ab":
            effective_mode = _stable_mode(str(user_id))

        behavior_map = await self._build_behavior_map(user_id)
        semantic_scores: dict[str, float] = {}

        semantic_query = (query or "").strip() or _profile_query(profile)
        if semantic_query:
            semantic_results = await opportunity_vector_service.search(
                semantic_query,
                top_k=min(max(150, limit * 10), 500),
            )
            semantic_scores = {
                result["id"]: max(0.0, float(result.get("similarity") or 0.0)) * 100.0
                for result in semantic_results
            }

        ranked: list[dict[str, Any]] = []
        for opportunity in opportunities:
            baseline_score, baseline_reasons = score_opportunity_match(profile, opportunity)
            semantic_score = round(float(semantic_scores.get(str(opportunity.id), 0.0)), 3)
            behavior_score = self._behavior_score(opportunity, behavior_map)

            if effective_mode == "baseline":
                final_score = baseline_score
                reasons = baseline_reasons
            else:
                # Personalization = content similarity + profile compatibility + behavior weighting.
                final_score = round(
                    (0.55 * semantic_score) + (0.30 * baseline_score) + (0.15 * behavior_score),
                    3,
                )
                reasons = list(baseline_reasons)
                if semantic_score > 0:
                    reasons.append(f"Semantic match score: {semantic_score:.1f}")
                if behavior_score > 0:
                    reasons.append(f"Behavioral preference boost: {behavior_score:.1f}")

            if final_score < min_score:
                continue

            ranked.append(
                {
                    "opportunity": opportunity,
                    "match_score": round(final_score, 3),
                    "match_reasons": reasons,
                    "baseline_score": round(baseline_score, 3),
                    "semantic_score": round(semantic_score, 3),
                    "behavior_score": round(behavior_score, 3),
                    "ranking_mode": effective_mode,
                }
            )

        ranked.sort(
            key=lambda item: (
                item["match_score"],
                *_activity_sort_key(item["opportunity"]),
            ),
            reverse=True,
        )

        return ranked[: max(1, min(limit, 50))], effective_mode


recommendation_service = RecommendationService()
