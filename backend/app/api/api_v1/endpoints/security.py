from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_current_admin_user
from app.core.config import settings
from app.models.security_event import SecurityEvent
from app.models.user import User

router = APIRouter()

_CSP_REPORT_FIELDS = (
    "blocked-uri",
    "column-number",
    "document-uri",
    "effective-directive",
    "line-number",
    "original-policy",
    "referrer",
    "source-file",
    "status-code",
    "violated-directive",
)
_CSP_REPORT_VALUE_LIMIT = 2_048


def _sanitize_csp_report(payload: Any) -> dict[str, str | int]:
    """Keep CSP telemetry useful without turning it into arbitrary storage."""

    report = payload.get("csp-report") or payload.get("body") or payload if isinstance(payload, dict) else {}
    if not isinstance(report, dict):
        return {}
    sanitized: dict[str, str | int] = {}
    for field in _CSP_REPORT_FIELDS:
        value = report.get(field)
        if isinstance(value, bool):
            sanitized[field] = str(value).lower()
        elif isinstance(value, (str, int, float)):
            sanitized[field] = str(value)[:_CSP_REPORT_VALUE_LIMIT]
    return sanitized


@router.post("/csp-report", include_in_schema=False)
async def record_csp_report(
    request: Request,
) -> dict[str, str]:
    limit = max(1_024, int(settings.SECURITY_CSP_REPORT_MAX_BYTES))
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > limit:
                raise HTTPException(status_code=413, detail="CSP report exceeds size limit")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")

    raw_payload = await request.body()
    if len(raw_payload) > limit:
        raise HTTPException(status_code=413, detail="CSP report exceeds size limit")
    try:
        payload = json.loads(raw_payload or b"{}")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="CSP report must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="CSP report must be a JSON object")

    row = SecurityEvent(
        event_type="csp_violation",
        source="frontend",
        metadata={
            "report": _sanitize_csp_report(payload),
            "user_agent": str(request.headers.get("user-agent") or "")[:512],
            "origin": str(request.headers.get("origin") or "")[:512],
            "content_type": str(request.headers.get("content-type") or "")[:128],
        },
    )
    await row.insert()
    return {"status": "accepted"}


@router.get("/events", response_model=list[dict])
async def list_security_events(
    limit: int = 100,
    _: User = Depends(get_current_admin_user),
) -> Any:
    rows = await SecurityEvent.find_many().sort("-created_at").limit(max(1, min(int(limit), 500))).to_list()
    return [row.model_dump(mode="json") for row in rows]
