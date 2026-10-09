import httpx
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional
from app.services.providers.base import ResearchProvider
from app.services.web.url_security import validate_url_security, SSRError
from app.core.config import settings

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
                    
                title = soup.title.string if soup.title else ""
                meta_desc = ""
                meta_tag = soup.find("meta", attrs={"name": "description"})
                if meta_tag:
                    meta_desc = meta_tag.get("content", "")
                
                text_content = soup.get_text(separator=" ", strip=True)
                
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
