from fastapi import APIRouter
from app.api.api_v1.endpoints import (
    admin,
    analytics,
    applications,
    auth,
    chat,
    employer,
    experiments,
    jobs,
    mlops,
    opportunities,
    rag_governance,
    security,
    social,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(opportunities.router, prefix="/opportunities", tags=["opportunities"])
api_router.include_router(applications.router, prefix="/applications", tags=["applications"])
api_router.include_router(social.router, prefix="/social", tags=["social"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(experiments.router, prefix="/experiments", tags=["experiments"])
api_router.include_router(mlops.router, prefix="/mlops", tags=["mlops"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(employer.router, prefix="/employer", tags=["employer"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(rag_governance.router, prefix="/rag-governance", tags=["rag-governance"])
api_router.include_router(security.router, prefix="/security", tags=["security"])
