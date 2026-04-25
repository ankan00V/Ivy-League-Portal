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
from app.services.mlops.incident_service import mlops_incident_service


def _render_markdown(payload: dict[str, Any]) -> str:
    summary = dict(payload.get("summary") or {})
    violations = list(payload.get("violations") or [])
    lines = [
        "# Incident Review SLA Audit",
        "",
        f"- Generated At: **{payload.get('generated_at')}**",
        f"- Window (days): **{payload.get('window_days')}**",
        f"- Incidents scanned: **{int(summary.get('incidents_scanned') or 0):,}**",
        f"- Overdue reviews: **{int(summary.get('overdue_reviews') or 0):,}**",
        f"- Breached SLA incidents: **{int(summary.get('breached_sla') or 0):,}**",
        "",
    ]
    if violations:
        lines.extend(
            [
                "## Violations",
                "",
                "| incident_key | status | owner | review_due_at | breached_sla |",
                "|---|---|---|---|---|",
            ]
        )
        for row in violations:
            lines.append(
                "| "
                f"`{row.get('incident_key')}` | "
                f"{row.get('status')} | "
                f"{row.get('owner') or 'unassigned'} | "
                f"{row.get('review_due_at') or 'n/a'} | "
                f"{row.get('breached_sla')} |"
            )
    else:
        lines.append("No review or SLA violations detected.")
    lines.append("")
    return "\n".join(lines)


async def _build_payload(*, days: int) -> dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=max(1, min(int(days), 90)))
    incidents = await MlopsIncident.find_many(MlopsIncident.created_at >= since).sort("-created_at").to_list()

    violations: list[dict[str, Any]] = []
    overdue_reviews = 0
    breached_sla = 0
    now = datetime.utcnow()
    for incident in incidents:
        incident = await mlops_incident_service.refresh_sla(incident)
        review_due_at = incident.review_due_at
        review_overdue = bool(review_due_at and incident.status != "resolved" and review_due_at < now)
        breached = bool(incident.breached_sla)
        if review_overdue:
            overdue_reviews += 1
        if breached:
            breached_sla += 1
        if review_overdue or breached:
            violations.append(
                {
                    "incident_key": incident.incident_key,
                    "status": incident.status,
                    "owner": incident.owner,
                    "review_due_at": review_due_at.isoformat() if review_due_at else None,
                    "breached_sla": breached,
                }
            )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "window_days": int(days),
        "summary": {
            "incidents_scanned": len(incidents),
            "overdue_reviews": overdue_reviews,
            "breached_sla": breached_sla,
        },
        "violations": violations,
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Audit unresolved MLOps incidents against review and SLA deadlines.")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--fail-on-breach", action="store_true")
    parser.add_argument(
        "--markdown-out",
        type=str,
        default="docs/portfolio/incident_review_sla_audit.md",
    )
    parser.add_argument(
        "--json-out",
        type=str,
        default="backend/benchmarks/incident_review_sla_audit.json",
    )
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[MlopsIncident],
    )
    try:
        payload = await _build_payload(days=max(1, min(int(args.days), 90)))
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

        violations = list(payload.get("violations") or [])
        print(
            json.dumps(
                {
                    "status": "ok",
                    "markdown": str(markdown_path),
                    "json": str(json_path),
                    "violations": len(violations),
                },
                indent=2,
                sort_keys=True,
            )
        )

        if args.fail_on_breach and violations:
            return 1
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
