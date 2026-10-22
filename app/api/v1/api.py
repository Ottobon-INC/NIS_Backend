from fastapi import APIRouter

from app.api.v1.endpoints import (
    health,
    contacts,
    bhanu,
    research,
    opportunities,
    meetings,
    company_knowledge,
    network,
    introductions,
    cockpit,
    matching,
    platform,
    trusted_context,
)

api_router = APIRouter()

# Core Infrastructure
api_router.include_router(health.router, prefix="/health", tags=["health"])

# Identity, Contacts & Research
api_router.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
api_router.include_router(bhanu.router, prefix="/bhanu", tags=["bhanu network"])
api_router.include_router(research.router, prefix="/research", tags=["research"])

# Opportunity Engine & Context
api_router.include_router(opportunities.router, prefix="/opportunities", tags=["opportunities"])
api_router.include_router(meetings.router, prefix="/meetings", tags=["meetings"])
api_router.include_router(company_knowledge.router, prefix="/knowledge", tags=["company knowledge"])
api_router.include_router(trusted_context.router, tags=["trusted context"])

# Network Graph, Introductions & Decision Cockpit
api_router.include_router(network.router, prefix="/network", tags=["network"])
api_router.include_router(introductions.router, prefix="/introductions", tags=["introductions"])
api_router.include_router(cockpit.router, prefix="/cockpit", tags=["founder cockpit"])

# Problem Matching
api_router.include_router(matching.router, prefix="/matching", tags=["problem matching"])

# Platform & Products
api_router.include_router(platform.router, tags=["platform"])

