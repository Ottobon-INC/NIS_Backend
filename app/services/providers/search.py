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
            "name": "DuckDuckGo Web Search",
            "provider_type": "EXTERNAL_API",
            "supported_entity_types": ["person", "company"],
            "supported_intelligence_types": ["public_web", "news", "executive_mentions"],
            "requires_api_key": False,
            "requires_paid_license": False
        }

    async def search_person(self, query: str) -> Dict[str, Any]:
        """Searches DuckDuckGo for the person or targeted query."""
        clean_query = query.strip()
        try:
            def sync_search():
                return list(DDGS().text(clean_query, max_results=4))

            results = await asyncio.to_thread(sync_search)
            if not results:
                return {
                    "status": "SUCCESS",
                    "final_url": f"https://duckduckgo.com/?q={clean_query}",
                    "records_count": 0,
                    "text_content": f"No search results returned for query '{clean_query}'.",
                    "extracted_data": {"results": []}
                }

            combined_text = "\n\n".join([f"Title: {r['title']}\nSnippet: {r['body']}\nSource URL: {r['href']}" for r in results])
            top_url = results[0]["href"] if results else f"https://duckduckgo.com/?q={clean_query}"

            return {
                "status": "SUCCESS",
                "final_url": top_url,
                "http_status": 200,
                "content_type": "text/plain",
                "title": f"DuckDuckGo Search: {clean_query}",
                "meta_description": results[0].get("body", "") if results else "",
                "text_content": combined_text,
                "records_count": len(results),
                "extracted_data": {
                    "results": results
                }
            }
        except Exception as e:
            logger.error(f"DDG Search error for {clean_query}: {e}")
            return {"status": "ERROR", "error": str(e)}

    async def fetch_public_webpage(self, url: str) -> Dict[str, Any]:
        return await self.search_person(url)
