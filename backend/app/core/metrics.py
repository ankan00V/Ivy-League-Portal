from __future__ import annotations

from typing import Optional

from app.core.config import settings

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest  # type: ignore
except Exception:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"  # type: ignore
    Counter = Gauge = Histogram = None  # type: ignore
    generate_latest = None  # type: ignore


def metrics_available() -> bool:
    return generate_latest is not None and bool(settings.METRICS_ENABLED)


REQUEST_LATENCY_SECONDS: Optional["Histogram"] = None
REQUESTS_TOTAL: Optional["Counter"] = None
RESPONSES_TOTAL: Optional["Counter"] = None

CACHE_HITS_TOTAL: Optional["Counter"] = None
CACHE_MISSES_TOTAL: Optional["Counter"] = None

JOBS_ENQUEUED_TOTAL: Optional["Counter"] = None
JOBS_SUCCEEDED_TOTAL: Optional["Counter"] = None
JOBS_FAILED_TOTAL: Optional["Counter"] = None
JOBS_DEAD_TOTAL: Optional["Counter"] = None

SCRAPER_RUNS_TOTAL: Optional["Counter"] = None
SCRAPER_SOURCE_TOTAL: Optional["Counter"] = None
OPPORTUNITY_FRESHNESS_SECONDS: Optional["Gauge"] = None
OPPORTUNITY_STALE: Optional["Gauge"] = None
RANKING_REQUESTS_TOTAL: Optional["Counter"] = None
RANKING_REQUEST_LATENCY_MS: Optional["Histogram"] = None
INTERACTION_EVENTS_TOTAL: Optional["Counter"] = None


def init_metrics() -> None:
    global REQUEST_LATENCY_SECONDS
    global REQUESTS_TOTAL
    global RESPONSES_TOTAL
    global CACHE_HITS_TOTAL
    global CACHE_MISSES_TOTAL
    global JOBS_ENQUEUED_TOTAL
    global JOBS_SUCCEEDED_TOTAL
    global JOBS_FAILED_TOTAL
    global JOBS_DEAD_TOTAL
    global SCRAPER_RUNS_TOTAL
    global SCRAPER_SOURCE_TOTAL
    global OPPORTUNITY_FRESHNESS_SECONDS
    global OPPORTUNITY_STALE
    global RANKING_REQUESTS_TOTAL
    global RANKING_REQUEST_LATENCY_MS
    global INTERACTION_EVENTS_TOTAL

    if not metrics_available() or Counter is None or Histogram is None or Gauge is None:
        return

    if REQUEST_LATENCY_SECONDS is not None:
        return

    REQUEST_LATENCY_SECONDS = Histogram(
        "http_request_duration_seconds",
        "HTTP request duration in seconds.",
        labelnames=("method", "route"),
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20),
    )
    REQUESTS_TOTAL = Counter(
        "http_requests_total",
        "Total HTTP requests started.",
        labelnames=("method", "route"),
    )
    RESPONSES_TOTAL = Counter(
        "http_responses_total",
        "Total HTTP responses completed.",
        labelnames=("method", "route", "status"),
    )

    CACHE_HITS_TOTAL = Counter(
        "cache_hits_total",
        "Cache hits.",
        labelnames=("cache",),
    )
    CACHE_MISSES_TOTAL = Counter(
        "cache_misses_total",
        "Cache misses.",
        labelnames=("cache",),
    )

    JOBS_ENQUEUED_TOTAL = Counter(
        "jobs_enqueued_total",
        "Jobs enqueued.",
        labelnames=("job_type",),
    )
    JOBS_SUCCEEDED_TOTAL = Counter(
        "jobs_succeeded_total",
        "Jobs succeeded.",
        labelnames=("job_type",),
    )
    JOBS_FAILED_TOTAL = Counter(
        "jobs_failed_total",
        "Jobs failed (will retry).",
        labelnames=("job_type",),
    )
    JOBS_DEAD_TOTAL = Counter(
        "jobs_dead_total",
        "Jobs moved to dead-letter.",
        labelnames=("job_type",),
    )

    SCRAPER_RUNS_TOTAL = Counter(
        "scraper_runs_total",
        "Scraper runs by status.",
        labelnames=("status",),
    )
    SCRAPER_SOURCE_TOTAL = Counter(
        "scraper_source_runs_total",
        "Scraper per-source runs.",
        labelnames=("source", "status"),
    )

    OPPORTUNITY_FRESHNESS_SECONDS = Gauge(
        "opportunity_freshness_seconds",
        "Seconds since latest opportunity last_seen_at.",
    )
    OPPORTUNITY_STALE = Gauge(
        "opportunity_freshness_sla_breached",
        "1 if freshness SLA is breached (stale), else 0.",
    )
    RANKING_REQUESTS_TOTAL = Counter(
        "ranking_requests_total",
        "Total ranking/ask-ai requests by mode/variant and status.",
        labelnames=("request_kind", "ranking_mode", "experiment_key", "experiment_variant", "success", "traffic_type"),
    )
    RANKING_REQUEST_LATENCY_MS = Histogram(
        "ranking_request_latency_ms",
        "Ranking/ask-ai request latency in milliseconds.",
        labelnames=("request_kind", "ranking_mode", "experiment_key", "experiment_variant", "traffic_type"),
        buckets=(10, 25, 50, 75, 100, 150, 250, 500, 750, 1000, 2000, 5000),
    )
    INTERACTION_EVENTS_TOTAL = Counter(
        "opportunity_interaction_events_total",
        "Interaction events by type and experiment variant.",
        labelnames=("interaction_type", "ranking_mode", "experiment_key", "experiment_variant", "traffic_type"),
    )


def render_metrics() -> bytes:
    if not metrics_available() or generate_latest is None:
        return b""
    init_metrics()
    return generate_latest()
