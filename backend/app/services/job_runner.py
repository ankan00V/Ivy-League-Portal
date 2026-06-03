from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from pymongo import ReturnDocument
from beanie.odm.operators.find.comparison import In

from app.core.config import settings
from app.core.metrics import (
    JOBS_DEAD_TOTAL,
    JOBS_ENQUEUED_TOTAL,
    JOBS_FAILED_TOTAL,
    JOBS_SUCCEEDED_TOTAL,
    SCRAPER_RUNS_TOTAL,
    SCRAPER_SOURCE_TOTAL,
    DISCOVERY_PROBATION_SOURCES,
    DISCOVERY_SOURCES_DISCOVERED_TOTAL,
    DISCOVERY_SOURCES_IN_PIPELINE,
    DISCOVERY_SOURCES_PROMOTED_TOTAL,
)
from app.models.background_job import BackgroundJob
from app.core.time import utc_now


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
        self._inflight: set[asyncio.Task[None]] = set()
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
        now = utc_now()
        run_after_value = run_after or now
        max_pending = max(0, int(settings.JOBS_MAX_PENDING_PER_TYPE))
        if dedupe_key:
            existing = await BackgroundJob.find_one(
                BackgroundJob.dedupe_key == dedupe_key,
                In(BackgroundJob.status, ["pending", "running", "retry"]),
            )
            if existing:
                return existing
        if max_pending > 0:
            collection = _get_collection(BackgroundJob)
            pending_count = await collection.count_documents(
                {"job_type": job_type, "status": {"$in": ["pending", "running", "retry"]}}
            )
            if int(pending_count) >= max_pending:
                raise RuntimeError(f"job_queue_full:{job_type}:{pending_count}/{max_pending}")

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
        now = utc_now()
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
        now = utc_now()
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
        now = utc_now()
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
            timeout_seconds = max(0.1, float(settings.JOBS_HANDLER_TIMEOUT_SECONDS))
            result = await asyncio.wait_for(handler(job.payload or {}), timeout=timeout_seconds)
            await self._mark_success(job, result=result)
        except asyncio.TimeoutError:
            await self._mark_failure(job, error=f"job_timeout:{settings.JOBS_HANDLER_TIMEOUT_SECONDS}s")
        except Exception as exc:
            await self._mark_failure(job, error=str(exc))

    async def _loop(self) -> None:
        poll = max(0.2, float(settings.JOBS_POLL_INTERVAL_SECONDS))
        while not self._stop_event.is_set():
            try:
                max_concurrency = max(1, int(settings.JOBS_MAX_CONCURRENCY))
                if len(self._inflight) >= max_concurrency:
                    await asyncio.sleep(poll)
                    continue
                job = await self._claim_next()
                if job is None:
                    await asyncio.sleep(poll)
                    continue
                task = asyncio.create_task(self._run_job(job))
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
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
        if self._inflight:
            await asyncio.gather(*list(self._inflight), return_exceptions=True)
            self._inflight.clear()


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


async def _job_scraper_recover_unhealthy(_: dict[str, Any]) -> dict[str, Any]:
    from app.services.scraper import run_scheduled_scrapers
    from app.services.scraper_health_service import scraper_health_service

    unhealthy = await scraper_health_service.unhealthy_sources()
    if not unhealthy:
        return {"status": "skipped", "reason": "all_sources_green", "sources": []}

    report = await run_scheduled_scrapers(force=True)
    red_24h = await scraper_health_service.red_sources_for_24h()
    alert_result: dict[str, Any] | None = None
    if red_24h:
        alert_result = await _send_scraper_health_alert(red_24h)
    return {
        "status": "ran",
        "target_sources": [str(row.get("source") or "unknown") for row in unhealthy],
        "red_sources_24h": [str(row.get("source") or "unknown") for row in red_24h],
        "alert": alert_result,
        "scraper_report": report,
    }


async def _send_scraper_health_alert(red_sources: list[dict[str, Any]]) -> dict[str, Any]:
    import requests

    payload = {
        "event": "scraper.health.red_24h",
        "reported_at": utc_now().isoformat(),
        "sources": red_sources,
    }
    webhook_url = (settings.MLOPS_ALERT_WEBHOOK_URL or "").strip()
    slack_url = (settings.MLOPS_ALERT_SLACK_WEBHOOK_URL or "").strip()
    timeout = max(1.0, float(settings.MLOPS_ALERT_WEBHOOK_TIMEOUT_SECONDS))
    sent_channels: list[str] = []
    errors: dict[str, str] = {}

    if webhook_url:
        try:
            response = await asyncio.to_thread(requests.post, webhook_url, json=payload, timeout=timeout)
            response.raise_for_status()
            sent_channels.append("webhook")
        except Exception as exc:
            errors["webhook"] = str(exc)

    if slack_url:
        try:
            response = await asyncio.to_thread(
                requests.post,
                slack_url,
                json={
                    "text": "VidyaVerse scraper health alert",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {"type": "plain_text", "text": "VidyaVerse scraper health alert"},
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "\n".join(
                                    f"*{row.get('source')}* health={row.get('health_score')} "
                                    f"stale={row.get('staleness_hours')}h"
                                    for row in red_sources
                                ),
                            },
                        },
                    ],
                },
                timeout=timeout,
            )
            response.raise_for_status()
            sent_channels.append("slack")
        except Exception as exc:
            errors["slack"] = str(exc)

    if not sent_channels:
        print(f"[ScraperHealthAlert] {payload}")

    return {
        "status": "sent" if sent_channels else "logged",
        "sent_channels": sent_channels,
        "errors": errors,
    }


async def _job_opportunity_quality(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.opportunity_quality_service import opportunity_quality_scorer

    limit = payload.get("limit")
    return await opportunity_quality_scorer.run_quality_pipeline(
        stale_days=int(payload.get("stale_days") or 7),
        limit=int(limit) if limit is not None else None,
    )


async def _job_opportunities_dedup_scan(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.duplicate_detector import duplicate_detector

    return await duplicate_detector.scan_existing(
        limit=int(payload.get("limit") or 1000),
        execute=bool(payload.get("execute") or False),
        mark_duplicate_closed=bool(payload.get("mark_duplicate_closed") or False),
    )


async def _job_embeddings_rebuild(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.embedding_pipeline import embedding_pipeline

    return await embedding_pipeline.rebuild_vector_index_if_stale(force=bool(payload.get("force") or False))


async def _job_mlops_retrain(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.mlops.retraining_service import retraining_service

    def _payload_or_default(key: str, default: Any) -> Any:
        value = payload.get(key)
        return default if value is None else value

    result = await retraining_service.retrain_and_register(
        lookback_days=int(_payload_or_default("lookback_days", settings.MLOPS_RETRAIN_LOOKBACK_DAYS)),
        label_window_hours=int(_payload_or_default("label_window_hours", settings.MLOPS_LABEL_WINDOW_HOURS)),
        min_rows=int(_payload_or_default("min_rows", settings.MLOPS_MIN_TRAINING_ROWS)),
        grid_step=float(_payload_or_default("grid_step", settings.MLOPS_TRAIN_GRID_STEP)),
        auto_activate=bool(_payload_or_default("auto_activate", settings.MLOPS_AUTO_ACTIVATE)),
        activation_policy=str(_payload_or_default("activation_policy", settings.MLOPS_ACTIVATION_POLICY)),
        min_auc_gain_for_activation=float(
            _payload_or_default("min_auc_gain_for_activation", settings.MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN)
        ),
        min_positive_rate_for_activation=float(
            _payload_or_default("min_positive_rate_for_activation", settings.MLOPS_AUTO_ACTIVATE_MIN_POSITIVE_RATE)
        ),
        max_weight_shift_for_activation=float(
            _payload_or_default("max_weight_shift_for_activation", settings.MLOPS_AUTO_ACTIVATE_MAX_WEIGHT_SHIFT)
        ),
        notes=str(_payload_or_default("notes", "scheduled")),
    )
    return {
        "window_start": result.window_start.isoformat(),
        "window_end": result.window_end.isoformat(),
        "training_rows": result.training_rows,
        "weights": result.weights,
        "metrics": result.metrics,
        "lifecycle": result.lifecycle,
        "auto_activated": bool(result.auto_activated),
        "activation_reason": result.activation_reason,
    }


async def _job_mlops_drift(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.mlops.drift_service import drift_service

    report = await drift_service.run(
        lookback_days=int(payload.get("lookback_days") or settings.MLOPS_DRIFT_LOOKBACK_DAYS)
    )
    alert_job_id: str | None = None
    retrain_enqueued = False

    if report.alert:
        if settings.MLOPS_ALERTS_ENABLED:
            alert_job = await job_runner.enqueue(
                job_type="mlops.alert",
                payload={"kind": "drift", "report_id": str(report.id)},
                dedupe_key=f"mlops.alert:{str(report.id)}",
            )
            alert_job_id = str(alert_job.id)

        if settings.MLOPS_TRIGGER_RETRAIN_ON_DRIFT_ALERT:
            await job_runner.enqueue(
                job_type="mlops.retrain",
                payload={
                    "lookback_days": settings.MLOPS_RETRAIN_LOOKBACK_DAYS,
                    "label_window_hours": settings.MLOPS_LABEL_WINDOW_HOURS,
                    "min_rows": settings.MLOPS_MIN_TRAINING_ROWS,
                    "grid_step": settings.MLOPS_TRAIN_GRID_STEP,
                    "auto_activate": settings.MLOPS_AUTO_ACTIVATE,
                    "activation_policy": settings.MLOPS_ACTIVATION_POLICY,
                    "min_auc_gain_for_activation": settings.MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN,
                    "min_positive_rate_for_activation": settings.MLOPS_AUTO_ACTIVATE_MIN_POSITIVE_RATE,
                    "max_weight_shift_for_activation": settings.MLOPS_AUTO_ACTIVATE_MAX_WEIGHT_SHIFT,
                    "notes": f"drift_alert:{str(report.id)}",
                },
                dedupe_key="mlops.retrain",
            )
            retrain_enqueued = True

    return {
        "id": str(report.id),
        "model_version_id": report.model_version_id,
        "alert": bool(report.alert),
        "metrics": report.metrics,
        "alert_job_id": alert_job_id,
        "retrain_enqueued": bool(retrain_enqueued),
        "created_at": report.created_at.isoformat(),
    }


async def _job_mlops_alert(payload: dict[str, Any]) -> dict[str, Any]:
    from app.models.model_drift_report import ModelDriftReport
    from app.services.mlops.alerting_service import mlops_alerting_service

    kind = str(payload.get("kind") or "drift").strip().lower()
    if kind != "drift":
        raise ValueError(f"unsupported_alert_kind:{kind}")

    report_id = str(payload.get("report_id") or "").strip()
    if not report_id:
        raise ValueError("missing_report_id")

    report = await ModelDriftReport.get(report_id)
    if report is None:
        raise ValueError("drift_report_not_found")

    return await mlops_alerting_service.notify_drift_alert(report=report)


async def _job_analytics_warehouse_rebuild(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.analytics_warehouse_service import analytics_warehouse_service

    lookback_days = int(payload.get("lookback_days") or settings.ANALYTICS_LOOKBACK_DAYS_DEFAULT)
    traffic_type = str(payload.get("traffic_type") or "real").strip().lower() or "real"
    return await analytics_warehouse_service.rebuild(
        lookback_days=lookback_days,
        traffic_type=traffic_type,
    )


async def _job_experiment_graduation(payload: dict[str, Any]) -> dict[str, Any]:
    from app.models.experiment import Experiment
    from app.services.experiment_analytics_service import experiment_analytics_service

    days = int(payload.get("days") or 30)
    traffic_type = str(payload.get("traffic_type") or "real").strip().lower() or "real"
    experiments = await Experiment.find_many().to_list()
    eligible = [item for item in experiments if item.status in {"active", "running"}]
    results: list[dict[str, Any]] = []
    for experiment in eligible:
        result = await experiment_analytics_service.maybe_graduate(
            experiment=experiment,
            days=days,
            traffic_type=traffic_type,
        )
        results.append(
            {
                "experiment_key": experiment.key,
                "graduated": bool(result.get("graduated")),
                "reason": result.get("reason"),
                "winning_variant": result.get("winning_variant"),
            }
        )
    return {
        "checked": len(eligible),
        "graduated": len([item for item in results if item.get("graduated")]),
        "results": results,
    }


async def _job_opportunity_trust_backfill(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.opportunity_trust_backfill import backfill_opportunity_trust

    return await backfill_opportunity_trust(
        batch_size=int(payload.get("batch_size") or 200),
        limit=int(payload["limit"]) if payload.get("limit") is not None else None,
    )


async def _refresh_discovery_metrics() -> None:
    from app.models.source_discovery import DiscoveredSource, SourceStatus

    if DISCOVERY_SOURCES_IN_PIPELINE is not None or DISCOVERY_PROBATION_SOURCES is not None:
        rows = await DiscoveredSource.find_many().to_list()
        for status in SourceStatus:
            count = sum(1 for row in rows if row.status == status)
            if DISCOVERY_SOURCES_IN_PIPELINE is not None:
                DISCOVERY_SOURCES_IN_PIPELINE.labels(status=status.value).set(count)
            if status == SourceStatus.probation and DISCOVERY_PROBATION_SOURCES is not None:
                DISCOVERY_PROBATION_SOURCES.set(count)


async def _job_source_discovery_run(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.source_discovery import source_discovery_engine

    summary = await source_discovery_engine.run_discovery(
        triggered_by=str(payload.get("triggered_by") or "scheduler")
    )
    if DISCOVERY_SOURCES_DISCOVERED_TOTAL is not None and summary.urls_discovered:
        DISCOVERY_SOURCES_DISCOVERED_TOTAL.inc(summary.urls_discovered)
    await _refresh_discovery_metrics()
    return summary.model_dump(mode="json")


async def _job_source_qualification_batch(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.source_discovery import source_qualification_service

    result = await source_qualification_service.process_batch(max_items=int(payload.get("max_items") or 50))
    await _refresh_discovery_metrics()
    return result


async def _job_source_extraction_batch(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.source_discovery import adaptive_extraction_service

    result = await adaptive_extraction_service.process_batch(max_items=int(payload.get("max_items") or 20))
    await _refresh_discovery_metrics()
    return result


async def _job_probation_scrape_run(payload: dict[str, Any]) -> dict[str, Any]:
    from app.models.source_discovery import DiscoveredSource, SourceStatus
    from app.services.source_discovery import probation_manager

    before = await DiscoveredSource.find_many(DiscoveredSource.status == SourceStatus.promoted).count()
    result = await probation_manager.run_all_probation_sources(limit=int(payload.get("limit") or 100))
    after = await DiscoveredSource.find_many(DiscoveredSource.status == SourceStatus.promoted).count()
    promoted = max(0, after - before)
    if DISCOVERY_SOURCES_PROMOTED_TOTAL is not None and promoted:
        DISCOVERY_SOURCES_PROMOTED_TOTAL.inc(promoted)
    await _refresh_discovery_metrics()
    return {**result, "promoted": promoted}


async def _job_source_health_monitor(_: dict[str, Any]) -> dict[str, Any]:
    from app.services.source_discovery import source_health_monitor

    result = await source_health_monitor.run()
    await _refresh_discovery_metrics()
    return result


async def _job_company_seed_careers_finder(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.source_discovery import source_discovery_engine

    result = await source_discovery_engine.enqueue_known_seed_sources(limit=int(payload.get("limit") or 50))
    if DISCOVERY_SOURCES_DISCOVERED_TOTAL is not None and result.get("queued"):
        DISCOVERY_SOURCES_DISCOVERED_TOTAL.inc(int(result["queued"]))
    await _refresh_discovery_metrics()
    return result


async def _job_trust_score_recompute(payload: dict[str, Any]) -> dict[str, Any]:
    from app.models.source_discovery import DiscoveredSource, SourceStatus
    from app.services.source_discovery import trust_scoring_engine

    rows = await DiscoveredSource.find_many(
        DiscoveredSource.status == SourceStatus.probation
    ).limit(int(payload.get("limit") or 500)).to_list()
    for row in rows:
        await trust_scoring_engine.score_source(row.id)
    await _refresh_discovery_metrics()
    return {"processed": len(rows)}


async def _job_opportunity_status_refresh(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.opportunity_status_service import opportunity_status_service

    result = await opportunity_status_service.refresh(
        limit=int(payload.get("limit") or 2000),
        check_liveness=bool(payload.get("check_liveness") or False),
        liveness_limit=int(payload.get("liveness_limit") or 50),
    )
    return result.model_dump()


def register_default_jobs() -> None:
    job_runner.register("scraper.run", _job_scraper)
    job_runner.register("scraper.recover_unhealthy", _job_scraper_recover_unhealthy)
    job_runner.register("opportunities.quality_pipeline", _job_opportunity_quality)
    job_runner.register("opportunities.dedup_scan", _job_opportunities_dedup_scan)
    job_runner.register("embeddings.rebuild", _job_embeddings_rebuild)
    job_runner.register("mlops.retrain", _job_mlops_retrain)
    job_runner.register("mlops.drift", _job_mlops_drift)
    job_runner.register("mlops.alert", _job_mlops_alert)
    job_runner.register("analytics.warehouse.rebuild", _job_analytics_warehouse_rebuild)
    job_runner.register("experiments.graduation", _job_experiment_graduation)
    job_runner.register("opportunities.trust_backfill", _job_opportunity_trust_backfill)
    job_runner.register("opportunities.status_refresh", _job_opportunity_status_refresh)
    job_runner.register("source_discovery_run", _job_source_discovery_run)
    job_runner.register("source_qualification_batch", _job_source_qualification_batch)
    job_runner.register("source_extraction_batch", _job_source_extraction_batch)
    job_runner.register("probation_scrape_run", _job_probation_scrape_run)
    job_runner.register("source_health_monitor", _job_source_health_monitor)
    job_runner.register("company_seed_careers_finder", _job_company_seed_careers_finder)
    job_runner.register("trust_score_recompute", _job_trust_score_recompute)
