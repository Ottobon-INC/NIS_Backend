import asyncio
from app.db.session import AsyncSessionLocal
from app.models.research import ResearchSource, SourceStatus, SourcePriority
import uuid

async def seed():
    async with AsyncSessionLocal() as db:
        # Check if already exists
        # We can just blindly add or check. Let's add General Web
        source = ResearchSource(
            id="general_web",
            name="General Public Website",
            source_type="public_web",
            priority=SourcePriority.P1,
            status=SourceStatus.ENABLED,
            provider_type="INTERNAL_HTTP",
            description="Fetches public web pages using HTTP GET",
            supported_entity_types=["person", "company"],
            supported_intelligence_types=["profile", "company", "public_web"],
            reliability_score=50,
            requires_api_key=False,
            requires_paid_license=False
        )
        db.add(source)
        
        source2 = ResearchSource(
            id="duckduckgo",
            name="DuckDuckGo Search",
            source_type="public_web",
            priority=SourcePriority.P2,
            status=SourceStatus.ENABLED,
            provider_type="EXTERNAL_API",
            description="Searches DuckDuckGo",
            supported_entity_types=["person", "company"],
            supported_intelligence_types=["public_web", "news"],
            reliability_score=70,
            requires_api_key=False,
            requires_paid_license=False
        )
        source3 = ResearchSource(
            id="agent_reach",
            name="Agent Reach Platform",
            source_type="public_web",
            priority=SourcePriority.P2,
            status=SourceStatus.ENABLED,
            provider_type="CLI_TOOL",
            description="Multi-platform search using agent-reach",
            supported_entity_types=["person", "company"],
            supported_intelligence_types=["github", "twitter", "public_web"],
            reliability_score=80,
            requires_api_key=False,
            requires_paid_license=False
        )
        db.add(source3)
        try:
            await db.commit()
            print("Successfully seeded ResearchSources.")
        except Exception as e:
            print(f"Error seeding database (might already exist): {e}")

if __name__ == "__main__":
    asyncio.run(seed())
