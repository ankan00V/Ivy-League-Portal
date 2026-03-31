from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import settings

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
import certifi

# Import all Beanie Documents
from app.models.user import User
from app.models.post import Post, Comment
from app.models.profile import Profile
from app.models.opportunity import Opportunity
from app.models.application import Application
from app.models.otp_code import OTPCode

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.scraper import run_scheduled_scrapers

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize MongoDB connection using explicit cert verification parameters
    client = AsyncIOMotorClient(
        settings.MONGODB_URL, 
        tls=True, 
        tlsAllowInvalidCertificates=True,
        tlsCAFile=certifi.where()
    )
    
    # Initialize Beanie ODM with the database and document models
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            User,
            Post,
            Comment,
            Profile,
            Opportunity,
            Application,
            OTPCode,
        ]
    )

    # Initialize and start the background scraper scheduler
    scheduler = AsyncIOScheduler(
        timezone="UTC",
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": max(60, settings.SCRAPER_INTERVAL_MINUTES * 60),
        },
    )
    scheduler.add_job(
        run_scheduled_scrapers,
        "interval",
        minutes=max(1, settings.SCRAPER_INTERVAL_MINUTES),
        id="scraper_job",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.start()
    print(
        "[Lifecycle] Background Scraper Scheduler started "
        f"(runs every {max(1, settings.SCRAPER_INTERVAL_MINUTES)} mins)."
    )

    yield
    
    # Clean up (if necessary)
    scheduler.shutdown()
    client.close()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.ENVIRONMENT != "production" else None,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    lifespan=lifespan,
)

from app.api.api_v1.api import api_router
app.include_router(api_router, prefix=settings.API_V1_STR)

# Security Middlewares
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["system"])
def health_check():
    """Health check endpoint for load balancers."""
    return {"status": "healthy", "environment": settings.ENVIRONMENT}

@app.get("/")
def read_root():
    return {"message": "Welcome to VidyaVerse API"}
