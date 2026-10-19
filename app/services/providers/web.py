import httpx
import logging
import os
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional
from app.services.providers.base import ResearchProvider
from app.services.web.url_security import validate_url_security, SSRError
from app.core.config import settings

logger = logging.getLogger("networkos.web_provider")

class GeneralWebProvider(ResearchProvider):
    def get_provider_metadata(self) -> Dict[str, Any]:
        return {
            "source_id": "general_web",
            "name": "General Public Website",
            "provider_type": "INTERNAL_HTTP",
            "supported_entity_types": ["person", "company"],
            "supported_intelligence_types": ["profile", "company", "public_web"],
            "requires_api_key": False,
            "requires_paid_license": False
        }

    async def fetch_public_webpage(self, url: str) -> Dict[str, Any]:
        try:
            safe_url = validate_url_security(url)
        except SSRError as e:
            return {"status": "BLOCKED", "error": str(e)}

        timeout = getattr(settings, "WEB_REQUEST_TIMEOUT_SECONDS", 15)
        max_bytes = getattr(settings, "WEB_MAX_RESPONSE_BYTES", 5 * 1024 * 1024)

        # 1. Attempt high-fidelity asynchronous crawling via Crawl4AI (in non-test or production mode)
        if os.environ.get("ENV") != "test":
            try:
                from app.services.web.crawler import CrawlerService
                res = await CrawlerService.scrape_page(safe_url, timeout_ms=int(timeout * 1000))
                if res and res.get("success"):
                    status_code = res.get("status_code", 200)
                    if status_code == 404:
                        return {"status": "NOT_FOUND"}
                    elif status_code in [401, 403]:
                        return {"status": "BLOCKED"}
                    elif status_code == 429:
                        return {"status": "RATE_LIMITED"}

                    markdown_content = res.get("markdown", "")
                    title = res.get("title", "")
                    text_content = markdown_content if markdown_content else res.get("html", "")
                    return {
                        "status": "SUCCESS",
                        "final_url": res.get("url", safe_url),
                        "http_status": status_code,
                        "content_type": "text/markdown",
                        "title": title,
                        "meta_description": "",
                        "text_content": text_content[:50000],
                        "links": res.get("links", []),
                        "media": res.get("media", [])
                    }
            except Exception as crawler_err:
                logger.info(f"Crawl4AI not active or failed for {safe_url}: {crawler_err}. Falling back to HTTP client.")

        # 2. Resilient fallback: Standard asynchronous HTTP client + BeautifulSoup
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(safe_url, headers={"User-Agent": "NetworkOS/1.0"})
                resp.raise_for_status()

                content_len = resp.headers.get("Content-Length")
                if content_len and int(content_len) > max_bytes:
                    return {"status": "UNSUPPORTED_CONTENT", "error": "Response too large"}

                html = resp.text
                if len(html) > max_bytes:
                    return {"status": "UNSUPPORTED_CONTENT", "error": "Response too large"}

                soup = BeautifulSoup(html, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()

                title = soup.title.string.strip() if soup.title and soup.title.string else ""
                meta_desc = ""
                meta_tag = soup.find("meta", attrs={"name": "description"})
                if meta_tag:
                    meta_desc = meta_tag.get("content", "").strip()

                body_text = soup.get_text(separator=" ", strip=True)
                structured_parts = []
                if title:
                    structured_parts.append(f"Title: {title}")
                if meta_desc:
                    structured_parts.append(f"Summary / Experience: {meta_desc}")
                if body_text:
                    structured_parts.append(body_text)

                text_content = "\n\n".join(structured_parts)

                return {
                    "status": "SUCCESS",
                    "final_url": str(resp.url),
                    "http_status": resp.status_code,
                    "content_type": resp.headers.get("content-type", ""),
                    "title": title,
                    "meta_description": meta_desc,
                    "text_content": text_content[:50000]
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"status": "NOT_FOUND"}
            elif e.response.status_code in [401, 403]:
                return {"status": "BLOCKED"}
            elif e.response.status_code == 429:
                return {"status": "RATE_LIMITED"}
            return {"status": "ERROR", "error": f"HTTP {e.response.status_code}"}
        except httpx.TimeoutException:
            return {"status": "TIMEOUT"}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def search_person(self, query: str): raise NotImplementedError()
    def search_company(self, query: str): raise NotImplementedError()
    def fetch_person(self, identifier: str): raise NotImplementedError()
    def fetch_company(self, identifier: str): raise NotImplementedError()
    def fetch_signals(self, query: str): raise NotImplementedError()
