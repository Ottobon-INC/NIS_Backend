from typing import Dict, Any, Optional
from app.services.providers.base import ResearchProvider
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
        # We overload fetch_public_webpage to treat the URL as the search query
        # Since the orchestrator sets target_url to the query
        query = url
        try:
            def sync_search():
                return list(DDGS().text(query, max_results=3))
                
            results = await asyncio.to_thread(sync_search)
            combined_text = "\n\n".join([f"Title: {r['title']}\nBody: {r['body']}\nURL: {r['href']}" for r in results])
            return {
                "status": "SUCCESS",
                "final_url": f"https://duckduckgo.com/?q={query}",
                "http_status": 200,
                "content_type": "text/plain",
                "title": f"Search Results for {query}",
                "meta_description": "",
                "text_content": combined_text
            }
        except Exception as e:
            logger.error(f"DDG Search error: {e}")
            return {"status": "ERROR", "error": str(e)}

    def search_person(self, query: str): raise NotImplementedError()
    def search_company(self, query: str): raise NotImplementedError()
    def fetch_person(self, identifier: str): raise NotImplementedError()
    def fetch_company(self, identifier: str): raise NotImplementedError()
    def fetch_signals(self, query: str): raise NotImplementedError()
