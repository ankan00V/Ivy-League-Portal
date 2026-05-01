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
from app.models.assistant_audit_event import AssistantAuditEvent
from app.models.feature_store_row import FeatureStoreRow
from app.models.model_drift_report import ModelDriftReport
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.profile import Profile
from app.models.ranking_model_version import RankingModelVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.services.data_science_observability_service import data_science_observability_service


def _gate(name: str, passed: bool, detail: str, severity: str = "blocker") -> dict[str, Any]:
    return {"name": name, "pass": bool(passed), "detail": detail, "severity": severity}


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


async def _build_payload(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = await data_science_observability_service.operating_loop_snapshot(lookback_days=int(args.lookback_days))
    freshness = dict(snapshot.get("feature_freshness") or {})
    drift_rows = list(snapshot.get("drift") or [])
    parity = dict(snapshot.get("parity") or {})
    assistant = dict(snapshot.get("assistant_quality") or {})

    latest_drift = drift_rows[0] if drift_rows else {}
    latest_drift_metrics = dict(latest_drift.get("metrics") or {})
    online = dict(parity.get("online") or {})
    candidate = dict(online.get(args.candidate_mode) or {})
    baseline = dict(online.get(args.baseline_mode) or {})
    ctr_delta = _to_float(candidate.get("ctr")) - _to_float(baseline.get("ctr"))
    apply_delta = _to_float(candidate.get("apply_rate")) - _to_float(baseline.get("apply_rate"))

    gates = [
        _gate(
            "feature_freshness",
            freshness.get("freshness_seconds") is not None and _to_float(freshness.get("freshness_seconds")) <= float(args.max_feature_freshness_seconds),
            f"freshness_seconds={freshness.get('freshness_seconds')}, max={float(args.max_feature_freshness_seconds):.3f}",
        ),
        _gate(
            "model_input_drift",
            not bool(latest_drift.get("alert")),
            (
                f"alert={bool(latest_drift.get('alert'))}, "
                f"psi={latest_drift_metrics.get('query_bucket_psi')}, "
                f"max_z={latest_drift_metrics.get('max_feature_mean_z')}"
            ),
        ),
        _gate(
            "parity_min_impressions",
            int(candidate.get("impressions") or 0) >= int(args.min_real_impressions)
            and int(baseline.get("impressions") or 0) >= int(args.min_real_impressions),
            (
                f"candidate={int(candidate.get('impressions') or 0)}, "
                f"baseline={int(baseline.get('impressions') or 0)}, min={int(args.min_real_impressions)}"
            ),
        ),
        _gate(
            "parity_ctr_regression",
            ctr_delta >= -float(args.max_ctr_regression),
            f"delta={ctr_delta:.6f}, threshold={-float(args.max_ctr_regression):.6f}",
        ),
        _gate(
            "parity_apply_rate_regression",
            apply_delta >= -float(args.max_apply_rate_regression),
            f"delta={apply_delta:.6f}, threshold={-float(args.max_apply_rate_regression):.6f}",
        ),
        _gate(
            "assistant_failure_rate",
            _to_float(assistant.get("failure_rate")) <= float(args.max_assistant_failure_rate),
            f"failure_rate={_to_float(assistant.get('failure_rate')):.6f}, max={float(args.max_assistant_failure_rate):.6f}",
        ),
    ]
    return {
        "generated_at": utc_now().isoformat(),
        "lookback_days": int(args.lookback_days),
        "candidate_mode": args.candidate_mode,
        "baseline_mode": args.baseline_mode,
        "overall_ready": all(bool(gate["pass"]) for gate in gates),
        "gates": gates,
        "snapshot": snapshot,
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Run mandatory DS operating-loop release gates.")
    parser.add_argument("--lookback-days", type=int, default=settings.MLOPS_GUARDRAIL_LOOKBACK_DAYS)
    parser.add_argument("--candidate-mode", type=str, default="ml")
    parser.add_argument("--baseline-mode", type=str, default=settings.LEARNED_RANKER_STAGED_BASELINE_MODE)
    parser.add_argument("--max-feature-freshness-seconds", type=float, default=60.0 * settings.ANALYTICS_WAREHOUSE_MAX_STALENESS_MINUTES)
    parser.add_argument("--max-assistant-failure-rate", type=float, default=0.05)
    parser.add_argument("--max-ctr-regression", type=float, default=settings.MLOPS_PARITY_MAX_CTR_REGRESSION)
    parser.add_argument("--max-apply-rate-regression", type=float, default=settings.MLOPS_PARITY_MAX_APPLY_RATE_REGRESSION)
    parser.add_argument("--min-real-impressions", type=int, default=settings.MLOPS_PARITY_MIN_REAL_IMPRESSIONS_PER_MODE)
    parser.add_argument("--json-out", type=str, default="backend/benchmarks/ds_release_gates.json")
    parser.add_argument("--fail-on-not-ready", action="store_true")
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            AssistantAuditEvent,
            FeatureStoreRow,
            ModelDriftReport,
            Opportunity,
            OpportunityInteraction,
            Profile,
            RankingModelVersion,
            RankingRequestTelemetry,
        ],
    )
    try:
        payload = await _build_payload(args)
        out_path = Path(args.json_out)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ok", "overall_ready": payload["overall_ready"], "json": str(out_path)}, indent=2))
        if args.fail_on_not_ready and not payload["overall_ready"]:
            return 2
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
