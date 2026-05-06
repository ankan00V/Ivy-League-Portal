from __future__ import annotations

import asyncio
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from beanie.odm.operators.find.comparison import In

from app.core.config import settings
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.services.experiment_service import experiment_service
from app.services.intelligence import score_opportunity_match
from app.services.mlops.learned_ranker_rollout_service import learned_ranker_rollout_service
from app.services.personalization.feature_builder import build_ranker_features, skills_overlap_score
from app.services.personalization.learned_ranker import learned_ranker
from app.services.ranking_model_service import ranking_model_service
from app.services.vector_service import opportunity_vector_service
from app.core.time import as_utc_aware, utc_now


def _activity_sort_key(opportunity: Opportunity) -> tuple[datetime, datetime]:
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    latest_touch = as_utc_aware(opportunity.last_seen_at or opportunity.updated_at or opportunity.created_at)
    created_at = as_utc_aware(opportunity.created_at) or latest_touch or minimum
    return latest_touch or minimum, created_at


def _profile_query(profile: Profile) -> str:
    values = [
        getattr(profile, "bio", "") or "",
        getattr(profile, "skills", "") or "",
        getattr(profile, "interests", "") or "",
        getattr(profile, "education", "") or "",
        getattr(profile, "achievements", "") or "",
        getattr(profile, "domain", "") or "",
        getattr(profile, "course", "") or "",
        getattr(profile, "course_specialization", "") or "",
        getattr(profile, "current_job_role", "") or "",
        getattr(profile, "experience_summary", "") or "",
        getattr(profile, "preferred_roles", "") or "",
        getattr(profile, "preferred_locations", "") or "",
        getattr(profile, "user_type", "") or "",
    ]
    values.extend(getattr(profile, "goals", []) or [])
    return " ".join(value for value in values if value).strip()


class RecommendationService:
    def _diversify_ranked(self, items: list[dict[str, Any]], *, per_source_cap: int = 2) -> list[dict[str, Any]]:
        capped = max(1, per_source_cap)
        source_counts: dict[str, int] = {}
        primary: list[dict[str, Any]] = []
        overflow: list[dict[str, Any]] = []

        for item in items:
            opportunity = item.get("opportunity")
            raw_source = str(getattr(opportunity, "source", "") or "").strip().lower() or "unknown"
            count = source_counts.get(raw_source, 0)
            if count < capped:
                primary.append(item)
                source_counts[raw_source] = count + 1
            else:
                overflow.append(item)

        return primary + overflow

    def _quantile(self, values: list[float], q: float) -> float:
        if not values:
            return 0.0
        sorted_values = sorted(float(value) for value in values)
        if len(sorted_values) == 1:
            return float(sorted_values[0])

        p = max(0.0, min(1.0, float(q)))
        idx = p * float(len(sorted_values) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(sorted_values) - 1)
        if lo == hi:
            return float(sorted_values[lo])
        frac = idx - float(lo)
        return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)

    async def _learn_user_filter_threshold(
        self,
        *,
        user_id,
        ranking_mode: str,
        lookback_days: int = 120,
        label_window_hours: int = 72,
        min_impressions: int = 30,
        min_positive: int = 4,
    ) -> dict[str, Any] | None:
        """
        Learn a user-specific shortlist cutoff from historical interactions.

        Training signal:
        - impression(match_score) is a candidate sample
        - positive label if click/save/apply occurred for same opportunity within label window
        """
        since = utc_now() - timedelta(days=max(7, min(int(lookback_days), 365)))
        label_window = timedelta(hours=max(1, min(int(label_window_hours), 168)))
        target_modes = {str(ranking_mode or "").strip().lower(), "ab"}

        try:
            interactions = await OpportunityInteraction.find_many(
                OpportunityInteraction.user_id == user_id,
                OpportunityInteraction.created_at >= since,
            ).sort("-created_at").limit(5000).to_list()
        except Exception:
            return None

        if not interactions:
            return None

        positive_map: dict[str, list[datetime]] = {}
        for item in interactions:
            if (getattr(item, "traffic_type", "real") or "real").strip().lower() not in {"", "real"}:
                continue
            mode = (getattr(item, "ranking_mode", "") or "").strip().lower()
            if mode and mode not in target_modes:
                continue
            action = (getattr(item, "interaction_type", "") or "").strip().lower()
            if action not in {"click", "save", "apply"}:
                continue
            key = str(item.opportunity_id)
            created_at = as_utc_aware(item.created_at)
            if created_at is None:
                continue
            positive_map.setdefault(key, []).append(created_at)

        for times in positive_map.values():
            times.sort()

        positives: list[float] = []
        negatives: list[float] = []
        for item in interactions:
            if (getattr(item, "traffic_type", "real") or "real").strip().lower() not in {"", "real"}:
                continue
            mode = (getattr(item, "ranking_mode", "") or "").strip().lower()
            if mode and mode not in target_modes:
                continue
            if (getattr(item, "interaction_type", "") or "").strip().lower() != "impression":
                continue
            score = getattr(item, "match_score", None)
            if score is None:
                continue

            created_at = as_utc_aware(item.created_at)
            if created_at is None:
                continue

            key = str(item.opportunity_id)
            times = positive_map.get(key, [])
            label = 0
            if times:
                left = bisect_left(times, created_at)
                if left < len(times) and times[left] <= (created_at + label_window):
                    label = 1

            if label == 1:
                positives.append(float(score))
            else:
                negatives.append(float(score))

        impression_count = len(positives) + len(negatives)
        if impression_count < int(min_impressions) or len(positives) < int(min_positive):
            return None

        positive_q25 = self._quantile(positives, 0.25)
        positive_q40 = self._quantile(positives, 0.40)
        negative_q80 = self._quantile(negatives, 0.80) if negatives else positive_q25
        threshold = max(10.0, min(95.0, max(positive_q25, negative_q80 * 0.85)))
        threshold = round((threshold + positive_q40) / 2.0, 3)

        return {
            "enabled": True,
            "threshold": float(max(10.0, min(95.0, threshold))),
            "trained_on_impressions": int(impression_count),
            "positives": int(len(positives)),
            "negatives": int(len(negatives)),
            "lookback_days": int(lookback_days),
            "label_window_hours": int(label_window_hours),
        }

    async def _build_behavior_map(self, user_id) -> dict[str, dict[str, float]]:
        since = utc_now() - timedelta(days=120)
        interactions = await OpportunityInteraction.find_many(
            OpportunityInteraction.user_id == user_id,
            OpportunityInteraction.created_at >= since,
        ).to_list()
        if not interactions:
            return {
                "domain": {},
                "type": {},
                "stats": {
                    "recent_interactions_7d": 0.0,
                    "recent_interactions_30d": 0.0,
                    "recent_applies_30d": 0.0,
                    "recent_clicks_30d": 0.0,
                    "recent_impressions_30d": 0.0,
                    "sequence_ctr_30d": 0.0,
                    "last_interaction_hours": 9999.0,
                },
            }

        now = utc_now()
        window_7d = now - timedelta(days=7)
        window_30d = now - timedelta(days=30)
        recent_interactions_7d = 0
        recent_interactions_30d = 0
        recent_applies_30d = 0
        recent_clicks_30d = 0
        recent_impressions_30d = 0
        last_interaction_at: datetime | None = None

        opp_ids = list({item.opportunity_id for item in interactions})
        opportunities = await Opportunity.find_many(In(Opportunity.id, opp_ids)).to_list()
        opportunity_map = {str(opportunity.id): opportunity for opportunity in opportunities}

        action_weights = {
            "impression": 0.2,
            "view": 0.5,
            "click": 1.0,
            "save": 1.2,
            "apply": 1.8,
        }

        domain_score: dict[str, float] = defaultdict(float)
        type_score: dict[str, float] = defaultdict(float)

        for interaction in interactions:
            created_at = as_utc_aware(interaction.created_at)
            if created_at is None:
                continue
            if created_at >= window_7d:
                recent_interactions_7d += 1
            if created_at >= window_30d:
                recent_interactions_30d += 1
                action = (interaction.interaction_type or "").strip().lower()
                if action == "apply":
                    recent_applies_30d += 1
                elif action == "click":
                    recent_clicks_30d += 1
                elif action == "impression":
                    recent_impressions_30d += 1
            if last_interaction_at is None or created_at > last_interaction_at:
                last_interaction_at = created_at

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
            "stats": {
                "recent_interactions_7d": float(recent_interactions_7d),
                "recent_interactions_30d": float(recent_interactions_30d),
                "recent_applies_30d": float(recent_applies_30d),
                "recent_clicks_30d": float(recent_clicks_30d),
                "recent_impressions_30d": float(recent_impressions_30d),
                "sequence_ctr_30d": float(recent_clicks_30d / max(1, recent_impressions_30d)),
                "last_interaction_hours": float(
                    max(0.0, (now - last_interaction_at).total_seconds() / 3600.0)
                )
                if last_interaction_at is not None
                else 9999.0,
            },
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
        ranking_mode: str = "ml",
        query: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not opportunities:
            return [], {"mode": ranking_mode}

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

        rollout_decision = learned_ranker_rollout_service.resolve(
            requested_mode=effective_mode,
            user_id=str(user_id),
        )
        serving_mode = rollout_decision.primary_mode
        shadow_enabled = learned_ranker_rollout_service.should_shadow(
            decision=rollout_decision,
            user_id=str(user_id),
        )
        shadow_candidate_limit = (
            max(0, int(settings.LEARNED_RANKER_SHADOW_MAX_CANDIDATES))
            if shadow_enabled
            else 0
        )

        meta["requested_mode"] = effective_mode
        meta["mode"] = serving_mode
        meta["model_version_id"] = active_model.model_version_id
        meta["weights"] = dict(weights)
        meta["rollout"] = {
            "key": rollout_decision.rollout_key,
            "variant": rollout_decision.rollout_variant,
            "bucket": rollout_decision.rollout_bucket,
            "percent": rollout_decision.rollout_percent,
            "in_cohort": rollout_decision.in_cohort,
            "baseline_mode": rollout_decision.baseline_mode,
        }
        meta["shadow"] = {
            "enabled": shadow_enabled,
            "mode": "ml" if shadow_enabled else None,
            "model_version_id": active_model.model_version_id if shadow_enabled else None,
            "candidate_limit": shadow_candidate_limit,
            "candidate_count": 0,
        }
        if serving_mode == "ml" or shadow_enabled:
            importance = learned_ranker.feature_importance(top_k=8)
            meta["feature_importance_top"] = [
                {"feature": item.feature, "importance": item.importance}
                for item in importance
            ]
        else:
            meta["feature_importance_top"] = []

        behavior_map = await self._build_behavior_map(user_id)
        behavior_stats = dict(behavior_map.get("stats") or {})
        semantic_scores: dict[str, float] = {}

        semantic_query = (query or "").strip() or _profile_query(profile)
        if semantic_query:
            semantic_timeout = max(0.25, min(float(settings.RECOMMENDATION_SEMANTIC_TIMEOUT_SECONDS), 15.0))
            try:
                semantic_results = await asyncio.wait_for(
                    opportunity_vector_service.search(
                        semantic_query,
                        top_k=min(max(150, limit * 10), 500),
                    ),
                    timeout=semantic_timeout,
                )
            except Exception as exc:
                semantic_results = []
                meta["semantic_fallback_reason"] = exc.__class__.__name__
            semantic_scores = {
                result["id"]: max(0.0, float(result.get("similarity") or 0.0)) * 100.0
                for result in semantic_results
            }

        candidates: list[dict[str, Any]] = []
        ml_request_failed = False
        shadow_request_failed = False
        shadow_candidate_count = 0
        top_features = [item["feature"] for item in list(meta.get("feature_importance_top") or [])[:3]]
        feature_reason = f"Top model features: {', '.join(top_features)}." if top_features else None
        for opportunity in opportunities:
            baseline_score, baseline_reasons = score_opportunity_match(profile, opportunity)
            semantic_score = round(float(semantic_scores.get(str(opportunity.id), 0.0)), 3)
            behavior_score = self._behavior_score(opportunity, behavior_map)
            behavior_domain_pref, behavior_type_pref = self._behavior_prefs(opportunity, behavior_map)
            overlap_score = skills_overlap_score(profile=profile, opportunity=opportunity)
            heuristic_blend_score = round(
                (weights["semantic"] * semantic_score)
                + (weights["baseline"] * baseline_score)
                + (weights["behavior"] * behavior_score),
                3,
            )
            features = build_ranker_features(
                profile=profile,
                opportunity=opportunity,
                semantic_score=semantic_score,
                skills_overlap_score=overlap_score,
                baseline_score=baseline_score,
                behavior_score=behavior_score,
                behavior_domain_pref=behavior_domain_pref,
                behavior_type_pref=behavior_type_pref,
                user_recent_interactions_7d=float(behavior_stats.get("recent_interactions_7d") or 0.0),
                user_recent_interactions_30d=float(behavior_stats.get("recent_interactions_30d") or 0.0),
                user_recent_applies_30d=float(behavior_stats.get("recent_applies_30d") or 0.0),
                user_recent_clicks_30d=float(behavior_stats.get("recent_clicks_30d") or 0.0),
                user_recent_impressions_30d=float(behavior_stats.get("recent_impressions_30d") or 0.0),
                user_last_interaction_hours=float(behavior_stats.get("last_interaction_hours") or 9999.0),
                sequence_ctr_30d=float(behavior_stats.get("sequence_ctr_30d") or 0.0),
            )

            reasons = list(baseline_reasons)
            ml_raw_score: float | None = None

            if serving_mode == "ml":
                ranker_result = learned_ranker.score(features)
                if ranker_result is None:
                    ml_request_failed = True
                else:
                    ml_raw_score = float(ranker_result.score)
                    reasons.append(f"Learned ranker: {ranker_result.model}")
                    if semantic_score > 0:
                        reasons.append(f"Semantic similarity: {semantic_score:.1f}")
                    if overlap_score > 0:
                        reasons.append(f"Skills overlap: {overlap_score:.2f}")
            if serving_mode == "semantic":
                if semantic_score > 0:
                    reasons.append(f"Semantic match score: {semantic_score:.1f}")
                if behavior_score > 0:
                    reasons.append(f"Behavioral preference boost: {behavior_score:.1f}")

            candidates.append(
                {
                    "opportunity": opportunity,
                    "baseline_score": round(baseline_score, 3),
                    "semantic_score": round(semantic_score, 3),
                    "behavior_score": round(behavior_score, 3),
                    "skills_overlap_score": round(float(overlap_score), 6),
                    "behavior_domain_pref": round(float(behavior_domain_pref), 6),
                    "behavior_type_pref": round(float(behavior_type_pref), 6),
                    "heuristic_blend_score": heuristic_blend_score,
                    "ml_raw_score": ml_raw_score,
                    "shadow_ml_raw_score": None,
                    "geo_match_score": float(features.values.get("geo_match_score") or 0.0),
                    "source_trust": float(features.values.get("source_trust") or 0.0),
                    "sequence_ctr_30d": float(features.values.get("sequence_ctr_30d") or 0.0),
                    "user_recent_interactions_30d": float(
                        features.values.get("user_recent_interactions_30d") or 0.0
                    ),
                    "ranker_features": dict(features.values),
                    "match_reasons": reasons,
                }
            )

        if shadow_enabled and shadow_candidate_limit > 0:
            shadow_candidates = sorted(
                candidates,
                key=lambda item: (
                    float(item.get("heuristic_blend_score") or 0.0),
                    *_activity_sort_key(item["opportunity"]),
                ),
                reverse=True,
            )[:shadow_candidate_limit]
            for candidate in shadow_candidates:
                ranker_result = learned_ranker.score(candidate["ranker_features"])
                if ranker_result is None:
                    shadow_request_failed = True
                    continue
                candidate["shadow_ml_raw_score"] = float(ranker_result.score)
                shadow_candidate_count += 1

        meta["shadow"]["candidate_count"] = shadow_candidate_count
        if shadow_enabled and shadow_request_failed:
            meta["shadow"]["fallback_reason"] = "ml_model_failure"

        if serving_mode == "ml" and ml_request_failed:
            meta["mode"] = "semantic"
            meta["fallback_reason"] = "ml_model_failure"

        ranked: list[dict[str, Any]] = []
        for candidate in candidates:
            opportunity = candidate["opportunity"]
            reasons = list(candidate.get("match_reasons") or [])

            if serving_mode == "baseline":
                final_score = float(candidate["baseline_score"])
                final_mode = "baseline"
            elif serving_mode == "ml" and not ml_request_failed:
                final_score = float(candidate.get("ml_raw_score") or 0.0)
                final_mode = "ml"
                if feature_reason:
                    reasons.append(feature_reason)
            else:
                final_score = float(candidate["heuristic_blend_score"])
                final_mode = "semantic"
                if serving_mode == "ml" and ml_request_failed:
                    reasons.append("ML ranker failed for this request; used heuristic blend fallback.")
                elif rollout_decision.requested_mode == "ml" and rollout_decision.primary_mode != "ml":
                    if shadow_enabled and candidate.get("shadow_ml_raw_score") is not None:
                        reasons.append("Staged rollout control cohort served heuristic ranking; learned ranker scored in shadow.")
                    else:
                        reasons.append("Staged rollout control cohort served heuristic ranking.")

            if final_mode != "ml" and final_score < min_score:
                continue

            ranked.append(
                {
                    "opportunity": opportunity,
                    "match_score": round(final_score, 3),
                    "match_reasons": reasons,
                    "baseline_score": candidate["baseline_score"],
                    "semantic_score": candidate["semantic_score"],
                    "behavior_score": candidate["behavior_score"],
                    "skills_overlap_score": candidate["skills_overlap_score"],
                    "behavior_domain_pref": candidate["behavior_domain_pref"],
                    "behavior_type_pref": candidate["behavior_type_pref"],
                    "geo_match_score": candidate["geo_match_score"],
                    "source_trust": candidate["source_trust"],
                    "sequence_ctr_30d": candidate["sequence_ctr_30d"],
                    "user_recent_interactions_30d": candidate["user_recent_interactions_30d"],
                    "ranker_features": candidate["ranker_features"],
                    "ranking_mode": final_mode,
                    "model_version_id": active_model.model_version_id,
                    "weights": dict(weights),
                    "ml_raw_score": candidate.get("ml_raw_score") if final_mode == "ml" else None,
                    "feature_importance_top": list(meta.get("feature_importance_top") or []),
                }
            )

        if serving_mode == "ml" and not ml_request_failed and ranked:
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

        adaptive_filter = await self._learn_user_filter_threshold(
            user_id=user_id,
            ranking_mode=str(meta.get("mode") or serving_mode or "semantic"),
        )
        if adaptive_filter and str(meta.get("mode") or serving_mode) in {"semantic", "ml"}:
            adaptive_min_score = max(float(min_score), float(adaptive_filter["threshold"]))
            filtered = [item for item in ranked if float(item.get("match_score") or 0.0) >= adaptive_min_score]
            if filtered:
                ranked = filtered
            meta["adaptive_filter"] = {
                **adaptive_filter,
                "applied": bool(filtered),
                "effective_min_score": float(round(adaptive_min_score, 3)),
            }
        else:
            meta["adaptive_filter"] = {"enabled": False}

        ranked.sort(
            key=lambda item: (
                item["match_score"],
                *_activity_sort_key(item["opportunity"]),
            ),
            reverse=True,
        )
        ranked = self._diversify_ranked(ranked, per_source_cap=2)

        return ranked[: max(1, min(limit, 50))], meta


recommendation_service = RecommendationService()
