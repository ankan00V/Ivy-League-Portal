from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import requests

from app.core.config import settings
from app.models.model_drift_report import ModelDriftReport


class MlopsAlertingService:
    async def _post_json(self, *, url: str, payload: dict[str, Any], timeout: float) -> None:
        response = await asyncio.to_thread(
            requests.post,
            url,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()

    def _slack_payload(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        metrics = payload.get("metrics") or {}
        return {
            "text": "VidyaVerse MLOps Drift Alert",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "VidyaVerse MLOps Drift Alert"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Report ID*\n`{payload.get('report_id')}`"},
                        {"type": "mrkdwn", "text": f"*Model Version*\n`{payload.get('model_version_id')}`"},
                        {"type": "mrkdwn", "text": f"*PSI*\n{metrics.get('query_bucket_psi')}"},
                        {"type": "mrkdwn", "text": f"*Max Feature Z*\n{metrics.get('max_feature_mean_z')}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Window*\n{payload.get('window_start')} -> {payload.get('window_end')}",
                    },
                },
            ],
        }

    def _pagerduty_payload(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        severity = str(settings.MLOPS_ALERT_PAGERDUTY_SEVERITY or "error").strip().lower() or "error"
        return {
            "routing_key": (settings.MLOPS_ALERT_PAGERDUTY_ROUTING_KEY or "").strip(),
            "event_action": "trigger",
            "payload": {
                "summary": (
                    f"VidyaVerse drift alert report={payload.get('report_id')} "
                    f"model={payload.get('model_version_id')}"
                ),
                "source": "vidyaverse-mlops",
                "severity": severity,
                "timestamp": payload.get("reported_at"),
                "component": "ranking_monitoring",
                "group": "mlops",
                "class": "drift",
                "custom_details": payload,
            },
        }

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
        slack_webhook_url = (settings.MLOPS_ALERT_SLACK_WEBHOOK_URL or "").strip()
        pagerduty_routing_key = (settings.MLOPS_ALERT_PAGERDUTY_ROUTING_KEY or "").strip()
        timeout = max(1.0, float(settings.MLOPS_ALERT_WEBHOOK_TIMEOUT_SECONDS))

        webhook_sent = False
        slack_sent = False
        pagerduty_sent = False
        channel_errors: dict[str, str] = {}

        if webhook_url:
            try:
                await self._post_json(url=webhook_url, payload=payload, timeout=timeout)
                webhook_sent = True
            except Exception as exc:
                channel_errors["webhook"] = str(exc)

        if slack_webhook_url:
            try:
                await self._post_json(
                    url=slack_webhook_url,
                    payload=self._slack_payload(payload=payload),
                    timeout=timeout,
                )
                slack_sent = True
            except Exception as exc:
                channel_errors["slack"] = str(exc)

        if pagerduty_routing_key:
            try:
                pagerduty_payload = self._pagerduty_payload(payload=payload)
                await self._post_json(
                    url="https://events.pagerduty.com/v2/enqueue",
                    payload=pagerduty_payload,
                    timeout=timeout,
                )
                pagerduty_sent = True
            except Exception as exc:
                channel_errors["pagerduty"] = str(exc)

        incident_id: str | None = None
        if bool(settings.MLOPS_INCIDENT_AUTO_CREATE):
            try:
                from app.services.mlops.incident_service import mlops_incident_service

                incident = await mlops_incident_service.create_from_drift_alert(
                    report=report,
                    alert_payload=payload,
                )
                incident_id = str(incident.id)
            except Exception as exc:
                channel_errors["incident"] = str(exc)

        if channel_errors and not (webhook_sent or slack_sent or pagerduty_sent):
            raise RuntimeError(f"alert_delivery_failed:{channel_errors}")

        now = datetime.utcnow()
        report.alert_notified_at = now
        await report.save()

        print(f"[MLOps Alert] {payload}")

        return {
            "status": "sent" if (webhook_sent or slack_sent or pagerduty_sent) else "logged",
            "report_id": str(report.id),
            "webhook_sent": bool(webhook_sent),
            "slack_sent": bool(slack_sent),
            "pagerduty_sent": bool(pagerduty_sent),
            "incident_id": incident_id,
            "channel_errors": channel_errors,
            "alert_notified_at": now.isoformat(),
        }


mlops_alerting_service = MlopsAlertingService()
