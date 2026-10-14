from fastapi import APIRouter
from .endpoints import health, research, company_knowledge, contacts, meetings, platform, matching

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(research.router, prefix="/research", tags=["research"])
api_router.include_router(company_knowledge.router, prefix="/knowledge", tags=["company knowledge"])
api_router.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
api_router.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
api_router.include_router(matching.router, prefix="/matching", tags=["problem matching"])
api_router.include_router(platform.router, tags=["platform"])
