from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.time import utc_now
from app.models.experiment import Experiment
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.services.mlops.rollout_guardrail_service import rollout_guardrail_service


def _gate(value: bool, *, name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "pass": bool(value), "detail": detail}


def _round(value: Any, digits: int = 6) -> float:
    try:
        return round(float(value), digits)
    except Exception:
        return 0.0


async def _mode_readiness(*, candidate_mode: str, baseline_mode: str, days: int) -> dict[str, Any]:
    report = await rollout_guardrail_service.compare(
        candidate_mode=candidate_mode,
        baseline_mode=baseline_mode,
        days=days,
    )
    candidate = dict(report.get("candidate") or {})
    baseline = dict(report.get("baseline") or {})
    deltas = dict(report.get("deltas") or {})

    min_impressions = int(max(0, settings.MLOPS_PARITY_MIN_REAL_IMPRESSIONS_PER_MODE))
    min_requests = int(max(0, settings.MLOPS_PARITY_MIN_REAL_REQUESTS_PER_MODE))
    max_ctr_regression = float(max(0.0, settings.MLOPS_PARITY_MAX_CTR_REGRESSION))
    max_apply_regression = float(max(0.0, settings.MLOPS_PARITY_MAX_APPLY_RATE_REGRESSION))

    candidate_impressions = int(candidate.get("impressions") or 0)
    baseline_impressions = int(baseline.get("impressions") or 0)
    candidate_requests = int(candidate.get("requests") or 0)
    baseline_requests = int(baseline.get("requests") or 0)
    ctr_delta = float(deltas.get("ctr") or 0.0)
    apply_delta = float(deltas.get("apply_rate") or 0.0)

    gates = [
        _gate(
            candidate_impressions >= min_impressions and baseline_impressions >= min_impressions,
            name="min_real_impressions",
            detail=(
                f"candidate={candidate_impressions}, baseline={baseline_impressions}, "
                f"required={min_impressions}"
            ),
        ),
        _gate(
            candidate_requests >= min_requests and baseline_requests >= min_requests,
            name="min_real_requests",
            detail=f"candidate={candidate_requests}, baseline={baseline_requests}, required={min_requests}",
        ),
        _gate(
            ctr_delta >= -max_ctr_regression,
            name="ctr_regression_guardrail",
            detail=f"delta={_round(ctr_delta)}, threshold={-_round(max_ctr_regression)}",
        ),
        _gate(
            apply_delta >= -max_apply_regression,
            name="apply_rate_regression_guardrail",
            detail=f"delta={_round(apply_delta)}, threshold={-_round(max_apply_regression)}",
        ),
    ]

    return {
        "candidate_mode": candidate_mode,
        "baseline_mode": baseline_mode,
        "ready": all(bool(item["pass"]) for item in gates),
        "gates": gates,
        "candidate": {
            "impressions": candidate_impressions,
            "requests": candidate_requests,
            "ctr": _round(candidate.get("ctr")),
            "apply_rate": _round(candidate.get("apply_rate")),
            "latency_p95_ms": _round(candidate.get("latency_p95_ms")),
            "failure_rate": _round(candidate.get("failure_rate")),
        },
        "baseline": {
            "impressions": baseline_impressions,
            "requests": baseline_requests,
            "ctr": _round(baseline.get("ctr")),
            "apply_rate": _round(baseline.get("apply_rate")),
            "latency_p95_ms": _round(baseline.get("latency_p95_ms")),
            "failure_rate": _round(baseline.get("failure_rate")),
        },
        "deltas": {
            "ctr": _round(ctr_delta),
            "apply_rate": _round(apply_delta),
            "latency_p95_ms": _round(deltas.get("latency_p95_ms")),
            "failure_rate": _round(deltas.get("failure_rate")),
            "freshness_seconds": _round(deltas.get("freshness_seconds")),
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Real Traffic Rollout Readiness",
        "",
        f"- Generated At: **{payload.get('generated_at')}**",
        f"- Window (days): **{payload.get('window_days')}**",
        f"- Overall Ready: **{payload.get('overall_ready')}**",
        "",
    ]
    for item in payload.get("modes", []):
        lines.extend(
            [
                f"## {item.get('candidate_mode')} vs {item.get('baseline_mode')}",
                "",
                f"- Ready: **{item.get('ready')}**",
                f"- Candidate impressions/requests: **{item.get('candidate', {}).get('impressions')} / {item.get('candidate', {}).get('requests')}**",
                f"- Baseline impressions/requests: **{item.get('baseline', {}).get('impressions')} / {item.get('baseline', {}).get('requests')}**",
                f"- CTR delta: **{item.get('deltas', {}).get('ctr')}**",
                f"- Apply-rate delta: **{item.get('deltas', {}).get('apply_rate')}**",
                "",
                "### Gates",
                "",
            ]
        )
        for gate in item.get("gates", []):
            status = "PASS" if gate.get("pass") else "FAIL"
            lines.append(f"- `{status}` {gate.get('name')}: {gate.get('detail')}")
        lines.append("")
    return "\n".join(lines)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Check real-traffic rollout readiness gates.")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument(
        "--json-out",
        type=str,
        default="backend/benchmarks/real_traffic_rollout_readiness.json",
    )
    parser.add_argument(
        "--markdown-out",
        type=str,
        default="docs/portfolio/real_traffic_rollout_readiness.md",
    )
    parser.add_argument("--fail-on-not-ready", action="store_true")
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[Experiment, OpportunityInteraction, RankingRequestTelemetry],
    )
    try:
        days = max(1, min(int(args.days), 90))
        modes = [
            await _mode_readiness(candidate_mode="semantic", baseline_mode="baseline", days=days),
            await _mode_readiness(candidate_mode="ml", baseline_mode="baseline", days=days),
        ]
        payload = {
            "generated_at": utc_now().isoformat(),
            "window_days": days,
            "overall_ready": all(bool(item.get("ready")) for item in modes),
            "modes": modes,
            "parity_thresholds": {
                "min_real_impressions_per_mode": int(settings.MLOPS_PARITY_MIN_REAL_IMPRESSIONS_PER_MODE),
                "min_real_requests_per_mode": int(settings.MLOPS_PARITY_MIN_REAL_REQUESTS_PER_MODE),
                "max_ctr_regression": float(settings.MLOPS_PARITY_MAX_CTR_REGRESSION),
                "max_apply_rate_regression": float(settings.MLOPS_PARITY_MAX_APPLY_RATE_REGRESSION),
            },
        }

        json_path = Path(args.json_out)
        if not json_path.is_absolute():
            json_path = REPO_ROOT / json_path
        md_path = Path(args.markdown_out)
        if not md_path.is_absolute():
            md_path = REPO_ROOT / md_path
        json_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        md_path.write_text(_render_markdown(payload), encoding="utf-8")

        print(json.dumps({"status": "ok", "overall_ready": payload["overall_ready"]}, indent=2))
        if args.fail_on_not_ready and not payload["overall_ready"]:
            return 2
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
