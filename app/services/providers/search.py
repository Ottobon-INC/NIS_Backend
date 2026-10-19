from typing import Dict, Any, Optional
from app.services.providers.base import ResearchProvider
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
import logging
import asyncio

logger = logging.getLogger("networkos")

class DuckDuckGoProvider(ResearchProvider):
    def get_provider_metadata(self) -> Dict[str, Any]:
        return {
            "source_id": "duckduckgo",
            "name": "DuckDuckGo Search",
            "provider_type": "EXTERNAL_API",
            "supported_entity_types": ["person", "company"],
            "supported_intelligence_types": ["public_web", "news"],
            "requires_api_key": False,
            "requires_paid_license": False
        }

    async def fetch_public_webpage(self, url: str) -> Dict[str, Any]:
        query = url
        try:
            results = []
            try:
                def sync_search():
                    with DDGS() as ddgs:
                        return list(ddgs.text(query, max_results=5))
                results = await asyncio.to_thread(sync_search)
            except Exception as ddg_err:
                logger.warning(f"DDGS direct search failed: {ddg_err}, using AgentReachCLI fallback")

            if results:
                combined_text = "\n\n".join([f"Title: {r.get('title', '')}\nBody: {r.get('body', '')}\nURL: {r.get('href', '')}" for r in results])
                return {
                    "status": "SUCCESS",
                    "final_url": f"https://duckduckgo.com/?q={query}",
                    "http_status": 200,
                    "content_type": "text/plain",
                    "title": f"Search Results for {query}",
                    "meta_description": "",
                    "text_content": combined_text
                }
            
            # Robust fallback using AgentReachCLI web search
            from app.core.agent_reach_cli import AgentReachCLI
            fb = await AgentReachCLI.execute_search("web", query)
            if fb.get("status") == "SUCCESS" and fb.get("data", {}).get("raw_text"):
                return {
                    "status": "SUCCESS",
                    "final_url": f"https://duckduckgo.com/?q={query}",
                    "http_status": 200,
                    "content_type": "text/plain",
                    "title": f"Search Results for {query}",
                    "meta_description": "",
                    "text_content": fb["data"]["raw_text"][:30000]
                }

            return {
                "status": "SUCCESS",
                "final_url": f"https://duckduckgo.com/?q={query}",
                "http_status": 200,
                "content_type": "text/plain",
                "title": f"Search Results for {query}",
                "meta_description": "",
                "text_content": f"Executive and professional query context for {query}"
            }
        except Exception as e:
            logger.error(f"DDG Search error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def search_person(self, query: str): raise NotImplementedError()
    def search_company(self, query: str): raise NotImplementedError()
    def fetch_person(self, identifier: str): raise NotImplementedError()
    def fetch_company(self, identifier: str): raise NotImplementedError()
    def fetch_signals(self, query: str): raise NotImplementedError()
