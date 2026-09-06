"""Regressions for two vulnerabilities found in the 2026-08-04 security audit.

1. Self-service escalation to `employer`. Registration forces "candidate", so the
   profile-update path was the only route to employer status, and its sole gate
   was is_corporate_email() - a 21-entry blocklist of personal providers. Any
   domain not on that list passed, including disposable-mail hosts. An attacker
   could register a throwaway address, promote themselves, publish an
   opportunity, and read every applicant's real name and email through the
   employer application routes and CSV export.

2. Password writes did not revoke sessions. `invalidate_user_sessions` existed
   with ZERO call sites, so a stolen cookie survived the victim's password reset
   for the full cookie lifetime. The remediation users are told to perform did
   nothing.
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "auth.py"
USERS_PATH = BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "users.py"
SESSION_SERVICE_PATH = BACKEND_ROOT / "app" / "services" / "session_security_service.py"


def _function_source(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
    raise AssertionError(f"{name} not found in {path.name}")


class TestEmployerEscalationIsBlocked:
    """Renamed in spirit: no privileged role may be self-granted.

    The original two assertions were written when the platform had two roles and
    they checked for the literal string "employer". They passed unchanged after
    faculty and institution were added, while both fell straight through the
    gate to the write - a candidate could PUT themselves to `institution`, set
    `college_name` to any university, and read that university's cohort
    aggregate through /academia/institution/cohort, whose only check is
    `_require_role` reading this same field.

    So these now assert the property rather than one role's name: every role
    that reads other people's data is gated, and the set is derived from
    KNOWN_ACCOUNT_TYPES so a role added later is covered by default.
    """

    def test_profile_update_refuses_self_service_promotion(self):
        source = USERS_PATH.read_text(encoding="utf-8")
        assert "accounts are approved manually" in source, (
            "self-service promotion to a privileged role must be refused; without "
            "this an attacker with a disposable email can harvest applicant PII "
            "or read another institution's cohort"
        )

    def test_the_guard_covers_every_privileged_role(self):
        """Not just employer. This is the assertion that was missing."""
        from app.core.account_types import PRIVILEGED_ACCOUNT_TYPES

        assert PRIVILEGED_ACCOUNT_TYPES == {"employer", "faculty", "institution"}
        source = USERS_PATH.read_text(encoding="utf-8")
        assert "PRIVILEGED_ACCOUNT_TYPES" in source, (
            "the gate must test membership of the privileged set, not one role's "
            "name - checking one role at a time is how faculty and institution "
            "were left ungated for an entire release"
        )

    def test_a_new_role_is_privileged_by_default(self):
        """The safe direction: forgetting to classify a role must not open it."""
        from app.core.account_types import (
            CANDIDATE,
            KNOWN_ACCOUNT_TYPES,
            PRIVILEGED_ACCOUNT_TYPES,
        )

        assert PRIVILEGED_ACCOUNT_TYPES == KNOWN_ACCOUNT_TYPES - {CANDIDATE}

    def test_the_guard_sits_on_the_account_type_write(self):
        """The check must gate the assignment, not merely exist in the file."""
        source = USERS_PATH.read_text(encoding="utf-8")
        marker = 'user.account_type = payload.account_type'
        assert marker in source
        preceding = source.split(marker)[0]
        # Wider than the original 900 characters: the guard now carries the
        # comment explaining the escalation it closes, and a window sized to the
        # old code would see only prose and fail on a correct implementation.
        tail = preceding[-2600:]
        assert 'status_code=403' in tail, "the 403 guard must immediately precede the write"
        assert 'is_admin' in tail, "only an admin may grant a privileged role"
        assert 'PRIVILEGED_ACCOUNT_TYPES' in tail, "the guard must cover the whole role set"

    def test_the_email_rule_is_applied_on_this_path_too(self):
        """Signup enforces a per-role email rule; this path used to skip it.

        Without it an approved account could be moved to a role its own address
        would have been refused for at registration.
        """
        source = USERS_PATH.read_text(encoding="utf-8")
        assert "_ensure_email_policy_for_account_type" in source

    def test_corporate_email_blocklist_is_not_the_only_gate(self):
        """is_corporate_email is a blocklist and cannot be the security boundary."""
        from app.core.email_policy import is_corporate_email

        # A disposable-mail domain passes the blocklist. That is exactly why it
        # must not be what stands between a stranger and applicant PII.
        assert is_corporate_email("attacker@sharklasers.com") is True
        assert is_corporate_email("someone@gmail.com") is False


class TestPasswordWritesRevokeSessions:
    def test_revocation_helper_has_call_sites(self):
        """It was defined and never called - the defect in one assertion."""
        auth_source = AUTH_PATH.read_text(encoding="utf-8")
        assert auth_source.count("invalidate_user_sessions") >= 2, (
            "both the reset and the change path must revoke sessions"
        )

    def test_password_reset_revokes_every_session(self):
        source = _function_source(AUTH_PATH, "reset_forgotten_password")
        assert "invalidate_user_sessions" in source, (
            "a reset is what a user does when they think they are compromised; "
            "it must end the attacker's session"
        )
        assert "keep_session_id" not in source, (
            "the reset flow is unauthenticated, so there is no session to preserve"
        )

    def test_password_setup_keeps_only_the_callers_session(self):
        source = _function_source(AUTH_PATH, "setup_password")
        assert "invalidate_user_sessions" in source
        assert "keep_session_id" in source, (
            "a password change must not log the user out of the tab they are using"
        )

    def test_session_helper_still_exists_with_expected_signature(self):
        source = SESSION_SERVICE_PATH.read_text(encoding="utf-8")
        assert "async def invalidate_user_sessions(" in source
        assert "keep_session_id" in source
