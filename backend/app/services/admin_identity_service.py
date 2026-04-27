from __future__ import annotations

from beanie.exceptions import CollectionWasNotInitialized

from app.core.config import settings
from app.core.security import get_password_hash
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
from app.services.totp_service import encrypt_secret, normalize_totp_secret
from app.services.username_service import ensure_system_username


def reserved_admin_email() -> str:
    return str(settings.ADMIN_BOOTSTRAP_EMAIL or "").strip().lower()


def is_reserved_admin_email(email: str | None) -> bool:
    candidate = str(email or "").strip().lower()
    return bool(candidate) and candidate == reserved_admin_email()


def _require_secret(value: str | None, *, env_name: str) -> str:
    normalized = str(value or "").strip()
    if normalized:
        return normalized
    raise RuntimeError(
        f"{env_name} must be configured when ADMIN_BOOTSTRAP_ENABLED=true. "
        "Set it via environment secrets and restart the API."
    )


async def _safe_delete_many(model: type, *filters: object) -> None:
    try:
        await model.find_many(*filters).delete()
    except CollectionWasNotInitialized:
        return


async def _delete_posts_and_comments(user_id: object) -> None:
    try:
        posts = await Post.find_many(Post.user_id == user_id).to_list()
    except CollectionWasNotInitialized:
        posts = []

    for post in posts:
        await _safe_delete_many(Comment, Comment.post_id == post.id)
    await _safe_delete_many(Post, Post.user_id == user_id)
    await _safe_delete_many(Comment, Comment.user_id == user_id)


async def _cleanup_user_artifacts(user: User) -> None:
    user_id = user.id
    user_id_str = str(user_id)
    email = str(user.email or "").strip().lower()

    await _safe_delete_many(Profile, Profile.user_id == user_id)
    await _safe_delete_many(Application, Application.user_id == user_id)
    await _safe_delete_many(OpportunityInteraction, OpportunityInteraction.user_id == user_id)
    await _safe_delete_many(AskAIQuerySnapshot, AskAIQuerySnapshot.user_id == user_id)
    await _safe_delete_many(AskAISavedQuery, AskAISavedQuery.user_id == user_id)
    await _safe_delete_many(RAGFeedbackEvent, RAGFeedbackEvent.user_id == user_id)
    await _safe_delete_many(RecruiterAuditLog, RecruiterAuditLog.recruiter_user_id == user_id)
    await _safe_delete_many(ExperimentAssignment, ExperimentAssignment.user_id == user_id)
    await _safe_delete_many(RankingRequestTelemetry, RankingRequestTelemetry.user_id == user_id)
    await _safe_delete_many(FeatureStoreRow, FeatureStoreRow.user_id == user_id_str)
    await _safe_delete_many(ImpactEvent, ImpactEvent.user_id == user_id_str)
    await _safe_delete_many(AuthAuditEvent, AuthAuditEvent.user_id == user_id)
    await _safe_delete_many(AuthAbuseState, AuthAbuseState.email == email)
    await _delete_posts_and_comments(user_id)


async def _demote_non_reserved_admins(admin_email: str) -> None:
    try:
        users = await User.find_many(User.is_admin == True).to_list()  # noqa: E712
    except CollectionWasNotInitialized:
        return
    for row in users:
        if str(row.email or "").strip().lower() == admin_email:
            continue
        row.is_admin = False
        await row.save()


async def ensure_single_admin_identity() -> None:
    if not bool(settings.ADMIN_BOOTSTRAP_ENABLED):
        return

    admin_email = reserved_admin_email()
    if not admin_email:
        raise RuntimeError("ADMIN_BOOTSTRAP_EMAIL cannot be empty when ADMIN_BOOTSTRAP_ENABLED=true")

    admin_password = _require_secret(settings.ADMIN_BOOTSTRAP_PASSWORD, env_name="ADMIN_BOOTSTRAP_PASSWORD")
    totp_secret = _require_secret(settings.ADMIN_TOTP_SECRET, env_name="ADMIN_TOTP_SECRET")
    normalized_totp_secret = normalize_totp_secret(totp_secret)
    encrypted_totp_secret = encrypt_secret(normalized_totp_secret)

    try:
        existing = await User.find_one(User.email == admin_email)
    except CollectionWasNotInitialized:
        return

    if existing and not bool(existing.is_admin):
        # Convert reserved identity from user space into admin-only identity.
        await _cleanup_user_artifacts(existing)
        await existing.delete()
        existing = None

    hashed_password = get_password_hash(admin_password)
    if existing is None:
        admin = User(
            email=admin_email,
            full_name="Platform Administrator",
            hashed_password=hashed_password,
            account_type="candidate",
            auth_provider="password",
            is_active=True,
            is_admin=True,
            totp_enabled=True,
            totp_secret_encrypted=encrypted_totp_secret,
        )
        await admin.insert()
        await ensure_system_username(admin)
    else:
        existing.is_admin = True
        existing.is_active = True
        existing.auth_provider = "password"
        existing.account_type = "candidate"
        existing.hashed_password = hashed_password
        existing.totp_enabled = True
        existing.totp_secret_encrypted = encrypted_totp_secret
        if not (existing.full_name or "").strip():
            existing.full_name = "Platform Administrator"
        await existing.save()
        await ensure_system_username(existing)

    await _demote_non_reserved_admins(admin_email)
