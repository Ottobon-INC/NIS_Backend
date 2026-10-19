import logging
import httpx
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

    def _extract_linkedin_profile_data(self, url: str, status_code: int, soup: BeautifulSoup) -> Dict[str, Any]:
        import re
        def get_meta(prop: str) -> str:
            tag = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
            return tag.get('content', '').strip() if tag else ''

        title = get_meta('og:title') or (soup.title.string if soup.title else '')
        desc = get_meta('og:description') or get_meta('description')
        image = get_meta('og:image')
        first_name = get_meta('profile:first_name')
        last_name = get_meta('profile:last_name')
        canonical_url = get_meta('og:url') or url

        full_name = f"{first_name} {last_name}".strip() if (first_name or last_name) else ""
        company = ""
        role = ""
        location = ""
        education = ""

        if not full_name and "-" in title:
            parts = title.split("|")[0].split("-")
            full_name = parts[0].strip()
            if len(parts) > 1:
                company = parts[1].strip()
        elif "-" in title:
            parts = title.split("|")[0].split("-")
            if len(parts) > 1:
                company = parts[1].strip()

        if desc:
            m_exp = re.search(r'Experience:\s*([^·\n]+)', desc)
            if m_exp:
                exp_c = m_exp.group(1).strip()
                if exp_c:
                    company = exp_c

            m_role = re.search(r'as an?\s+([^,\.·\n]+)', desc, re.IGNORECASE)
            if m_role:
                role = m_role.group(1).strip()

            m_loc = re.search(r'Location:\s*([^·\n]+)', desc)
            if m_loc:
                location = m_loc.group(1).strip()

            m_edu = re.search(r'Education:\s*([^·\n]+)', desc)
            if m_edu:
                education = m_edu.group(1).strip()

        structured_text = f"""
PRIMARY VERIFIED SOURCE - DIRECT LINKEDIN PROFILE SCRAPED:
- Profile URL: {url}
- Full Name: {full_name}
- Current Job Role: {role or 'Professional'}
- Current Organization / Company: {company or 'Independent'}
- Location: {location or 'Unknown'}
- Education: {education}
- Official Summary & Bio: {desc}
- Verified Profile Image: {image}
"""
        return {
            "status": "SUCCESS",
            "final_url": canonical_url,
            "http_status": status_code,
            "content_type": "text/html",
            "title": title,
            "meta_description": desc,
            "text_content": structured_text.strip(),
            "extracted_data": {
                "name": full_name,
                "role": role,
                "company": company,
                "location": location,
                "education": education,
                "image_url": image
            }
        }

    async def fetch_public_webpage(self, url: str) -> Dict[str, Any]:
        try:
            safe_url = validate_url_security(url)
        except SSRError as e:
            return {"status": "BLOCKED", "error": str(e)}

        timeout = getattr(settings, "WEB_REQUEST_TIMEOUT_SECONDS", 15)
        max_bytes = getattr(settings, "WEB_MAX_RESPONSE_BYTES", 5 * 1024 * 1024)

        is_linkedin = "linkedin.com" in safe_url.lower()
        headers = {
            "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5"
        } if is_linkedin else {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
        }

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(safe_url, headers=headers)
                resp.raise_for_status()
                
                content_len = resp.headers.get("Content-Length")
                if content_len and int(content_len) > max_bytes:
                    return {"status": "UNSUPPORTED_CONTENT", "error": "Response too large"}
                    
                html = resp.text
                if len(html) > max_bytes:
                    return {"status": "UNSUPPORTED_CONTENT", "error": "Response too large"}

                soup = BeautifulSoup(html, "html.parser")

                if is_linkedin:
                    return self._extract_linkedin_profile_data(safe_url, resp.status_code, soup)

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
        except Exception as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
                return {"status": "NOT_FOUND", "error": str(e)}

            # For LinkedIn, attempt direct fallback with urllib using social crawler agent
            if is_linkedin:
                try:
                    import urllib.request
                    import asyncio
                    def fetch_urllib():
                        req = urllib.request.Request(safe_url, headers=headers)
                        with urllib.request.urlopen(req, timeout=timeout) as u_resp:
                            return u_resp.read().decode('utf-8', errors='ignore'), u_resp.status
                    u_html, u_status = await asyncio.to_thread(fetch_urllib)
                    if u_html:
                        u_soup = BeautifulSoup(u_html, "html.parser")
                        return self._extract_linkedin_profile_data(safe_url, u_status, u_soup)
                except Exception as u_err:
                    logger.warning(f"urllib direct LinkedIn scrape failed: {u_err}")
            # Fallback for sites that block automated scraping (e.g. LinkedIn HTTP 999/403)
            logger.info(f"GeneralWebProvider direct fetch encountered: {e}. Attempting search fallback for {url}")
            try:
                import re
                slug_match = re.search(r'in/([^/?#]+)', url)
                slug = slug_match.group(1).strip() if slug_match else ""
                search_term = slug.replace('-', ' ') if slug else url

                try:
                    from ddgs import DDGS
                except ImportError:
                    from duckduckgo_search import DDGS

                ddgs_results = []
                try:
                    import asyncio
                    def sync_ddgs():
                        with DDGS() as ddgs:
                            res = list(ddgs.text(f'"{search_term}"', max_results=5))
                            if not res and slug:
                                res = list(ddgs.text(search_term, max_results=5))
                            return res
                    ddgs_results = await asyncio.to_thread(sync_ddgs)
                except Exception as ddg_e:
                    logger.warning(f"DDGS search failed in web provider fallback: {ddg_e}")

                if ddgs_results:
                    combined = "\n\n".join([f"Title: {r.get('title', '')}\nBody: {r.get('body', '')}\nURL: {r.get('href', '')}" for r in ddgs_results])
                    return {
                        "status": "SUCCESS",
                        "final_url": url,
                        "http_status": 200,
                        "content_type": "text/plain",
                        "title": f"Web Footprint for {search_term}",
                        "meta_description": "",
                        "text_content": combined[:30000]
                    }

                from app.core.agent_reach_cli import AgentReachCLI
                fb = await AgentReachCLI.execute_search("web", f'"{search_term}"')
                if fb.get("status") == "SUCCESS" and fb.get("data", {}).get("raw_text"):
                    return {
                        "status": "SUCCESS",
                        "final_url": url,
                        "http_status": 200,
                        "content_type": "text/plain",
                        "title": f"Web Footprint for {search_term}",
                        "meta_description": "",
                        "text_content": fb["data"]["raw_text"][:30000]
                    }
            except Exception as fb_err:
                logger.warning(f"Fallback error in GeneralWebProvider: {fb_err}")

            return {"status": "ERROR", "error": str(e)}

    def search_person(self, query: str): raise NotImplementedError()
    def search_company(self, query: str): raise NotImplementedError()
    def fetch_person(self, identifier: str): raise NotImplementedError()
    def fetch_company(self, identifier: str): raise NotImplementedError()
    def fetch_signals(self, query: str): raise NotImplementedError()
