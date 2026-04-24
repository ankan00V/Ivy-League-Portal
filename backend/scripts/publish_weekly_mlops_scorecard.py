from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.models.mlops_incident import MlopsIncident
from app.models.model_drift_report import ModelDriftReport
from app.models.ranking_model_version import RankingModelVersion


def _md_line(label: str, value: Any) -> str:
    return f"- {label}: **{value}**"


def _safe_float(value: Any, digits: int = 6) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "n/a"


async def _build_scorecard(*, days: int) -> dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=max(1, min(days, 90)))
    incidents = await MlopsIncident.find_many(MlopsIncident.created_at >= since).to_list()
    drift_reports = (
        await ModelDriftReport.find_many(ModelDriftReport.created_at >= since)
        .sort("-created_at")
        .to_list()
    )
    latest_model = await RankingModelVersion.find_many().sort("-created_at").limit(1).to_list()

    total_incidents = len(incidents)
    open_incidents = sum(1 for row in incidents if (row.status or "").strip().lower() != "resolved")
    breached_incidents = sum(1 for row in incidents if bool(row.breached_sla))
    drift_alerts = sum(1 for row in drift_reports if bool(row.alert))

    latest_drift = drift_reports[0] if drift_reports else None
    latest_model_row = latest_model[0] if latest_model else None

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "window_days": int(days),
        "window_start": since.isoformat(),
        "window_end": datetime.utcnow().isoformat(),
        "incidents": {
            "total": total_incidents,
            "open": open_incidents,
            "breached_sla": breached_incidents,
        },
        "drift_reports": {
            "total": len(drift_reports),
            "alerts": drift_alerts,
            "latest": {
                "id": str(latest_drift.id) if latest_drift else None,
                "alert": bool(latest_drift.alert) if latest_drift else None,
                "query_bucket_psi": (latest_drift.metrics or {}).get("query_bucket_psi") if latest_drift else None,
                "max_feature_mean_z": (latest_drift.metrics or {}).get("max_feature_mean_z") if latest_drift else None,
            },
        },
        "latest_model": {
            "id": str(latest_model_row.id) if latest_model_row else None,
            "active": bool(latest_model_row.is_active) if latest_model_row else None,
            "auc_gain_test": (latest_model_row.metrics or {}).get("auc_gain_test") if latest_model_row else None,
            "positive_rate": (latest_model_row.metrics or {}).get("positive_rate") if latest_model_row else None,
            "activation_reason": ((latest_model_row.lifecycle or {}).get("activation_reason") if latest_model_row else None),
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    incidents = payload.get("incidents") or {}
    drift = payload.get("drift_reports") or {}
    latest_drift = drift.get("latest") or {}
    latest_model = payload.get("latest_model") or {}
    lines = [
        "# Weekly MLOps Scorecard",
        "",
        _md_line("Generated At", payload.get("generated_at")),
        _md_line("Window (days)", payload.get("window_days")),
        "",
        "## Incident Loop",
        "",
        _md_line("Incidents (total)", incidents.get("total", 0)),
        _md_line("Incidents (open)", incidents.get("open", 0)),
        _md_line("Incidents (breached SLA)", incidents.get("breached_sla", 0)),
        "",
        "## Drift Monitoring",
        "",
        _md_line("Drift reports", drift.get("total", 0)),
        _md_line("Drift alerts", drift.get("alerts", 0)),
        _md_line("Latest drift report", latest_drift.get("id") or "n/a"),
        _md_line("Latest PSI", _safe_float(latest_drift.get("query_bucket_psi"))),
        _md_line("Latest max feature Z", _safe_float(latest_drift.get("max_feature_mean_z"))),
        "",
        "## Model Lifecycle",
        "",
        _md_line("Latest model", latest_model.get("id") or "n/a"),
        _md_line("Active", latest_model.get("active")),
        _md_line("AUC gain (test)", _safe_float(latest_model.get("auc_gain_test"))),
        _md_line("Positive rate", _safe_float(latest_model.get("positive_rate"))),
        _md_line("Activation reason", latest_model.get("activation_reason") or "n/a"),
        "",
    ]
    return "\n".join(lines)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Publish a weekly MLOps scorecard markdown + json artifact.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--markdown-out",
        type=str,
        default="docs/portfolio/weekly_mlops_scorecard.md",
    )
    parser.add_argument(
        "--json-out",
        type=str,
        default="backend/benchmarks/weekly_mlops_scorecard.json",
    )
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[MlopsIncident, ModelDriftReport, RankingModelVersion],
    )
    try:
        payload = await _build_scorecard(days=max(1, min(int(args.days), 90)))
        markdown = _render_markdown(payload)

        markdown_path = Path(args.markdown_out)
        if not markdown_path.is_absolute():
            markdown_path = REPO_ROOT / markdown_path
        json_path = Path(args.json_out)
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
                    "window_days": int(args.days),
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
