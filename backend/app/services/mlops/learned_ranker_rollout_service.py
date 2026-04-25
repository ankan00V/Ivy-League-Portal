from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.core.config import settings


def _stable_bucket(*, key: str, user_id: str) -> int:
    digest = sha256(f"{key}:{user_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) % 10_000


@dataclass(frozen=True)
class LearnedRankerRolloutDecision:
    requested_mode: str
    primary_mode: str
    baseline_mode: str
    rollout_key: str
    rollout_variant: str
    rollout_bucket: int | None
    rollout_percent: int
    in_cohort: bool


class LearnedRankerRolloutService:
    def resolve(self, *, requested_mode: str, user_id: str) -> LearnedRankerRolloutDecision:
        normalized_requested = str(requested_mode or "semantic").strip().lower() or "semantic"
        baseline_mode = str(settings.LEARNED_RANKER_STAGED_BASELINE_MODE or "semantic").strip().lower() or "semantic"
        rollout_key = str(settings.LEARNED_RANKER_ROLLOUT_EXPERIMENT_KEY or "learned_ranker_rollout").strip().lower()
        rollout_percent = max(0, min(int(settings.LEARNED_RANKER_STAGED_ROLLOUT_PERCENT), 100))

        if normalized_requested != "ml":
            return LearnedRankerRolloutDecision(
                requested_mode=normalized_requested,
                primary_mode=normalized_requested,
                baseline_mode=baseline_mode,
                rollout_key=rollout_key,
                rollout_variant=normalized_requested,
                rollout_bucket=None,
                rollout_percent=rollout_percent,
                in_cohort=False,
            )

        if not settings.LEARNED_RANKER_STAGED_ROLLOUT_ENABLED:
            return LearnedRankerRolloutDecision(
                requested_mode=normalized_requested,
                primary_mode="ml",
                baseline_mode=baseline_mode,
                rollout_key=rollout_key,
                rollout_variant="ml",
                rollout_bucket=None,
                rollout_percent=rollout_percent,
                in_cohort=True,
            )

        bucket = _stable_bucket(key=rollout_key, user_id=user_id)
        in_cohort = bucket < (rollout_percent * 100)
        primary_mode = "ml" if in_cohort else baseline_mode
        rollout_variant = "ml" if in_cohort else baseline_mode
        return LearnedRankerRolloutDecision(
            requested_mode=normalized_requested,
            primary_mode=primary_mode,
            baseline_mode=baseline_mode,
            rollout_key=rollout_key,
            rollout_variant=rollout_variant,
            rollout_bucket=bucket,
            rollout_percent=rollout_percent,
            in_cohort=in_cohort,
        )

    def should_shadow(self, *, decision: LearnedRankerRolloutDecision, user_id: str) -> bool:
        if not settings.LEARNED_RANKER_SHADOW_ENABLED:
            return False
        if decision.requested_mode != "ml":
            return False
        if decision.primary_mode == "ml":
            return False
        sample_rate = max(0.0, min(float(settings.LEARNED_RANKER_SHADOW_SAMPLE_RATE), 1.0))
        if sample_rate <= 0.0:
            return False
        if sample_rate >= 1.0:
            return True
        shadow_bucket = _stable_bucket(
            key=f"{decision.rollout_key}:shadow",
            user_id=user_id,
        )
        return shadow_bucket < int(sample_rate * 10_000)


learned_ranker_rollout_service = LearnedRankerRolloutService()
