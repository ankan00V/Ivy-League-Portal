"""One live session per user, expiring after 24 hours.

Owner policy: signing in keeps the browser signed in for 24 hours with no
re-login, then logs out automatically. A second sign-in anywhere ends the first,
so a forgotten session on a shared or lost machine cannot outlive the login that
replaced it.
"""
from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

from jose import ExpiredSignatureError, jwt

from app.core.config import settings
from app.core.security import create_access_token

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = BACKEND_ROOT / "app" / "api" / "api_v1" / "endpoints" / "auth.py"


class TestSessionLifetime:
    def test_session_lasts_twenty_four_hours(self):
        assert settings.AUTH_SESSION_COOKIE_MAX_AGE_SECONDS == 60 * 60 * 24
        assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 60 * 24

    def test_issued_token_carries_that_lifetime(self):
        """Measured against wall clock: these tokens carry exp but no iat."""
        ttl = settings.AUTH_SESSION_COOKIE_MAX_AGE_SECONDS
        before = int(time.time())
        token = create_access_token(
            "507f1f77bcf86cd799439011",
            expires_delta=timedelta(seconds=ttl),
            scopes=[],
            extra_claims={"jti": "t", "typ": "user_session"},
        )
        claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        remaining = claims["exp"] - before
        assert ttl - 5 <= remaining <= ttl + 5, f"expected ~{ttl}s of life, got {remaining}s"

    def test_expired_token_is_rejected(self):
        """Auto-logout depends on this actually being enforced, not just set."""
        token = create_access_token(
            "507f1f77bcf86cd799439011",
            expires_delta=timedelta(seconds=-10),
            scopes=[],
            extra_claims={"jti": "t", "typ": "user_session"},
        )
        try:
            jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        except ExpiredSignatureError:
            return
        raise AssertionError("an expired session token was accepted")


class TestSingleActiveSession:
    def test_policy_is_enabled(self):
        assert settings.AUTH_SINGLE_ACTIVE_SESSION is True

    def test_enforced_at_the_single_token_issuance_choke_point(self):
        """Password, OTP and OAuth all issue through _issue_user_session_token.

        Enforcing anywhere else would leave one of those paths able to open a
        second concurrent session.
        """
        source = AUTH_PATH.read_text(encoding="utf-8")
        start = source.index("async def _issue_user_session_token")
        body = source[start : source.index("\nclass ", start)]
        assert "AUTH_SINGLE_ACTIVE_SESSION" in body
        assert "invalidate_user_sessions" in body
        assert "keep_session_id=session_id" in body, (
            "the session just created must be the one kept, not revoked"
        )

    def test_new_session_is_registered_before_older_ones_are_revoked(self):
        """Ordering matters: revoking first could leave the user with none."""
        source = AUTH_PATH.read_text(encoding="utf-8")
        start = source.index("async def _issue_user_session_token")
        body = source[start : source.index("\nclass ", start)]
        assert body.index("create_session") < body.index("invalidate_user_sessions")

    def test_revocation_failure_cannot_block_sign_in(self):
        source = AUTH_PATH.read_text(encoding="utf-8")
        start = source.index("async def _issue_user_session_token")
        body = source[start : source.index("\nclass ", start)]
        revoke_at = body.index("invalidate_user_sessions")
        assert "try:" in body[:revoke_at], "cleanup must not raise into a valid login"
        assert "except Exception" in body[revoke_at:]
