from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.traffic import matches_traffic_type
from app.services.interaction_service import interaction_service
from app.core.time import utc_now


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (max(0.0, min(100.0, q)) / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


class RolloutGuardrailService:
    def _matches_traffic_type(self, *, value: str | None, traffic_type: str) -> bool:
        # Blank traffic_type is unknown provenance, not real. See models/traffic.py.
        return matches_traffic_type(value, traffic_type)

    async def _mode_request_metrics(
        self, *, mode: str, days: int, traffic_type: str = "real"
    ) -> dict[str, float]:
        since = utc_now() - timedelta(days=max(1, min(int(days), 365)))
        rows = await RankingRequestTelemetry.find_many(
            RankingRequestTelemetry.created_at >= since,
            RankingRequestTelemetry.ranking_mode == mode,
        ).to_list()
        rows = [
            row
            for row in rows
            if self._matches_traffic_type(
                value=getattr(row, "traffic_type", None),
                traffic_type=traffic_type,
            )
        ]
        if not rows:
            return {
                "requests": 0.0,
                "success_rate": 0.0,
                "failure_rate": 0.0,
                "latency_p95_ms": 0.0,
                "freshness_seconds": 0.0,
            }

        latency_values = [float(row.latency_ms or 0.0) for row in rows if row.success]
        freshness_values = [float(row.freshness_seconds or 0.0) for row in rows if row.success and row.freshness_seconds is not None]
        success_count = sum(1 for row in rows if row.success)
        total = float(len(rows))
        failure_rate = 1.0 - (success_count / total)
        return {
            "requests": total,
            "success_rate": float(success_count / total),
            "failure_rate": float(failure_rate),
            "latency_p95_ms": _percentile(latency_values, 95.0),
            "freshness_seconds": float(sum(freshness_values) / len(freshness_values)) if freshness_values else 0.0,
        }

    async def compare(
        self,
        *,
        candidate_mode: str,
        baseline_mode: str,
        days: int = 30,
        traffic_type: str = "real",
    ) -> dict[str, Any]:
        """Compare two ranking modes over one traffic population.

        `traffic_type` decides whose behaviour is being measured. "real" is the only
        value that says anything about the product; "simulated" measures a seeded
        fixture and is for verifying that this machinery computes correctly in CI.
        Callers must carry the value through to whatever they publish, so a reader
        can never mistake a fixture run for a measurement of real students.
        """
        interaction_rows = await interaction_service.ctr_by_mode(days=days, traffic_type=traffic_type)
        interaction_map = {str(row.get("mode") or ""): row for row in interaction_rows}
        candidate_interactions = interaction_map.get(candidate_mode) or {}
        baseline_interactions = interaction_map.get(baseline_mode) or {}
        candidate_requests = await self._mode_request_metrics(
            mode=candidate_mode, days=days, traffic_type=traffic_type
        )
        baseline_requests = await self._mode_request_metrics(
            mode=baseline_mode, days=days, traffic_type=traffic_type
        )

        data_complete = bool(
            candidate_interactions
            and baseline_interactions
            and candidate_requests.get("requests", 0.0) > 0
            and baseline_requests.get("requests", 0.0) > 0
        )
        deltas = {
            "ctr": float(candidate_interactions.get("ctr") or 0.0) - float(baseline_interactions.get("ctr") or 0.0),
            "apply_rate": float(candidate_interactions.get("apply_rate") or 0.0)
            - float(baseline_interactions.get("apply_rate") or 0.0),
            "freshness_seconds": float(candidate_requests.get("freshness_seconds") or 0.0)
            - float(baseline_requests.get("freshness_seconds") or 0.0),
            "latency_p95_ms": float(candidate_requests.get("latency_p95_ms") or 0.0)
            - float(baseline_requests.get("latency_p95_ms") or 0.0),
            "failure_rate": float(candidate_requests.get("failure_rate") or 0.0)
            - float(baseline_requests.get("failure_rate") or 0.0),
        }
        return {
            "days": int(max(1, min(int(days), 365))),
            # Provenance travels with the numbers. Anything that renders this
            # payload must surface it, or a fixture run reads as a real result.
            "traffic_type": (traffic_type or "real").strip().lower(),
            "candidate_mode": candidate_mode,
            "baseline_mode": baseline_mode,
            "candidate": {
                **candidate_interactions,
                **candidate_requests,
            },
            "baseline": {
                **baseline_interactions,
                **baseline_requests,
            },
            "deltas": deltas,
            "data_complete": data_complete,
        }


rollout_guardrail_service = RolloutGuardrailService()
