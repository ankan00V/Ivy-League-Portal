import asyncio
import logging
import time
from typing import Any, Optional

from fastapi import Depends, FastAPI, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import auth_cookie_only_mode_enabled, resolved_csp_value, settings

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
import certifi

# Import all Beanie Documents
from app.models.user import User
from app.models.post import Post, Comment
from app.models.profile import Profile
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.application import Application
from app.models.otp_code import OTPCode
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.evaluation_run import EvaluationRun
from app.models.impact_event import ImpactEvent
from app.models.experiment import Experiment, ExperimentAssignment
from app.models.model_drift_report import ModelDriftReport
from app.models.nlp_model_version import NLPModelVersion
from app.models.rag_feedback_event import RAGFeedbackEvent
from app.models.ask_ai_query_snapshot import AskAIQuerySnapshot
from app.models.ask_ai_saved_query import AskAISavedQuery
from app.models.rag_template_version import RAGTemplateVersion
from app.models.rag_template_evaluation_run import RAGTemplateEvaluationRun
from app.models.ranking_model_version import RankingModelVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.vector_index_entry import VectorIndexEntry
from app.models.background_job import BackgroundJob
from app.models.recruiter_audit_log import RecruiterAuditLog
from app.models.auth_audit_event import AuthAuditEvent
from app.models.auth_abuse_state import AuthAbuseState
from app.models.analytics_daily_aggregate import AnalyticsDailyAggregate
from app.models.analytics_funnel_aggregate import AnalyticsFunnelAggregate
from app.models.analytics_cohort_aggregate import AnalyticsCohortAggregate
from app.models.feature_store_row import FeatureStoreRow
from app.models.mlops_incident import MlopsIncident
from app.models.assistant_conversation_turn import AssistantConversationTurn
from app.models.assistant_memory_state import AssistantMemoryState
from app.models.assistant_audit_event import AssistantAuditEvent
from app.models.model_artifact_version import ModelArtifactVersion
from app.models.warehouse_export_run import WarehouseExportRun
from app.models.security_event import SecurityEvent

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.experiment_service import experiment_service
from app.services.rag_template_registry_service import rag_template_registry_service
from app.services.ranking_model_service import ranking_model_service
from app.services.admin_identity_service import ensure_single_admin_identity
 
from app.services.job_runner import job_runner, register_default_jobs
from app.services.system_metrics import refresh_freshness_metrics
from app.services.embedding_service import embedding_service
from app.services.nlp_service import nlp_service
from app.services.model_artifact_service import model_artifact_service
from app.services.vector_service import opportunity_vector_service
from app.core.redis import close_redis
from app.core.metrics import CONTENT_TYPE_LATEST, init_metrics, render_metrics
from app.core.http_middleware import (
    CSRFMiddleware,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.deps import get_current_admin_user, require_scopes

logger = logging.getLogger(__name__)


def _has_wildcard(values: list[str]) -> bool:
    return any(str(value).strip() == "*" for value in list(values or []))


def _csp_has_unsafe_tokens(csp_value: str) -> bool:
    normalized = str(csp_value or "").lower()
    return "'unsafe-inline'" in normalized or "'unsafe-eval'" in normalized


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENVIRONMENT.strip().lower() == "production":
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

    # Initialize MongoDB connection using explicit cert verification parameters
    mongo_kwargs = {}
    url = (settings.MONGODB_URL or "").strip()
    tls_needed = bool(
        settings.MONGODB_TLS_FORCE
        or settings.ENVIRONMENT.strip().lower() == "production"
        or url.startswith("mongodb+srv://")
        or "tls=true" in url.lower()
    )
    if tls_needed:
        mongo_kwargs.update(
            {
                "tls": True,
                "tlsCAFile": certifi.where(),
                "tlsAllowInvalidCertificates": bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS),
            }
        )

    mongo_kwargs.update(
        {
            "serverSelectionTimeoutMS": max(1000, int(settings.MONGODB_SERVER_SELECTION_TIMEOUT_MS)),
            "connectTimeoutMS": max(1000, int(settings.MONGODB_CONNECT_TIMEOUT_MS)),
            "socketTimeoutMS": max(1000, int(settings.MONGODB_SOCKET_TIMEOUT_MS)),
        }
    )

    startup_retries = max(1, int(settings.MONGODB_STARTUP_MAX_RETRIES))
    startup_backoff = max(0.25, float(settings.MONGODB_STARTUP_RETRY_BACKOFF_SECONDS))
    ping_timeout_seconds = max(
        3.0,
        float(settings.MONGODB_SERVER_SELECTION_TIMEOUT_MS) / 1000.0 + 2.0,
    )

    client: Optional[AsyncIOMotorClient] = None
    last_mongo_error: Exception | None = None
    for attempt in range(1, startup_retries + 1):
        client = AsyncIOMotorClient(settings.MONGODB_URL, **mongo_kwargs)
        try:
            await asyncio.wait_for(client.admin.command("ping"), timeout=ping_timeout_seconds)
            logger.info("MongoDB ping succeeded on startup attempt %s/%s", attempt, startup_retries)
            break
        except Exception as exc:
            last_mongo_error = exc
            logger.error(
                "MongoDB startup ping failed on attempt %s/%s: %s",
                attempt,
                startup_retries,
                exc,
            )
            client.close()
            client = None
            if attempt >= startup_retries:
                raise RuntimeError("MongoDB unavailable during startup; aborting API boot.") from exc
            await asyncio.sleep(startup_backoff * attempt)
    if client is None:
        raise RuntimeError(
            f"MongoDB client initialization failed after {startup_retries} attempts: {last_mongo_error}"
        )
    
    # Initialize Beanie ODM with the database and document models
    await asyncio.wait_for(
        init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            User,
            Post,
            Comment,
            Profile,
            Opportunity,
            OpportunityInteraction,
            Application,
            OTPCode,
            KnowledgeChunk,
            EvaluationRun,
            ImpactEvent,
            Experiment,
            ExperimentAssignment,
            RankingModelVersion,
            NLPModelVersion,
            ModelDriftReport,
            RankingRequestTelemetry,
            RAGFeedbackEvent,
            AskAIQuerySnapshot,
            AskAISavedQuery,
            RAGTemplateVersion,
            RAGTemplateEvaluationRun,
            VectorIndexEntry,
            BackgroundJob,
            RecruiterAuditLog,
            AuthAuditEvent,
            AuthAbuseState,
            AnalyticsDailyAggregate,
            AnalyticsFunnelAggregate,
            AnalyticsCohortAggregate,
            FeatureStoreRow,
            MlopsIncident,
            AssistantConversationTurn,
            AssistantMemoryState,
            AssistantAuditEvent,
            ModelArtifactVersion,
            WarehouseExportRun,
            SecurityEvent,
        ]
        ),
        timeout=max(10.0, ping_timeout_seconds * 2.0),
    )
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
    if settings.SCRAPER_AUTORUN_ENABLED or settings.MLOPS_AUTORUN_ENABLED or settings.ANALYTICS_WAREHOUSE_AUTORUN_ENABLED:
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

            scheduler.add_job(
                _enqueue_scraper,
                "interval",
                minutes=max(1, settings.SCRAPER_INTERVAL_MINUTES),
                id="scraper_job",
                replace_existing=True,
                next_run_time=datetime.now(timezone.utc),
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

        scheduler.start()
        print("[Lifecycle] Background Scheduler started.")
    else:
        print(
            "[Lifecycle] Background Scheduler disabled (SCRAPER_AUTORUN_ENABLED=false, "
            "MLOPS_AUTORUN_ENABLED=false, ANALYTICS_WAREHOUSE_AUTORUN_ENABLED=false)."
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

@app.get("/health", tags=["system"])
def health_check():
    """Health check endpoint for load balancers."""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
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
        },
    }

@app.get("/metrics", tags=["system"])
async def metrics_endpoint(_: Any = Depends(require_scopes(["metrics:read"]))):  # type: ignore[name-defined]
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
