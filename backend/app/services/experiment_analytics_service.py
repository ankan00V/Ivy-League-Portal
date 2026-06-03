from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import erf, sqrt
from typing import Any, Iterable, Optional

from app.core.config import settings
from app.models.experiment import Experiment
from app.models.opportunity_interaction import OpportunityInteraction
from app.core.time import utc_now
from app.services.interaction_service import canonical_event_type, funnel_event_type


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
    alert_threshold = float(max(0.0, min(1.0, settings.EXPERIMENT_SRM_P_VALUE_THRESHOLD)))
    alert = bool(p_value is not None and p_value < alert_threshold)
    return {
        "eligible": True,
        "reason": None,
        "chi_square": round(float(chi_square), 8),
        "df": int(df),
        "p_value": round(float(p_value), 8) if p_value is not None else None,
        "threshold": round(float(alert_threshold), 8),
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


def _z_beta_for_target_power(target_power: float) -> float:
    # Practical defaults for common thresholds.
    if target_power >= 0.9:
        return 1.2815515655446004
    if target_power >= 0.85:
        return 1.0364333894937898
    return 0.8416212335729143


def _required_sample_size_per_variant(
    *,
    baseline_rate: float,
    mde_absolute: float,
    alpha: float = 0.05,
    target_power: float = 0.8,
) -> Optional[int]:
    safe_p = max(1e-6, min(1.0 - 1e-6, float(baseline_rate)))
    safe_mde = max(0.0, float(mde_absolute))
    if safe_mde <= 0.0:
        return None
    z_alpha = 1.959963984540054 if alpha <= 0.05 else 1.6448536269514722
    z_beta = _z_beta_for_target_power(target_power)
    numerator = ((z_alpha + z_beta) ** 2) * (2.0 * safe_p * (1.0 - safe_p))
    n = numerator / (safe_mde ** 2)
    if not (n > 0):
        return None
    return int(max(1, round(n)))


@dataclass(frozen=True)
class VariantCounts:
    impressions: int
    conversions: int


@dataclass(frozen=True)
class VariantMetricCounts:
    impressions: int = 0
    clicks: int = 0
    saves: int = 0
    applies: int = 0
    dwell_time_ms_total: float = 0.0
    dwell_count: int = 0
    event_count: int = 0
    session_count: int = 0


def _safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator > 0 else 0.0


def _primary_metric_conversions(metric: str) -> tuple[str, ...]:
    normalized = (metric or "ctr").strip().lower()
    if normalized == "apply_rate":
        return ("apply",)
    if normalized == "save_rate":
        return ("save",)
    return ("click",)


def _is_proportion_metric(metric: str) -> bool:
    return (metric or "ctr").strip().lower() in {"ctr", "apply_rate", "save_rate"}


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
                        "interaction_type": "$interaction_type",
                        "event_type": "$event_type",
                    },
                    "count": {"$sum": 1},
                }
            },
        ]
        rows = await collection.aggregate(pipeline).to_list(length=None)

        by_variant: dict[str, dict[str, int]] = {}
        for row in rows:
            variant = str(row["_id"]["variant"])
            count = int(row["count"])
            interaction_type = str(row["_id"].get("interaction_type") or "")
            event_type = str(row["_id"].get("event_type") or "")
            canonical = canonical_event_type(event_type or interaction_type)
            funnel = funnel_event_type(interaction_type=interaction_type, event_type=event_type)
            counts = by_variant.setdefault(variant, {})
            for key in {interaction_type, canonical, funnel}:
                if key:
                    counts[str(key)] = int(counts.get(str(key), 0)) + count

        result: dict[str, VariantCounts] = {}
        for variant, counts in by_variant.items():
            impressions = int(counts.get("impression", 0))
            conversions = sum(int(counts.get(t, 0)) for t in conversion_types)
            result[variant] = VariantCounts(impressions=impressions, conversions=conversions)

        return result

    async def _metrics_by_variant(
        self,
        *,
        experiment_key: str,
        since: datetime,
        traffic_type: str = "all",
    ) -> dict[str, VariantMetricCounts]:
        collection = _get_collection(OpportunityInteraction)
        traffic_match = self._traffic_match(experiment_key=experiment_key, traffic_type=traffic_type)
        match_stage: dict[str, Any] = {
            "created_at": {"$gte": since},
            "experiment_key": experiment_key,
            "experiment_variant": {"$ne": None},
        }
        if traffic_match:
            match_stage.update(traffic_match)

        event_pipeline: list[dict[str, Any]] = [
            {"$match": match_stage},
            {
                "$group": {
                    "_id": {
                        "variant": "$experiment_variant",
                        "interaction_type": "$interaction_type",
                        "event_type": "$event_type",
                    },
                    "count": {"$sum": 1},
                    "dwell_sum": {"$sum": {"$ifNull": ["$dwell_time_ms", 0]}},
                    "dwell_count": {
                        "$sum": {
                            "$cond": [
                                {"$gt": [{"$ifNull": ["$dwell_time_ms", 0]}, 0]},
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
        ]
        rows = await collection.aggregate(event_pipeline).to_list(length=None)

        mutable: dict[str, dict[str, float]] = {}
        for row in rows:
            variant = str(row["_id"]["variant"])
            interaction_type = str(row["_id"].get("interaction_type") or "")
            event_type = str(row["_id"].get("event_type") or "")
            action = funnel_event_type(interaction_type=interaction_type, event_type=event_type)
            count = int(row.get("count") or 0)
            values = mutable.setdefault(
                variant,
                {
                    "impressions": 0.0,
                    "clicks": 0.0,
                    "saves": 0.0,
                    "applies": 0.0,
                    "dwell_time_ms_total": 0.0,
                    "dwell_count": 0.0,
                    "event_count": 0.0,
                    "session_count": 0.0,
                },
            )
            values["event_count"] += count
            values["dwell_time_ms_total"] += float(row.get("dwell_sum") or 0.0)
            values["dwell_count"] += float(row.get("dwell_count") or 0.0)
            if action == "impression":
                values["impressions"] += count
            elif action == "click":
                values["clicks"] += count
            elif action == "save":
                values["saves"] += count
            elif action == "apply":
                values["applies"] += count

        session_pipeline: list[dict[str, Any]] = [
            {"$match": {**match_stage, "session_id": {"$ne": None}}},
            {"$group": {"_id": {"variant": "$experiment_variant", "session_id": "$session_id"}}},
            {"$group": {"_id": "$_id.variant", "session_count": {"$sum": 1}}},
        ]
        session_rows = await collection.aggregate(session_pipeline).to_list(length=None)
        for row in session_rows:
            variant = str(row["_id"])
            values = mutable.setdefault(
                variant,
                {
                    "impressions": 0.0,
                    "clicks": 0.0,
                    "saves": 0.0,
                    "applies": 0.0,
                    "dwell_time_ms_total": 0.0,
                    "dwell_count": 0.0,
                    "event_count": 0.0,
                    "session_count": 0.0,
                },
            )
            values["session_count"] = float(row.get("session_count") or 0.0)

        return {
            variant: VariantMetricCounts(
                impressions=int(values["impressions"]),
                clicks=int(values["clicks"]),
                saves=int(values["saves"]),
                applies=int(values["applies"]),
                dwell_time_ms_total=float(values["dwell_time_ms_total"]),
                dwell_count=int(values["dwell_count"]),
                event_count=int(values["event_count"]),
                session_count=int(values["session_count"]),
            )
            for variant, values in mutable.items()
        }

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

        since = utc_now() - timedelta(days=safe_days)
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
                    "weight": float(variant.traffic_fraction)
                    if variant.traffic_fraction is not None
                    else float(variant.weight),
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
                        target_power=float(max(0.5, min(0.99, settings.EXPERIMENT_TARGET_POWER))),
                    ),
                }
            )

        srm_diagnostic = _srm_diagnostic(variants_payload=variants_payload)
        guardrail_reasons: list[str] = []
        significance_failures: list[dict[str, Any]] = []
        alpha = float(max(0.0, min(1.0, settings.EXPERIMENT_SIGNIFICANCE_ALPHA)))
        min_impressions = int(max(1, settings.EXPERIMENT_GUARDRAIL_MIN_IMPRESSIONS_PER_VARIANT))
        min_lift_impressions = int(max(1, settings.EXPERIMENT_MIN_IMPRESSIONS_PER_VARIANT_FOR_LIFT))
        target_power = float(max(0.5, min(0.99, settings.EXPERIMENT_TARGET_POWER)))

        variant_impressions = {item["name"]: int(item.get("impressions") or 0) for item in variants_payload}
        for idx, comparison in enumerate(comparisons):
            p_value = comparison.get("p_value")
            diff = comparison.get("diff")
            variant_name = str(comparison.get("variant") or "")
            control_name_for_cmp = str(comparison.get("control") or control_name)
            control_impressions = int(variant_impressions.get(control_name_for_cmp, 0))
            variant_impressions_count = int(variant_impressions.get(variant_name, 0))
            sample_size_eligible = (
                control_impressions >= min_lift_impressions
                and variant_impressions_count >= min_lift_impressions
            )
            sample_gate_reason = None if sample_size_eligible else "min_sample_size_not_met"
            comparison["sample_size_gate"] = {
                "eligible": bool(sample_size_eligible),
                "reason": sample_gate_reason,
                "min_impressions_per_variant": int(min_lift_impressions),
                "control_impressions": int(control_impressions),
                "variant_impressions": int(variant_impressions_count),
            }

            power_payload = dict(comparison.get("power") or {})
            if power_payload.get("eligible"):
                power_payload["target_power"] = round(target_power, 8)
                power_payload["is_underpowered"] = bool(
                    bool(power_payload.get("is_underpowered"))
                    or not sample_size_eligible
                )
                power_payload["label"] = "insufficient_power" if power_payload["is_underpowered"] else "sufficient_power"
            else:
                power_payload["target_power"] = round(target_power, 8)
                power_payload["is_underpowered"] = True
                power_payload["label"] = "insufficient_power"

            baseline_rate = float(control.get("conversion_rate") or 0.0)
            observed_delta = abs(float(diff or 0.0))
            design_mde = max(0.01, observed_delta)
            power_payload["required_sample_size_per_variant"] = _required_sample_size_per_variant(
                baseline_rate=baseline_rate,
                mde_absolute=design_mde,
                alpha=alpha,
                target_power=target_power,
            )
            comparison["power"] = power_payload

            if power_payload.get("label") == "insufficient_power":
                comparison["lift_declared"] = False
                comparison["lift_label"] = "insufficient_power"
            elif p_value is not None and diff is not None and float(p_value) < alpha and float(diff) > 0.0:
                comparison["lift_declared"] = True
                comparison["lift_label"] = "significant_positive"
            elif p_value is not None and diff is not None and float(p_value) < alpha and float(diff) < 0.0:
                comparison["lift_declared"] = True
                comparison["lift_label"] = "significant_negative"
            else:
                comparison["lift_declared"] = False
                comparison["lift_label"] = "not_significant"

            comparisons[idx] = comparison
            if p_value is None or diff is None:
                continue
            if float(p_value) < alpha and float(diff) < 0.0:
                if (
                    variant_impressions.get(variant_name, 0) >= min_impressions
                    and variant_impressions.get(control_name_for_cmp, 0) >= min_impressions
                ):
                    significance_failures.append(
                        {
                            "control": control_name_for_cmp,
                            "variant": variant_name,
                            "diff": float(diff),
                            "p_value": float(p_value),
                            "alpha": alpha,
                        }
                    )

        if bool(srm_diagnostic.get("alert")):
            guardrail_reasons.append("srm_failure")
        if significance_failures:
            guardrail_reasons.append("significant_regression")

        should_pause = (
            bool(settings.EXPERIMENT_AUTO_PAUSE_ON_GUARDRAIL_FAIL)
            and experiment.status in {"active", "running"}
            and bool(guardrail_reasons)
        )
        auto_paused = False
        if should_pause and hasattr(experiment, "save"):
            experiment.status = "paused"  # type: ignore[assignment]
            experiment.updated_at = utc_now()
            await experiment.save()
            auto_paused = True

        return {
            "experiment_key": experiment.key,
            "status": "paused" if auto_paused else experiment.status,
            "days": safe_days,
            "traffic_type": (traffic_type or "all").strip().lower() or "all",
            "conversion_types": sorted(conversion_set),
            "variants": variants_payload,
            "comparisons": comparisons,
            "diagnostics": {
                "srm": srm_diagnostic,
                "guardrails": {
                    "alpha": alpha,
                    "min_impressions_per_variant": min_impressions,
                    "significance_failures": significance_failures,
                    "triggered_reasons": guardrail_reasons,
                    "should_pause": bool(guardrail_reasons),
                    "auto_paused": auto_paused,
                },
            },
        }

    async def results(
        self,
        *,
        experiment: Experiment,
        days: int = 30,
        traffic_type: str = "all",
    ) -> dict[str, Any]:
        safe_days = max(1, min(int(days), 365))
        primary_metric = str(getattr(experiment, "primary_metric", "ctr") or "ctr")
        conversion_types = _primary_metric_conversions(primary_metric)
        base_report = await self.report(
            experiment=experiment,
            days=safe_days,
            conversion_types=conversion_types,
            traffic_type=traffic_type,
        )

        since = utc_now() - timedelta(days=safe_days)
        metric_counts = await self._metrics_by_variant(
            experiment_key=experiment.key,
            since=since,
            traffic_type=traffic_type,
        )

        total_impressions = sum(counts.impressions for counts in metric_counts.values())
        variant_metrics: list[dict[str, Any]] = []
        for variant in experiment.variants:
            counts = metric_counts.get(variant.name, VariantMetricCounts())
            impressions = int(counts.impressions)
            avg_dwell = _safe_ratio(counts.dwell_time_ms_total, float(counts.dwell_count))
            session_depth = _safe_ratio(float(counts.event_count), float(counts.session_count))
            configured_fraction = (
                float(variant.traffic_fraction)
                if variant.traffic_fraction is not None
                else float(variant.weight)
            )
            variant_metrics.append(
                {
                    "name": variant.name,
                    "ranking_mode": variant.ranking_mode or variant.name,
                    "is_control": bool(variant.is_control),
                    "configured_traffic": configured_fraction,
                    "observed_traffic_fraction": _safe_ratio(float(impressions), float(total_impressions)),
                    "sample_size": impressions,
                    "ctr": round(_safe_ratio(float(counts.clicks), float(impressions)), 8),
                    "apply_rate": round(_safe_ratio(float(counts.applies), float(impressions)), 8),
                    "save_rate": round(_safe_ratio(float(counts.saves), float(impressions)), 8),
                    "avg_dwell_time_ms": round(float(avg_dwell), 3),
                    "session_length": round(float(session_depth), 6),
                    "events": int(counts.event_count),
                    "sessions": int(counts.session_count),
                }
            )

        recommendation = self._recommendation(
            experiment=experiment,
            report=base_report,
            variant_metrics=variant_metrics,
        )

        return {
            "experiment_id": experiment.key,
            "name": experiment.name or experiment.key,
            "description": experiment.description,
            "status": base_report.get("status", experiment.status),
            "primary_metric": primary_metric,
            "guardrail_metrics": list(getattr(experiment, "guardrail_metrics", []) or []),
            "days": safe_days,
            "traffic_type": (traffic_type or "all").strip().lower() or "all",
            "min_sample_size": int(getattr(experiment, "min_sample_size", 1) or 1),
            "variants": variant_metrics,
            "statistical_significance": base_report.get("comparisons", []),
            "traffic_allocation": {
                "total_impressions": int(total_impressions),
                "variants": [
                    {
                        "name": item["name"],
                        "configured": item["configured_traffic"],
                        "observed": item["observed_traffic_fraction"],
                    }
                    for item in variant_metrics
                ],
            },
            "recommendation": recommendation,
            "diagnostics": base_report.get("diagnostics", {}),
            "base_report": base_report,
        }

    def _recommendation(
        self,
        *,
        experiment: Experiment,
        report: dict[str, Any],
        variant_metrics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        min_sample_size = int(
            max(
                1,
                getattr(experiment, "min_sample_size", None)
                or settings.EXPERIMENT_GRADUATION_MIN_SAMPLE_SIZE,
            )
        )
        guardrails = dict((report.get("diagnostics") or {}).get("guardrails") or {})
        triggered_reasons = list(guardrails.get("triggered_reasons") or [])
        if triggered_reasons:
            return {
                "code": "guardrail_regressed_pause_recommended",
                "message": "Guardrail metric regressed - pause recommended",
                "winning_variant": None,
                "ready_for_graduation": False,
                "reasons": triggered_reasons,
            }

        under_sampled = [
            item["name"]
            for item in variant_metrics
            if int(item.get("sample_size") or 0) < min_sample_size
        ]
        if under_sampled:
            return {
                "code": "insufficient_data",
                "message": "Insufficient data",
                "winning_variant": None,
                "ready_for_graduation": False,
                "reasons": [f"sample_size_below_min:{','.join(under_sampled)}"],
            }

        p_threshold = float(settings.EXPERIMENT_GRADUATION_P_VALUE)
        min_lift = float(settings.EXPERIMENT_GRADUATION_MIN_LIFT)
        primary_metric = str(getattr(experiment, "primary_metric", "ctr") or "ctr")
        if not _is_proportion_metric(primary_metric):
            return {
                "code": "manual_review_required_non_proportion_metric",
                "message": "Primary metric requires manual review",
                "winning_variant": None,
                "ready_for_graduation": False,
                "reasons": [f"non_proportion_metric:{primary_metric}"],
            }

        candidates: list[dict[str, Any]] = []
        for comparison in report.get("comparisons", []) or []:
            p_value = comparison.get("p_value")
            lift = comparison.get("lift")
            if p_value is None or lift is None:
                continue
            if float(p_value) < p_threshold and float(lift) >= min_lift:
                candidates.append(comparison)

        if candidates:
            candidates.sort(key=lambda item: float(item.get("lift") or 0.0), reverse=True)
            winner = str(candidates[0].get("variant") or "")
            return {
                "code": "significant_lift_consider_graduating",
                "message": "Significant lift - consider graduating",
                "winning_variant": winner,
                "ready_for_graduation": True,
                "reasons": [
                    f"p_value<{p_threshold}",
                    f"lift>={min_lift}",
                    f"sample_size>={min_sample_size}",
                ],
            }

        return {
            "code": "no_significant_difference",
            "message": "No significant difference",
            "winning_variant": None,
            "ready_for_graduation": False,
            "reasons": [],
        }

    async def maybe_graduate(
        self,
        *,
        experiment: Experiment,
        days: int = 30,
        traffic_type: str = "real",
        force: bool = False,
    ) -> dict[str, Any]:
        results = await self.results(experiment=experiment, days=days, traffic_type=traffic_type)
        recommendation = dict(results.get("recommendation") or {})
        winning_variant = str(recommendation.get("winning_variant") or "").strip()
        ready = bool(recommendation.get("ready_for_graduation"))
        if not force and (not settings.EXPERIMENT_AUTO_GRADUATION_ENABLED or not ready or not winning_variant):
            return {
                "graduated": False,
                "reason": recommendation.get("code") or "not_ready",
                "results": results,
            }

        if not winning_variant:
            return {
                "graduated": False,
                "reason": "winning_variant_missing",
                "results": results,
            }

        event = {
            "graduated_at": utc_now().isoformat(),
            "winning_variant": winning_variant,
            "primary_metric": results.get("primary_metric"),
            "recommendation": recommendation,
            "traffic_type": traffic_type,
            "days": int(days),
            "forced": bool(force),
        }
        history = list(getattr(experiment, "graduation_history", []) or [])
        history.append(event)
        experiment.winning_variant = winning_variant
        experiment.default_variant = winning_variant
        experiment.status = "concluded"  # type: ignore[assignment]
        experiment.graduated_at = utc_now()
        experiment.graduation_history = history[-20:]
        experiment.updated_at = utc_now()
        await experiment.save()
        return {
            "graduated": True,
            "winning_variant": winning_variant,
            "results": results,
            "event": event,
        }


experiment_analytics_service = ExperimentAnalyticsService()
