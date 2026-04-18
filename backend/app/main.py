import asyncio
from typing import Any

from fastapi import Depends, FastAPI, Response
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import settings

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
from app.models.ranking_model_version import RankingModelVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.vector_index_entry import VectorIndexEntry
from app.models.background_job import BackgroundJob

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.experiment_service import experiment_service
from app.services.ranking_model_service import ranking_model_service
 
from app.services.job_runner import job_runner, register_default_jobs
from app.services.system_metrics import refresh_freshness_metrics
from app.core.redis import close_redis
from app.core.metrics import CONTENT_TYPE_LATEST, init_metrics, render_metrics
from app.core.http_middleware import ObservabilityMiddleware, RateLimitMiddleware
from app.api.deps import get_current_admin_user, require_scopes

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENVIRONMENT.strip().lower() == "production":
        if settings.SECRET_KEY.startswith("your_super_secret_key_here"):
            raise RuntimeError("SECRET_KEY must be set via environment in production.")
        if bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS):
            raise RuntimeError("MONGODB_TLS_ALLOW_INVALID_CERTS must be false in production.")

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

    client = AsyncIOMotorClient(settings.MONGODB_URL, **mongo_kwargs)
    
    # Initialize Beanie ODM with the database and document models
    await init_beanie(
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
            VectorIndexEntry,
            BackgroundJob,
        ]
    )
    try:
        init_metrics()
    except Exception:
        pass
    try:
        await experiment_service.ensure_defaults()
    except Exception as exc:
        print(f"[Lifecycle] Experiment defaults init failed: {exc}")
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
    if settings.SCRAPER_AUTORUN_ENABLED or settings.MLOPS_AUTORUN_ENABLED:
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

        scheduler.start()
        print("[Lifecycle] Background Scheduler started.")
    else:
        print("[Lifecycle] Background Scheduler disabled (SCRAPER_AUTORUN_ENABLED=false and MLOPS_AUTORUN_ENABLED=false).")

    try:
        await refresh_freshness_metrics()
    except Exception:
        pass

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
        try:
            await freshness_task
        except Exception:
            pass
    await job_runner.stop()
    await close_redis()
    client.close()

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
    return {"status": "healthy", "environment": settings.ENVIRONMENT}

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
