from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import certifi
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.models.analytics_cohort_aggregate import AnalyticsCohortAggregate
from app.models.analytics_daily_aggregate import AnalyticsDailyAggregate
from app.models.analytics_funnel_aggregate import AnalyticsFunnelAggregate
from app.models.application import Application
from app.models.application_outcome import ApplicationOutcome
from app.models.ask_ai_query_snapshot import AskAIQuerySnapshot
from app.models.ask_ai_saved_query import AskAISavedQuery
from app.models.assistant_audit_event import AssistantAuditEvent
from app.models.assistant_conversation_turn import AssistantConversationTurn
from app.models.assistant_memory_state import AssistantMemoryState
from app.models.auth_abuse_state import AuthAbuseState
from app.models.auth_audit_event import AuthAuditEvent
from app.models.background_job import BackgroundJob
from app.models.duplicate_merge_event import DuplicateMergeEvent
from app.models.evaluation_run import EvaluationRun
from app.models.experiment import Experiment, ExperimentAssignment
from app.models.feature_store_row import FeatureStoreRow
from app.models.impact_event import ImpactEvent
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.mlops_incident import MlopsIncident
from app.models.model_artifact_version import ModelArtifactVersion
from app.models.model_drift_report import ModelDriftReport
from app.models.nlp_model_version import NLPModelVersion
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.otp_code import OTPCode
from app.models.post import Comment, Post
from app.models.profile import Profile
from app.models.rag_feedback_event import RAGFeedbackEvent
from app.models.rag_template_evaluation_run import RAGTemplateEvaluationRun
from app.models.rag_template_version import RAGTemplateVersion
from app.models.ranking_model_version import RankingModelVersion
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.recruiter_audit_log import RecruiterAuditLog
from app.models.scraper_run_log import ScraperRunLog
from app.models.security_event import SecurityEvent
from app.models.source_discovery import SOURCE_DISCOVERY_DOCUMENTS, create_indexes as create_source_discovery_indexes
from app.models.user import User
from app.models.user_journey import UserJourney
from app.models.vector_index_entry import VectorIndexEntry
from app.models.warehouse_export_run import WarehouseExportRun

logger = logging.getLogger(__name__)

DOCUMENT_MODELS = [
    User,
    Post,
    Comment,
    Profile,
    Opportunity,
    OpportunityInteraction,
    UserJourney,
    ApplicationOutcome,
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
    DuplicateMergeEvent,
    ScraperRunLog,
    *SOURCE_DISCOVERY_DOCUMENTS,
]


def mongo_client_kwargs() -> dict[str, Any]:
    url = (settings.MONGODB_URL or "").strip()
    tls_needed = bool(
        settings.MONGODB_TLS_FORCE
        or settings.ENVIRONMENT.strip().lower() == "production"
        or url.startswith("mongodb+srv://")
        or "tls=true" in url.lower()
    )
    kwargs: dict[str, Any] = {}
    if tls_needed:
        kwargs.update(
            {
                "tls": True,
                "tlsCAFile": certifi.where(),
                "tlsAllowInvalidCertificates": bool(settings.MONGODB_TLS_ALLOW_INVALID_CERTS),
            }
        )
    kwargs.update(
        {
            "serverSelectionTimeoutMS": max(1000, int(settings.MONGODB_SERVER_SELECTION_TIMEOUT_MS)),
            "connectTimeoutMS": max(1000, int(settings.MONGODB_CONNECT_TIMEOUT_MS)),
            "socketTimeoutMS": max(1000, int(settings.MONGODB_SOCKET_TIMEOUT_MS)),
        }
    )
    return kwargs


def mongo_ping_timeout_seconds() -> float:
    return max(3.0, float(settings.MONGODB_SERVER_SELECTION_TIMEOUT_MS) / 1000.0 + 2.0)


async def connect_mongo_with_retries() -> AsyncIOMotorClient:
    startup_retries = max(1, int(settings.MONGODB_STARTUP_MAX_RETRIES))
    startup_backoff = max(0.25, float(settings.MONGODB_STARTUP_RETRY_BACKOFF_SECONDS))
    timeout = mongo_ping_timeout_seconds()
    last_error: Exception | None = None

    for attempt in range(1, startup_retries + 1):
        client: Optional[AsyncIOMotorClient] = AsyncIOMotorClient(settings.MONGODB_URL, **mongo_client_kwargs())
        try:
            await asyncio.wait_for(client.admin.command("ping"), timeout=timeout)
            logger.info("MongoDB ping succeeded on startup attempt %s/%s", attempt, startup_retries)
            return client
        except Exception as exc:
            last_error = exc
            logger.error("MongoDB startup ping failed on attempt %s/%s: %s", attempt, startup_retries, exc)
            client.close()
            if attempt >= startup_retries:
                raise RuntimeError("MongoDB unavailable during startup; aborting runtime boot.") from exc
            await asyncio.sleep(startup_backoff * attempt)

    raise RuntimeError(f"MongoDB client initialization failed after {startup_retries} attempts: {last_error}")


async def init_database() -> AsyncIOMotorClient:
    client = await connect_mongo_with_retries()
    database = client[settings.MONGODB_DB_NAME]
    await _drop_incompatible_bootstrap_indexes(database)
    timeout = max(10.0, mongo_ping_timeout_seconds() * 2.0)
    await asyncio.wait_for(
        init_beanie(
            database=database,
            document_models=DOCUMENT_MODELS,
        ),
        timeout=timeout,
    )
    await create_source_discovery_indexes()
    return client


async def _drop_incompatible_bootstrap_indexes(database: Any) -> None:
    """
    Resolve safe, known index option migrations before Beanie initialization.

    PyMongo raises IndexOptionsConflict when an index exists with the same key
    and name but different options. Dropping the index, not the collection,
    lets Beanie recreate the intended retention policy without touching data.
    """
    migrations = [
        {
            "collection": "auth_audit_events",
            "index": "created_at_1",
            "expected": {"expireAfterSeconds": 90 * 24 * 60 * 60},
        },
    ]
    for migration in migrations:
        collection = database[migration["collection"]]
        index_name = str(migration["index"])
        expected = dict(migration["expected"])
        try:
            indexes = await collection.index_information()
            current = indexes.get(index_name)
            if not current:
                continue
            if all(current.get(key) == value for key, value in expected.items()):
                continue
            await collection.drop_index(index_name)
            logger.info(
                "Dropped incompatible Mongo index before bootstrap: %s.%s",
                migration["collection"],
                index_name,
            )
        except Exception as exc:
            logger.warning(
                "Unable to preflight Mongo index %s.%s: %s",
                migration["collection"],
                index_name,
                exc,
            )
