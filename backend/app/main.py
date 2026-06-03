import asyncio
import logging
import os
import time
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import analytics_bi_tool_url, auth_cookie_only_mode_enabled, resolved_csp_value, settings

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.bootstrap import init_database
from app.services.experiment_service import experiment_service
from app.services.rag_template_registry_service import rag_template_registry_service
from app.services.ranking_model_service import ranking_model_service
from app.services.admin_identity_service import ensure_single_admin_identity
 
from app.services.job_runner import job_runner, register_default_jobs
from app.services.system_metrics import refresh_freshness_metrics
from app.services.embedding_service import embedding_service
from app.services.nlp_service import nlp_service
from app.services.model_artifact_service import model_artifact_service
from app.services.personalization.learned_ranker import learned_ranker
from app.services.warehouse_export_service import warehouse_export_service
from app.services.vector_service import opportunity_vector_service
from app.core.redis import close_redis, get_redis
from app.core import metrics as metrics_module
from app.core.metrics import (
    CONTENT_TYPE_LATEST,
    init_metrics,
    render_metrics,
)
from app.core.http_middleware import (
    CSRFMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.deps import get_current_admin_user, get_current_user

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    level_name = str(settings.LOG_LEVEL or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(message)s" if settings.LOG_FORMAT == "json" else None)


_configure_logging()


def _has_wildcard(values: list[str]) -> bool:
    return any(str(value).strip() == "*" for value in list(values or []))


def _csp_has_unsafe_tokens(csp_value: str) -> bool:
    normalized = str(csp_value or "").lower()
    return "'unsafe-inline'" in normalized or "'unsafe-eval'" in normalized


def _validate_production_analytics_config() -> None:
    if not settings.ANALYTICS_WAREHOUSE_ENABLED or not settings.ANALYTICS_WAREHOUSE_EXPORT_ENABLED:
        return
    if not settings.ANALYTICS_WAREHOUSE_ENFORCE_CLICKHOUSE_IN_PRODUCTION:
        return
    if not settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED:
        raise RuntimeError("ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED must be true in production.")
    if not (settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST or "").strip():
        raise RuntimeError("ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST is required in production.")
    if not (settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE or "").strip():
        raise RuntimeError("ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE is required in production.")
    if not (settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME or "").strip():
        raise RuntimeError("ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME is required in production.")
    if not (settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD or "").strip():
        raise RuntimeError("ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD is required in production.")


def validate_production_operational_config() -> None:
    if settings.ENVIRONMENT.strip().lower() != "production":
        return
    mongo_url = (settings.MONGODB_URL or "").strip().lower()
    redis_url = (settings.REDIS_URL or "").strip().lower()
    if settings.SECRET_KEY.startswith("your_super_secret_key_here"):
        raise RuntimeError("SECRET_KEY must be set via environment in production.")
    if mongo_url.startswith("mongodb://localhost") or mongo_url.startswith("mongodb://127.0.0.1"):
        raise RuntimeError("Production requires managed MongoDB; MONGODB_URL cannot point at localhost.")
    if redis_url.startswith("redis://localhost") or redis_url.startswith("redis://127.0.0.1"):
        raise RuntimeError("Production requires managed Redis/Upstash; REDIS_URL cannot point at localhost.")
    _validate_production_analytics_config()
    if not (settings.MLOPS_MODEL_ARTIFACT_S3_REGION or "").strip():
        raise RuntimeError("Production model artifact registry requires S3/MinIO region.")
    if not (settings.MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID or "").strip():
        raise RuntimeError("Production model artifact registry requires S3/MinIO access key.")
    if not (settings.MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY or "").strip():
        raise RuntimeError("Production model artifact registry requires S3/MinIO secret key.")
    llm_provider = str(settings.LLM_PROVIDER or "openai_compatible").strip().lower()
    llm_key_configured = bool((settings.LLM_API_KEY or settings.OPENROUTER_API_KEY or "").strip())
    bedrock_key_configured = bool((settings.AWS_BEARER_TOKEN_BEDROCK or "").strip())
    if llm_provider == "bedrock":
        llm_key_configured = bedrock_key_configured
    if not llm_key_configured:
        raise RuntimeError("Production assistant requires an LLM API key.")
    judge_key_configured = bool((settings.LLM_JUDGE_API_KEY or settings.LLM_API_KEY or settings.OPENROUTER_API_KEY or "").strip())
    if llm_provider == "bedrock":
        judge_key_configured = bedrock_key_configured
    if settings.LLM_JUDGE_ENABLED and not judge_key_configured:
        raise RuntimeError("LLM judge is enabled but no judge/LLM API key is configured.")
    if settings.SMTP_REQUIRE_AUTH and not ((settings.SMTP_USER or "").strip() and (settings.SMTP_PASSWORD or "").strip()):
        raise RuntimeError("Production SMTP auth requires SMTP_USER and SMTP_PASSWORD.")
    if not ((settings.GOOGLE_OAUTH_CLIENT_ID or "").strip() and (settings.GOOGLE_OAUTH_CLIENT_SECRET or "").strip()):
        raise RuntimeError("Production requires Google OAuth client id/secret.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENVIRONMENT.strip().lower() == "production":
        validate_production_operational_config()
        if settings.SECRET_KEY.startswith("your_super_secret_key_here"):
            raise RuntimeError("SECRET_KEY must be set via environment in production.")
        if not settings.AUTH_SESSION_COOKIE_ENABLED:
            raise RuntimeError("AUTH_SESSION_COOKIE_ENABLED must remain enabled in production.")
        if not auth_cookie_only_mode_enabled():
            raise RuntimeError("Production requires cookie-only auth mode.")
        if not settings.AUTH_SESSION_COOKIE_SECURE:
            raise RuntimeError("AUTH_SESSION_COOKIE_SECURE must be true in production.")
        if bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS):
            raise RuntimeError("MONGODB_TLS_ALLOW_INVALID_CERTS must be false in production.")
        model_artifact_service.ensure_learned_ranker_artifact_ready()
        if bool(settings.LEARNED_RANKER_REQUIRE_LOADED_IN_PRODUCTION):
            learned_ranker.ensure_loaded_for_production()
        if settings.MLOPS_ALERTS_ENABLED and settings.MLOPS_ENFORCE_LIVE_ALERT_CHANNELS_IN_PRODUCTION:
            has_live_channel = any(
                [
                    bool((settings.MLOPS_ALERT_WEBHOOK_URL or "").strip()),
                    bool((settings.MLOPS_ALERT_SLACK_WEBHOOK_URL or "").strip()),
                    bool((settings.MLOPS_ALERT_PAGERDUTY_ROUTING_KEY or "").strip()),
                ]
            )
            if not has_live_channel:
                raise RuntimeError(
                    "MLOPS alerts are enabled in production, but no live alert channel is configured."
                )
        if (
            settings.MLOPS_INCIDENT_AUTO_CREATE
            and settings.MLOPS_ENFORCE_OWNER_IN_PRODUCTION
            and not (settings.MLOPS_INCIDENT_DEFAULT_OWNER or "").strip()
        ):
            raise RuntimeError(
                "MLOPS incident auto-create requires MLOPS_INCIDENT_DEFAULT_OWNER in production."
            )
        if _has_wildcard(settings.BACKEND_CORS_ORIGINS):
            raise RuntimeError("BACKEND_CORS_ORIGINS cannot include '*' in production.")
        if _has_wildcard(settings.ALLOWED_HOSTS):
            raise RuntimeError("ALLOWED_HOSTS cannot include '*' in production.")
        if settings.SECURITY_CSP_ENFORCE_STRICT_IN_PRODUCTION and _csp_has_unsafe_tokens(resolved_csp_value()):
            raise RuntimeError(
                "SECURITY_CSP_VALUE includes unsafe-inline/unsafe-eval while strict CSP is enforced."
            )

    client = await init_database()
    app.state.mongo_client = client
    app.state.started_at = datetime.now(timezone.utc)
    try:
        await ensure_single_admin_identity()
    except Exception as exc:
        print(f"[Lifecycle] Admin identity bootstrap failed: {exc}")
        raise

    try:
        init_metrics()
    except Exception:
        pass
    if settings.ENVIRONMENT.strip().lower() == "production":
        embedding_service.ensure_healthy_for_production()
    try:
        await experiment_service.ensure_defaults()
    except Exception as exc:
        print(f"[Lifecycle] Experiment defaults init failed: {exc}")
    try:
        await rag_template_registry_service.ensure_defaults()
    except Exception as exc:
        print(f"[Lifecycle] RAG template defaults init failed: {exc}")
    if settings.MLOPS_BOOTSTRAP_ACTIVE_MODEL_ON_STARTUP:
        try:
            active_model = await ranking_model_service.ensure_active_model()
            print(
                f"[Lifecycle] Active ranking model ready: id={active_model.model_version_id}, "
                f"weights={active_model.weights}"
            )
        except Exception as exc:
            print(f"[Lifecycle] Ranking model bootstrap failed: {exc}")

    register_default_jobs()
    job_runner.start()

    # Initialize and start background schedulers (enqueue scraper + MLOps).
    scheduler: AsyncIOScheduler | None = None
    if (
        settings.SCRAPER_AUTORUN_ENABLED
        or settings.MLOPS_AUTORUN_ENABLED
        or settings.ANALYTICS_WAREHOUSE_AUTORUN_ENABLED
        or settings.EMBEDDING_AUTORUN_ENABLED
        or settings.DISCOVERY_ENABLED
        or settings.EXPERIMENT_AUTO_GRADUATION_ENABLED
        or settings.OPPORTUNITY_STATUS_AUTORUN_ENABLED
    ):
        scheduler = AsyncIOScheduler(
            timezone="UTC",
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": max(60, settings.SCRAPER_INTERVAL_MINUTES * 60),
            },
        )

        if settings.SCRAPER_AUTORUN_ENABLED:
            async def _enqueue_scraper() -> None:
                await job_runner.enqueue(job_type="scraper.run", dedupe_key="scraper.run")

            async def _enqueue_scraper_recovery() -> None:
                await job_runner.enqueue(
                    job_type="scraper.recover_unhealthy",
                    max_attempts=2,
                    dedupe_key="scraper.recover_unhealthy",
                )

            scheduler.add_job(
                _enqueue_scraper,
                "interval",
                minutes=max(1, settings.SCRAPER_INTERVAL_MINUTES),
                id="scraper_job",
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
            )
            scheduler.add_job(
                _enqueue_scraper_recovery,
                "interval",
                hours=6,
                id="scraper_recovery_job",
                replace_existing=True,
            )

        if settings.MLOPS_AUTORUN_ENABLED:

            async def _safe_retrain() -> None:
                try:
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
                            "notes": "scheduled",
                        },
                        dedupe_key="mlops.retrain",
                    )
                    print("[Lifecycle] MLOps retrain enqueued.")
                except Exception as exc:
                    print(f"[Lifecycle] MLOps retrain skipped/failed: {exc}")

            async def _safe_drift() -> None:
                try:
                    await job_runner.enqueue(
                        job_type="mlops.drift",
                        payload={"lookback_days": settings.MLOPS_DRIFT_LOOKBACK_DAYS},
                        dedupe_key="mlops.drift",
                    )
                    print("[Lifecycle] Drift check enqueued.")
                except Exception as exc:
                    print(f"[Lifecycle] Drift check failed: {exc}")

            scheduler.add_job(
                _safe_retrain,
                "interval",
                hours=max(1, int(settings.MLOPS_RETRAIN_INTERVAL_HOURS)),
                id="mlops_retrain_job",
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
            )
            scheduler.add_job(
                _safe_drift,
                "interval",
                hours=max(1, int(settings.MLOPS_DRIFT_CHECK_INTERVAL_HOURS)),
                id="mlops_drift_job",
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
            )

        if settings.ANALYTICS_WAREHOUSE_AUTORUN_ENABLED:

            async def _safe_warehouse_rebuild() -> None:
                try:
                    await job_runner.enqueue(
                        job_type="analytics.warehouse.rebuild",
                        payload={
                            "lookback_days": settings.ANALYTICS_LOOKBACK_DAYS_DEFAULT,
                            "traffic_type": "real",
                        },
                        dedupe_key="analytics.warehouse.rebuild",
                    )
                    print("[Lifecycle] Analytics warehouse rebuild enqueued.")
                except Exception as exc:
                    print(f"[Lifecycle] Analytics warehouse rebuild enqueue failed: {exc}")

            scheduler.add_job(
                _safe_warehouse_rebuild,
                "interval",
                hours=max(1, int(settings.ANALYTICS_WAREHOUSE_REBUILD_INTERVAL_HOURS)),
                id="analytics_warehouse_rebuild_job",
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
            )

        if settings.EXPERIMENT_AUTO_GRADUATION_ENABLED:

            async def _safe_experiment_graduation() -> None:
                try:
                    await job_runner.enqueue(
                        job_type="experiments.graduation",
                        payload={"days": settings.ANALYTICS_LOOKBACK_DAYS_DEFAULT, "traffic_type": "real"},
                        max_attempts=2,
                        dedupe_key="experiments.graduation",
                    )
                    print("[Lifecycle] Experiment graduation check enqueued.")
                except Exception as exc:
                    print(f"[Lifecycle] Experiment graduation enqueue failed: {exc}")

            scheduler.add_job(
                _safe_experiment_graduation,
                "interval",
                hours=max(1, int(settings.EXPERIMENT_GRADUATION_INTERVAL_HOURS)),
                id="experiment_graduation_job",
                replace_existing=True,
            )

        if settings.OPPORTUNITY_STATUS_AUTORUN_ENABLED:

            async def _safe_opportunity_status_refresh() -> None:
                try:
                    await job_runner.enqueue(
                        job_type="opportunities.status_refresh",
                        payload={"limit": 5000, "check_liveness": False},
                        max_attempts=2,
                        dedupe_key="opportunities.status_refresh",
                    )
                    print("[Lifecycle] Opportunity status refresh enqueued.")
                except Exception as exc:
                    print(f"[Lifecycle] Opportunity status refresh enqueue failed: {exc}")

            scheduler.add_job(
                _safe_opportunity_status_refresh,
                "interval",
                hours=max(1, int(settings.OPPORTUNITY_STATUS_REFRESH_INTERVAL_HOURS)),
                id="opportunity_status_refresh_job",
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
            )

        if settings.EMBEDDING_AUTORUN_ENABLED:

            async def _enqueue_embedding_rebuild() -> None:
                await job_runner.enqueue(
                    job_type="embeddings.rebuild",
                    payload={"force": False},
                    max_attempts=2,
                    dedupe_key="embeddings.rebuild",
                )

            scheduler.add_job(
                _enqueue_embedding_rebuild,
                "interval",
                minutes=max(5, int(settings.EMBEDDING_REBUILD_INTERVAL_MINUTES)),
                id="embedding_rebuild_job",
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
            )

        if settings.DISCOVERY_ENABLED:

            async def _enqueue_company_seed_careers_finder() -> None:
                await job_runner.enqueue(
                    job_type="company_seed_careers_finder",
                    payload={"limit": 50},
                    max_attempts=1,
                    dedupe_key="company_seed_careers_finder",
                )

            async def _enqueue_source_discovery_run() -> None:
                await job_runner.enqueue(
                    job_type="source_discovery_run",
                    payload={"triggered_by": "scheduler"},
                    max_attempts=1,
                    dedupe_key="source_discovery_run",
                )

            async def _enqueue_source_qualification_batch() -> None:
                await job_runner.enqueue(
                    job_type="source_qualification_batch",
                    payload={"max_items": 50},
                    max_attempts=2,
                    dedupe_key="source_qualification_batch",
                )

            async def _enqueue_source_extraction_batch() -> None:
                await job_runner.enqueue(
                    job_type="source_extraction_batch",
                    payload={"max_items": 20},
                    max_attempts=1,
                    dedupe_key="source_extraction_batch",
                )

            async def _enqueue_probation_scrape_run() -> None:
                await job_runner.enqueue(
                    job_type="probation_scrape_run",
                    payload={"limit": 100},
                    max_attempts=1,
                    dedupe_key="probation_scrape_run",
                )

            async def _enqueue_source_health_monitor() -> None:
                await job_runner.enqueue(
                    job_type="source_health_monitor",
                    payload={},
                    max_attempts=2,
                    dedupe_key="source_health_monitor",
                )

            async def _enqueue_trust_score_recompute() -> None:
                await job_runner.enqueue(
                    job_type="trust_score_recompute",
                    payload={"limit": 500},
                    max_attempts=1,
                    dedupe_key="trust_score_recompute",
                )

            scheduler.add_job(
                _enqueue_company_seed_careers_finder,
                "cron",
                hour=16,
                minute=30,
                id="company_seed_careers_finder_job",
                replace_existing=True,
            )
            scheduler.add_job(
                _enqueue_source_discovery_run,
                "cron",
                hour=17,
                minute=30,
                id="source_discovery_run_job",
                replace_existing=True,
            )
            scheduler.add_job(
                _enqueue_source_qualification_batch,
                "interval",
                hours=2,
                id="source_qualification_batch_job",
                replace_existing=True,
            )
            scheduler.add_job(
                _enqueue_source_extraction_batch,
                "interval",
                hours=4,
                id="source_extraction_batch_job",
                replace_existing=True,
            )
            scheduler.add_job(
                _enqueue_probation_scrape_run,
                "cron",
                day_of_week="sun,tue,thu",
                hour=20,
                minute=30,
                id="probation_scrape_run_job",
                replace_existing=True,
            )
            scheduler.add_job(
                _enqueue_source_health_monitor,
                "cron",
                hour=0,
                minute=30,
                id="source_health_monitor_job",
                replace_existing=True,
            )
            scheduler.add_job(
                _enqueue_trust_score_recompute,
                "cron",
                day_of_week="sat",
                hour=22,
                minute=30,
                id="trust_score_recompute_job",
                replace_existing=True,
            )

        scheduler.start()
        print("[Lifecycle] Background Scheduler started.")
    else:
        print(
            "[Lifecycle] Background Scheduler disabled (SCRAPER_AUTORUN_ENABLED=false, "
            "MLOPS_AUTORUN_ENABLED=false, ANALYTICS_WAREHOUSE_AUTORUN_ENABLED=false, "
            "EMBEDDING_AUTORUN_ENABLED=false, DISCOVERY_ENABLED=false, "
            "OPPORTUNITY_STATUS_AUTORUN_ENABLED=false)."
        )

    try:
        await refresh_freshness_metrics()
    except Exception:
        pass

    if settings.RAG_WARMUP_ON_STARTUP:
        warmup_started_at = time.perf_counter()
        try:
            await asyncio.wait_for(
                _warmup_rag_components(),
                timeout=max(10.0, float(settings.RAG_WARMUP_TIMEOUT_SECONDS)),
            )
            logger.info("RAG warmup completed in %.2fs", time.perf_counter() - warmup_started_at)
        except Exception as exc:
            logger.warning("RAG warmup skipped/failed: %s", exc)

    freshness_task: asyncio.Task[None] | None = None
    if settings.METRICS_ENABLED:
        async def _freshness_loop() -> None:
            while True:
                try:
                    await refresh_freshness_metrics()
                except Exception:
                    pass
                await asyncio.sleep(60)

        freshness_task = asyncio.create_task(_freshness_loop())

    yield
    
    # Clean up (if necessary)
    if scheduler:
        scheduler.shutdown()
    if freshness_task is not None:
        freshness_task.cancel()
    await job_runner.stop()
    await close_redis()
    client.close()


async def _warmup_rag_components() -> None:
    # Preload embeddings + vector index so first Ask AI request isn't penalized by cold starts.
    await embedding_service.embed_query("warmup query")
    await nlp_service.classify_intent("data science internships")
    await opportunity_vector_service.rebuild(force=False)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.ENVIRONMENT != "production" else None,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)

from app.api.api_v1.api import api_router
app.include_router(api_router, prefix=settings.API_V1_STR)

# Security/observability middleware (order matters)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Security Middlewares
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _run_check(name: str, checker: Any, *, required: bool = True) -> dict[str, Any]:
    timeout = max(0.25, float(settings.HEALTH_CHECK_TIMEOUT_SECONDS))
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(checker(), timeout=timeout)
        ok = bool(result.get("ok", True)) if isinstance(result, dict) else bool(result)
        detail = str(result.get("detail") or "ok") if isinstance(result, dict) else "ok"
        metadata = dict(result.get("metadata") or {}) if isinstance(result, dict) else {}
        return {
            "ok": ok,
            "required": bool(required),
            "detail": detail,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            **({"metadata": metadata} if metadata else {}),
        }
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "required": bool(required),
            "detail": f"timeout_after_{timeout}s",
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "required": bool(required),
            "detail": f"{exc.__class__.__name__}: {exc}",
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }


async def _mongo_health(request: Request) -> dict[str, Any]:
    client = getattr(request.app.state, "mongo_client", None)
    if client is None:
        return {"ok": False, "detail": "mongo_client_missing"}
    await client.admin.command("ping")
    return {"ok": True, "detail": "ping ok", "metadata": {"database": settings.MONGODB_DB_NAME}}


async def _redis_health() -> dict[str, Any]:
    redis = get_redis()
    if redis is None:
        return {"ok": False, "detail": "redis_client_unavailable"}
    pong = await redis.ping()
    return {"ok": bool(pong), "detail": "ping ok" if pong else "ping returned false"}


async def _clickhouse_health() -> dict[str, Any]:
    if not settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED:
        return {"ok": True, "detail": "disabled"}

    def _query() -> int:
        import clickhouse_connect  # type: ignore

        client = clickhouse_connect.get_client(
            host=(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST or "").strip(),
            port=int(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_PORT),
            username=settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME or "default",
            password=settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD or "",
            database=settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE,
            secure=bool(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_SECURE),
            connect_timeout=max(1, int(settings.HEALTH_CHECK_TIMEOUT_SECONDS)),
            send_receive_timeout=max(1, int(settings.HEALTH_CHECK_TIMEOUT_SECONDS)),
        )
        return int(client.query("SELECT 1").first_row[0])

    value = await asyncio.to_thread(_query)
    return {
        "ok": value == 1,
        "detail": "SELECT 1 ok",
        "metadata": {"database": settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE},
    }


async def _artifact_store_health() -> dict[str, Any]:
    bucket = (settings.MODEL_ARTIFACT_BUCKET or "").strip()
    if not bucket:
        uri = model_artifact_service.resolve_learned_ranker_uri()
        if uri.startswith("s3://"):
            from urllib.parse import urlparse

            bucket = urlparse(uri).netloc
    if not bucket:
        return {"ok": True, "detail": "not_configured"}

    def _head_bucket() -> None:
        import boto3  # type: ignore

        session = boto3.session.Session(
            aws_access_key_id=settings.MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY or None,
            region_name=settings.MLOPS_MODEL_ARTIFACT_S3_REGION or None,
        )
        client = session.client(
            "s3",
            endpoint_url=(settings.MLOPS_MODEL_ARTIFACT_S3_ENDPOINT_URL or None),
        )
        client.head_bucket(Bucket=bucket)

    await asyncio.to_thread(_head_bucket)
    return {"ok": True, "detail": "bucket head ok", "metadata": {"bucket": bucket}}


async def _queue_health() -> dict[str, Any]:
    from app.models.background_job import BackgroundJob

    pending = await BackgroundJob.find_many({"status": {"$in": ["pending", "retry", "running"]}}).count()
    dead = await BackgroundJob.find_many(BackgroundJob.status == "dead").count()
    return {
        "ok": True,
        "detail": "queue readable",
        "metadata": {"active_jobs": int(pending), "dead_jobs": int(dead)},
    }


async def _refresh_operational_metrics() -> dict[str, Any]:
    from app.models.experiment import Experiment
    from app.models.opportunity import Opportunity
    from app.services.scraper_health_service import scraper_health_service

    opportunity_count = int(await Opportunity.find_many().count())
    active_experiments = int(await Experiment.find_many({"status": {"$in": ["active", "running"]}}).count())
    scraper_health = await scraper_health_service.source_health()
    scraper_summary = dict(scraper_health.get("summary") or {})
    silent_failures = sum(int(row.get("silent_failures") or 0) for row in list(scraper_health.get("sources") or []))

    if metrics_module.OPPORTUNITY_COUNT is not None:
        metrics_module.OPPORTUNITY_COUNT.set(opportunity_count)
    if metrics_module.ACTIVE_EXPERIMENTS is not None:
        metrics_module.ACTIVE_EXPERIMENTS.set(active_experiments)
    if metrics_module.SCRAPER_RED_SOURCES is not None:
        metrics_module.SCRAPER_RED_SOURCES.set(float(scraper_summary.get("red_count") or 0))
    if metrics_module.SCRAPER_SILENT_FAILURES is not None:
        metrics_module.SCRAPER_SILENT_FAILURES.set(float(silent_failures))

    learned_ready = (not settings.LEARNED_RANKER_ENABLED) or learned_ranker.is_loaded
    if settings.LEARNED_RANKER_ENABLED and not learned_ranker.is_loaded:
        try:
            learned_ranker.reload_if_needed()
            learned_ready = learned_ranker.is_loaded
        except Exception:
            learned_ready = False
    if metrics_module.LEARNED_RANKER_MODEL_READY is not None:
        metrics_module.LEARNED_RANKER_MODEL_READY.labels(enabled=str(bool(settings.LEARNED_RANKER_ENABLED)).lower()).set(
            1.0 if learned_ready else 0.0
        )

    return {
        "opportunity_count": opportunity_count,
        "active_experiments": active_experiments,
        "scraper_health": scraper_summary,
        "scraper_silent_failures": silent_failures,
        "learned_ranker_ready": bool(learned_ready),
    }


async def _metrics_dependency(request: Request) -> Any:
    if not settings.METRICS_REQUIRE_AUTH:
        return None
    auth_header = (request.headers.get("authorization") or "").strip()
    token = None
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip() or None
    current_user = await get_current_user(request=request, token=token)
    scopes = set(getattr(current_user, "_token_scopes", []) or [])
    if "metrics:read" not in scopes:
        raise HTTPException(status_code=403, detail="Missing required scopes")
    return current_user


@app.get("/health", tags=["system"])
async def health_check(request: Request):
    """Health check endpoint for load balancers."""
    init_metrics()
    checks = {
        "mongodb": await _run_check("mongodb", lambda: _mongo_health(request), required=True),
        "redis": await _run_check("redis", _redis_health, required=bool(settings.REDIS_URL)),
        "clickhouse": await _run_check(
            "clickhouse",
            _clickhouse_health,
            required=bool(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED),
        ),
        "artifact_store": await _run_check("artifact_store", _artifact_store_health, required=False),
        "queue": await _run_check("queue", _queue_health, required=bool(settings.JOBS_ENABLED)),
    }
    operational = await _refresh_operational_metrics()
    required_ok = all(bool(payload["ok"]) for payload in checks.values() if bool(payload.get("required")))
    started_at = getattr(request.app.state, "started_at", None)
    return {
        "status": "healthy" if required_ok else "degraded",
        "environment": settings.ENVIRONMENT,
        "service": settings.PROJECT_NAME,
        "pid": os.getpid(),
        "started_at": started_at.isoformat() if isinstance(started_at, datetime) else None,
        "uptime_seconds": (
            round((datetime.now(timezone.utc) - started_at).total_seconds(), 3)
            if isinstance(started_at, datetime)
            else None
        ),
        "checks": checks,
        "operational": operational,
        "embedding": embedding_service.status(),
        "learned_ranker": {
            "enabled": bool(settings.LEARNED_RANKER_ENABLED),
            "artifact_uri": model_artifact_service.resolve_learned_ranker_uri(),
            "artifact_ready": model_artifact_service.learned_ranker_artifact_exists(),
            "artifact_checksum_sha256": bool((settings.LEARNED_RANKER_ARTIFACT_CHECKSUM_SHA256 or "").strip()),
        },
        "warehouse": {
            "enabled": bool(settings.ANALYTICS_WAREHOUSE_ENABLED),
            "export_enabled": bool(settings.ANALYTICS_WAREHOUSE_EXPORT_ENABLED),
            "export_root": settings.ANALYTICS_WAREHOUSE_EXPORT_ROOT,
            "models_dir": settings.ANALYTICS_WAREHOUSE_SQL_MODELS_DIR,
            "clickhouse_enabled": bool(settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED),
            "clickhouse_host": settings.ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST,
            "bi_tool_url": analytics_bi_tool_url(),
            "freshness": await warehouse_export_service.freshness_status(),
        },
    }

@app.get("/metrics", tags=["system"])
async def metrics_endpoint(_: Any = Depends(_metrics_dependency)):
    init_metrics()
    try:
        await _refresh_operational_metrics()
    except Exception:
        logger.exception("Failed to refresh scrape-time operational metrics")
    payload = render_metrics()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


@app.get(f"{settings.API_V1_STR}/admin/openapi.json", include_in_schema=False)
async def admin_openapi(_: Any = Depends(get_current_admin_user)) -> Any:
    """
    Authenticated OpenAPI export for operations. Public docs remain disabled in production.
    """
    return app.openapi()


@app.get(f"{settings.API_V1_STR}/admin/docs", include_in_schema=False)
async def admin_docs(_: Any = Depends(get_current_admin_user)) -> Any:
    """
    Authenticated Swagger UI for operations/debugging.
    """
    return get_swagger_ui_html(
        openapi_url=f"{settings.API_V1_STR}/admin/openapi.json",
        title=f"{settings.PROJECT_NAME} Admin Docs",
    )

@app.get("/")
def read_root():
    return {"message": "Welcome to VidyaVerse API"}
