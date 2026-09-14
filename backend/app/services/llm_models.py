"""Which model an LLM call is sent to, and a guard against withdrawn ones.

Kept from a larger module that was removed with the SIH 2026 work. This part
predates the reason that module existed and is load-bearing for Ask AI.
"""

from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def live_model(configured: str | None, *, fallback: str, context: str) -> str:
    """Refuse to send a request to a model the provider has withdrawn.

    A retired model is not a slow model or a bad model - it is an HTTP 410, and
    every LLM path in this codebase catches provider errors and serves a
    deterministic answer. That is the correct behaviour for a transient failure
    and exactly the wrong shape for a permanent one: the feature reports healthy,
    the pages render, and the only evidence is a warning in a log nobody reads.

    This is how Ask AI ran from 2026-08-26 without anyone noticing, after the
    endpoint retired meta/llama-3.1-8b-instruct.

    Checked at construction rather than at call time so the substitution is
    logged once at startup, where it will be seen, instead of on every request.
    """
    candidate = (configured or "").strip()
    retired = {str(name).strip() for name in (getattr(settings, "RETIRED_LLM_MODELS", None) or [])}
    if candidate and candidate in retired:
        logger.warning(
            "%s is configured for %s, which the provider has retired; using %s instead. "
            "Update the deployment's model setting - this substitution is a safety net, "
            "not the configuration.",
            candidate,
            context,
            fallback,
        )
        return fallback
    return candidate or fallback
