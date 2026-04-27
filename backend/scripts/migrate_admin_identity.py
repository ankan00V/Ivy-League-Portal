from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.models.application import Application
from app.models.ask_ai_query_snapshot import AskAIQuerySnapshot
from app.models.ask_ai_saved_query import AskAISavedQuery
from app.models.auth_abuse_state import AuthAbuseState
from app.models.auth_audit_event import AuthAuditEvent
from app.models.experiment import ExperimentAssignment
from app.models.feature_store_row import FeatureStoreRow
from app.models.impact_event import ImpactEvent
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.post import Comment, Post
from app.models.profile import Profile
from app.models.rag_feedback_event import RAGFeedbackEvent
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.recruiter_audit_log import RecruiterAuditLog
from app.models.user import User
from app.services.admin_identity_service import ensure_single_admin_identity


async def run() -> None:
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            User,
            Profile,
            Application,
            OpportunityInteraction,
            AskAIQuerySnapshot,
            AskAISavedQuery,
            RAGFeedbackEvent,
            RecruiterAuditLog,
            ExperimentAssignment,
            RankingRequestTelemetry,
            FeatureStoreRow,
            ImpactEvent,
            Post,
            Comment,
            AuthAuditEvent,
            AuthAbuseState,
        ],
    )
    await ensure_single_admin_identity()
    print("Admin identity migration completed.")
    client.close()


if __name__ == "__main__":
    asyncio.run(run())
