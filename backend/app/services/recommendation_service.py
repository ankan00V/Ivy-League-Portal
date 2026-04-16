from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from beanie.odm.operators.find.comparison import In

from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.services.experiment_service import experiment_service
from app.services.intelligence import score_opportunity_match
from app.services.personalization.feature_builder import build_ranker_features, skills_overlap_score
from app.services.personalization.learned_ranker import learned_ranker
from app.services.ranking_model_service import ranking_model_service
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

    def _behavior_prefs(
        self, opportunity: Opportunity, behavior_map: dict[str, dict[str, float]]
    ) -> tuple[float, float]:
        domain_map = behavior_map.get("domain", {})
        type_map = behavior_map.get("type", {})

        domain_key = (opportunity.domain or "").lower()
        type_key = (opportunity.opportunity_type or "").lower()

        return float(domain_map.get(domain_key, 0.0)), float(type_map.get(type_key, 0.0))

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
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not opportunities:
            return [], {"mode": "semantic"}

        active_model = await ranking_model_service.get_active()
        weights = active_model.weights

        effective_mode = ranking_mode
        if ranking_mode == "ab":
            decision = await experiment_service.assign(user_id=user_id, experiment_key="ranking_mode")
            if decision:
                effective_mode = decision.variant
                meta = {
                    "mode": effective_mode,
                    "experiment_key": decision.experiment_key,
                    "variant": decision.variant,
                    "bucket": decision.bucket,
                    "assigned_at": decision.assigned_at,
                }
            else:
                effective_mode = "semantic"
                meta = {"mode": effective_mode}
        else:
            meta = {"mode": effective_mode}

        meta["model_version_id"] = active_model.model_version_id
        meta["weights"] = dict(weights)

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
            behavior_domain_pref, behavior_type_pref = self._behavior_prefs(opportunity, behavior_map)
            overlap_score = skills_overlap_score(profile=profile, opportunity=opportunity)

            if effective_mode == "baseline":
                final_score = baseline_score
                reasons = baseline_reasons
            elif effective_mode == "ml":
                features = build_ranker_features(
                    profile=profile,
                    opportunity=opportunity,
                    semantic_score=semantic_score,
                    skills_overlap_score=overlap_score,
                    baseline_score=baseline_score,
                    behavior_score=behavior_score,
                    behavior_domain_pref=behavior_domain_pref,
                    behavior_type_pref=behavior_type_pref,
                )
                ranker_result = learned_ranker.score(features)
                if ranker_result is None:
                    final_score = round(
                        (weights["semantic"] * semantic_score)
                        + (weights["baseline"] * baseline_score)
                        + (weights["behavior"] * behavior_score),
                        3,
                    )
                    reasons = list(baseline_reasons)
                    reasons.append("Learned ranker unavailable; used heuristic blend.")
                    ml_raw_score: float | None = None
                else:
                    # Keep raw score for later per-request normalization to 0-100.
                    ml_raw_score = float(ranker_result.score)
                    final_score = ml_raw_score
                    reasons = list(baseline_reasons)
                    reasons.append(f"Learned ranker: {ranker_result.model}")
                    if semantic_score > 0:
                        reasons.append(f"Semantic similarity: {semantic_score:.1f}")
                    if overlap_score > 0:
                        reasons.append(f"Skills overlap: {overlap_score:.2f}")
            else:
                # Personalization = content similarity + profile compatibility + behavior weighting.
                final_score = round(
                    (weights["semantic"] * semantic_score)
                    + (weights["baseline"] * baseline_score)
                    + (weights["behavior"] * behavior_score),
                    3,
                )
                reasons = list(baseline_reasons)
                if semantic_score > 0:
                    reasons.append(f"Semantic match score: {semantic_score:.1f}")
                if behavior_score > 0:
                    reasons.append(f"Behavioral preference boost: {behavior_score:.1f}")

            # For ML scoring, normalize after collecting all raw scores.
            if effective_mode != "ml" and final_score < min_score:
                continue

            ranked.append(
                {
                    "opportunity": opportunity,
                    "match_score": round(final_score, 3),
                    "match_reasons": reasons,
                    "baseline_score": round(baseline_score, 3),
                    "semantic_score": round(semantic_score, 3),
                    "behavior_score": round(behavior_score, 3),
                    "skills_overlap_score": round(float(overlap_score), 6),
                    "behavior_domain_pref": round(float(behavior_domain_pref), 6),
                    "behavior_type_pref": round(float(behavior_type_pref), 6),
                    "ranking_mode": effective_mode,
                    "model_version_id": active_model.model_version_id,
                    "weights": dict(weights),
                    "ml_raw_score": ml_raw_score if effective_mode == "ml" else None,
                }
            )

        if effective_mode == "ml" and ranked:
            raw_scores = [float(item.get("ml_raw_score")) for item in ranked if item.get("ml_raw_score") is not None]
            if raw_scores:
                lo = min(raw_scores)
                hi = max(raw_scores)
                denom = (hi - lo) if (hi - lo) > 1e-9 else None
                for item in ranked:
                    raw = item.get("ml_raw_score")
                    if raw is None:
                        continue
                    scaled = 50.0 if denom is None else ((float(raw) - lo) / denom) * 100.0
                    item["match_score"] = round(float(scaled), 3)

            ranked = [item for item in ranked if float(item.get("match_score") or 0.0) >= float(min_score)]

        ranked.sort(
            key=lambda item: (
                item["match_score"],
                *_activity_sort_key(item["opportunity"]),
            ),
            reverse=True,
        )

        return ranked[: max(1, min(limit, 50))], meta


recommendation_service = RecommendationService()
