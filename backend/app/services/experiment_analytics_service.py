from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import erf, sqrt
from typing import Any, Iterable, Optional

from app.models.experiment import Experiment
from app.models.opportunity_interaction import OpportunityInteraction


def _get_collection(document_cls: type) -> Any:
    getter = getattr(document_cls, "get_motor_collection", None)
    if callable(getter):
        return getter()
    getter = getattr(document_cls, "get_pymongo_collection", None)
    if callable(getter):
        return getter()
    raise AttributeError(f"No collection getter found for {document_cls.__name__}")


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = k / float(n)
    z2 = z * z
    denom = 1.0 + (z2 / n)
    center = (p + (z2 / (2.0 * n))) / denom
    half = (z * sqrt((p * (1.0 - p) + (z2 / (4.0 * n))) / n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _two_proportion_z_test(
    *,
    k_control: int,
    n_control: int,
    k_variant: int,
    n_variant: int,
) -> tuple[Optional[float], Optional[float]]:
    if n_control <= 0 or n_variant <= 0:
        return None, None
    p1 = k_control / float(n_control)
    p2 = k_variant / float(n_variant)
    pooled = (k_control + k_variant) / float(n_control + n_variant)
    se = sqrt(max(0.0, pooled * (1.0 - pooled) * ((1.0 / n_control) + (1.0 / n_variant))))
    if se <= 0:
        return 0.0, 1.0
    z = (p2 - p1) / se
    p_value = 2.0 * (1.0 - _norm_cdf(abs(z)))
    return z, max(0.0, min(1.0, p_value))


def _diff_ci_unpooled(
    *,
    k_control: int,
    n_control: int,
    k_variant: int,
    n_variant: int,
    z: float = 1.96,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if n_control <= 0 or n_variant <= 0:
        return None, None, None
    p1 = k_control / float(n_control)
    p2 = k_variant / float(n_variant)
    diff = p2 - p1
    se = sqrt(max(0.0, (p1 * (1.0 - p1) / n_control) + (p2 * (1.0 - p2) / n_variant)))
    if se <= 0:
        return diff, diff, diff
    return diff, diff - (z * se), diff + (z * se)


@dataclass(frozen=True)
class VariantCounts:
    impressions: int
    conversions: int


class ExperimentAnalyticsService:
    async def _counts_by_variant(
        self,
        *,
        experiment_key: str,
        since: datetime,
        conversion_types: set[str],
    ) -> dict[str, VariantCounts]:
        collection = _get_collection(OpportunityInteraction)
        pipeline: list[dict[str, Any]] = [
            {
                "$match": {
                    "created_at": {"$gte": since},
                    "experiment_key": experiment_key,
                    "experiment_variant": {"$ne": None},
                }
            },
            {
                "$group": {
                    "_id": {
                        "variant": "$experiment_variant",
                        "type": "$interaction_type",
                    },
                    "count": {"$sum": 1},
                }
            },
        ]
        rows = await collection.aggregate(pipeline).to_list(length=None)

        by_variant: dict[str, dict[str, int]] = {}
        for row in rows:
            variant = str(row["_id"]["variant"])
            event_type = str(row["_id"]["type"])
            count = int(row["count"])
            by_variant.setdefault(variant, {})[event_type] = count

        result: dict[str, VariantCounts] = {}
        for variant, counts in by_variant.items():
            impressions = int(counts.get("impression", 0))
            conversions = sum(int(counts.get(t, 0)) for t in conversion_types)
            result[variant] = VariantCounts(impressions=impressions, conversions=conversions)

        return result

    async def report(
        self,
        *,
        experiment: Experiment,
        days: int = 30,
        conversion_types: Iterable[str] = ("click",),
    ) -> dict[str, Any]:
        safe_days = max(1, min(int(days), 365))
        conversion_set = {str(value) for value in conversion_types if value}
        if not conversion_set:
            conversion_set = {"click"}

        since = datetime.utcnow() - timedelta(days=safe_days)
        counts = await self._counts_by_variant(
            experiment_key=experiment.key,
            since=since,
            conversion_types=conversion_set,
        )

        variants_payload: list[dict[str, Any]] = []
        for variant in experiment.variants:
            c = counts.get(variant.name, VariantCounts(impressions=0, conversions=0))
            cr = (c.conversions / c.impressions) if c.impressions > 0 else 0.0
            low, high = _wilson_ci(c.conversions, c.impressions)
            variants_payload.append(
                {
                    "name": variant.name,
                    "weight": float(variant.weight),
                    "is_control": bool(variant.is_control),
                    "impressions": int(c.impressions),
                    "conversions": int(c.conversions),
                    "conversion_rate": round(float(cr), 8),
                    "ci_low": round(float(low), 8),
                    "ci_high": round(float(high), 8),
                }
            )

        if not variants_payload:
            return {
                "experiment_key": experiment.key,
                "status": experiment.status,
                "days": safe_days,
                "conversion_types": sorted(conversion_set),
                "variants": [],
                "comparisons": [],
            }

        control_name = next((v["name"] for v in variants_payload if v["is_control"]), variants_payload[0]["name"])
        control = next(v for v in variants_payload if v["name"] == control_name)

        comparisons: list[dict[str, Any]] = []
        for variant in variants_payload:
            if variant["name"] == control_name:
                continue
            z_stat, p_value = _two_proportion_z_test(
                k_control=int(control["conversions"]),
                n_control=int(control["impressions"]),
                k_variant=int(variant["conversions"]),
                n_variant=int(variant["impressions"]),
            )
            diff, diff_low, diff_high = _diff_ci_unpooled(
                k_control=int(control["conversions"]),
                n_control=int(control["impressions"]),
                k_variant=int(variant["conversions"]),
                n_variant=int(variant["impressions"]),
            )
            p1 = float(control["conversion_rate"])
            lift = (diff / p1) if (diff is not None and p1 > 0) else None
            comparisons.append(
                {
                    "control": control_name,
                    "variant": variant["name"],
                    "diff": round(float(diff), 8) if diff is not None else None,
                    "diff_ci_low": round(float(diff_low), 8) if diff_low is not None else None,
                    "diff_ci_high": round(float(diff_high), 8) if diff_high is not None else None,
                    "lift": round(float(lift), 8) if lift is not None else None,
                    "z": round(float(z_stat), 8) if z_stat is not None else None,
                    "p_value": round(float(p_value), 8) if p_value is not None else None,
                }
            )

        return {
            "experiment_key": experiment.key,
            "status": experiment.status,
            "days": safe_days,
            "conversion_types": sorted(conversion_set),
            "variants": variants_payload,
            "comparisons": comparisons,
        }


experiment_analytics_service = ExperimentAnalyticsService()
