from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

class Settings(BaseSettings):
    PROJECT_NAME: str = "VidyaVerse API"
    API_V1_STR: str = "/api/v1"
    
    # JWT Auth
    SECRET_KEY: str = "your_super_secret_key_here_for_development_change_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
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
    
    # Celery & Redis
    REDIS_URL: str = "redis://localhost:6379/0"

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
    
    # Production configs
    ENVIRONMENT: str = "local"
    BACKEND_CORS_ORIGINS: list[str] = ["*"]  # E.g., ["http://localhost:3000", "https://vidyaverse.com"]
    ALLOWED_HOSTS: list[str] = ["*"]
    
    # SMTP & Email Auth
    SMTP_SERVER: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_STARTTLS: bool = True
    SMTP_USE_TLS: bool = False
    SMTP_TIMEOUT_SECONDS: float = 20.0
    SMTP_REQUIRE_AUTH: bool = True
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = "noreply@vidyaverse.com"

    # OTP delivery behavior
    OTP_ALLOW_DEBUG_FALLBACK: bool = False
    
    # AI Chatbot / OpenRouter
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: str = "meta-llama/llama-3-8b-instruct:free"

    # Quality / safety evaluation (optional)
    LLM_JUDGE_ENABLED: bool = False
    LLM_JUDGE_MODEL: Optional[str] = None
    LLM_JUDGE_MIN_SCORE: float = 0.55  # 0..1 gate when enabled

    # Embeddings / semantic ranking
    EMBEDDING_PROVIDER: str = "sentence_transformers"  # sentence_transformers | openai | auto
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    SEMANTIC_DEDUP_THRESHOLD: float = 0.9

    # Learned ranker (LightGBM/XGBoost) for real personalization
    LEARNED_RANKER_ENABLED: bool = False
    LEARNED_RANKER_MODEL_PATH: str = ""
    LEARNED_RANKER_FEATURES: list[str] = []

    # Data + MLOps (ranking weights)
    MLOPS_AUTORUN_ENABLED: bool = True
    MLOPS_RETRAIN_INTERVAL_HOURS: int = 24
    MLOPS_RETRAIN_LOOKBACK_DAYS: int = 90
    MLOPS_LABEL_WINDOW_HOURS: int = 72
    MLOPS_MIN_TRAINING_ROWS: int = 200
    MLOPS_TRAIN_GRID_STEP: float = 0.05
    MLOPS_AUTO_ACTIVATE: bool = False
    MLOPS_AUTO_ACTIVATE_MIN_AUC_GAIN: float = 0.0
    MLOPS_BOOTSTRAP_ACTIVE_MODEL_ON_STARTUP: bool = True
    MLOPS_DRIFT_CHECK_INTERVAL_HOURS: int = 6
    MLOPS_DRIFT_LOOKBACK_DAYS: int = 7
    
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

settings = Settings()
