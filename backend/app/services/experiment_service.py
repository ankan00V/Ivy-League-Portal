from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Optional

from beanie import PydanticObjectId
from beanie.exceptions import CollectionWasNotInitialized
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.models.experiment import Experiment, ExperimentAssignment, ExperimentVariant
from app.models.opportunity_interaction import OpportunityInteraction


ACTIVE_EXPERIMENT_STATUSES = {"active", "running"}


@dataclass(frozen=True)
class ExperimentDecision:
    experiment_key: str
    variant: str
    is_control: bool
    bucket: int
    assigned_at: datetime


def _stable_bucket(*, experiment_key: str, salt: str, user_id: str) -> int:
    digest = sha256(f"{experiment_key}:{salt}:{user_id}".encode("utf-8")).digest()
    # Use 64-bit slice for speed + portability.
    value = int.from_bytes(digest[:8], "big", signed=False)
    return value % 10_000


def _allocate_units(variants: list[ExperimentVariant]) -> list[int]:
    total = sum(_variant_weight(v) for v in variants)
    if total <= 0:
        return [0 for _ in variants]

    raw = [(_variant_weight(v) / total) * 10_000.0 for v in variants]
    floor_units = [int(x) for x in raw]
    remainder = [raw[i] - floor_units[i] for i in range(len(raw))]
    missing = 10_000 - sum(floor_units)
    if missing > 0:
        # Largest remainder method.
        order = sorted(range(len(remainder)), key=lambda i: remainder[i], reverse=True)
        for idx in order[:missing]:
            floor_units[idx] += 1
    return floor_units


def _variant_weight(variant: ExperimentVariant) -> float:
    if variant.traffic_fraction is not None:
        return max(0.0, float(variant.traffic_fraction))
    return max(0.0, float(variant.weight))


def _pick_variant(variants: list[ExperimentVariant], bucket: int) -> tuple[str, bool]:
    if not variants:
        return "control", True

    names = [v.name for v in variants]
    if len(set(names)) != len(names):
        raise ValueError("Experiment variants must have unique names")

    units = _allocate_units(variants)
    cumulative = 0
    picked_idx = 0
    for idx, amount in enumerate(units):
        cumulative += amount
        if bucket < cumulative:
            picked_idx = idx
            break

    picked = variants[picked_idx]
    is_control = bool(picked.is_control) or not any(v.is_control for v in variants) and picked_idx == 0
    return picked.name, is_control


class ExperimentService:
    DEFAULT_EXPERIMENTS: dict[str, dict] = {
        "ranking_mode": {
            "key": "ranking_mode",
            "description": "Recommendation ranking algorithm: baseline vs semantic vs learned ranker.",
            "status": "active",
            "variants": [
                {
                    "name": "baseline",
                    "weight": 1.0,
                    "ranking_mode": "baseline",
                    "description": "Rules + profile matching baseline.",
                    "is_control": True,
                },
                {
                    "name": "semantic",
                    "weight": 1.0,
                    "ranking_mode": "semantic",
                    "description": "Embedding retrieval plus heuristic reranking.",
                    "is_control": False,
                },
                {
                    "name": "ml",
                    "weight": 1.0,
                    "ranking_mode": "ml",
                    "description": "Learned ranker treatment.",
                    "exclude_cold_start": True,
                    "is_control": False,
                },
            ],
        }
    }

    async def ensure_defaults(self) -> None:
        for key, template in self.DEFAULT_EXPERIMENTS.items():
            existing = await Experiment.find_one(Experiment.key == key)
            if existing:
                continue
            experiment = Experiment(
                key=template["key"],
                name="Ranking Mode",
                description=template.get("description"),
                status=template.get("status", "active"),
                variants=[ExperimentVariant(**v) for v in template.get("variants", [])],
            )
            await experiment.insert()

    async def get(self, key: str) -> Optional[Experiment]:
        return await Experiment.find_one(Experiment.key == key)

    async def assign(
        self,
        *,
        user_id: PydanticObjectId,
        experiment_key: str,
        override_variant: Optional[str] = None,
        cold_start: Optional[bool] = None,
    ) -> Optional[ExperimentDecision]:
        experiment = await self.get(experiment_key)
        if not experiment or experiment.status not in ACTIVE_EXPERIMENT_STATUSES:
            return None

        existing = await self._find_assignment(user_id=user_id, experiment_key=experiment_key)
        if existing:
            # Sticky assignment.
            return ExperimentDecision(
                experiment_key=existing.experiment_key,
                variant=existing.variant,
                is_control=any(v.name == existing.variant and v.is_control for v in experiment.variants),
                bucket=int(existing.bucket),
                assigned_at=existing.assigned_at,
            )

        user_id_str = str(user_id)
        bucket = _stable_bucket(experiment_key=experiment_key, salt=experiment.salt, user_id=user_id_str)
        bucket_percent = int(bucket // 100)

        if override_variant:
            variant = override_variant
            if variant not in {v.name for v in experiment.variants}:
                raise ValueError("override_variant must be an existing variant")
            is_control = any(v.name == variant and v.is_control for v in experiment.variants)
        else:
            variant, is_control = _pick_variant(experiment.variants, bucket)
            variant, is_control, exclusion_reason = await self._apply_exclusion_rules(
                variants=experiment.variants,
                selected_variant=variant,
                cold_start=cold_start,
                user_id=user_id,
            )
        if override_variant:
            exclusion_reason = None

        assignment = self._make_assignment(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=variant,
            bucket=bucket,
            bucket_percent=bucket_percent,
            assigned_via_exclusion=bool(exclusion_reason),
            exclusion_reason=exclusion_reason,
        )
        try:
            await assignment.insert()
        except DuplicateKeyError:
            # Another request created the assignment concurrently; keep it sticky.
            existing = await self._find_assignment(user_id=user_id, experiment_key=experiment_key)
            if existing:
                return ExperimentDecision(
                    experiment_key=existing.experiment_key,
                    variant=existing.variant,
                    is_control=any(v.name == existing.variant and v.is_control for v in experiment.variants),
                    bucket=int(existing.bucket),
                    assigned_at=existing.assigned_at,
                )
            raise

        return ExperimentDecision(
            experiment_key=experiment_key,
            variant=variant,
            is_control=is_control,
            bucket=bucket,
            assigned_at=assignment.assigned_at,
        )

    async def _find_assignment(
        self,
        *,
        user_id: PydanticObjectId,
        experiment_key: str,
    ) -> Optional[ExperimentAssignment]:
        return await ExperimentAssignment.find_one(
            ExperimentAssignment.user_id == user_id,
            ExperimentAssignment.experiment_key == experiment_key,
        )

    def _make_assignment(
        self,
        *,
        user_id: PydanticObjectId,
        experiment_key: str,
        variant: str,
        bucket: int,
        bucket_percent: int,
        assigned_via_exclusion: bool,
        exclusion_reason: Optional[str],
    ) -> ExperimentAssignment:
        return ExperimentAssignment(
            user_id=user_id,
            experiment_key=experiment_key,
            variant=variant,
            bucket=bucket,
            bucket_percent=bucket_percent,
            assigned_via_exclusion=assigned_via_exclusion,
            exclusion_reason=exclusion_reason,
        )

    async def _apply_exclusion_rules(
        self,
        *,
        variants: list[ExperimentVariant],
        selected_variant: str,
        cold_start: Optional[bool],
        user_id: PydanticObjectId,
    ) -> tuple[str, bool, Optional[str]]:
        selected = next((variant for variant in variants if variant.name == selected_variant), None)
        if selected is None:
            return selected_variant, False, None

        cold_start_value = cold_start
        if cold_start_value is None and self._variant_excludes_cold_start(selected):
            cold_start_value = await self._is_cold_start_user(user_id=user_id)

        if not bool(cold_start_value) or not self._variant_excludes_cold_start(selected):
            return selected.name, bool(selected.is_control), None

        fallback = next(
            (variant for variant in variants if variant.is_control and not self._variant_excludes_cold_start(variant)),
            None,
        )
        if fallback is None:
            fallback = next((variant for variant in variants if not self._variant_excludes_cold_start(variant)), selected)

        is_control = bool(fallback.is_control) or not any(v.is_control for v in variants)
        return fallback.name, is_control, "cold_start_excluded_from_ml"

    def _variant_excludes_cold_start(self, variant: ExperimentVariant) -> bool:
        ranking_mode = str(variant.ranking_mode or variant.name or "").strip().lower()
        return bool(variant.exclude_cold_start) or (
            bool(settings.EXPERIMENT_EXCLUDE_COLD_START_FROM_ML) and ranking_mode == "ml"
        )

    async def _is_cold_start_user(self, *, user_id: PydanticObjectId) -> bool:
        try:
            rows = (
                await OpportunityInteraction.find_many(OpportunityInteraction.user_id == user_id)
                .limit(1)
                .to_list()
            )
        except CollectionWasNotInitialized:
            return True
        return not rows


experiment_service = ExperimentService()
