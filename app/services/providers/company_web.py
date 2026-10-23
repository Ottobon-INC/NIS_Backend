import asyncio
import logging
from typing import Dict, Any, Optional
from app.services.providers.base import ResearchProvider
from app.services.providers.web import GeneralWebProvider
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
from app.core.config import settings

logger = logging.getLogger("networkos")

class CompanyWebsiteProvider(ResearchProvider):
    def __init__(self):
        self.web_provider = GeneralWebProvider()

    def get_provider_metadata(self) -> Dict[str, Any]:
        return {
            "source_id": "company_web",
            "name": "Company & Professional Websites",
            "provider_type": "WEB_SCRAPER",
            "supported_entity_types": ["person", "company"],
            "supported_intelligence_types": ["company_bio", "official_role", "leadership", "team_page"],
            "requires_api_key": False,
            "requires_paid_license": False
        }

    async def search_person(self, query: str) -> Dict[str, Any]:
        """Searches official company pages and leadership bios for the person."""
        clean_query = query.strip()
        if not clean_query:
            return {"status": "EMPTY_QUERY", "error": "Query is empty"}

        try:
            # 1. Search for official corporate bio or team mention
            base_term = clean_query.strip().strip('"').strip("'")
            search_term = f'"{base_term}" (team OR leadership OR "about us" OR executive OR biography)'
            def sync_search():
                return list(DDGS().text(search_term, max_results=3))

            results = await asyncio.to_thread(sync_search)
            if not results:
                return {
                    "status": "SUCCESS",
                    "final_url": f"https://duckduckgo.com/?q={clean_query}",
                    "records_count": 0,
                    "text_content": f"No official company team or bio pages found for '{clean_query}'.",
                    "extracted_data": {"pages": []}
                }

            # 2. Extract best candidate URL (exclude social media sites)
            candidate_pages = []
            for item in results:
                href = item.get("href", "")
                if not any(excluded in href for excluded in ["linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com"]):
                    candidate_pages.append(item)

            if not candidate_pages:
                candidate_pages = results[:2]

            top_page = candidate_pages[0]
            top_url = top_page.get("href")

            # 3. Attempt genuine fetch and extraction of the top company webpage
            page_content = await self.web_provider.fetch_public_webpage(top_url)

            extracted_bio = ""
            if page_content.get("status") == "SUCCESS":
                extracted_bio = page_content.get("text_content", "")[:1500]
            else:
                extracted_bio = top_page.get("body", "")

            summary_text = (
                f"Official Company Page / Leadership Mention:\n"
                f"Title: {top_page.get('title')}\n"
                f"URL: {top_url}\n"
                f"Context Excerpt:\n{extracted_bio}\n"
            )

            return {
                "status": "SUCCESS",
                "final_url": top_url,
                "http_status": 200,
                "title": top_page.get("title") or f"Company Profile: {clean_query}",
                "text_content": summary_text,
                "records_count": len(candidate_pages),
                "extracted_data": {
                    "url": top_url,
                    "title": top_page.get("title"),
                    "snippet": extracted_bio,
                    "all_candidates": [{"title": p.get("title"), "url": p.get("href"), "snippet": p.get("body")} for p in candidate_pages]
                }
            }

        except Exception as e:
            logger.error(f"CompanyWebsiteProvider error for {clean_query}: {e}")
            return {"status": "ERROR", "error": str(e)}

    async def fetch_public_webpage(self, url: str) -> Dict[str, Any]:
        return await self.search_person(url)
