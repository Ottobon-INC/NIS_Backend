import asyncio
import logging
import re
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
import base64
import httpx

from app.core.config import settings
from app.services.providers.base import ResearchProvider

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

logger = logging.getLogger("networkos")


def unwrap_search_redirect(url: str) -> str:
    """
    Unwraps search engine redirect/tracking wrappers (Bing /ck/a?, Google /url?, DDG /l/?uddg=)
    to return canonical target URLs.
    """
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        query = urllib.parse.parse_qs(parsed.query)

        # Bing redirect: /ck/a?...&u=a1...
        if "bing.com" in netloc:
            u_param = query.get("u", [""])[0]
            if u_param.startswith("a1"):
                raw_b64 = u_param[2:]
                padded = raw_b64 + "=" * ((4 - len(raw_b64) % 4) % 4)
                decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
                if decoded.startswith("http://") or decoded.startswith("https://"):
                    return decoded
            elif u_param:
                decoded = urllib.parse.unquote(u_param)
                if decoded.startswith("http://") or decoded.startswith("https://"):
                    return decoded

        # Google redirect: /url?...&q=... or &url=...
        if "google." in netloc:
            target = query.get("url", [""])[0] or query.get("q", [""])[0]
            if target and (target.startswith("http://") or target.startswith("https://")):
                return target

        # DuckDuckGo redirect: /l/?uddg=...
        if "duckduckgo.com" in netloc:
            uddg = query.get("uddg", [""])[0]
            if uddg:
                target = urllib.parse.unquote(uddg)
                if target.startswith("http://") or target.startswith("https://"):
                    return target
    except Exception:
        pass
    return url


class DuckDuckGoProvider(ResearchProvider):
    """
    Unified Precision Search Provider.
    1. Primary (Google): Queries Serper Google API when settings.SERPER_API_KEY is configured.
    2. Secondary (Bing): Direct HTTP Bing search with browser headers for accurate public LinkedIn cards.
    3. Fallback (DuckDuckGo): Strict-quoted DDG fallback ensuring zero query degradation or celebrity drift.
    """

    def get_provider_metadata(self) -> Dict[str, Any]:
        return {
            "source_id": "duckduckgo",
            "name": "Google & Precision Web Search",
            "provider_type": "EXTERNAL_API",
            "supported_entity_types": ["person", "company"],
            "supported_intelligence_types": ["public_web", "news", "executive_mentions", "linkedin_preview"],
            "requires_api_key": False,
            "requires_paid_license": False
        }

    async def _search_serper_google(self, query: str) -> Optional[List[Dict[str, str]]]:
        """Queries Google via Serper API when SERPER_API_KEY is configured."""
        api_key = getattr(settings, "SERPER_API_KEY", "")
        if not api_key:
            return None

        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json"
        }
        payload = {"q": query, "num": 5}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    organic = data.get("organic", [])
                    results = []
                    for item in organic:
                        results.append({
                            "title": item.get("title", ""),
                            "href": unwrap_search_redirect(item.get("link", "")),
                            "body": item.get("snippet", "")
                        })
                    if results:
                        logger.info(f"Serper Google search returned {len(results)} hits for query: {query}")
                        return results
                else:
                    logger.warning(f"Serper Google search returned HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.warning(f"Serper Google search error: {e}")

        return None

    def _sync_search_bing(self, query: str) -> List[Dict[str, str]]:
        """Queries Bing directly with desktop browser headers to extract exact public profile cards."""
        url = "https://www.bing.com/search?q=" + urllib.parse.quote_plus(query)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9"
            }
        )
        query_keywords = [
            w for w in re.findall(r'\b[a-zA-Z0-9]{3,}\b', query.lower())
            if w not in {"http", "https", "com", "org", "the", "and", "for", "with", "site", "overview", "technology", "software"}
        ]
        with urllib.request.urlopen(req, timeout=7) as r:
            soup = BeautifulSoup(r.read(), "html.parser")
            results = []
            for li in soup.find_all("li", class_="b_algo"):
                h2 = li.find("h2")
                a = h2.find("a") if h2 else None
                p = li.find("p")
                if a:
                    title = a.get_text().strip()
                    raw_href = a.get("href", "").strip()
                    href = unwrap_search_redirect(raw_href)
                    body = p.get_text().strip() if p else ""

                    # Discard junk / generic trending results (e.g. BingHomepageQuiz, YouTube, SpiceJet)
                    lower_all = f"{title.lower()} {body.lower()} {href.lower()}"
                    if len(query_keywords) >= 2:
                        longest_kw = max(query_keywords, key=len)
                        has_distinctive = longest_kw in lower_all
                        matches_count = sum(1 for k in query_keywords if k in lower_all)
                        if not has_distinctive and matches_count < 2:
                            continue
                    elif query_keywords and not any(k in lower_all for k in query_keywords):
                        continue

                    # Skip search engines or quizzes if not targeted
                    if any(j in href.lower() for j in ["bing.com/ck", "bingquiz", "binghomepagequiz"]):
                        continue

                    results.append({"title": title, "href": href, "body": body})
            return results

    def _sync_search_ddg(self, query: str) -> List[Dict[str, str]]:
        """Queries DuckDuckGo preserving exact quotes strictly."""
        if not DDGS:
            return []
        with DDGS() as ddgs:
            raw_hits = list(ddgs.text(query, max_results=4))
            for h in raw_hits:
                if "href" in h:
                    h["href"] = unwrap_search_redirect(h["href"])
            return raw_hits

    async def search_person(self, query: str) -> Dict[str, Any]:
        """
        Executes precision search cascading across Serper Google, Bing, and DDG.
        Guarantees exact-quote preservation to prevent celebrity name hallucination.
        """
        clean_query = query.strip()
        if not clean_query:
            return {"status": "EMPTY_QUERY", "error": "Query is empty"}

        active_provider = "unknown"
        results: List[Dict[str, str]] = []

        # 1. Primary: Serper (Google SERP)
        serper_hits = await self._search_serper_google(clean_query)
        if serper_hits:
            active_provider = "serper_google"
            results = serper_hits

        # 2. Secondary: Bing Web Search
        if not results:
            try:
                bing_hits = await asyncio.to_thread(self._sync_search_bing, clean_query)
                if bing_hits:
                    active_provider = "bing_search"
                    results = bing_hits
            except Exception as bing_err:
                logger.debug(f"Bing search error for '{clean_query}': {bing_err}")

        # 3. Fallback: DuckDuckGo (strict quotes only, no relaxing)
        if not results:
            try:
                ddg_hits = await asyncio.to_thread(self._sync_search_ddg, clean_query)
                if ddg_hits:
                    active_provider = "duckduckgo"
                    results = ddg_hits
            except Exception as ddg_err:
                logger.debug(f"DDG search error for '{clean_query}': {ddg_err}")

        if results:
            combined_text = "\n\n".join([
                f"Title: {r['title']}\nSnippet: {r['body']}\nSource URL: {r['href']}"
                for r in results
            ])
            top_url = results[0]["href"] if results else f"https://google.com/search?q={clean_query}"

            return {
                "status": "SUCCESS",
                "final_url": top_url,
                "http_status": 200,
                "content_type": "text/plain",
                "title": f"{active_provider.replace('_', ' ').title()} Search: {clean_query}",
                "meta_description": results[0].get("body", "") if results else "",
                "text_content": combined_text,
                "records_count": len(results),
                "extracted_data": {
                    "results": results,
                    "search_engine": active_provider
                }
            }

        return {
            "status": "SUCCESS",
            "final_url": f"https://google.com/search?q={clean_query}",
            "records_count": 0,
            "text_content": f"No search results returned for query '{clean_query}'.",
            "extracted_data": {"results": [], "search_engine": "none"}
        }

    async def fetch_public_webpage(self, url: str) -> Dict[str, Any]:
        return await self.search_person(url)


# Alias for backward and forward compatibility
SearchProvider = DuckDuckGoProvider
