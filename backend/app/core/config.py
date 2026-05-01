from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
STRICT_DEFAULT_CSP = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "script-src 'self'; "
    "style-src 'self' https:; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self' data: https:; "
    "connect-src 'self' https:; "
    "worker-src 'self' blob:; "
    "manifest-src 'self'; "
    "form-action 'self'; "
    "frame-src 'none'; "
    "require-trusted-types-for 'script'; "
    "trusted-types default"
)

class Settings(BaseSettings):
    PROJECT_NAME: str = "VidyaVerse API"
    API_V1_STR: str = "/api/v1"
    
    # JWT Auth
    SECRET_KEY: str = "your_super_secret_key_here_for_development_change_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    AUTH_SESSION_COOKIE_ENABLED: bool = True
    AUTH_SESSION_COOKIE_NAME: str = "vidyaverse_session"
    AUTH_SESSION_COOKIE_SECURE: bool = False
    AUTH_SESSION_COOKIE_SAMESITE: str = "lax"  # none | lax | strict
    AUTH_SESSION_COOKIE_PATH: str = "/"
    AUTH_SESSION_COOKIE_DOMAIN: Optional[str] = None
    AUTH_SESSION_COOKIE_MAX_AGE_SECONDS: int = 60 * 60 * 24  # 24h
    AUTH_COOKIE_ONLY_MODE: bool = False
    ADMIN_BOOTSTRAP_ENABLED: bool = True
    ADMIN_BOOTSTRAP_EMAIL: str = "ghoshankan005@gmail.com"
    ADMIN_BOOTSTRAP_PASSWORD: Optional[str] = None
    ADMIN_TOTP_SECRET: Optional[str] = None
    ADMIN_TOTP_ISSUER: str = "Vidyaverse"
    ADMIN_TOTP_DIGITS: int = 6
    ADMIN_TOTP_PERIOD_SECONDS: int = 30
    ADMIN_TOTP_WINDOW_STEPS: int = 1
    CSRF_PROTECTION_ENABLED: bool = True
    CSRF_ENFORCE_ON_AUTH_COOKIE: bool = True
    CSRF_TRUSTED_ORIGINS: list[str] = []
    SECURITY_HEADERS_ENABLED: bool = True
    SECURITY_CSP_ENABLED: bool = True
    SECURITY_CSP_REPORT_ONLY: bool = False
    SECURITY_CSP_ENFORCE_STRICT_IN_PRODUCTION: bool = True
    SECURITY_CSP_VALUE: Optional[str] = None
    
    # Database layer (MongoDB)
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "vidyaverse"

    # Browser automation (Playwright) for auto-application flow
    PLAYWRIGHT_HEADLESS: bool = True
    PLAYWRIGHT_TIMEOUT_MS: int = 45000
    AUTO_SUBMIT_ENABLED: bool = False
    AUTO_APPLY_SCREENSHOT_DIR: str = "/tmp/vidyaverse-auto-apply"

    # Scraper reliability controls
    SCRAPER_AUTORUN_ENABLED: bool = True
    SCRAPER_INTERVAL_MINUTES: int = 30
    SCRAPER_MAX_STALENESS_MINUTES: int = 30
    SCRAPER_ON_DEMAND_REFRESH_ENABLED: bool = True
    SCRAPER_TIMEOUT_SECONDS: int = 20
    SCRAPER_HTTP_RETRIES: int = 4
    SCRAPER_RETRY_BACKOFF: float = 0.8
    SCRAPER_UNSTOP_MAX_ITEMS: int = 60
    SCRAPER_NAUKRI_MAX_ITEMS: int = 25
    SCRAPER_NAUKRI_ENABLE_PLAYWRIGHT_FALLBACK: bool = False
    SCRAPER_INTERNSHALA_MAX_ITEMS: int = 30
    SCRAPER_HACK2SKILL_MAX_ITEMS: int = 24
    SCRAPER_FRESHERSWORLD_MAX_ITEMS: int = 30
    SCRAPER_INDEED_MAX_ITEMS: int = 20
    SCRAPER_GENERIC_PORTAL_MAX_ITEMS: int = 12
    
    # Celery & Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    UPSTASH_REDIS_REST_URL: Optional[str] = None
    UPSTASH_REDIS_REST_TOKEN: Optional[str] = None

    # Caching (Redis-backed)
    CACHE_ENABLED: bool = True
    CACHE_EMBEDDINGS_ENABLED: bool = True
    CACHE_SEARCH_ENABLED: bool = True
    CACHE_EMBEDDING_TTL_SECONDS: int = 60 * 60 * 24  # 24h
    CACHE_SEARCH_TTL_SECONDS: int = 60  # 1m
    CACHE_MAX_TEXT_LENGTH: int = 1200

    # Observability / Metrics
    METRICS_ENABLED: bool = True
    METRICS_REQUIRE_AUTH: bool = True

    # Rate limiting (Redis-backed)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 240
    RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE: int = 30

    # Background jobs (Mongo-backed queue + retry + DLQ)
    JOBS_ENABLED: bool = True
    JOBS_POLL_INTERVAL_SECONDS: float = 0.8
    JOBS_LOCK_TIMEOUT_SECONDS: int = 60 * 10
    JOBS_RETRY_BASE_SECONDS: float = 2.0
    JOBS_RETRY_MAX_SECONDS: float = 10 * 60.0

    # Mongo TLS controls (keep local dev easy, prod strict)
    MONGODB_TLS_FORCE: bool = False
    MONGODB_TLS_ALLOW_INVALID_CERTS: bool = False
    MONGODB_SERVER_SELECTION_TIMEOUT_MS: int = 10000
    MONGODB_CONNECT_TIMEOUT_MS: int = 10000
    MONGODB_SOCKET_TIMEOUT_MS: int = 15000
    MONGODB_STARTUP_MAX_RETRIES: int = 4
    MONGODB_STARTUP_RETRY_BACKOFF_SECONDS: float = 1.5
    
    # Production configs
    ENVIRONMENT: str = "local"
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://web.test",
    ]
    ALLOWED_HOSTS: list[str] = [
        "localhost",
        "127.0.0.1",
        "api.test",
        "web.test",
    ]
    
    # SMTP & Email Auth
    SMTP_SERVER: Optional[str] = None
    SMTP_HOST: Optional[str] = None  # compatibility alias
    SMTP_PORT: int = 587
    SMTP_STARTTLS: bool = True
    SMTP_USE_TLS: bool = False
    SMTP_TLS_VALIDATE_CERTS: bool = True
    SMTP_TLS_CA_FILE: Optional[str] = None
    SMTP_TIMEOUT_SECONDS: float = 20.0
    SMTP_REQUIRE_AUTH: bool = True
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = "noreply@vidyaverse.com"
    SMTP_FROM_NAME: Optional[str] = None
    AUTH_OTP_FROM_EMAIL: Optional[str] = None  # compatibility alias
    AUTH_OTP_FROM_NAME: Optional[str] = None   # compatibility alias

    # OTP delivery behavior
    OTP_ALLOW_DEBUG_FALLBACK: bool = False
    OTP_SEND_COOLDOWN_SECONDS: int = 60
    OTP_EMAIL_MAX_RETRIES: int = 3
    AUTH_AUDIT_ENABLED: bool = True
    AUTH_ABUSE_MAX_FAILED_ATTEMPTS: int = 5
    AUTH_ABUSE_WINDOW_SECONDS: int = 15 * 60
    AUTH_ABUSE_LOCK_SECONDS: int = 30 * 60

    # OAuth (Google implemented, other providers surfaced as config status)
    GOOGLE_OAUTH_CLIENT_ID: Optional[str] = None
    GOOGLE_OAUTH_CLIENT_SECRET: Optional[str] = None
    GOOGLE_OAUTH_REDIRECT_URI: Optional[str] = None
    LINKEDIN_OAUTH_CLIENT_ID: Optional[str] = None
    LINKEDIN_OAUTH_CLIENT_SECRET: Optional[str] = None
    MICROSOFT_OAUTH_CLIENT_ID: Optional[str] = None
    MICROSOFT_OAUTH_CLIENT_SECRET: Optional[str] = None
    FRONTEND_OAUTH_SUCCESS_URL: str = "http://localhost:3000/auth/callback"
    FRONTEND_OAUTH_FAILURE_URL: str = "http://localhost:3000/login"
    
    # AI Chatbot / OpenRouter
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: str = "meta-llama/llama-3-8b-instruct:free"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # Generic OpenAI-compatible LLM endpoint (preferred over OPENROUTER_* when set)
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: Optional[str] = None
    LLM_API_BASE_URL: Optional[str] = None

    # Quality / safety evaluation (optional)
    LLM_JUDGE_ENABLED: bool = False
    LLM_JUDGE_MODEL: Optional[str] = None
    LLM_JUDGE_API_KEY: Optional[str] = None
    LLM_JUDGE_API_BASE_URL: Optional[str] = None
    LLM_JUDGE_MIN_SCORE: float = 0.55  # 0..1 gate when enabled

    # RAG governance defaults
    RAG_TEMPLATE_KEY_DEFAULT: str = "ask_ai"
    RAG_DEFAULT_RETRIEVAL_TOP_K: int = 8
    RAG_LLM_MODEL: Optional[str] = None
    RAG_JUDGE_MODEL: Optional[str] = None
    RAG_WARMUP_ON_STARTUP: bool = True
    RAG_WARMUP_TIMEOUT_SECONDS: float = 120.0
    RAG_REQUEST_TIMEOUT_SECONDS: float = 25.0
    RAG_RETRIEVAL_TIMEOUT_SECONDS: float = 45.0
    RAG_LLM_TIMEOUT_SECONDS: float = 15.0
    RAG_JUDGE_TIMEOUT_SECONDS: float = 8.0
    RAG_OFFLINE_EVAL_DATASET_PATH: str = "backend/benchmarks/data/gold_temporal_holdout.jsonl"
    RAG_OFFLINE_MIN_RECALL_AT_K: float = 0.35
    RAG_ONLINE_MIN_POSITIVE_FEEDBACK_RATE: float = 0.55
    RAG_ONLINE_MIN_REQUESTS: int = 50

    # Analytics warehouse / feature-store controls
    ANALYTICS_WAREHOUSE_ENABLED: bool = True
    ANALYTICS_LOOKBACK_DAYS_DEFAULT: int = 30
    FEATURE_STORE_LABEL_WINDOW_HOURS: int = 72
    ANALYTICS_WAREHOUSE_EXPORT_ENABLED: bool = True
    ANALYTICS_WAREHOUSE_EXPORT_ROOT: str = "backend/storage/warehouse"
    ANALYTICS_WAREHOUSE_DUCKDB_PATH: str = "backend/storage/warehouse/warehouse.duckdb"
    ANALYTICS_WAREHOUSE_EXPORT_FORMAT: str = "duckdb_parquet"  # duckdb_parquet | parquet | disabled
    ANALYTICS_WAREHOUSE_SQL_MODELS_DIR: str = "backend/warehouse/models"
    ANALYTICS_WAREHOUSE_CLICKHOUSE_ENABLED: bool = False
    ANALYTICS_WAREHOUSE_CLICKHOUSE_HOST: Optional[str] = None
    ANALYTICS_WAREHOUSE_CLICKHOUSE_PORT: int = 8123
    ANALYTICS_WAREHOUSE_CLICKHOUSE_DATABASE: str = "vidyaverse"
    ANALYTICS_WAREHOUSE_CLICKHOUSE_USERNAME: Optional[str] = None
    ANALYTICS_WAREHOUSE_CLICKHOUSE_PASSWORD: Optional[str] = None
    ANALYTICS_WAREHOUSE_CLICKHOUSE_SECURE: bool = False
    ANALYTICS_WAREHOUSE_CLICKHOUSE_TABLE_PREFIX: str = "mart_"
    ANALYTICS_WAREHOUSE_REQUIRED_MARTS: list[str] = [
        "mart_daily_metrics",
        "mart_funnel_metrics",
        "mart_cohort_metrics",
        "mart_feature_freshness",
        "mart_parity_scorecard",
        "mart_training_dataset",
        "mart_ranking_slice_metrics",
        "mart_metadata",
    ]
    ANALYTICS_WAREHOUSE_MAX_STALENESS_MINUTES: int = 180
    ANALYTICS_WAREHOUSE_ENFORCE_CLICKHOUSE_IN_PRODUCTION: bool = True
    ANALYTICS_WAREHOUSE_ENFORCE_FRESHNESS_IN_PRODUCTION: bool = True
    ANALYTICS_WAREHOUSE_BI_TOOL_URL: Optional[str] = None
    ANALYTICS_BI_TOOL_URL: Optional[str] = None
    ONLINE_FEATURES_PUBLISH_ENABLED: bool = True
    ONLINE_FEATURES_KEY_PREFIX: str = "vidyaverse:features"
    ONLINE_FEATURES_TTL_SECONDS: int = 60 * 60 * 24 * 14

    # Resume storage & parsing
    RESUME_STORAGE_DIR: str = "backend/storage/resumes"
    RESUME_MAX_FILE_SIZE_MB: int = 8
    ANALYTICS_WAREHOUSE_AUTORUN_ENABLED: bool = True
    ANALYTICS_WAREHOUSE_REBUILD_INTERVAL_HOURS: int = 24

    # Embeddings / semantic ranking
    EMBEDDING_PROVIDER: str = "sentence_transformers"  # sentence_transformers | openai | auto
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_API_BASE_URL: Optional[str] = None
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    SEMANTIC_DEDUP_THRESHOLD: float = 0.9
    VECTOR_STORE_PROVIDER: str = "mongo"  # mongo | memory
    VECTOR_STORE_PERSISTENCE_ENABLED: bool = True

    # Learned ranker (LightGBM/XGBoost) for real personalization
    LEARNED_RANKER_ENABLED: bool = False
    LEARNED_RANKER_MODEL_PATH: str = ""
    LEARNED_RANKER_ARTIFACT_URI: str = ""
    LEARNED_RANKER_ARTIFACT_CHECKSUM_SHA256: str = ""
    LEARNED_RANKER_FEATURES: list[str] = []
    LEARNED_RANKER_SHADOW_ENABLED: bool = True
    LEARNED_RANKER_SHADOW_SAMPLE_RATE: float = 1.0
    LEARNED_RANKER_SHADOW_MAX_CANDIDATES: int = 100
    LEARNED_RANKER_STAGED_ROLLOUT_ENABLED: bool = False
    LEARNED_RANKER_STAGED_ROLLOUT_PERCENT: int = 0
    LEARNED_RANKER_STAGED_BASELINE_MODE: str = "semantic"
    LEARNED_RANKER_ROLLOUT_EXPERIMENT_KEY: str = "learned_ranker_rollout"
    LEARNED_RANKER_ROLLBACK_ON_GUARDRAIL_FAILURE: bool = True
    LEARNED_RANKER_REQUIRE_ARTIFACT_IN_PRODUCTION: bool = True
    LEARNED_RANKER_REQUIRE_LOADED_IN_PRODUCTION: bool = True
    MODEL_REGISTRY_REQUIRE_APPROVED_FOR_ACTIVATION: bool = True

    # Data + MLOps (ranking weights)
    MLOPS_AUTORUN_ENABLED: bool = True
    MLOPS_RETRAIN_INTERVAL_HOURS: int = 24
    MLOPS_RETRAIN_LOOKBACK_DAYS: int = 90
    MLOPS_LABEL_WINDOW_HOURS: int = 72
    MLOPS_MIN_TRAINING_ROWS: int = 200
    MLOPS_TRAIN_GRID_STEP: float = 0.05
    MLOPS_ACTIVATION_POLICY: str = "guarded"  # manual | auc_gain | guarded
    MLOPS_AUTO_ACTIVATE: bool = False
    MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN: float = 0.0
    MLOPS_AUTO_ACTIVATE_MIN_POSITIVE_RATE: float = 0.005
    MLOPS_AUTO_ACTIVATE_MAX_WEIGHT_SHIFT: float = 0.35
    MLOPS_GUARDRAIL_LOOKBACK_DAYS: int = 30
    MLOPS_GUARDRAIL_REQUIRE_ONLINE_KPIS: bool = True
    MLOPS_GUARDRAIL_MAX_APPLY_RATE_DROP: float = 0.0
    MLOPS_GUARDRAIL_MAX_FRESHNESS_REGRESSION_SECONDS: float = 300.0
    MLOPS_GUARDRAIL_MAX_LATENCY_P95_REGRESSION_MS: float = 75.0
    MLOPS_GUARDRAIL_MAX_FAILURE_RATE_REGRESSION: float = 0.01
    MLOPS_BOOTSTRAP_ACTIVE_MODEL_ON_STARTUP: bool = True
    MLOPS_DRIFT_CHECK_INTERVAL_HOURS: int = 6
    MLOPS_DRIFT_LOOKBACK_DAYS: int = 7
    MLOPS_MODEL_ARTIFACT_ROOT: str = "backend/models"
    MLOPS_MODEL_ARTIFACT_CACHE_DIR: str = "backend/storage/model_artifacts"
    MLOPS_MODEL_ARTIFACT_S3_ENDPOINT_URL: Optional[str] = None
    MLOPS_MODEL_ARTIFACT_S3_REGION: Optional[str] = None
    MLOPS_MODEL_ARTIFACT_S3_ACCESS_KEY_ID: Optional[str] = None
    MLOPS_MODEL_ARTIFACT_S3_SECRET_ACCESS_KEY: Optional[str] = None

    # Assistant orchestration
    ASSISTANT_CHAT_MEMORY_ENABLED: bool = True
    ASSISTANT_CHAT_MEMORY_MAX_TURNS: int = 12
    ASSISTANT_CHAT_RAG_AUTO_ROUTE_ENABLED: bool = True
    ASSISTANT_CHAT_SURFACE_DEFAULT: str = "global_chat"
    ASSISTANT_CHAT_SUMMARY_ENABLED: bool = True
    ASSISTANT_CHAT_SUMMARY_TRIGGER_TURNS: int = 16
    ASSISTANT_CHAT_SUMMARY_RETAIN_TURNS: int = 8
    ASSISTANT_CHAT_PROMPT_VERSION: str = "assistant.v2"
    ASSISTANT_CHAT_TOOLS_ENABLED: bool = True

    # Security event reporting
    SECURITY_CSP_REPORT_URI: str = "/api/v1/security/csp-report"
    SECURITY_CSP_REPORT_ONLY_FRONTEND: bool = False

    # Embedding health posture
    EMBEDDING_HEALTH_ENFORCE_IN_PRODUCTION: bool = True
    EMBEDDING_HEALTH_FAIL_ON_HASH_FALLBACK: bool = True
    MLOPS_DRIFT_PSI_ALERT_THRESHOLD: float = 0.25
    MLOPS_DRIFT_Z_ALERT_THRESHOLD: float = 3.0
    MLOPS_ALERTS_ENABLED: bool = True
    MLOPS_ALERT_WEBHOOK_URL: Optional[str] = None
    MLOPS_ALERT_WEBHOOK_TIMEOUT_SECONDS: float = 8.0
    MLOPS_ALERT_COOLDOWN_MINUTES: int = 120
    MLOPS_ALERT_SLACK_WEBHOOK_URL: Optional[str] = None
    MLOPS_ALERT_PAGERDUTY_ROUTING_KEY: Optional[str] = None
    MLOPS_ALERT_PAGERDUTY_SEVERITY: str = "error"
    MLOPS_INCIDENT_AUTO_CREATE: bool = True
    MLOPS_INCIDENT_DEFAULT_OWNER: Optional[str] = None
    MLOPS_INCIDENT_REVIEW_DUE_HOURS: int = 24
    MLOPS_INCIDENT_BREACH_SLA_HOURS: int = 72
    MLOPS_ENFORCE_LIVE_ALERT_CHANNELS_IN_PRODUCTION: bool = True
    MLOPS_ENFORCE_OWNER_IN_PRODUCTION: bool = True

    # Offline/online parity gate (auto-activation safety)
    MLOPS_PARITY_ENABLED: bool = True
    MLOPS_PARITY_MIN_REAL_IMPRESSIONS_PER_MODE: int = 200
    MLOPS_PARITY_MIN_REAL_REQUESTS_PER_MODE: int = 100
    MLOPS_PARITY_MAX_CTR_REGRESSION: float = 0.0
    MLOPS_PARITY_MAX_APPLY_RATE_REGRESSION: float = 0.0
    MLOPS_PARITY_MIN_OFFLINE_AUC_GAIN_FOR_ONLINE_GATES: float = 0.0
    MLOPS_TRIGGER_RETRAIN_ON_DRIFT_ALERT: bool = True

    # Experiment guardrails / auto-pause
    EXPERIMENT_AUTO_PAUSE_ON_GUARDRAIL_FAIL: bool = True
    EXPERIMENT_SRM_P_VALUE_THRESHOLD: float = 0.01
    EXPERIMENT_SIGNIFICANCE_ALPHA: float = 0.05
    EXPERIMENT_GUARDRAIL_MIN_IMPRESSIONS_PER_VARIANT: int = 50
    EXPERIMENT_MIN_IMPRESSIONS_PER_VARIANT_FOR_LIFT: int = 200
    EXPERIMENT_TARGET_POWER: float = 0.8
    
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

settings = Settings()


def normalized_environment() -> str:
    return str(settings.ENVIRONMENT or "local").strip().lower() or "local"


def is_production_env() -> bool:
    return normalized_environment() == "production"


def auth_cookie_only_mode_enabled() -> bool:
    return bool(settings.AUTH_COOKIE_ONLY_MODE) or is_production_env()


def resolved_csp_value() -> str:
    explicit = str(settings.SECURITY_CSP_VALUE or "").strip()
    if explicit:
        return explicit
    return STRICT_DEFAULT_CSP


def smtp_server_value() -> Optional[str]:
    return (settings.SMTP_SERVER or settings.SMTP_HOST or "").strip() or None


def smtp_from_email_value() -> str:
    default_from = "noreply@vidyaverse.com"
    smtp_from = (settings.SMTP_FROM_EMAIL or "").strip()
    otp_from = (settings.AUTH_OTP_FROM_EMAIL or "").strip()

    # Keep backward compatibility with AUTH_OTP_FROM_EMAIL while avoiding
    # accidental use of the placeholder default sender in SMTP providers
    # that require a verified mailbox (for example Gmail SMTP).
    if otp_from and (not smtp_from or smtp_from.lower() == default_from):
        return otp_from
    return smtp_from or otp_from or default_from


def analytics_bi_tool_url() -> Optional[str]:
    value = (settings.ANALYTICS_WAREHOUSE_BI_TOOL_URL or settings.ANALYTICS_BI_TOOL_URL or "").strip()
    return value or None


def smtp_from_name_value() -> Optional[str]:
    return (settings.SMTP_FROM_NAME or settings.AUTH_OTP_FROM_NAME or "").strip() or None
