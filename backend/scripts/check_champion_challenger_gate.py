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
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.ranking_model_version import RankingModelVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.services.mlops.rollout_guardrail_service import rollout_guardrail_service


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _model_auc_gain(model: RankingModelVersion | None) -> float:
    if model is None:
        return 0.0
    metrics = dict(model.metrics or {})
    if metrics.get("auc_gain_test") is not None:
        return _to_float(metrics.get("auc_gain_test"))
    return _to_float(metrics.get("auc_gain"))


def _model_to_dict(model: RankingModelVersion | None) -> dict[str, Any] | None:
    if model is None:
        return None
    return {
        "id": str(model.id),
        "name": model.name,
        "is_active": bool(model.is_active),
        "created_at": model.created_at.isoformat(),
        "training_rows": _to_int(model.training_rows),
        "auc_gain": _model_auc_gain(model),
        "metrics": dict(model.metrics or {}),
        "lifecycle": dict(model.lifecycle or {}),
    }


def _gate(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "pass": bool(passed), "detail": detail}


def _render_markdown(payload: dict[str, Any]) -> str:
    champion = payload.get("champion") or {}
    challenger = payload.get("challenger") or {}
    parity = payload.get("parity") or {}
    deltas = dict(parity.get("deltas") or {})
    lines = [
        "# Champion Challenger Gate",
        "",
        f"- Generated At: **{payload.get('generated_at')}**",
        f"- Window (days): **{payload.get('window_days')}**",
        f"- Overall Ready: **{payload.get('overall_ready')}**",
        "",
        "## Models",
        "",
        f"- Champion: **{champion.get('name') or 'n/a'}** (`{champion.get('id') or 'n/a'}`)",
        f"- Champion AUC gain: **{_to_float(champion.get('auc_gain')):.6f}**",
        f"- Challenger: **{challenger.get('name') or 'n/a'}** (`{challenger.get('id') or 'n/a'}`)",
        f"- Challenger AUC gain: **{_to_float(challenger.get('auc_gain')):.6f}**",
        "",
        "## Live Parity Snapshot",
        "",
        f"- Baseline mode: **{payload.get('baseline_mode')}**",
        f"- Candidate mode: **{payload.get('candidate_mode')}**",
        f"- Candidate requests: **{_to_int((parity.get('candidate') or {}).get('requests'))}**",
        f"- Baseline requests: **{_to_int((parity.get('baseline') or {}).get('requests'))}**",
        f"- Candidate impressions: **{_to_int((parity.get('candidate') or {}).get('impressions'))}**",
        f"- Baseline impressions: **{_to_int((parity.get('baseline') or {}).get('impressions'))}**",
        f"- CTR delta: **{_to_float(deltas.get('ctr')):.6f}**",
        f"- Apply-rate delta: **{_to_float(deltas.get('apply_rate')):.6f}**",
        f"- Latency p95 delta (ms): **{_to_float(deltas.get('latency_p95_ms')):.6f}**",
        f"- Failure-rate delta: **{_to_float(deltas.get('failure_rate')):.6f}**",
        "",
        "## Gates",
        "",
    ]
    for gate in payload.get("gates") or []:
        status = "PASS" if gate.get("pass") else "FAIL"
        lines.append(f"- `{status}` {gate.get('name')}: {gate.get('detail')}")
    lines.append("")
    return "\n".join(lines)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Run champion/challenger and live parity blocking gates.")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument(
        "--json-out",
        type=str,
        default="backend/benchmarks/champion_challenger_gate.json",
    )
    parser.add_argument(
        "--markdown-out",
        type=str,
        default="docs/portfolio/champion_challenger_gate.md",
    )
    parser.add_argument("--fail-on-not-ready", action="store_true")
    args = parser.parse_args()

    days = max(1, min(int(args.days), 90))
    baseline_mode = str(settings.LEARNED_RANKER_STAGED_BASELINE_MODE or "semantic").strip().lower() or "semantic"

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[RankingModelVersion, OpportunityInteraction, RankingRequestTelemetry],
    )
    try:
        champion = await RankingModelVersion.find_one(RankingModelVersion.is_active == True)  # noqa: E712
        challenger_rows = (
            await RankingModelVersion.find_many(RankingModelVersion.is_active == False)  # noqa: E712
            .sort("-created_at")
            .limit(1)
            .to_list()
        )
        challenger = challenger_rows[0] if challenger_rows else None

        champion_auc = _model_auc_gain(champion)
        challenger_auc = _model_auc_gain(challenger)
        auc_delta = challenger_auc - champion_auc
        required_auc_delta = _to_float(settings.MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN)

        parity = await rollout_guardrail_service.compare(
            candidate_mode="ml",
            baseline_mode=baseline_mode,
            days=days,
        )
        candidate = dict(parity.get("candidate") or {})
        baseline = dict(parity.get("baseline") or {})
        deltas = dict(parity.get("deltas") or {})

        min_impressions = _to_int(settings.MLOPS_PARITY_MIN_REAL_IMPRESSIONS_PER_MODE)
        min_requests = _to_int(settings.MLOPS_PARITY_MIN_REAL_REQUESTS_PER_MODE)
        max_ctr_regression = _to_float(settings.MLOPS_PARITY_MAX_CTR_REGRESSION)
        max_apply_regression = _to_float(settings.MLOPS_PARITY_MAX_APPLY_RATE_REGRESSION)
        max_latency_regression_ms = _to_float(settings.MLOPS_GUARDRAIL_MAX_LATENCY_P95_REGRESSION_MS)
        max_failure_regression = _to_float(settings.MLOPS_GUARDRAIL_MAX_FAILURE_RATE_REGRESSION)
        max_freshness_regression = _to_float(settings.MLOPS_GUARDRAIL_MAX_FRESHNESS_REGRESSION_SECONDS)

        gates = [
            _gate("champion_exists", champion is not None, "Active champion model must exist."),
            _gate("challenger_exists", challenger is not None, "Latest non-active challenger model must exist."),
            _gate(
                "challenger_offline_auc_gain",
                challenger is not None and auc_delta >= required_auc_delta,
                f"auc_delta={auc_delta:.6f}, required>={required_auc_delta:.6f}",
            ),
            _gate(
                "min_real_impressions",
                _to_int(candidate.get("impressions")) >= min_impressions
                and _to_int(baseline.get("impressions")) >= min_impressions,
                (
                    f"candidate={_to_int(candidate.get('impressions'))}, "
                    f"baseline={_to_int(baseline.get('impressions'))}, required={min_impressions}"
                ),
            ),
            _gate(
                "min_real_requests",
                _to_int(candidate.get("requests")) >= min_requests
                and _to_int(baseline.get("requests")) >= min_requests,
                (
                    f"candidate={_to_int(candidate.get('requests'))}, "
                    f"baseline={_to_int(baseline.get('requests'))}, required={min_requests}"
                ),
            ),
            _gate(
                "ctr_guardrail",
                _to_float(deltas.get("ctr")) >= -max_ctr_regression,
                f"delta={_to_float(deltas.get('ctr')):.6f}, threshold={-max_ctr_regression:.6f}",
            ),
            _gate(
                "apply_rate_guardrail",
                _to_float(deltas.get("apply_rate")) >= -max_apply_regression,
                f"delta={_to_float(deltas.get('apply_rate')):.6f}, threshold={-max_apply_regression:.6f}",
            ),
            _gate(
                "latency_guardrail",
                _to_float(deltas.get("latency_p95_ms")) <= max_latency_regression_ms,
                f"delta={_to_float(deltas.get('latency_p95_ms')):.6f}, threshold<={max_latency_regression_ms:.6f}",
            ),
            _gate(
                "failure_rate_guardrail",
                _to_float(deltas.get("failure_rate")) <= max_failure_regression,
                f"delta={_to_float(deltas.get('failure_rate')):.6f}, threshold<={max_failure_regression:.6f}",
            ),
            _gate(
                "freshness_guardrail",
                _to_float(deltas.get("freshness_seconds")) <= max_freshness_regression,
                f"delta={_to_float(deltas.get('freshness_seconds')):.6f}, threshold<={max_freshness_regression:.6f}",
            ),
        ]

        payload = {
            "generated_at": utc_now().isoformat(),
            "window_days": days,
            "baseline_mode": baseline_mode,
            "candidate_mode": "ml",
            "overall_ready": all(bool(gate.get("pass")) for gate in gates),
            "champion": _model_to_dict(champion),
            "challenger": _model_to_dict(challenger),
            "auc_delta": auc_delta,
            "required_auc_delta": required_auc_delta,
            "parity": parity,
            "gates": gates,
        }

        json_path = Path(args.json_out)
        markdown_path = Path(args.markdown_out)
        if not json_path.is_absolute():
            json_path = REPO_ROOT / json_path
        if not markdown_path.is_absolute():
            markdown_path = REPO_ROOT / markdown_path
        json_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)

        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        markdown_path.write_text(_render_markdown(payload), encoding="utf-8")

        print(json.dumps({"status": "ok", "overall_ready": payload["overall_ready"]}, indent=2))
        if args.fail_on_not_ready and not payload["overall_ready"]:
            return 2
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
