import httpx
import asyncio
import logging
from typing import Dict, Any, Optional, List
from app.services.providers.base import ResearchProvider
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
from app.core.config import settings

logger = logging.getLogger("networkos")

class NewsPublicProvider(ResearchProvider):
    def __init__(self):
        self.wikidata_base = "https://www.wikidata.org/w/api.php"

    def get_provider_metadata(self) -> Dict[str, Any]:
        return {
            "source_id": "news_public",
            "name": "News, Public Media & Wikidata Entity Registry",
            "provider_type": "EXTERNAL_API",
            "supported_entity_types": ["person", "company"],
            "supported_intelligence_types": ["news_articles", "interviews", "wikidata_entities", "press_releases"],
            "requires_api_key": False,
            "requires_paid_license": False
        }

    async def search_person(self, query: str) -> Dict[str, Any]:
        """Searches Wikidata for structured public profiles and DuckDuckGo News for media coverage."""
        clean_name = query.strip()
        if not clean_name:
            return {"status": "EMPTY_QUERY", "error": "Query is empty"}

        timeout = getattr(settings, "WEB_REQUEST_TIMEOUT_SECONDS", 12)
        wikidata_matches = []
        news_articles = []

        try:
            # 1. Search Wikidata Knowledge Graph
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    self.wikidata_base,
                    params={
                        "action": "wbsearchentities",
                        "search": clean_name,
                        "language": "en",
                        "format": "json",
                        "limit": 3
                    },
                    headers={"User-Agent": "NetworkOS-PublicIntelligence/1.0"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("search", []):
                        wikidata_matches.append({
                            "id": item.get("id"),
                            "label": item.get("label"),
                            "description": item.get("description") or "Public entity",
                            "url": f"https://www.wikidata.org/wiki/{item.get('id')}"
                        })

            # 2. Search DuckDuckGo News
            def sync_news():
                try:
                    return list(DDGS().news(f'"{clean_name}"', max_results=3))
                except Exception:
                    # Fallback to general text search with news intent
                    return list(DDGS().text(f'"{clean_name}" (news OR interview OR "press release" OR speaker OR conference)', max_results=3))

            raw_news = await asyncio.to_thread(sync_news)
            for item in raw_news:
                news_articles.append({
                    "title": item.get("title"),
                    "date": item.get("date"),
                    "source": item.get("source"),
                    "body": item.get("body"),
                    "url": item.get("url") or item.get("href")
                })

            total_records = len(wikidata_matches) + len(news_articles)
            if total_records == 0:
                return {
                    "status": "SUCCESS",
                    "final_url": f"https://www.wikidata.org/w/index.php?search={clean_name}",
                    "records_count": 0,
                    "text_content": f"No public news articles, press releases, or Wikidata entities found for '{clean_name}'.",
                    "extracted_data": {"wikidata": [], "news": []}
                }

            summary_lines = [f"Public Media & News Intelligence: {clean_name}"]
            if wikidata_matches:
                summary_lines.append("\nWikidata Knowledge Entities:")
                for ent in wikidata_matches:
                    summary_lines.append(f"- {ent['label']} ({ent['id']}): {ent['description']} - {ent['url']}")

            if news_articles:
                summary_lines.append("\nNews Articles & Media Mentions:")
                for article in news_articles:
                    date_str = f" [{article['date']}]" if article.get('date') else ""
                    source_str = f" ({article['source']})" if article.get('source') else ""
                    summary_lines.append(f"- {article['title']}{date_str}{source_str}: {article['body']}\n  URL: {article['url']}")

            full_text = "\n".join(summary_lines)
            primary_url = news_articles[0]["url"] if news_articles else wikidata_matches[0]["url"]

            return {
                "status": "SUCCESS",
                "final_url": primary_url,
                "http_status": 200,
                "title": f"News & Public Intelligence: {clean_name}",
                "text_content": full_text,
                "records_count": total_records,
                "extracted_data": {
                    "wikidata": wikidata_matches,
                    "news": news_articles
                }
            }

        except Exception as e:
            logger.error(f"NewsPublicProvider error for {clean_name}: {e}")
            return {"status": "ERROR", "error": str(e)}

    async def fetch_public_webpage(self, url: str) -> Dict[str, Any]:
        return await self.search_person(url)
