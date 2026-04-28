from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request

from app.api.deps import get_current_admin_user
from app.models.security_event import SecurityEvent
from app.models.user import User

router = APIRouter()


@router.post("/csp-report", include_in_schema=False)
async def record_csp_report(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, str]:
    report = payload.get("csp-report") or payload.get("body") or payload
    row = SecurityEvent(
        event_type="csp_violation",
        source="frontend",
        metadata={
            "report": report,
            "user_agent": request.headers.get("user-agent"),
            "origin": request.headers.get("origin"),
            "content_type": request.headers.get("content-type"),
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
