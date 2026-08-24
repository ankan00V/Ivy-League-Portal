"""Server-side port of frontend/src/lib/role-classification.ts.

Why this exists: role track was classified in the browser, and the classifier
reads `description`. That is the only reason the feed shipped all ~1500 active
listings to the client. description (703 B avg) plus extras (613 B) is 59% of
every row, and at 3.36 MB per feed request a 5.5 GB monthly Postgres egress
budget is gone in roughly 1,600 page loads - which is exactly how the Supabase
free tier was exhausted at 16.86 GB by a single developer.

Classifying here lets the feed return a `role_track` string and stop shipping
descriptions at all.

The vocabulary is NOT duplicated. app/data/role_classification.json is generated
from the TypeScript source by frontend/scripts/generate-role-vocabulary.mjs, and
tests/test_role_classification_parity.py regenerates it and fails if the
committed copy is stale. A 120-entry taxonomy maintained by hand in two
languages drifts; this way there is still one definition.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

RoleTrack = Literal["technical", "non_technical"]

_VOCAB_PATH = Path(__file__).resolve().parent.parent / "data" / "role_classification.json"


@lru_cache(maxsize=1)
def _vocabulary() -> dict[str, Any]:
    """Load once. Resolved relative to this file, never the working directory.

    The skill extractor shipped an artifact with an absolute model_dir and it
    failed silently after the repo moved - the loader warned and degraded to
    keyword extraction, so the model looked installed while contributing
    nothing. Same failure shape applies here, so the path stays repo-relative.
    """
    with _VOCAB_PATH.open() as handle:
        return json.load(handle)


def _flatten(filters: Iterable[dict[str, Any]]) -> list[str]:
    return [keyword for entry in filters for keyword in entry.get("keywords", [])]


@lru_cache(maxsize=1)
def _hints() -> tuple[list[str], list[str], list[str], list[str]]:
    vocab = _vocabulary()
    return (
        list(vocab["technical_role_names"]),
        list(vocab["non_technical_role_names"]),
        _flatten(vocab["technical_filters"]),
        _flatten(vocab["non_technical_filters"]),
    )


def _count_hits(haystack: str, needles: Iterable[str]) -> int:
    return sum(1 for needle in needles if needle in haystack)


def _normalise_tags(tags: Any) -> str:
    if isinstance(tags, (list, tuple)):
        return " ".join(str(item) for item in tags).lower()
    return str(tags or "").lower()


@lru_cache(maxsize=8192)
def _classify_cached(title_text: str, body: str) -> RoleTrack:
    """Memoised core. Keyed on the normalised strings, not the raw record.

    Classification is a fixed cost per listing but it was being paid per
    serialization: ~200 substring scans over an 850-character description, for
    every row, on every request. Measured on the 1500-row feed that took the
    endpoint from 4.5s to 10-16s - trading an egress problem for a latency one.

    The corpus turns over slowly (the scraper runs every 30 minutes) while the
    feed is requested constantly, so the same rows are reclassified over and
    over with identical inputs. 8192 entries covers the active corpus several
    times over.

    The durable fix is a stored column written at ingest, which would make this
    free rather than merely cheap. This keeps the endpoint usable until then.
    """
    technical_names, non_technical_names, technical_hints, non_technical_hints = _hints()

    # An exact taxonomy role name in the title is the strongest signal available.
    title_exact_technical = any(name in title_text for name in technical_names)
    title_exact_non_technical = any(name in title_text for name in non_technical_names)
    if title_exact_technical != title_exact_non_technical:
        return "technical" if title_exact_technical else "non_technical"

    technical_score = _count_hits(title_text, technical_hints) * 3 + _count_hits(body, technical_hints)
    non_technical_score = (
        _count_hits(title_text, non_technical_hints) * 3 + _count_hits(body, non_technical_hints)
    )

    if technical_score != non_technical_score:
        return "technical" if technical_score > non_technical_score else "non_technical"

    # Nothing decisive. Default to non-technical so a mislabelled listing surfaces
    # in the broader track rather than being asserted as engineering.
    return "technical" if _count_hits(title_text, technical_hints) > 0 else "non_technical"


def classify_role_track(
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Any = None,
    opportunity_type: Optional[str] = None,  # noqa: ARG001 - parity with the TS signature
) -> RoleTrack:
    """Classify a listing. Must match classifyRoleTrack in the TS module exactly.

    Scored rather than first-match: "Data Analyst, Marketing" contains both
    "data" and "marketing", and a first-match rule would be decided by branch
    order. Ties resolve to technical only when the title itself carries a
    technical term, so a business listing that merely mentions Excel is not
    filed as engineering.
    """
    return _classify_cached(
        str(title or "").lower(),
        f"{str(description or '').lower()} {_normalise_tags(tags)}",
    )
