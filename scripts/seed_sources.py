import asyncio
import sys
import os
sys.path.insert(0, os.path.abspath("."))
from app.db.session import AsyncSessionLocal
from app.models.research import ResearchSource, SourceStatus, SourcePriority
from sqlalchemy.future import select

SOURCES_TO_SEED = [
    {
        "id": "general_web",
        "name": "General Public Website",
        "source_type": "public_web",
        "priority": SourcePriority.P1,
        "status": SourceStatus.ENABLED,
        "provider_type": "INTERNAL_HTTP",
        "description": "Fetches and analyzes public web pages and profiles using HTTP GET with SSRF protection",
        "supported_entity_types": ["person", "company"],
        "supported_intelligence_types": ["profile", "company", "public_web"],
        "reliability_score": 60,
        "requires_api_key": False,
        "requires_paid_license": False
    },
    {
        "id": "duckduckgo",
        "name": "DuckDuckGo Web Search",
        "source_type": "search_engine",
        "priority": SourcePriority.P1,
        "status": SourceStatus.ENABLED,
        "provider_type": "EXTERNAL_API",
        "description": "Performs targeted search engine indexing for profiles, news, and executive mentions",
        "supported_entity_types": ["person", "company"],
        "supported_intelligence_types": ["public_web", "news", "executive_mentions"],
        "reliability_score": 75,
        "requires_api_key": False,
        "requires_paid_license": False
    },
    {
        "id": "github",
        "name": "GitHub Developer Intelligence",
        "source_type": "code_repository",
        "priority": SourcePriority.P1,
        "status": SourceStatus.ENABLED,
        "provider_type": "EXTERNAL_API",
        "description": "Discovers developer profiles, open-source repositories, tech stacks, and contributions via GitHub REST API",
        "supported_entity_types": ["person", "company"],
        "supported_intelligence_types": ["profile", "repositories", "technologies", "public_projects"],
        "reliability_score": 90,
        "requires_api_key": False,
        "requires_paid_license": False
    },
    {
        "id": "academic_openalex",
        "name": "Academic Research & Publications (OpenAlex & Crossref)",
        "source_type": "academic_database",
        "priority": SourcePriority.P2,
        "status": SourceStatus.ENABLED,
        "provider_type": "EXTERNAL_API",
        "description": "Searches scholarly publications, citations, co-authors, and ORCID records via OpenAlex & Crossref APIs",
        "supported_entity_types": ["person"],
        "supported_intelligence_types": ["publications", "academic_citations", "orcid", "research_topics"],
        "reliability_score": 95,
        "requires_api_key": False,
        "requires_paid_license": False
    },
    {
        "id": "company_web",
        "name": "Company & Professional Websites",
        "source_type": "corporate_web",
        "priority": SourcePriority.P1,
        "status": SourceStatus.ENABLED,
        "provider_type": "WEB_SCRAPER",
        "description": "Discovers corporate leadership pages, team directories, and professional bios",
        "supported_entity_types": ["person", "company"],
        "supported_intelligence_types": ["company_bio", "official_role", "leadership", "team_page"],
        "reliability_score": 85,
        "requires_api_key": False,
        "requires_paid_license": False
    },
    {
        "id": "news_public",
        "name": "News, Public Media & Wikidata Registry",
        "source_type": "news_media",
        "priority": SourcePriority.P2,
        "status": SourceStatus.ENABLED,
        "provider_type": "EXTERNAL_API",
        "description": "Searches Wikidata Knowledge Graph for entity validation and media coverage for interviews & conferences",
        "supported_entity_types": ["person", "company"],
        "supported_intelligence_types": ["news_articles", "interviews", "wikidata_entities", "press_releases"],
        "reliability_score": 80,
        "requires_api_key": False,
        "requires_paid_license": False
    },
    {
        "id": "agent_reach",
        "name": "Agent Reach Platform",
        "source_type": "public_web",
        "priority": SourcePriority.P2,
        "status": SourceStatus.ENABLED,
        "provider_type": "CLI_TOOL",
        "description": "Multi-platform intelligence tool for web and social profiles",
        "supported_entity_types": ["person", "company"],
        "supported_intelligence_types": ["github", "twitter", "public_web"],
        "reliability_score": 80,
        "requires_api_key": False,
        "requires_paid_license": False
    },
    {
        "id": "evidence_engine",
        "name": "Commercial Opportunity Intelligence Engine",
        "source_type": "ai_synthesis",
        "priority": SourcePriority.P0,
        "status": SourceStatus.ENABLED,
        "provider_type": "AI_SYNTHESIS",
        "description": "Synthesizes raw evidence across all sources into executive snapshots and commercial intelligence reports",
        "supported_entity_types": ["person", "company"],
        "supported_intelligence_types": ["commercial_opportunity", "executive_snapshot", "claims"],
        "reliability_score": 95,
        "requires_api_key": True,
        "requires_paid_license": False
    }
]

async def seed():
    async with AsyncSessionLocal() as db:
        for s_data in SOURCES_TO_SEED:
            existing = (await db.execute(select(ResearchSource).where(ResearchSource.id == s_data["id"]))).scalars().first()
            if not existing:
                src = ResearchSource(**s_data)
                db.add(src)
            else:
                for k, v in s_data.items():
                    setattr(existing, k, v)
        try:
            await db.commit()
            print(f"Successfully seeded {len(SOURCES_TO_SEED)} ResearchSources.")
        except Exception as e:
            print(f"Error seeding sources: {e}")

if __name__ == "__main__":
    asyncio.run(seed())
