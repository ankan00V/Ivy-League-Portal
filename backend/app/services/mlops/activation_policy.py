from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ALLOWED_ACTIVATION_POLICIES = {"manual", "auc_gain", "guarded"}


@dataclass(frozen=True)
class ActivationDecision:
    should_activate: bool
    reason: str
    policy: str
    diagnostics: dict[str, Any]



def _normalize_policy(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in ALLOWED_ACTIVATION_POLICIES:
        return normalized
    return "guarded"



def _l1_weight_shift(*, baseline: dict[str, float], learned: dict[str, float]) -> float:
    keys = {"semantic", "baseline", "behavior"}
    return float(
        sum(
            abs(float(baseline.get(key, 0.0)) - float(learned.get(key, 0.0)))
            for key in keys
        )
    )



def evaluate_activation_policy(
    *,
    auto_activate: bool,
    policy: str,
    auc_gain: float,
    min_auc_gain: float,
    positive_rate: float,
    min_positive_rate: float,
    learned_weights: dict[str, float],
    baseline_weights: dict[str, float],
    max_weight_shift: float,
    guardrail_report: dict[str, Any] | None = None,
    require_online_kpis: bool = True,
    max_apply_rate_drop: float = 0.0,
    max_freshness_regression_seconds: float = 300.0,
    max_latency_p95_regression_ms: float = 75.0,
    max_failure_rate_regression: float = 0.01,
) -> ActivationDecision:
    effective_policy = _normalize_policy(policy)
    weight_shift_l1 = _l1_weight_shift(baseline=baseline_weights, learned=learned_weights)

    diagnostics: dict[str, Any] = {
        "auto_activate_requested": bool(auto_activate),
        "policy": effective_policy,
        "auc_gain": float(round(auc_gain, 6)),
        "min_auc_gain": float(round(min_auc_gain, 6)),
        "positive_rate": float(round(positive_rate, 6)),
        "min_positive_rate": float(round(min_positive_rate, 6)),
        "weight_shift_l1": float(round(weight_shift_l1, 6)),
        "max_weight_shift": float(round(max_weight_shift, 6)),
        "guardrails": guardrail_report or {},
    }

    if not auto_activate:
        return ActivationDecision(
            should_activate=False,
            reason="auto_activate_disabled",
            policy=effective_policy,
            diagnostics=diagnostics,
        )

    if effective_policy == "manual":
        return ActivationDecision(
            should_activate=False,
            reason="manual_policy_requires_explicit_activation",
            policy=effective_policy,
            diagnostics=diagnostics,
        )

    if auc_gain < float(min_auc_gain):
        return ActivationDecision(
            should_activate=False,
            reason=f"auc_gain_below_threshold:{auc_gain:.6f}<{float(min_auc_gain):.6f}",
            policy=effective_policy,
            diagnostics=diagnostics,
        )

    if positive_rate < float(min_positive_rate):
        return ActivationDecision(
            should_activate=False,
            reason=(
                f"positive_rate_below_threshold:{positive_rate:.6f}"
                f"<{float(min_positive_rate):.6f}"
            ),
            policy=effective_policy,
            diagnostics=diagnostics,
        )

    if effective_policy == "guarded" and weight_shift_l1 > float(max_weight_shift):
        return ActivationDecision(
            should_activate=False,
            reason=(
                f"weight_shift_above_threshold:{weight_shift_l1:.6f}"
                f">{float(max_weight_shift):.6f}"
            ),
            policy=effective_policy,
            diagnostics=diagnostics,
        )

    if require_online_kpis and not bool((guardrail_report or {}).get("data_complete")):
        return ActivationDecision(
            should_activate=False,
            reason="guardrail_data_missing",
            policy=effective_policy,
            diagnostics=diagnostics,
        )

    deltas = (guardrail_report or {}).get("deltas") or {}
    ctr_delta = float(deltas.get("ctr") or 0.0)
    apply_rate_delta = float(deltas.get("apply_rate") or 0.0)
    freshness_delta = float(deltas.get("freshness_seconds") or 0.0)
    latency_delta = float(deltas.get("latency_p95_ms") or 0.0)
    failure_delta = float(deltas.get("failure_rate") or 0.0)

    if ctr_delta > 0.0 and apply_rate_delta < -float(max_apply_rate_drop):
        return ActivationDecision(
            should_activate=False,
            reason=(
                f"guardrail_apply_rate_regression:{apply_rate_delta:.6f}"
                f"<{-float(max_apply_rate_drop):.6f}"
            ),
            policy=effective_policy,
            diagnostics=diagnostics,
        )

    if ctr_delta > 0.0 and freshness_delta > float(max_freshness_regression_seconds):
        return ActivationDecision(
            should_activate=False,
            reason=(
                f"guardrail_freshness_regression:{freshness_delta:.3f}"
                f">{float(max_freshness_regression_seconds):.3f}"
            ),
            policy=effective_policy,
            diagnostics=diagnostics,
        )

    if ctr_delta > 0.0 and latency_delta > float(max_latency_p95_regression_ms):
        return ActivationDecision(
            should_activate=False,
            reason=(
                f"guardrail_latency_regression:{latency_delta:.3f}"
                f">{float(max_latency_p95_regression_ms):.3f}"
            ),
            policy=effective_policy,
            diagnostics=diagnostics,
        )

    if ctr_delta > 0.0 and failure_delta > float(max_failure_rate_regression):
        return ActivationDecision(
            should_activate=False,
            reason=(
                f"guardrail_failure_rate_regression:{failure_delta:.6f}"
                f">{float(max_failure_rate_regression):.6f}"
            ),
            policy=effective_policy,
            diagnostics=diagnostics,
        )

    return ActivationDecision(
        should_activate=True,
        reason="activated",
        policy=effective_policy,
        diagnostics=diagnostics,
    )
