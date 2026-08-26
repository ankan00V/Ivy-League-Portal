"""The account types this platform serves, in one place.

This existed as two copies of `VALID_ACCOUNT_TYPES = {"candidate", "employer"}`,
in auth.py and users.py. Two sets that must agree, edited by hand, where the
failure mode is that a type is valid at signup and invalid at profile update -
or the reverse, which is a hole rather than an annoyance. Adding two more roles
made keeping them in step a matter of time rather than luck.

Each type is separately gated. The employer portal was retired once precisely
because a role can turn out to be a liability before it is useful, and the
supported way to withdraw one is a flag rather than an edit across call sites.
"""

from __future__ import annotations

from app.core.config import settings

CANDIDATE = "candidate"
EMPLOYER = "employer"
FACULTY = "faculty"
INSTITUTION = "institution"

#: Every account type the product knows about, whether or not it is currently
#: open for signup. Validation uses this; availability is a separate question.
KNOWN_ACCOUNT_TYPES: frozenset[str] = frozenset({CANDIDATE, EMPLOYER, FACULTY, INSTITUTION})

#: Human-readable, for error messages that tell the caller what is allowed.
ACCOUNT_TYPE_LABELS: dict[str, str] = {
    CANDIDATE: "Student",
    EMPLOYER: "Industry",
    FACULTY: "Academician",
    INSTITUTION: "Institution",
}


def account_type_enabled(account_type: str) -> bool:
    """Whether new accounts of this type may be created right now.

    Candidates are never gated - they are the product. The other three each
    carry powers a self-serve signup should not hand out silently: posting into
    the feed, and reading cohort-level data about somebody else's students.
    """
    value = str(account_type or "").strip().lower()
    if value == CANDIDATE:
        return True
    if value == EMPLOYER:
        return bool(settings.EMPLOYER_PORTAL_ENABLED)
    if value == FACULTY:
        return bool(getattr(settings, "FACULTY_PORTAL_ENABLED", False))
    if value == INSTITUTION:
        return bool(getattr(settings, "INSTITUTION_PORTAL_ENABLED", False))
    return False


def enabled_account_types() -> frozenset[str]:
    return frozenset(name for name in KNOWN_ACCOUNT_TYPES if account_type_enabled(name))


def normalise_account_type(value: str | None, *, default: str = CANDIDATE) -> str:
    """Lower-case and trim, without deciding whether it is allowed."""
    return str(value or default).strip().lower()


def describe_allowed() -> str:
    """For error messages, so a rejection says what would have worked."""
    return ", ".join(sorted(enabled_account_types()))
