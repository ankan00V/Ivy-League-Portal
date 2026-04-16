from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.models.background_job import BackgroundJob
from app.models.user import User
from app.services.job_runner import job_runner

router = APIRouter()


class JobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    attempts: int
    max_attempts: int
    run_after: datetime
    created_at: datetime
    updated_at: datetime
    last_error: Optional[str] = None
    result: Optional[dict[str, Any]] = None


class EnqueueJobRequest(BaseModel):
    job_type: str = Field(min_length=3)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=5, ge=1, le=50)
    dedupe_key: Optional[str] = None


@router.get("/recent", response_model=list[JobResponse])
async def recent_jobs(
    limit: int = 30,
    _: User = Depends(get_current_admin_user),
) -> Any:
    safe_limit = max(1, min(limit, 200))
    jobs = await BackgroundJob.find_many().sort("-created_at").limit(safe_limit).to_list()
    return [
        JobResponse(
            id=str(job.id),
            job_type=job.job_type,
            status=job.status,
            attempts=int(job.attempts or 0),
            max_attempts=int(job.max_attempts or 0),
            run_after=job.run_after,
            created_at=job.created_at,
            updated_at=job.updated_at,
            last_error=job.last_error,
            result=job.result,
        )
        for job in jobs
    ]


@router.get("/dead-letter", response_model=list[JobResponse])
async def dead_letter_jobs(
    limit: int = 50,
    _: User = Depends(get_current_admin_user),
) -> Any:
    safe_limit = max(1, min(limit, 200))
    jobs = (
        await BackgroundJob.find_many(BackgroundJob.status == "dead")
        .sort("-updated_at")
        .limit(safe_limit)
        .to_list()
    )
    return [
        JobResponse(
            id=str(job.id),
            job_type=job.job_type,
            status=job.status,
            attempts=int(job.attempts or 0),
            max_attempts=int(job.max_attempts or 0),
            run_after=job.run_after,
            created_at=job.created_at,
            updated_at=job.updated_at,
            last_error=job.last_error,
            result=job.result,
        )
        for job in jobs
    ]


@router.post("/enqueue", response_model=dict)
async def enqueue_job(
    request: EnqueueJobRequest,
    _: User = Depends(get_current_admin_user),
) -> Any:
    job = await job_runner.enqueue(
        job_type=request.job_type.strip(),
        payload=request.payload or {},
        max_attempts=int(request.max_attempts),
        dedupe_key=request.dedupe_key,
    )
    return {"status": "ok", "job_id": str(job.id)}

