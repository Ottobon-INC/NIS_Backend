import httpx
import logging
from typing import Dict, Any, Optional, List
from app.services.providers.base import ResearchProvider
from app.core.config import settings

logger = logging.getLogger("networkos")

class AcademicResearchProvider(ResearchProvider):
    def __init__(self):
        self.openalex_base = "https://api.openalex.org"
        self.crossref_base = "https://api.crossref.org"

    def get_provider_metadata(self) -> Dict[str, Any]:
        return {
            "source_id": "academic_openalex",
            "name": "Academic Research & Publications (OpenAlex & Crossref)",
            "provider_type": "EXTERNAL_API",
            "supported_entity_types": ["person"],
            "supported_intelligence_types": ["publications", "academic_citations", "orcid", "research_topics"],
            "requires_api_key": False,
            "requires_paid_license": False
        }

    async def search_person(self, query: str) -> Dict[str, Any]:
        """Searches scholarly works and author records across OpenAlex and Crossref."""
        clean_name = query.strip()
        if not clean_name:
            return {"status": "EMPTY_QUERY", "error": "Query is empty"}

        timeout = getattr(settings, "WEB_REQUEST_TIMEOUT_SECONDS", 12)
        headers = {"User-Agent": "NetworkOS-AcademicResearch/1.0 (mailto:research@ottobon.com)"}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 1. Search OpenAlex Authors
                author_url = f"{self.openalex_base}/authors"
                resp = await client.get(
                    author_url,
                    params={"search": clean_name, "per-page": 3},
                    headers=headers
                )

                authors = []
                publications = []
                openalex_error = None
                crossref_error = None

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        data = None
                    if isinstance(data, dict):
                        results = data.get("results")
                        if isinstance(results, list):
                            for a in results:
                                if not isinstance(a, dict):
                                    continue
                                raw_inst = a.get("last_known_institutions")
                                inst_list = [
                                    i.get("display_name")
                                    for i in (raw_inst or [])
                                    if isinstance(i, dict) and i.get("display_name")
                                ]
                                raw_topics = a.get("topics")
                                topics_slice = (raw_topics or [])[:4] if isinstance(raw_topics, list) else []
                                topics_list = [
                                    t.get("display_name")
                                    for t in topics_slice
                                    if isinstance(t, dict) and t.get("display_name")
                                ]
                                author_info = {
                                    "id": a.get("id"),
                                    "display_name": a.get("display_name"),
                                    "orcid": a.get("orcid"),
                                    "works_count": a.get("works_count", 0),
                                    "cited_by_count": a.get("cited_by_count", 0),
                                    "institutions": inst_list,
                                    "topics": topics_list
                                }
                                authors.append(author_info)
                elif resp.status_code in [403, 429]:
                    openalex_error = f"OpenAlex rate limit or access denied ({resp.status_code})"
                else:
                    openalex_error = f"OpenAlex API error {resp.status_code}"

                # 2. If author found, get recent works from OpenAlex
                if authors and authors[0].get("id"):
                    top_author = authors[0]
                    author_id = top_author["id"].split("/")[-1]
                    works_resp = await client.get(
                        f"{self.openalex_base}/works",
                        params={"filter": f"author.id:{author_id}", "sort": "publication_year:desc", "per-page": 4},
                        headers=headers
                    )
                    if works_resp.status_code == 200:
                        try:
                            works_data = works_resp.json()
                        except Exception:
                            works_data = None
                        if isinstance(works_data, dict):
                            works_results = works_data.get("results")
                            if isinstance(works_results, list):
                                for w in works_results:
                                    if not isinstance(w, dict):
                                        continue
                                    publications.append({
                                        "title": w.get("title") or "Untitled Work",
                                        "year": w.get("publication_year"),
                                        "doi": w.get("doi"),
                                        "citations": w.get("cited_by_count", 0),
                                        "source": "OpenAlex"
                                    })

                # 3. Fallback / supplementary search on Crossref if no OpenAlex works
                if not publications:
                    crossref_url = f"{self.crossref_base}/works"
                    cr_resp = await client.get(
                        crossref_url,
                        params={"query.author": clean_name, "rows": 3},
                        headers=headers
                    )
                    if cr_resp.status_code == 200:
                        try:
                            cr_data = cr_resp.json()
                        except Exception:
                            cr_data = None
                        if isinstance(cr_data, dict):
                            msg = cr_data.get("message")
                            items = msg.get("items") if isinstance(msg, dict) else None
                            if isinstance(items, list):
                                for item in items:
                                    if not isinstance(item, dict):
                                        continue
                                    title_list = item.get("title")
                                    title = title_list[0] if isinstance(title_list, list) and title_list and title_list[0] else "Academic Publication"
                                    published_year = None
                                    issued = item.get("issued")
                                    if isinstance(issued, dict):
                                        dp = issued.get("date-parts")
                                        if isinstance(dp, list) and dp and isinstance(dp[0], list) and dp[0]:
                                            published_year = dp[0][0]
                                    publications.append({
                                        "title": title,
                                        "year": published_year,
                                        "doi": item.get("DOI"),
                                        "citations": item.get("is-referenced-by-count", 0),
                                        "source": "Crossref"
                                    })
                    else:
                        crossref_error = f"Crossref API error {cr_resp.status_code}"

                total_records = len(authors) + len(publications)
                if total_records == 0:
                    if openalex_error and crossref_error:
                        return {
                            "status": "ERROR",
                            "error": f"{openalex_error}; {crossref_error}",
                            "http_status": resp.status_code
                        }
                    elif openalex_error:
                        return {
                            "status": "ERROR",
                            "error": openalex_error,
                            "http_status": resp.status_code
                        }
                    elif crossref_error and not authors:
                        return {
                            "status": "ERROR",
                            "error": crossref_error,
                            "http_status": cr_resp.status_code
                        }
                    return {
                        "status": "SUCCESS",
                        "final_url": f"https://openalex.org/authors?search={clean_name}",
                        "records_count": 0,
                        "text_content": f"No academic publications or ORCID records found for '{clean_name}'.",
                        "extracted_data": {"authors": [], "publications": []}
                    }

                top_author = authors[0] if authors else None
                summary_lines = [f"Academic Research Profile: {clean_name}"]
                if top_author:
                    summary_lines.append(f"Identified Scholar: {top_author['display_name']}")
                    if top_author.get("orcid"):
                        summary_lines.append(f"ORCID: {top_author['orcid']}")
                    if top_author.get("institutions"):
                        summary_lines.append(f"Affiliated Institutions: {', '.join(top_author['institutions'])}")
                    summary_lines.append(f"Total Publications: {top_author['works_count']} | Total Citations: {top_author['cited_by_count']}")
                    if top_author.get("topics"):
                        summary_lines.append(f"Research Topics: {', '.join(top_author['topics'])}")

                if publications:
                    summary_lines.append("\nRecent Publications:")
                    for pub in publications:
                        doi_str = f" (DOI: {pub['doi']})" if pub.get('doi') else ""
                        year_str = f" [{pub['year']}]" if pub.get('year') else ""
                        summary_lines.append(f"- \"{pub['title']}\"{year_str}{doi_str} (Citations: {pub['citations']})")

                full_text = "\n".join(summary_lines)

                return {
                    "status": "SUCCESS",
                    "final_url": ((top_author.get("orcid") or top_author.get("id")) if top_author else None) or f"https://openalex.org/authors?search={clean_name}",
                    "http_status": 200,
                    "title": f"Academic Research: {clean_name}",
                    "text_content": full_text,
                    "records_count": total_records,
                    "extracted_data": {
                        "authors": authors,
                        "publications": publications
                    }
                }

        except httpx.TimeoutException:
            return {"status": "TIMEOUT", "error": "Academic API request timed out"}
        except Exception as e:
            logger.error(f"Academic provider error for {clean_name}: {e}")
            return {"status": "ERROR", "error": str(e)}

    async def fetch_public_webpage(self, url: str) -> Dict[str, Any]:
        return await self.search_person(url)
