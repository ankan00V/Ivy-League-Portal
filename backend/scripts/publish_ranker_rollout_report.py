from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import timedelta
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
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_model_version import RankingModelVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.services.mlops.rollout_guardrail_service import rollout_guardrail_service
from app.services.ranking_model_service import ranking_model_service


def _safe_float(value: Any, digits: int = 6) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "n/a"


def _guardrail_failure(report: dict[str, Any]) -> tuple[bool, list[str]]:
    if not bool(report.get("data_complete")):
        return False, []
    deltas = dict(report.get("deltas") or {})
    reasons: list[str] = []
    if float(deltas.get("ctr") or 0.0) < -float(settings.MLOPS_PARITY_MAX_CTR_REGRESSION):
        reasons.append("ctr_regression")
    if float(deltas.get("apply_rate") or 0.0) < -float(settings.MLOPS_PARITY_MAX_APPLY_RATE_REGRESSION):
        reasons.append("apply_rate_regression")
    if float(deltas.get("freshness_seconds") or 0.0) > float(settings.MLOPS_GUARDRAIL_MAX_FRESHNESS_REGRESSION_SECONDS):
        reasons.append("freshness_regression")
    if float(deltas.get("latency_p95_ms") or 0.0) > float(settings.MLOPS_GUARDRAIL_MAX_LATENCY_P95_REGRESSION_MS):
        reasons.append("latency_regression")
    if float(deltas.get("failure_rate") or 0.0) > float(settings.MLOPS_GUARDRAIL_MAX_FAILURE_RATE_REGRESSION):
        reasons.append("failure_rate_regression")
    return bool(reasons), reasons


async def _build_report(*, days: int) -> dict[str, Any]:
    since = utc_now() - timedelta(days=max(1, min(int(days), 30)))
    baseline_mode = str(settings.LEARNED_RANKER_STAGED_BASELINE_MODE or "semantic").strip().lower() or "semantic"

    active_model = await RankingModelVersion.find_one(RankingModelVersion.is_active == True)  # noqa: E712
    challenger_rows = (
        await RankingModelVersion.find_many(RankingModelVersion.is_active == False)  # noqa: E712
        .sort("-created_at")
        .limit(1)
        .to_list()
    )
    challenger = challenger_rows[0] if challenger_rows else None

    telemetry_rows = await RankingRequestTelemetry.find_many(
        RankingRequestTelemetry.created_at >= since,
    ).to_list()
    real_rows = [
        row
        for row in telemetry_rows
        if str(getattr(row, "traffic_type", "real") or "real").strip().lower() in {"", "real"}
    ]
    shadow_rows = [row for row in real_rows if int(getattr(row, "shadow_candidate_count", 0) or 0) > 0]
    rollout_rows = [row for row in real_rows if getattr(row, "rollout_variant", None)]

    served_modes = Counter(str(getattr(row, "ranking_mode", "unknown") or "unknown") for row in real_rows)
    rollout_variants = Counter(str(getattr(row, "rollout_variant", "none") or "none") for row in rollout_rows)
    shadow_modes = Counter(str(getattr(row, "shadow_mode", "none") or "none") for row in shadow_rows)

    guardrail_report = await rollout_guardrail_service.compare(
        candidate_mode="ml",
        baseline_mode=baseline_mode,
        days=days,
    )
    rollback_recommended, rollback_reasons = _guardrail_failure(guardrail_report)

    return {
        "generated_at": utc_now().isoformat(),
        "window_days": int(days),
        "baseline_mode": baseline_mode,
        "active_model": None
        if active_model is None
        else {
            "id": str(active_model.id),
            "name": active_model.name,
            "created_at": active_model.created_at.isoformat(),
            "metrics": dict(active_model.metrics or {}),
            "lifecycle": dict(active_model.lifecycle or {}),
        },
        "challenger_model": None
        if challenger is None
        else {
            "id": str(challenger.id),
            "name": challenger.name,
            "created_at": challenger.created_at.isoformat(),
            "metrics": dict(challenger.metrics or {}),
            "lifecycle": dict(challenger.lifecycle or {}),
        },
        "request_telemetry": {
            "real_requests": len(real_rows),
            "shadow_covered_requests": len(shadow_rows),
            "rollout_requests": len(rollout_rows),
            "served_modes": dict(sorted(served_modes.items())),
            "rollout_variants": dict(sorted(rollout_variants.items())),
            "shadow_modes": dict(sorted(shadow_modes.items())),
        },
        "guardrails": guardrail_report,
        "rollback_recommended": rollback_recommended,
        "rollback_reasons": rollback_reasons,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    active_model = payload.get("active_model") or {}
    challenger_model = payload.get("challenger_model") or {}
    telemetry = payload.get("request_telemetry") or {}
    guardrails = payload.get("guardrails") or {}
    deltas = dict(guardrails.get("deltas") or {})
    lines = [
        "# Learned Ranker Rollout Report",
        "",
        f"- Generated At: **{payload.get('generated_at')}**",
        f"- Window (days): **{payload.get('window_days')}**",
        f"- Baseline Mode: **{payload.get('baseline_mode')}**",
        "",
        "## Champion / Challenger",
        "",
        f"- Active model: **{active_model.get('name') or 'n/a'}** (`{active_model.get('id') or 'n/a'}`)",
        f"- Active AUC gain (test): **{_safe_float((active_model.get('metrics') or {}).get('auc_gain_test') or (active_model.get('metrics') or {}).get('auc_gain'))}**",
        f"- Challenger model: **{challenger_model.get('name') or 'n/a'}** (`{challenger_model.get('id') or 'n/a'}`)",
        f"- Challenger AUC gain (test): **{_safe_float((challenger_model.get('metrics') or {}).get('auc_gain_test') or (challenger_model.get('metrics') or {}).get('auc_gain'))}**",
        "",
        "## Live Rollout Telemetry",
        "",
        f"- Real requests: **{int(telemetry.get('real_requests') or 0):,}**",
        f"- Shadow-covered requests: **{int(telemetry.get('shadow_covered_requests') or 0):,}**",
        f"- Rollout requests: **{int(telemetry.get('rollout_requests') or 0):,}**",
        f"- Served modes: **{json.dumps(telemetry.get('served_modes') or {}, sort_keys=True)}**",
        f"- Rollout variants: **{json.dumps(telemetry.get('rollout_variants') or {}, sort_keys=True)}**",
        f"- Shadow modes: **{json.dumps(telemetry.get('shadow_modes') or {}, sort_keys=True)}**",
        "",
        "## Guardrails",
        "",
        f"- Data complete: **{bool(guardrails.get('data_complete'))}**",
        f"- CTR delta: **{_safe_float(deltas.get('ctr'))}**",
        f"- Apply-rate delta: **{_safe_float(deltas.get('apply_rate'))}**",
        f"- Freshness delta (seconds): **{_safe_float(deltas.get('freshness_seconds'))}**",
        f"- Latency p95 delta (ms): **{_safe_float(deltas.get('latency_p95_ms'))}**",
        f"- Failure-rate delta: **{_safe_float(deltas.get('failure_rate'))}**",
        f"- Rollback recommended: **{bool(payload.get('rollback_recommended'))}**",
        f"- Rollback reasons: **{', '.join(payload.get('rollback_reasons') or []) or 'none'}**",
        "",
    ]
    return "\n".join(lines)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Publish learned-ranker rollout telemetry and champion/challenger report.")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument(
        "--markdown-out",
        type=str,
        default="docs/portfolio/learned_ranker_rollout_report.md",
    )
    parser.add_argument(
        "--json-out",
        type=str,
        default="backend/benchmarks/learned_ranker_rollout_report.json",
    )
    parser.add_argument(
        "--rollback-on-fail",
        action="store_true",
        help="Roll back to the previously active model if live guardrails recommend rollback.",
    )
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[RankingModelVersion, RankingRequestTelemetry, OpportunityInteraction],
    )
    try:
        payload = await _build_report(days=max(1, min(int(args.days), 30)))

        rollback_performed = False
        rollback_error: str | None = None
        if args.rollback_on_fail and bool(payload.get("rollback_recommended")) and settings.LEARNED_RANKER_ROLLBACK_ON_GUARDRAIL_FAILURE:
            try:
                rolled_back = await ranking_model_service.rollback()
                rollback_performed = True
                payload["rollback_performed"] = {
                    "id": str(rolled_back.id),
                    "name": rolled_back.name,
                }
            except Exception as exc:
                rollback_error = str(exc)
                payload["rollback_error"] = rollback_error

        markdown = _render_markdown(payload)

        markdown_path = Path(args.markdown_out)
        json_path = Path(args.json_out)
        if not markdown_path.is_absolute():
            markdown_path = REPO_ROOT / markdown_path
        if not json_path.is_absolute():
            json_path = REPO_ROOT / json_path
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

        print(
            json.dumps(
                {
                    "status": "ok",
                    "markdown": str(markdown_path),
                    "json": str(json_path),
                    "rollback_performed": rollback_performed,
                    "rollback_error": rollback_error,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
