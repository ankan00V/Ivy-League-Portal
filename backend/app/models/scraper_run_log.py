from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from beanie import Document
from pydantic import Field

from app.core.time import utc_now


ScraperRunStatus = Literal["success", "partial", "failed"]


class ScraperRunLog(Document):
    source_name: str = Field(json_schema_extra={"index": True})
    run_start: datetime = Field(json_schema_extra={"index": True})
    run_end: datetime = Field(json_schema_extra={"index": True})
    status: ScraperRunStatus = Field(json_schema_extra={"index": True})

    items_fetched: int = Field(default=0, ge=0)
    items_parsed: int = Field(default=0, ge=0)
    items_inserted: int = Field(default=0, ge=0)
    items_updated: int = Field(default=0, ge=0)
    items_deduplicated: int = Field(default=0, ge=0)
    # Rows fetched and parsed successfully but rejected by the early-career
    # scope filter. Previously discarded, which made an over-aggressive filter
    # indistinguishable from a healthy run.
    items_out_of_scope: int = Field(default=0, ge=0)
    # Rows fetched but rejected before the scope check as not being an
    # opportunity posting at all - site navigation, marketing copy, category
    # links, page furniture.
    #
    # Same omission as items_out_of_scope above, one field over, and it hid five
    # dead sources for 229 runs. scrape_and_store has always counted this, but
    # nothing persisted it, so a source returning pure navigation logged
    # parsed=0, out_of_scope=0, parse_error_count=0 - identical to a broken
    # parser, and indistinguishable from a healthy source that simply found
    # nothing new. devpost, handshake and wayup each sat at 0 inserts for
    # 229 consecutive runs looking exactly like a quiet day.
    items_non_posting: int = Field(default=0, ge=0)
    parse_error_count: int = Field(default=0, ge=0)
    error_samples: list[dict[str, Any]] = Field(default_factory=list)

    p50_parse_time_ms: Optional[float] = None
    p95_parse_time_ms: Optional[float] = None
    avg_trust_score: Optional[float] = None
    silent_failure: bool = Field(default=False, json_schema_extra={"index": True})

    created_at: datetime = Field(default_factory=utc_now, json_schema_extra={"index": True})

    class Settings:
        name = "scraper_run_logs"
        indexes = [
            "source_name",
            "status",
            "silent_failure",
            "run_start",
            "run_end",
            "created_at",
            [("source_name", 1), ("run_end", -1)],
            [("source_name", 1), ("status", 1), ("run_end", -1)],
        ]
