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
WAREHOUSE_EXPORTS_TOTAL: Optional["Counter"] = None
ONLINE_FEATURE_PUBLISH_TOTAL: Optional["Counter"] = None
EMBEDDING_PROVIDER_HEALTH: Optional["Gauge"] = None
FEATURE_FRESHNESS_SECONDS: Optional["Gauge"] = None
MODEL_INPUT_DRIFT_VALUE: Optional["Gauge"] = None
RANKING_SLICE_RATE: Optional["Gauge"] = None
ASSISTANT_QUALITY_VALUE: Optional["Gauge"] = None
PARITY_SCORECARD_VALUE: Optional["Gauge"] = None
MODEL_PROMOTION_INFO: Optional["Gauge"] = None


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
    global WAREHOUSE_EXPORTS_TOTAL
    global ONLINE_FEATURE_PUBLISH_TOTAL
    global EMBEDDING_PROVIDER_HEALTH
    global FEATURE_FRESHNESS_SECONDS
    global MODEL_INPUT_DRIFT_VALUE
    global RANKING_SLICE_RATE
    global ASSISTANT_QUALITY_VALUE
    global PARITY_SCORECARD_VALUE
    global MODEL_PROMOTION_INFO

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
    WAREHOUSE_EXPORTS_TOTAL = Counter(
        "warehouse_exports_total",
        "Warehouse export attempts by format and status.",
        labelnames=("format", "status"),
    )
    ONLINE_FEATURE_PUBLISH_TOTAL = Counter(
        "online_feature_publish_total",
        "Online feature publication counts by target and status.",
        labelnames=("target", "status"),
    )
    EMBEDDING_PROVIDER_HEALTH = Gauge(
        "embedding_provider_health",
        "Embedding provider health: 1 healthy, 0 degraded.",
        labelnames=("provider", "mode"),
    )
    FEATURE_FRESHNESS_SECONDS = Gauge(
        "ds_feature_freshness_seconds",
        "Seconds since the latest feature-store row was updated.",
    )
    MODEL_INPUT_DRIFT_VALUE = Gauge(
        "ds_model_input_drift_value",
        "Latest model input drift metrics by metric name.",
        labelnames=("metric",),
    )
    RANKING_SLICE_RATE = Gauge(
        "ds_ranking_slice_rate",
        "Ranking slice CTR/apply-rate metrics by monitored slice.",
        labelnames=("slice_type", "slice_name", "metric"),
    )
    ASSISTANT_QUALITY_VALUE = Gauge(
        "ds_assistant_quality_value",
        "Assistant quality metrics by prompt version and route.",
        labelnames=("metric", "prompt_version", "route"),
    )
    PARITY_SCORECARD_VALUE = Gauge(
        "ds_parity_scorecard_value",
        "Offline/online parity scorecard values by mode and metric.",
        labelnames=("mode", "metric"),
    )
    MODEL_PROMOTION_INFO = Gauge(
        "ds_model_promotion_info",
        "Model promotion history and active-state marker.",
        labelnames=("model_id", "model_name", "status", "reason"),
    )


def render_metrics() -> bytes:
    if not metrics_available() or generate_latest is None:
        return b""
    init_metrics()
    return generate_latest()
