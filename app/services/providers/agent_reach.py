from typing import Dict, Any, Optional
from app.services.providers.base import ResearchProvider
from app.core.agent_reach_cli import AgentReachCLI
import logging

logger = logging.getLogger("networkos")

class AgentReachProvider(ResearchProvider):
    def get_provider_metadata(self) -> Dict[str, Any]:
        return {
            "source_id": "agent_reach",
            "name": "Agent Reach Platform",
            "provider_type": "CLI_TOOL",
            "supported_entity_types": ["person", "company"],
            "supported_intelligence_types": ["public_web", "github", "twitter"],
            "requires_api_key": False,
            "requires_paid_license": False
        }

    async def fetch_public_webpage(self, url: str) -> Dict[str, Any]:
        """Reads a webpage using agent-reach read"""
        logger.info(f"AgentReach: Reading webpage {url}")
        result = await AgentReachCLI.execute_read(url)
        
        if result["status"] == "SUCCESS":
            return {
                "status": "SUCCESS",
                "final_url": url,
                "http_status": 200,
                "content_type": "application/json",
                "text_content": str(result["data"])
            }
        return {"status": "ERROR", "error": result.get("error", "Unknown error")}

    async def search_person(self, query: str) -> Dict[str, Any]:
        # For person search, we'll default to searching web or a specific platform
        # The Orchestrator should probably invoke specific searches, but we provide a default
        logger.info(f"AgentReach: Searching person {query}")
        result = await AgentReachCLI.execute_search("web", query)
        if result["status"] == "SUCCESS":
            return {
                "status": "SUCCESS",
                "extracted_data": result["data"]
            }
        return {"status": "ERROR", "error": result.get("error", "Unknown error")}

    async def search_target(self, target: str, query: str) -> Dict[str, Any]:
        """Custom method for specific agent-reach targets (e.g. github, twitter)"""
        logger.info(f"AgentReach: Searching {target} for {query}")
        result = await AgentReachCLI.execute_search(target, query)
        if result["status"] == "SUCCESS":
            return {
                "status": "SUCCESS",
                "extracted_data": result["data"]
            }
        return {"status": "ERROR", "error": result.get("error", "Unknown error")}

    async def search_company(self, query: str) -> Dict[str, Any]:
        return await self.search_person(query)

    async def fetch_person(self, identifier: str) -> Dict[str, Any]:
        return await self.fetch_public_webpage(identifier)

    async def fetch_company(self, identifier: str) -> Dict[str, Any]:
        return await self.fetch_public_webpage(identifier)

    async def fetch_signals(self, query: str) -> Dict[str, Any]:
        return await self.search_target("web", query)
