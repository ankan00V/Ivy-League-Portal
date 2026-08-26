"""Account erasure: what happens to a student's data when they leave.

Until this module existed there was no way out of VidyaVerse. A student handed us
their mobile number, college, addresses and an original resume file, and nothing in
the codebase could give any of it back. `grep` for `delete_account`, `erasure`,
`gdpr`, `retention` or `purge` across `backend/app` and `frontend/src` returned
zero hits. Our primary audience is Indian students, so the operative regime is the
DPDP Act 2023, which grants erasure; the GDPR Art. 17 equivalent applies to any EEA
user. Either way the engineering obligation is the same.

Two dispositions, and the split is deliberate.

**ERASE** — the row *is about the person* and has no meaning once they leave. Their
profile, their posts, their applications, their saved queries, their assistant
conversations. These are hard-deleted.

**PSEUDONYMIZE** — the row is a *measurement* whose statistical value outlives the
person: impressions, exposures, feature snapshots, experiment assignments. Deleting
these would silently rewrite historical experiment results and training sets. This
repo has twice published numbers that turned out to be artefacts of its own data
handling (see `app/models/traffic.py`), so quietly mutating the measurement record
on every account deletion is exactly the failure mode to avoid. Instead the row
survives with its `user_id` replaced by a pseudonym that maps to no account.

The pseudonym is a **freshly generated ObjectId**, not a hash of the real id. A hash
is reversible by anyone holding the user list, which is precisely the party we are
protecting against. One pseudonym is generated per deletion and reused across every
collection, so cross-collection cohort joins still work while the chain back to a
person is severed.

`User` is deleted **last**. If the process dies halfway the account still exists and
the deletion can be retried; the reverse order would strand orphaned data behind a
login that no longer resolves.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from beanie import Document, PydanticObjectId

from app.models.application import Application
from app.models.skill_assessment import SkillAssessment
from app.models.application_outcome import ApplicationOutcome
from app.models.ask_ai_query_snapshot import AskAIQuerySnapshot
from app.models.ask_ai_saved_query import AskAISavedQuery
from app.models.assistant_audit_event import AssistantAuditEvent
from app.models.assistant_conversation_turn import AssistantConversationTurn
from app.models.assistant_memory_state import AssistantMemoryState
from app.models.auth_audit_event import AuthAuditEvent
from app.models.evaluation_run import EvaluationRun
from app.models.experiment import ExperimentAssignment
from app.models.feature_store_row import FeatureStoreRow
from app.models.impact_event import ImpactEvent
from app.models.opportunity import Opportunity
from app.models.opportunity_interaction import OpportunityInteraction
from app.models.otp_code import OTPCode
from app.models.post import Comment, Post
from app.models.profile import Profile
from app.models.recruiter_audit_log import RecruiterAuditLog
from app.models.source_discovery import EmployerCareersClaim
from app.models.rag_feedback_event import RAGFeedbackEvent
from app.models.ranking_request_telemetry import RankingRequestTelemetry
from app.models.recommendation_funnel import (
    CareerOutcomeEvent,
    RecommendationExposure,
    RecommendationFeatureSnapshot,
    RecommendationFeedback,
    RecommendationSession,
)
from app.models.user import User
from app.models.user_journey import UserJourney
from app.services.telemetry_privacy import get_collection

logger = logging.getLogger(__name__)

Disposition = Literal["erase", "pseudonymize"]


@dataclass(frozen=True)
class ErasureRule:
    """How one collection responds to an account deletion."""

    document: type[Document]
    disposition: Disposition
    #: Every field on this document that points at the departing user. Most
    #: collections have exactly one; `Opportunity` has two (poster and reviewer).
    user_fields: tuple[str, ...] = ("user_id",)
    #: What we match on. A few collections predate the user row and are keyed by
    #: email instead of id — OTP codes are issued before an account exists.
    match_by: Literal["user_id", "email"] = "user_id"
    #: True when the collection stores the user id as a string rather than an
    #: ObjectId. `ImpactEvent` and `FeatureStoreRow` both do.
    user_id_as_str: bool = False
    #: Free-text fields that can carry personal data the user typed themselves.
    #: Cleared on pseudonymize; irrelevant on erase because the row is gone.
    redact_fields: tuple[str, ...] = field(default_factory=tuple)
    #: Why this disposition, in one line. Surfaced by the sweep test so a future
    #: reader has to justify each classification rather than copy the neighbour.
    rationale: str = ""


#: The single source of truth for account erasure.
#:
#: `tests/test_account_deletion.py` sweeps `bootstrap.DOCUMENT_MODELS` and fails if
#: any registered document carries a user identifier that is not listed here. Adding
#: a user-scoped collection without deciding its disposition is a build failure, not
#: a silent data-retention bug.
ERASURE_RULES: tuple[ErasureRule, ...] = (
    # --- Identity and user-authored content: hard delete -------------------
    ErasureRule(
        document=Profile,
        disposition="erase",
        rationale="The profile is the person: name, mobile, college, addresses, resume pointer.",
    ),
    ErasureRule(
        document=Post,
        disposition="erase",
        rationale="User-authored content.",
    ),
    ErasureRule(
        document=Comment,
        disposition="erase",
        rationale="User-authored content.",
    ),
    ErasureRule(
        document=Application,
        disposition="erase",
        rationale="An application is a statement of intent by a named person to a named employer.",
    ),
    ErasureRule(
        document=SkillAssessment,
        disposition="erase",
        rationale=(
            "A self-assessment is the person's own account of what they can and "
            "cannot do, plus the gaps derived from it. Nothing downstream needs "
            "it once they leave, and aggregate skill demand is computed from "
            "postings rather than from students, so erasing costs no analytics."
        ),
    ),
    ErasureRule(
        document=ApplicationOutcome,
        disposition="erase",
        rationale="Career outcomes are among the most sensitive rows we hold.",
    ),
    ErasureRule(
        document=AskAISavedQuery,
        disposition="erase",
        rationale="Saved queries are free text the student wrote and expected to control.",
    ),
    ErasureRule(
        document=AskAIQuerySnapshot,
        disposition="erase",
        rationale="Snapshots embed the query verbatim; pseudonymizing the id would not redact the text.",
    ),
    ErasureRule(
        document=AssistantConversationTurn,
        disposition="erase",
        rationale="Conversation transcripts.",
    ),
    ErasureRule(
        document=AssistantMemoryState,
        disposition="erase",
        rationale="Derived long-term memory about the person.",
    ),
    ErasureRule(
        document=AssistantAuditEvent,
        disposition="erase",
        rationale="Assistant audit rows reference conversations that no longer exist.",
    ),
    ErasureRule(
        document=UserJourney,
        disposition="erase",
        rationale="A per-person narrative of everything they did on the product.",
    ),
    ErasureRule(
        document=RAGFeedbackEvent,
        disposition="erase",
        rationale="Feedback text is user-authored and low volume; no measurement depends on it.",
    ),
    # --- Measurements: keep the row, sever the person ----------------------
    ErasureRule(
        document=OpportunityInteraction,
        disposition="pseudonymize",
        redact_fields=("query",),
        rationale="The ranking measurement record. Deleting rows would retroactively alter experiment results.",
    ),
    ErasureRule(
        document=RankingRequestTelemetry,
        disposition="pseudonymize",
        rationale="Per-request serving telemetry; carries no free text.",
    ),
    ErasureRule(
        document=RecommendationSession,
        disposition="pseudonymize",
        rationale="Funnel integrity depends on sessions remaining countable.",
    ),
    ErasureRule(
        document=RecommendationExposure,
        disposition="pseudonymize",
        rationale="Immutable exposure log; the whole point is that it is not rewritten.",
    ),
    ErasureRule(
        document=RecommendationFeatureSnapshot,
        disposition="pseudonymize",
        rationale="Frozen numeric features used for training reproducibility.",
    ),
    ErasureRule(
        document=RecommendationFeedback,
        disposition="pseudonymize",
        redact_fields=("comment",),
        rationale=(
            "The hide/negative signal feeds ranking, so the row stays. `reason` is a "
            "closed enum and safe to keep; `comment` is free text and is cleared."
        ),
    ),
    ErasureRule(
        document=CareerOutcomeEvent,
        disposition="pseudonymize",
        rationale="Matured labels; deleting them would bias any model trained afterwards.",
    ),
    ErasureRule(
        document=ExperimentAssignment,
        disposition="pseudonymize",
        rationale="Removing an assignment changes a variant's denominator after the fact.",
    ),
    ErasureRule(
        document=FeatureStoreRow,
        disposition="pseudonymize",
        user_id_as_str=True,
        rationale="Offline training rows; user id is stored as a string here.",
    ),
    ErasureRule(
        document=ImpactEvent,
        disposition="pseudonymize",
        user_id_as_str=True,
        rationale="Aggregate impact reporting; user id is stored as a string here.",
    ),
    ErasureRule(
        document=AuthAuditEvent,
        disposition="pseudonymize",
        redact_fields=("email", "user_agent"),
        rationale=(
            "Deliberately not erased: otherwise deleting an account would wipe its own "
            "abuse trail. Identity is severed (user_id pseudonymized, email and "
            "user_agent cleared) while ip_address and lock state survive for abuse "
            "defence, and the collection's 90-day TTL retires the row on its own."
        ),
    ),
    ErasureRule(
        document=RecruiterAuditLog,
        disposition="pseudonymize",
        user_fields=("recruiter_user_id",),
        rationale="Audit logs must not develop holes; the actor link is severed instead.",
    ),
    ErasureRule(
        document=EvaluationRun,
        disposition="pseudonymize",
        user_fields=("created_by_user_id",),
        rationale="Benchmark provenance survives; the operator who triggered it is unlinked.",
    ),
    ErasureRule(
        document=EmployerCareersClaim,
        disposition="pseudonymize",
        user_fields=("employer_user_id",),
        rationale="A source claim already promoted into discovery cannot be silently revoked.",
    ),
    ErasureRule(
        document=Opportunity,
        disposition="pseudonymize",
        user_fields=("posted_by_user_id", "reviewed_by_user_id"),
        rationale=(
            "Listings outlive the accounts that posted or reviewed them, and AGENTS.md "
            "forbids hard-deleting opportunity rows. Only the person link is removed."
        ),
    ),
    # --- Keyed by email rather than user id --------------------------------
    ErasureRule(
        document=OTPCode,
        disposition="erase",
        user_fields=("email",),
        match_by="email",
        rationale=(
            "Issued before an account exists, so it is keyed by email. Self-expires via "
            "TTL, but a departing user should not have to wait for that."
        ),
    ),
)


#: Collections that carry a user-ish field but are deliberately **not** part of
#: erasure. The sweep test reads this map, so skipping a collection requires
#: writing down why rather than quietly leaving it off the list.
ERASURE_EXEMPTIONS: dict[str, str] = {
    "users": (
        "Handled directly by erase_account, which deletes the User row last so a "
        "mid-flight failure leaves a retryable account rather than orphaned data."
    ),
    "auth_abuse_states": (
        "Retained on purpose. The lock is keyed by email, so erasing it would turn "
        "delete-then-reregister into a lock bypass. It carries no profile data and "
        "clears itself at lock_until."
    ),
    "mlops_incidents": (
        "`owner` is an on-call operator address from configuration, not a student "
        "account."
    ),
    "analytics_cohort_aggregates": (
        "Stores counts (users_in_cohort, active_users), not identifiers."
    ),
}


@dataclass
class ErasureReceipt:
    """What actually happened, per collection. Returned to the caller and logged."""

    user_id: str
    pseudonym: str
    erased: dict[str, int] = field(default_factory=dict)
    pseudonymized: dict[str, int] = field(default_factory=dict)
    resume_file_removed: bool = False
    sessions_revoked: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "pseudonym": self.pseudonym,
            "erased": dict(self.erased),
            "pseudonymized": dict(self.pseudonymized),
            "resume_file_removed": self.resume_file_removed,
            "sessions_revoked": self.sessions_revoked,
            "total_rows_erased": sum(self.erased.values()),
            "total_rows_pseudonymized": sum(self.pseudonymized.values()),
        }


def _collection_name(document: type[Document]) -> str:
    settings = getattr(document, "Settings", None)
    return str(getattr(settings, "name", document.__name__))




async def _apply_rule(
    rule: ErasureRule,
    *,
    user_id: PydanticObjectId,
    email: str | None,
    pseudonym: PydanticObjectId,
    receipt: ErasureReceipt,
) -> None:
    collection = _collection_name(rule.document)

    if rule.match_by == "email":
        if not (email or "").strip():
            return
        match_value: Any = email
    else:
        match_value = str(user_id) if rule.user_id_as_str else user_id

    # Deliberately NOT wrapped in a try/except that continues.
    #
    # It was, and that was a real defect: Beanie 2.x renamed `get_motor_collection`,
    # so every rule raised AttributeError, every rule was "skipped" with a warning,
    # and `erase_account` returned a success receipt having deleted nothing. A
    # deletion endpoint that reports success without deleting is precisely the
    # silent-failure shape this whole change set exists to remove, so an
    # unreachable collection now aborts the erasure loudly and the caller retries.
    motor_collection = get_collection(rule.document)

    # Each user field is handled independently: a row can reference the departing
    # user through more than one of them (an employer who posted an opportunity and
    # later reviewed it), and the same row must be cleaned on every path.
    for user_field in rule.user_fields:
        query = {user_field: match_value}

        if rule.disposition == "erase":
            result = await motor_collection.delete_many(query)
            count = int(getattr(result, "deleted_count", 0) or 0)
            if count:
                receipt.erased[collection] = receipt.erased.get(collection, 0) + count
            continue

        updates: dict[str, Any] = {
            user_field: str(pseudonym) if rule.user_id_as_str else pseudonym,
        }
        for redacted in rule.redact_fields:
            updates[redacted] = None

        result = await motor_collection.update_many(query, {"$set": updates})
        count = int(getattr(result, "modified_count", 0) or 0)
        if count:
            receipt.pseudonymized[collection] = receipt.pseudonymized.get(collection, 0) + count


async def erase_account(user: User) -> ErasureReceipt:
    """Erase a user end to end and return a receipt of what was touched.

    Order is load-bearing: content and measurements first, `User` last, so a crash
    leaves a still-valid account that can retry rather than orphaned rows behind a
    dead login.
    """
    user_id = user.id
    if user_id is None:
        raise ValueError("Cannot erase a user that has not been persisted.")

    pseudonym = PydanticObjectId()
    email = (getattr(user, "email", None) or "").strip() or None
    receipt = ErasureReceipt(user_id=str(user_id), pseudonym=str(pseudonym))

    receipt.resume_file_removed = await _remove_resume_file(user_id)

    for rule in ERASURE_RULES:
        await _apply_rule(
            rule,
            user_id=user_id,
            email=email,
            pseudonym=pseudonym,
            receipt=receipt,
        )

    receipt.sessions_revoked = await _revoke_sessions(str(user_id))
    await _invalidate_caches(str(user_id))

    await user.delete()
    receipt.erased[_collection_name(User)] = 1

    logger.info("Account erased: %s", receipt.as_dict())
    return receipt


async def _remove_resume_file(user_id: PydanticObjectId) -> bool:
    """Delete the stored resume from disk before the profile row that points at it."""
    try:
        profile = await Profile.find_one(Profile.user_id == user_id)
    except Exception as exc:
        logger.warning("Could not load profile for resume removal: %s", exc)
        return False

    storage_key = (getattr(profile, "resume_storage_key", None) or "").strip() if profile else ""
    if not storage_key:
        return False

    # Imported lazily: the endpoint module owns the storage location, and importing
    # it at module scope would create a cycle (endpoint -> service -> endpoint).
    from app.api.api_v1.endpoints.users import _resume_storage_dir

    try:
        path = _resume_storage_dir() / storage_key
        if path.exists():
            path.unlink(missing_ok=True)
            return True
    except Exception as exc:
        logger.warning("Failed to remove stored resume during erasure: %s", exc)
    return False


async def _revoke_sessions(user_id: str) -> int:
    try:
        from app.services.session_security_service import session_security_service

        return int(await session_security_service.invalidate_user_sessions(user_id) or 0)
    except Exception as exc:
        logger.warning("Session revocation during erasure failed for %s: %s", user_id, exc)
        return 0


async def _invalidate_caches(user_id: str) -> None:
    try:
        from app.core.cache import cache_manager

        await cache_manager.invalidate_after_profile_update(user_id=user_id)
    except Exception as exc:
        logger.warning("Cache invalidation during erasure failed for %s: %s", user_id, exc)
