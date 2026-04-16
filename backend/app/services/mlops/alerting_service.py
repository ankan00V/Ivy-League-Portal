from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import requests

from app.core.config import settings
from app.models.model_drift_report import ModelDriftReport


class MlopsAlertingService:
    async def _is_within_cooldown(self, *, current_report_id: str) -> tuple[bool, str | None]:
        cooldown_minutes = max(0, int(settings.MLOPS_ALERT_COOLDOWN_MINUTES))
        if cooldown_minutes <= 0:
            return False, None

        cutoff = datetime.utcnow() - timedelta(minutes=cooldown_minutes)
        recent = (
            await ModelDriftReport.find_many(
                ModelDriftReport.alert == True,  # noqa: E712
                ModelDriftReport.alert_notified_at >= cutoff,
            )
            .sort("-alert_notified_at")
            .limit(1)
            .to_list()
        )
        if not recent:
            return False, None

        latest = recent[0]
        if str(latest.id) == current_report_id:
            return False, None

        return True, str(latest.id)

    async def notify_drift_alert(self, *, report: ModelDriftReport) -> dict[str, Any]:
        if not report.alert:
            return {"status": "skipped", "reason": "report_not_alerting"}

        if report.alert_notified_at is not None:
            return {
                "status": "skipped",
                "reason": "already_notified",
                "alert_notified_at": report.alert_notified_at.isoformat(),
            }

        if not settings.MLOPS_ALERTS_ENABLED:
            return {"status": "disabled", "reason": "alerts_disabled"}

        within_cooldown, recent_report_id = await self._is_within_cooldown(current_report_id=str(report.id))
        if within_cooldown:
            return {
                "status": "suppressed",
                "reason": "cooldown",
                "recent_report_id": recent_report_id,
                "cooldown_minutes": int(settings.MLOPS_ALERT_COOLDOWN_MINUTES),
            }

        metrics = report.metrics or {}
        payload: dict[str, Any] = {
            "event": "mlops.drift.alert",
            "reported_at": datetime.utcnow().isoformat(),
            "report_id": str(report.id),
            "model_version_id": report.model_version_id,
            "window_start": report.window_start.isoformat(),
            "window_end": report.window_end.isoformat(),
            "metrics": {
                "impressions": metrics.get("impressions"),
                "query_bucket_psi": metrics.get("query_bucket_psi"),
                "psi_alert_threshold": metrics.get("psi_alert_threshold"),
                "max_feature_mean_z": metrics.get("max_feature_mean_z"),
                "z_alert_threshold": metrics.get("z_alert_threshold"),
                "feature_mean_z": metrics.get("feature_mean_z"),
            },
        }

        webhook_url = (settings.MLOPS_ALERT_WEBHOOK_URL or "").strip()
        webhook_sent = False
        if webhook_url:
            timeout = max(1.0, float(settings.MLOPS_ALERT_WEBHOOK_TIMEOUT_SECONDS))
            try:
                response = await asyncio.to_thread(
                    requests.post,
                    webhook_url,
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                webhook_sent = True
            except Exception as exc:
                raise RuntimeError(f"webhook_delivery_failed:{exc}") from exc

        now = datetime.utcnow()
        report.alert_notified_at = now
        await report.save()

        print(f"[MLOps Alert] {payload}")

        return {
            "status": "sent" if webhook_sent else "logged",
            "report_id": str(report.id),
            "webhook_sent": bool(webhook_sent),
            "webhook_error": None,
            "alert_notified_at": now.isoformat(),
        }


mlops_alerting_service = MlopsAlertingService()
