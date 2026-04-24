from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.core.config import settings
from app.models.mlops_incident import MlopsIncident
from app.models.model_drift_report import ModelDriftReport


def _now() -> datetime:
    return datetime.utcnow()


class MlopsIncidentService:
    async def create_from_drift_alert(
        self,
        *,
        report: ModelDriftReport,
        alert_payload: dict[str, Any],
    ) -> MlopsIncident:
        key = f"drift:{str(report.id)}"
        existing = await MlopsIncident.find_one(MlopsIncident.incident_key == key)
        if existing:
            return existing

        now = _now()
        review_due_hours = max(1, int(settings.MLOPS_INCIDENT_REVIEW_DUE_HOURS))
        incident = MlopsIncident(
            incident_key=key,
            source_type="drift_alert",
            source_id=str(report.id),
            report_id=str(report.id),
            model_version_id=report.model_version_id,
            severity=str(settings.MLOPS_ALERT_PAGERDUTY_SEVERITY or "error").strip().lower() or "error",
            status="open",
            owner=(settings.MLOPS_INCIDENT_DEFAULT_OWNER or "").strip() or None,
            title="MLOps Drift Alert",
            summary=(
                "Automated drift alert created from model monitoring. "
                "Add root cause and mitigation before resolving."
            ),
            review_due_at=now + timedelta(hours=review_due_hours),
            timeline=[
                {
                    "at": now.isoformat(),
                    "event": "incident_opened",
                    "message": "Incident auto-created from drift alert.",
                    "payload": {
                        "report_id": str(report.id),
                        "model_version_id": report.model_version_id,
                        "metrics": dict(report.metrics or {}),
                    },
                }
            ],
            action_items=[
                {"id": "impact-summary", "title": "Document blast radius and impacted surfaces", "done": False},
                {"id": "root-cause", "title": "Capture root-cause hypothesis and validation steps", "done": False},
                {"id": "mitigation-pr", "title": "Link mitigation PR(s) and deployment evidence", "done": False},
                {"id": "followup-issue", "title": "Create long-term prevention backlog issue", "done": False},
            ],
            metadata={
                "alert_payload": alert_payload,
                "incident_loop": "auto",
            },
            created_at=now,
            updated_at=now,
        )
        await incident.insert()
        return incident

    async def refresh_sla(self, incident: MlopsIncident) -> MlopsIncident:
        now = _now()
        breach_hours = max(1, int(settings.MLOPS_INCIDENT_BREACH_SLA_HOURS))
        breached = incident.status != "resolved" and incident.created_at <= (now - timedelta(hours=breach_hours))
        if bool(incident.breached_sla) != bool(breached):
            incident.breached_sla = bool(breached)
            incident.updated_at = now
            await incident.save()
        return incident

    async def append_timeline(
        self,
        *,
        incident: MlopsIncident,
        event: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> MlopsIncident:
        incident.timeline = list(incident.timeline or [])
        incident.timeline.append(
            {
                "at": _now().isoformat(),
                "event": str(event).strip().lower() or "update",
                "message": str(message).strip() or "updated",
                "payload": dict(payload or {}),
            }
        )
        incident.updated_at = _now()
        await incident.save()
        return incident


mlops_incident_service = MlopsIncidentService()
