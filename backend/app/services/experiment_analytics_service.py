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


def _chi_square_sf(chi_square: float, df: int) -> Optional[float]:
    if df <= 0 or chi_square < 0:
        return None
    # Wilson-Hilferty approximation: chi-square to standard normal.
    # Accurate enough for online SRM diagnostics with df >= 1.
    denom = sqrt(2.0 / (9.0 * float(df)))
    if denom <= 0:
        return None
    transformed = ((chi_square / float(df)) ** (1.0 / 3.0) - (1.0 - 2.0 / (9.0 * float(df)))) / denom
    p_value = 1.0 - _norm_cdf(transformed)
    return max(0.0, min(1.0, p_value))


def _srm_diagnostic(
    *,
    variants_payload: list[dict[str, Any]],
) -> dict[str, Any]:
    if not variants_payload:
        return {
            "eligible": False,
            "reason": "no_variants",
            "chi_square": None,
            "p_value": None,
            "alert": False,
        }

    total_impressions = int(sum(int(item.get("impressions") or 0) for item in variants_payload))
    if total_impressions <= 0:
        return {
            "eligible": False,
            "reason": "no_impressions",
            "chi_square": None,
            "p_value": None,
            "alert": False,
        }

    total_weight = float(sum(max(0.0, float(item.get("weight") or 0.0)) for item in variants_payload))
    if total_weight <= 0.0:
        total_weight = float(len(variants_payload))

    observed: dict[str, float] = {}
    expected: dict[str, float] = {}
    chi_square = 0.0
    for item in variants_payload:
        name = str(item.get("name") or "")
        impressions = int(item.get("impressions") or 0)
        weight = max(0.0, float(item.get("weight") or 0.0))
        if total_weight <= 0:
            expected_ratio = 1.0 / float(max(1, len(variants_payload)))
        else:
            expected_ratio = weight / total_weight
        expected_count = float(total_impressions) * expected_ratio

        observed[name] = float(impressions / float(total_impressions))
        expected[name] = float(expected_ratio)
        if expected_count > 0:
            chi_square += ((float(impressions) - expected_count) ** 2) / expected_count

    df = max(1, len(variants_payload) - 1)
    p_value = _chi_square_sf(chi_square, df)
    alert = bool(p_value is not None and p_value < 0.01)
    return {
        "eligible": True,
        "reason": None,
        "chi_square": round(float(chi_square), 8),
        "df": int(df),
        "p_value": round(float(p_value), 8) if p_value is not None else None,
        "alert": alert,
        "expected_allocation": expected,
        "observed_allocation": observed,
        "total_impressions": total_impressions,
    }


def _observed_power_and_mde(
    *,
    k_control: int,
    n_control: int,
    k_variant: int,
    n_variant: int,
    alpha: float = 0.05,
    target_power: float = 0.8,
) -> dict[str, Any]:
    if n_control <= 0 or n_variant <= 0:
        return {
            "eligible": False,
            "reason": "insufficient_impressions",
            "alpha": alpha,
            "target_power": target_power,
            "observed_power": None,
            "mde_absolute": None,
            "is_underpowered": None,
        }

    p1 = k_control / float(n_control)
    p2 = k_variant / float(n_variant)
    diff = p2 - p1
    z_alpha = 1.959963984540054  # two-sided alpha=0.05
    z_beta = 0.8416212335729143  # target power=0.8

    se_alt = sqrt(max(0.0, (p1 * (1.0 - p1) / n_control) + (p2 * (1.0 - p2) / n_variant)))
    z_effect = (abs(diff) / se_alt) if se_alt > 0 else 0.0
    power = _norm_cdf(z_effect - z_alpha) + (1.0 - _norm_cdf(z_effect + z_alpha))
    power = max(0.0, min(1.0, power))

    pooled = (k_control + k_variant) / float(n_control + n_variant)
    se_null = sqrt(max(0.0, pooled * (1.0 - pooled) * ((1.0 / n_control) + (1.0 / n_variant))))
    mde_absolute = (z_alpha + z_beta) * se_null

    return {
        "eligible": True,
        "reason": None,
        "alpha": alpha,
        "target_power": target_power,
        "observed_power": round(float(power), 8),
        "mde_absolute": round(float(mde_absolute), 8),
        "is_underpowered": bool(power < target_power),
    }


@dataclass(frozen=True)
class VariantCounts:
    impressions: int
    conversions: int


class ExperimentAnalyticsService:
    def _traffic_match(self, *, experiment_key: str, traffic_type: str) -> dict[str, Any]:
        normalized = (traffic_type or "all").strip().lower()
        if normalized == "all":
            return {}
        if normalized == "real":
            return {"$or": [{"traffic_type": "real"}, {"traffic_type": {"$exists": False}}, {"traffic_type": None}]}
        if normalized == "simulated":
            return {
                "$or": [
                    {"traffic_type": "simulated"},
                    {
                        "$and": [
                            {"$or": [{"traffic_type": {"$exists": False}}, {"traffic_type": None}]},
                            {"experiment_key": {"$regex": "sim", "$options": "i"}},
                        ]
                    },
                ]
            }
        return {}

    async def _counts_by_variant(
        self,
        *,
        experiment_key: str,
        since: datetime,
        conversion_types: set[str],
        traffic_type: str = "all",
    ) -> dict[str, VariantCounts]:
        collection = _get_collection(OpportunityInteraction)
        traffic_match = self._traffic_match(experiment_key=experiment_key, traffic_type=traffic_type)
        match_stage: dict[str, Any] = {
            "created_at": {"$gte": since},
            "experiment_key": experiment_key,
            "experiment_variant": {"$ne": None},
        }
        if traffic_match:
            match_stage.update(traffic_match)
        pipeline: list[dict[str, Any]] = [
            {"$match": match_stage},
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
        traffic_type: str = "all",
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
            traffic_type=traffic_type,
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
                "traffic_type": (traffic_type or "all").strip().lower() or "all",
                "conversion_types": sorted(conversion_set),
                "variants": [],
                "comparisons": [],
                "diagnostics": {
                    "srm": _srm_diagnostic(variants_payload=[]),
                },
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
                    "power": _observed_power_and_mde(
                        k_control=int(control["conversions"]),
                        n_control=int(control["impressions"]),
                        k_variant=int(variant["conversions"]),
                        n_variant=int(variant["impressions"]),
                    ),
                }
            )

        return {
            "experiment_key": experiment.key,
            "status": experiment.status,
            "days": safe_days,
            "traffic_type": (traffic_type or "all").strip().lower() or "all",
            "conversion_types": sorted(conversion_set),
            "variants": variants_payload,
            "comparisons": comparisons,
            "diagnostics": {
                "srm": _srm_diagnostic(variants_payload=variants_payload),
            },
        }


experiment_analytics_service = ExperimentAnalyticsService()
