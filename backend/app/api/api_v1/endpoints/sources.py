from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_active_user
from app.models.source_discovery import DiscoveredSource, DiscoveryMethod
from app.models.user import User
from app.services.source_discovery import source_discovery_engine

router = APIRouter()


class SourceSubmissionRequest(BaseModel):
    url: str = Field(min_length=8)
    context: Optional[str] = Field(default=None, max_length=1000)


def _source_summary(row: DiscoveredSource) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "url": row.url,
        "domain": row.domain,
        "name": row.name,
        "source_type": row.source_type,
        "status": row.status,
        "trust_score": row.trust_score,
        "qualification_score": row.qualification_score,
        "extraction_confidence": row.extraction_confidence,
        "requires_admin_review": bool(row.requires_admin_review),
        "rejection_reason": row.rejection_reason,
        "discovered_at": row.discovered_at,
        "promoted_at": row.promoted_at,
    }


@router.post("/submit", response_model=dict)
async def submit_source(
    payload: SourceSubmissionRequest,
    current_user: User = Depends(get_current_active_user),
) -> Any:
    try:
        source = await source_discovery_engine.submit_user_source(
            url=payload.url,
            context=payload.context,
            user=current_user,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "daily_submission_limit_exceeded":
            raise HTTPException(status_code=429, detail="You can submit up to 3 sources per day")
        if message == "domain_is_blocked":
            raise HTTPException(status_code=400, detail="This source domain is blocked")
        raise HTTPException(status_code=400, detail=message)
    return {
        "status": "queued",
        "message": "Thanks! We'll review this source.",
        "source": _source_summary(source),
    }


@router.get("/my-submissions", response_model=list[dict[str, Any]])
async def my_submissions(
    current_user: User = Depends(get_current_active_user),
) -> Any:
    rows = await DiscoveredSource.find_many(
        DiscoveredSource.discovery_method == DiscoveryMethod.user_submission,
        DiscoveredSource.discovered_by == str(current_user.id),
    ).sort("-discovered_at").limit(100).to_list()
    return [_source_summary(row) for row in rows]
