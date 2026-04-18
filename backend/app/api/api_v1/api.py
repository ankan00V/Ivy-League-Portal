from fastapi import APIRouter
from app.api.api_v1.endpoints import auth, users, opportunities, applications, social, chat, experiments, mlops, jobs, employer

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(opportunities.router, prefix="/opportunities", tags=["opportunities"])
api_router.include_router(applications.router, prefix="/applications", tags=["applications"])
api_router.include_router(social.router, prefix="/social", tags=["social"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(experiments.router, prefix="/experiments", tags=["experiments"])
api_router.include_router(mlops.router, prefix="/mlops", tags=["mlops"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(employer.router, prefix="/employer", tags=["employer"])
