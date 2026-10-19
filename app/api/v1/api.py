from fastapi import APIRouter
from app.api.v1.endpoints import (
    health,
    # Stream 1: Identity, Contacts & Research
    contacts,
    bhanu,
    research,
    # Stream 2: Opportunity Engine & Context
    opportunities,
    meetings,
    company_knowledge,
    # Stream 3: Network Graph & Introductions
    network,
    introductions,
    cockpit,
)

api_router = APIRouter()

# Core Infrastructure
api_router.include_router(health.router, prefix="/health", tags=["health"])

# Stream 1: Identity, Contacts & Live Research
api_router.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
api_router.include_router(bhanu.router, prefix="/bhanu", tags=["bhanu network"])
api_router.include_router(research.router, prefix="/research", tags=["research"])

# Stream 2: Opportunity Engine & Context (Live Opportunity Search, Lifecycle, Meetings)
api_router.include_router(opportunities.router, prefix="/opportunities", tags=["opportunities"])
api_router.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
api_router.include_router(company_knowledge.router, prefix="/knowledge", tags=["company knowledge"])

# Stream 3: Network Graph, Introductions & Decision Cockpit
api_router.include_router(network.router, prefix="/network", tags=["network"])
api_router.include_router(introductions.router, prefix="/introductions", tags=["introductions"])
api_router.include_router(cockpit.router, prefix="/cockpit", tags=["founder cockpit"])
