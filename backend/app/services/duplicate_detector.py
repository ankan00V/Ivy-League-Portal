from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import hashlib
import re
from typing import Any, Iterable, Optional

from beanie.exceptions import CollectionWasNotInitialized

from app.core.time import utc_now
from app.models.duplicate_merge_event import DuplicateMergeEvent
from app.models.opportunity import Opportunity

try:  # rapidfuzz is preferred in production; tests still pass with the stdlib fallback.
    from rapidfuzz import fuzz as _rapidfuzz
except Exception:  # pragma: no cover - depends on optional runtime package installation
    _rapidfuzz = None


SOURCE_PRIORITY = {
    "linkedin": 100,
    "internshala": 95,
    "unstop": 90,
    "ycombinator_jobs": 88,
    "freshersworld": 85,
    "greenhouse": 83,
    "hackerearth": 80,
    "devfolio": 78,
    "ivy_rss": 75,
    "promilo": 70,
}

TRUST_STATUS_PRIORITY = {
    "verified": 30,
    "unreviewed": 15,
    "needs_review": 5,
    "blocked": -50,
}

EXACT_URL_STAGE = "exact_url_hash"
TCL_STAGE = "title_company_location_hash"
FUZZY_STAGE = "fuzzy_title_company_location"
EMBEDDING_STAGE = "embedding_similarity"


@dataclass(frozen=True)
class DuplicateMatch:
    canonical: Any
    duplicate: Any
    stage: str
    score: float
    reason: str


def _field(row: Any, name: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _set_field(row: Any, name: str, value: Any) -> None:
    if isinstance(row, dict):
        row[name] = value
        return
    setattr(row, name, value)


def _row_id(row: Any) -> Any:
    return _field(row, "id") or _field(row, "_id")


def _same_identity(left: Any, right: Any) -> bool:
    left_id = _row_id(left)
    right_id = _row_id(right)
    if left_id is not None and right_id is not None:
        return str(left_id) == str(right_id)
    return left is right


def _as_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_tokens(value: Any) -> str:
    text = _as_text(value).lower()
    text = re.sub(r"[^a-z0-9+#]+", " ", text)
    tokens = [token for token in text.split() if token]
    return " ".join(tokens)


def _canonical_url(value: Any) -> str:
    raw = _as_text(value)
    if not raw:
        return ""
    try:
        from app.services.scraper import canonicalize_apply_url

        return canonicalize_apply_url(raw)
    except Exception:
        return raw.split("#", 1)[0].strip()


def _stable_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _url_hash(row: Any) -> str:
    existing = _as_text(_field(row, "canonical_url_hash"))
    if existing:
        return existing
    return _stable_hash(_canonical_url(_field(row, "url")))


def _token_sort_ratio(left: Any, right: Any) -> float:
    left_norm = _normalize_tokens(left)
    right_norm = _normalize_tokens(right)
    if not left_norm or not right_norm:
        return 0.0
    if _rapidfuzz is not None:
        return float(_rapidfuzz.token_sort_ratio(left_norm, right_norm)) / 100.0
    left_sorted = " ".join(sorted(left_norm.split()))
    right_sorted = " ".join(sorted(right_norm.split()))
    return SequenceMatcher(None, left_sorted, right_sorted).ratio()


def _source(row: Any) -> str:
    return _as_text(_field(row, "source") or "unknown").lower() or "unknown"


def _source_identifier(row: Any) -> str:
    return _as_text(_field(row, "source_id") or _field(row, "url"))


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=utc_now().tzinfo)
    return value.astimezone(utc_now().tzinfo)


def _canonical_rank(row: Any) -> tuple[float, ...]:
    source = _source(row)
    trust_status = _as_text(_field(row, "trust_status")).lower()
    created_at = _coerce_datetime(_field(row, "created_at"))
    created_ts = created_at.timestamp() if created_at else float("inf")
    return (
        float(_field(row, "trust_score") or 0),
        float(TRUST_STATUS_PRIORITY.get(trust_status, 0)),
        float(SOURCE_PRIORITY.get(source, 0)),
        float(_field(row, "quality_score") or 0),
        float(_field(row, "source_count") or 1),
        -created_ts,
    )


def _source_ids(row: Any) -> dict[str, list[str]]:
    existing = _field(row, "source_ids") or {}
    merged: dict[str, list[str]] = {}
    if isinstance(existing, dict):
        for source, values in existing.items():
            source_key = _as_text(source).lower()
            if not source_key:
                continue
            merged[source_key] = []
            for value in list(values or []):
                value_text = _as_text(value)
                if value_text and value_text not in merged[source_key]:
                    merged[source_key].append(value_text)
    row_source = _source(row)
    identifier = _source_identifier(row)
    if row_source and identifier:
        merged.setdefault(row_source, [])
        if identifier not in merged[row_source]:
            merged[row_source].append(identifier)
    return merged


def _merge_source_ids(left: Any, right: Any) -> dict[str, list[str]]:
    merged = _source_ids(left)
    for source, values in _source_ids(right).items():
        bucket = merged.setdefault(source, [])
        for value in values:
            if value not in bucket:
                bucket.append(value)
    return merged


def _seen_sources(row: Any) -> list[str]:
    values = [_as_text(value).lower() for value in list(_field(row, "seen_on") or [])]
    source = _source(row)
    if source:
        values.append(source)
    return [value for value in dict.fromkeys(values) if value]


class DuplicateDetector:
    def __init__(
        self,
        *,
        fuzzy_threshold: float = 0.88,
        embedding_threshold: float = 0.93,
        candidate_limit: int = 1_000,
    ) -> None:
        self.fuzzy_threshold = max(0.0, min(1.0, float(fuzzy_threshold)))
        self.embedding_threshold = max(0.0, min(1.0, float(embedding_threshold)))
        self.candidate_limit = max(10, int(candidate_limit))

    def score_pair(self, left: Any, right: Any) -> Optional[tuple[str, float, str]]:
        if _same_identity(left, right):
            return None

        left_url_hash = _url_hash(left)
        right_url_hash = _url_hash(right)
        if left_url_hash and right_url_hash and left_url_hash == right_url_hash:
            return EXACT_URL_STAGE, 1.0, "canonical_url_hash matched"

        left_url = _canonical_url(_field(left, "url"))
        right_url = _canonical_url(_field(right, "url"))
        if left_url and right_url and left_url == right_url:
            return EXACT_URL_STAGE, 1.0, "canonical apply URL matched"

        left_tcl = _as_text(_field(left, "title_company_location_hash"))
        right_tcl = _as_text(_field(right, "title_company_location_hash"))
        if left_tcl and right_tcl and left_tcl == right_tcl:
            return TCL_STAGE, 0.97, "title/company/location hash matched"

        title_score = _token_sort_ratio(_field(left, "title"), _field(right, "title"))
        company_score = _token_sort_ratio(_field(left, "university"), _field(right, "university"))
        location_score = _token_sort_ratio(_field(left, "location"), _field(right, "location"))

        if not _as_text(_field(left, "location")) or not _as_text(_field(right, "location")):
            location_score = 0.65

        blended = (0.55 * title_score) + (0.30 * company_score) + (0.15 * location_score)
        if title_score >= 0.84 and company_score >= 0.76 and blended >= self.fuzzy_threshold:
            return FUZZY_STAGE, round(blended, 4), "fuzzy title/company/location matched"

        return None

    def choose_canonical(self, left: Any, right: Any) -> Any:
        if _canonical_rank(left) >= _canonical_rank(right):
            return left
        return right

    def find_best_match(self, candidate: Any, corpus: Iterable[Any]) -> Optional[DuplicateMatch]:
        best: Optional[DuplicateMatch] = None
        for row in corpus:
            scored = self.score_pair(candidate, row)
            if scored is None:
                continue
            stage, score, reason = scored
            canonical = self.choose_canonical(candidate, row)
            duplicate = row if canonical is candidate else candidate
            match = DuplicateMatch(
                canonical=canonical,
                duplicate=duplicate,
                stage=stage,
                score=score,
                reason=reason,
            )
            if best is None or match.score > best.score:
                best = match
        return best

    async def find_duplicate(self, candidate: Any, *, use_embedding: bool = True) -> Optional[DuplicateMatch]:
        try:
            exact = await self._find_exact_url_match(candidate)
            if exact is not None:
                return exact

            fuzzy = await self._find_fuzzy_match(candidate)
            if fuzzy is not None:
                return fuzzy

            if use_embedding:
                semantic = await self._find_embedding_match(candidate)
                if semantic is not None:
                    return semantic
        except CollectionWasNotInitialized:
            return None
        return None

    async def _find_exact_url_match(self, candidate: Any) -> Optional[DuplicateMatch]:
        url_hash = _url_hash(candidate)
        if not url_hash:
            return None
        rows = await Opportunity.find_many({"canonical_url_hash": url_hash}).limit(5).to_list()
        return self.find_best_match(candidate, rows)

    async def _find_fuzzy_match(self, candidate: Any) -> Optional[DuplicateMatch]:
        query: dict[str, Any] = {}
        opportunity_type = _as_text(_field(candidate, "opportunity_type"))
        if opportunity_type:
            query["opportunity_type"] = opportunity_type
        rows = await Opportunity.find_many(query).sort("-last_seen_at").limit(self.candidate_limit).to_list()
        return self.find_best_match(candidate, rows)

    async def _find_embedding_match(self, candidate: Any) -> Optional[DuplicateMatch]:
        text = " ".join(
            part
            for part in [
                _as_text(_field(candidate, "title")),
                _as_text(_field(candidate, "university")),
                _as_text(_field(candidate, "location")),
                _as_text(_field(candidate, "description")),
            ]
            if part
        )
        if len(text) < 20:
            return None
        try:
            from app.services.vector_service import opportunity_vector_service

            hits = await opportunity_vector_service.find_semantic_duplicates(
                text,
                threshold=self.embedding_threshold,
                top_k=3,
                exclude_urls=[_as_text(_field(candidate, "url"))],
            )
        except Exception:
            return None

        for hit in hits:
            hit_url = _as_text(hit.get("url"))
            if not hit_url:
                continue
            row = await Opportunity.find_one({"url": hit_url})
            if row is None or _same_identity(candidate, row):
                continue
            score = float(hit.get("similarity") or self.embedding_threshold)
            canonical = self.choose_canonical(candidate, row)
            duplicate = row if canonical is candidate else candidate
            return DuplicateMatch(
                canonical=canonical,
                duplicate=duplicate,
                stage=EMBEDDING_STAGE,
                score=round(max(self.embedding_threshold, min(1.0, score)), 4),
                reason="semantic embedding similarity matched",
            )
        return None

    async def merge_duplicate(
        self,
        canonical: Any,
        duplicate: Any,
        *,
        stage: str,
        score: float,
        mark_duplicate_closed: bool = False,
        persist_event: bool = True,
    ) -> dict[str, Any]:
        if _same_identity(canonical, duplicate):
            return {"status": "skipped", "reason": "same_opportunity"}

        preferred = self.choose_canonical(canonical, duplicate)
        if preferred is duplicate:
            canonical, duplicate = duplicate, canonical

        now = utc_now()
        source_ids = _merge_source_ids(canonical, duplicate)
        seen_on = [value for value in dict.fromkeys(_seen_sources(canonical) + _seen_sources(duplicate)) if value]
        duplicate_count = (
            int(_field(canonical, "duplicate_count") or 0)
            + int(_field(duplicate, "duplicate_count") or 0)
            + 1
        )

        for field_name in [
            "location",
            "work_mode",
            "stipend",
            "eligibility",
            "deadline",
            "duration_months",
            "ppo_available",
        ]:
            if not _field(canonical, field_name) and _field(duplicate, field_name):
                _set_field(canonical, field_name, _field(duplicate, field_name))

        tags = list(_field(canonical, "tags") or [])
        for tag in list(_field(duplicate, "tags") or []):
            if tag not in tags:
                tags.append(tag)

        _set_field(canonical, "tags", tags)
        _set_field(canonical, "seen_on", seen_on)
        _set_field(canonical, "source_ids", source_ids)
        _set_field(canonical, "source_count", max(1, len(source_ids)))
        _set_field(canonical, "duplicate_count", duplicate_count)
        _set_field(canonical, "dedup_score", max(float(_field(canonical, "dedup_score") or 0.0), float(score)))
        _set_field(canonical, "duplicate_last_merged_at", now)
        last_seen_candidates = [
            _coerce_datetime(_field(canonical, "last_seen_at")),
            _coerce_datetime(_field(duplicate, "last_seen_at")),
            now,
        ]
        _set_field(canonical, "last_seen_at", max(value for value in last_seen_candidates if value is not None))
        _set_field(canonical, "updated_at", now)

        save = getattr(canonical, "save", None)
        if callable(save):
            await save()

        if mark_duplicate_closed:
            _set_field(duplicate, "lifecycle_status", "closed")
            _set_field(duplicate, "closed_at", now)
            _set_field(duplicate, "updated_at", now)
            duplicate_save = getattr(duplicate, "save", None)
            if callable(duplicate_save):
                await duplicate_save()

        if persist_event and _row_id(canonical) is not None:
            event = DuplicateMergeEvent(
                canonical_opportunity_id=_row_id(canonical),
                duplicate_opportunity_id=_row_id(duplicate),
                canonical_source=_source(canonical),
                duplicate_source=_source(duplicate),
                canonical_source_id=_field(canonical, "source_id"),
                duplicate_source_id=_field(duplicate, "source_id"),
                canonical_url=_field(canonical, "url"),
                duplicate_url=_field(duplicate, "url"),
                stage=stage,
                score=round(float(score), 4),
                created_at=now,
            )
            await event.insert()

        return {
            "status": "merged",
            "canonical_id": str(_row_id(canonical)),
            "duplicate_id": str(_row_id(duplicate)) if _row_id(duplicate) is not None else None,
            "stage": stage,
            "score": round(float(score), 4),
            "source_count": len(source_ids),
            "seen_on": seen_on,
        }

    async def scan_existing(
        self,
        *,
        limit: int = 1_000,
        execute: bool = False,
        mark_duplicate_closed: bool = False,
    ) -> dict[str, Any]:
        rows = await Opportunity.find_many().sort("-last_seen_at").limit(max(1, int(limit))).to_list()
        canonical_rows: list[Any] = []
        matches: list[DuplicateMatch] = []
        stage_counts: Counter[str] = Counter()

        for row in rows:
            match = self.find_best_match(row, canonical_rows)
            if match is None:
                canonical_rows.append(row)
                continue

            matches.append(match)
            stage_counts[match.stage] += 1
            if execute:
                await self.merge_duplicate(
                    match.canonical,
                    match.duplicate,
                    stage=match.stage,
                    score=match.score,
                    mark_duplicate_closed=mark_duplicate_closed,
                    persist_event=True,
                )

        return {
            "status": "executed" if execute else "dry_run",
            "scanned": len(rows),
            "duplicates_found": len(matches),
            "stage_counts": dict(stage_counts),
            "sample_matches": [
                {
                    "canonical_id": str(_row_id(match.canonical)),
                    "duplicate_id": str(_row_id(match.duplicate)) if _row_id(match.duplicate) is not None else None,
                    "canonical_title": _field(match.canonical, "title"),
                    "duplicate_title": _field(match.duplicate, "title"),
                    "stage": match.stage,
                    "score": match.score,
                    "reason": match.reason,
                }
                for match in matches[:20]
            ],
        }

    async def report(self, *, days: int = 7, limit: int = 500) -> dict[str, Any]:
        since = utc_now() - timedelta(days=max(1, int(days)))
        try:
            events = (
                await DuplicateMergeEvent.find_many({"created_at": {"$gte": since}})
                .sort("-created_at")
                .limit(max(1, int(limit)))
                .to_list()
            )
        except CollectionWasNotInitialized:
            events = []

        stage_counts: Counter[str] = Counter()
        source_pairs: Counter[str] = Counter()
        canonical_counts: Counter[str] = Counter()
        for event in events:
            stage_counts[str(event.stage)] += 1
            pair = f"{event.canonical_source}->{event.duplicate_source}"
            source_pairs[pair] += 1
            canonical_counts[str(event.canonical_opportunity_id)] += 1

        top_opportunities: list[dict[str, Any]] = []
        for opportunity_id, count in canonical_counts.most_common(10):
            title = None
            source = None
            url = None
            try:
                opportunity = await Opportunity.get(opportunity_id)
                if opportunity is not None:
                    title = opportunity.title
                    source = opportunity.source
                    url = opportunity.url
            except Exception:
                pass
            top_opportunities.append(
                {
                    "opportunity_id": opportunity_id,
                    "title": title,
                    "source": source,
                    "url": url,
                    "merge_count": count,
                }
            )

        matrix: dict[str, dict[str, int]] = defaultdict(dict)
        for pair, count in source_pairs.items():
            canonical_source, duplicate_source = pair.split("->", 1)
            matrix[canonical_source][duplicate_source] = count

        return {
            "window_days": max(1, int(days)),
            "total_merges": len(events),
            "stage_counts": dict(stage_counts),
            "source_pair_matrix": {source: dict(values) for source, values in matrix.items()},
            "top_duplicated_opportunities": top_opportunities,
            "generated_at": utc_now().isoformat(),
        }


duplicate_detector = DuplicateDetector()
