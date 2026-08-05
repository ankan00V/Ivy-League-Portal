"""Make `consent_data_processing` mean something.

The flag already existed. It was stored on the profile, counted toward profile
completeness, and labelled in the UI as "Accept privacy and data processing policy"
— and then nothing anywhere read it. No pipeline checked it, no export honoured it,
and the policy it referred to did not exist. A consent control that changes no
behaviour is the cookie-banner pattern Privacy Guides describes: it moves the
burden onto the user and delivers nothing in return.

What the flag now governs, and what it deliberately does not:

**Governed — analytics processing.** Warehouse exports (DuckDB/ClickHouse marts,
BI, cohort and funnel analysis) only include rows belonging to students with active
consent. This is secondary processing: the student gets nothing from it, we do, and
it is the part that is genuinely optional.

**Not governed — serving their own feed.** Ranking a student's recommendations
requires reading their profile. That is the thing they asked for, so gating it on a
separate toggle would be theatre of a different kind: a switch that, if flipped,
simply breaks the product. Withdrawing from analytics keeps the product working;
leaving entirely is what account deletion is for.

Consent is versioned. `PRIVACY_POLICY_VERSION` stamps which text was agreed to, so
a future material change to the policy can require re-consent rather than silently
inheriting agreement to a document nobody saw.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from app.models.profile import Profile

logger = logging.getLogger(__name__)

#: Bump when the privacy policy changes materially. Profiles that consented to an
#: older version are treated as not having consented to the new one.
PRIVACY_POLICY_VERSION = "2026-08-05"


def has_active_consent(profile: Profile | None) -> bool:
    """True only for an un-withdrawn consent to the *current* policy version.

    Fails closed on every uncertain case: no profile, flag off, consent withdrawn,
    or consent recorded against a policy version we no longer publish. An
    over-broad analytics export is not recoverable after the fact.
    """
    if profile is None:
        return False
    if not bool(getattr(profile, "consent_data_processing", False)):
        return False
    if getattr(profile, "consent_withdrawn_at", None) is not None:
        return False

    version = (getattr(profile, "consent_policy_version", None) or "").strip()
    return version == PRIVACY_POLICY_VERSION


def apply_consent_change(profile: Profile, *, granted: bool) -> None:
    """Stamp the consent decision onto the profile.

    Called from the profile update path so the timestamp and policy version are
    recorded at the moment of the decision rather than inferred later.
    """
    now = datetime.now(timezone.utc)

    if granted:
        profile.consent_data_processing = True
        profile.consent_withdrawn_at = None
        profile.consent_policy_version = PRIVACY_POLICY_VERSION
        if getattr(profile, "consent_data_processing_at", None) is None:
            profile.consent_data_processing_at = now
        return

    # Withdrawal keeps the original grant timestamp: knowing when consent was held
    # and when it ended is what makes an export auditable after the fact.
    profile.consent_data_processing = False
    profile.consent_withdrawn_at = now


async def consented_user_ids() -> set[str]:
    """User ids whose analytics processing is permitted right now."""
    permitted: set[str] = set()
    try:
        async for profile in Profile.find_all():
            if has_active_consent(profile):
                permitted.add(str(profile.user_id))
    except Exception as exc:
        # Fail closed: an empty set exports nothing rather than exporting everything.
        logger.error("Could not resolve analytics consent; exporting no user rows: %s", exc)
        return set()
    return permitted


def filter_rows_by_consent(
    rows: Iterable[dict[str, Any]],
    *,
    permitted_user_ids: set[str],
    user_key: str = "user_id",
) -> list[dict[str, Any]]:
    """Drop rows belonging to users who have not consented to analytics.

    Rows with no user attached (aggregates, anonymous serving telemetry) pass
    through: there is no person to have withheld consent.
    """
    kept: list[dict[str, Any]] = []
    for row in rows:
        raw = row.get(user_key)
        if raw in (None, ""):
            kept.append(row)
            continue
        if str(raw) in permitted_user_ids:
            kept.append(row)
    return kept
