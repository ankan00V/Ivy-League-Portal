from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from pymongo import ReturnDocument

from app.core.config import settings
from app.core.metrics import (
    JOBS_DEAD_TOTAL,
    JOBS_ENQUEUED_TOTAL,
    JOBS_FAILED_TOTAL,
    JOBS_SUCCEEDED_TOTAL,
    SCRAPER_RUNS_TOTAL,
    SCRAPER_SOURCE_TOTAL,
)
from app.models.background_job import BackgroundJob


JobHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _get_collection(document_cls: type) -> Any:
    getter = getattr(document_cls, "get_motor_collection", None)
    if callable(getter):
        return getter()
    getter = getattr(document_cls, "get_pymongo_collection", None)
    if callable(getter):
        return getter()
    raise AttributeError(f"No collection getter found for {document_cls.__name__}")


class JobRunner:
    def __init__(self) -> None:
        self._worker_id = f"api:{random.randint(1000, 9999)}"
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    async def enqueue(
        self,
        *,
        job_type: str,
        payload: Optional[dict[str, Any]] = None,
        max_attempts: int = 5,
        run_after: Optional[datetime] = None,
        dedupe_key: Optional[str] = None,
    ) -> BackgroundJob:
        now = datetime.utcnow()
        run_after_value = run_after or now
        if dedupe_key:
            existing = await BackgroundJob.find_one(
                BackgroundJob.dedupe_key == dedupe_key,
                BackgroundJob.status.in_(["pending", "running", "retry"]),
            )
            if existing:
                return existing

        job = BackgroundJob(
            job_type=job_type,
            payload=payload or {},
            status="pending",
            attempts=0,
            max_attempts=max(1, int(max_attempts)),
            run_after=run_after_value,
            dedupe_key=dedupe_key,
            created_at=now,
            updated_at=now,
        )
        await job.insert()
        if JOBS_ENQUEUED_TOTAL is not None:
            JOBS_ENQUEUED_TOTAL.labels(job_type=job_type).inc()
        return job

    async def _claim_next(self) -> Optional[BackgroundJob]:
        lock_timeout = timedelta(seconds=max(30, int(settings.JOBS_LOCK_TIMEOUT_SECONDS)))
        now = datetime.utcnow()
        cutoff = now - lock_timeout

        collection = _get_collection(BackgroundJob)
        doc = await collection.find_one_and_update(
            {
                "status": {"$in": ["pending", "retry"]},
                "run_after": {"$lte": now},
                "$or": [{"locked_at": None}, {"locked_at": {"$lte": cutoff}}],
            },
            {
                "$set": {
                    "status": "running",
                    "locked_by": self._worker_id,
                    "locked_at": now,
                    "started_at": now,
                    "updated_at": now,
                }
            },
            sort=[("run_after", 1), ("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            return None
        return BackgroundJob.model_validate(doc)

    def _backoff(self, attempts: int) -> timedelta:
        base = max(0.25, float(settings.JOBS_RETRY_BASE_SECONDS))
        cap = max(base, float(settings.JOBS_RETRY_MAX_SECONDS))
        exp = min(12, max(0, int(attempts)))
        seconds = min(cap, base * (2**exp))
        jitter = seconds * 0.15 * (random.random() - 0.5)
        return timedelta(seconds=max(0.25, seconds + jitter))

    async def _mark_success(self, job: BackgroundJob, result: dict[str, Any]) -> None:
        now = datetime.utcnow()
        await BackgroundJob.find_one(BackgroundJob.id == job.id).update(
            {
                "$set": {
                    "status": "succeeded",
                    "finished_at": now,
                    "updated_at": now,
                    "result": result,
                    "last_error": None,
                    "last_error_at": None,
                }
            }
        )
        if JOBS_SUCCEEDED_TOTAL is not None:
            JOBS_SUCCEEDED_TOTAL.labels(job_type=job.job_type).inc()

    async def _mark_failure(self, job: BackgroundJob, error: str) -> None:
        now = datetime.utcnow()
        attempts = int(job.attempts) + 1
        max_attempts = max(1, int(job.max_attempts))

        if attempts >= max_attempts:
            await BackgroundJob.find_one(BackgroundJob.id == job.id).update(
                {
                    "$set": {
                        "status": "dead",
                        "attempts": attempts,
                        "finished_at": now,
                        "updated_at": now,
                        "last_error": error,
                        "last_error_at": now,
                        "locked_at": None,
                        "locked_by": None,
                    }
                }
            )
            if JOBS_DEAD_TOTAL is not None:
                JOBS_DEAD_TOTAL.labels(job_type=job.job_type).inc()
            return

        delay = self._backoff(attempts=attempts - 1)
        await BackgroundJob.find_one(BackgroundJob.id == job.id).update(
            {
                "$set": {
                    "status": "retry",
                    "attempts": attempts,
                    "run_after": now + delay,
                    "updated_at": now,
                    "last_error": error,
                    "last_error_at": now,
                    "locked_at": None,
                    "locked_by": None,
                }
            }
        )
        if JOBS_FAILED_TOTAL is not None:
            JOBS_FAILED_TOTAL.labels(job_type=job.job_type).inc()

    async def _run_job(self, job: BackgroundJob) -> None:
        handler = self._handlers.get(job.job_type)
        if handler is None:
            await self._mark_failure(job, f"unknown_job_type:{job.job_type}")
            return

        try:
            result = await handler(job.payload or {})
            await self._mark_success(job, result=result)
        except Exception as exc:
            await self._mark_failure(job, error=str(exc))

    async def _loop(self) -> None:
        poll = max(0.2, float(settings.JOBS_POLL_INTERVAL_SECONDS))
        while not self._stop_event.is_set():
            try:
                job = await self._claim_next()
                if job is None:
                    await asyncio.sleep(poll)
                    continue
                await self._run_job(job)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(min(2.0, poll))

    def start(self) -> None:
        if not settings.JOBS_ENABLED:
            return
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except Exception:
            pass
        self._task = None


job_runner = JobRunner()


async def _job_scraper(_: dict[str, Any]) -> dict[str, Any]:
    from app.services.scraper import run_scheduled_scrapers
    from app.services.system_metrics import refresh_freshness_metrics

    report = await run_scheduled_scrapers(force=True)
    status = str(report.get("status") or "unknown")

    if SCRAPER_RUNS_TOTAL is not None:
        SCRAPER_RUNS_TOTAL.labels(status=status).inc()
    if SCRAPER_SOURCE_TOTAL is not None:
        for source in report.get("sources", []) or []:
            name = str(source.get("source") or "unknown")
            source_status = "error" if (source.get("errors") or []) else "ok"
            SCRAPER_SOURCE_TOTAL.labels(source=name, status=source_status).inc()

    await refresh_freshness_metrics()

    if status == "failed":
        raise RuntimeError("scraper_failed")
    return report


async def _job_mlops_retrain(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.mlops.retraining_service import retraining_service

    result = await retraining_service.retrain_and_register(
        lookback_days=int(payload.get("lookback_days") or settings.MLOPS_RETRAIN_LOOKBACK_DAYS),
        label_window_hours=int(payload.get("label_window_hours") or settings.MLOPS_LABEL_WINDOW_HOURS),
        min_rows=int(payload.get("min_rows") or settings.MLOPS_MIN_TRAINING_ROWS),
        grid_step=float(payload.get("grid_step") or settings.MLOPS_TRAIN_GRID_STEP),
        auto_activate=bool(payload.get("auto_activate") if payload.get("auto_activate") is not None else settings.MLOPS_AUTO_ACTIVATE),
        notes=str(payload.get("notes") or "scheduled"),
    )
    return {
        "window_start": result.window_start.isoformat(),
        "window_end": result.window_end.isoformat(),
        "training_rows": result.training_rows,
        "weights": result.weights,
        "metrics": result.metrics,
    }


async def _job_mlops_drift(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.mlops.drift_service import drift_service

    report = await drift_service.run(
        lookback_days=int(payload.get("lookback_days") or settings.MLOPS_DRIFT_LOOKBACK_DAYS)
    )
    return {
        "id": str(report.id),
        "model_version_id": report.model_version_id,
        "alert": bool(report.alert),
        "metrics": report.metrics,
        "created_at": report.created_at.isoformat(),
    }


def register_default_jobs() -> None:
    job_runner.register("scraper.run", _job_scraper)
    job_runner.register("mlops.retrain", _job_mlops_retrain)
    job_runner.register("mlops.drift", _job_mlops_drift)
