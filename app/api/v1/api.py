from fastapi import APIRouter
from app.api.v1.endpoints import health, research, company_knowledge, contacts

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(research.router, prefix="/research", tags=["research"])
api_router.include_router(company_knowledge.router, prefix="/knowledge", tags=["company knowledge"])
api_router.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
