import logging
from datetime import datetime
from typing import List, Optional
import httpx

from app.services.scraping.ports import ScraperPort, ScrapedJobRecord, CollectorResult

logger = logging.getLogger("networkos.scrapers.remotive")

class RemotiveCollector(ScraperPort):
    """
    Collects remote job opportunities from Remotive's official public API.
    Docs: https://remotive.com/api/remote-jobs
    """
    ENDPOINT = "https://remotive.com/api/remote-jobs"
    HEADERS = {"User-Agent": "NetworkOS-JobCollector/1.0 (Commercial Opportunity Pipeline)"}

    @property
    def source_name(self) -> str:
        return "remotive"

    async def scrape(self, limit: int = 50) -> CollectorResult:
        records: List[ScrapedJobRecord] = []
        try:
            async with httpx.AsyncClient(timeout=15.0, headers=self.HEADERS, follow_redirects=True) as client:
                response = await client.get(self.ENDPOINT, params={"limit": limit})
                if response.status_code != 200:
                    logger.warning(f"Remotive API returned status {response.status_code}")
                    return CollectorResult(
                        source=self.source_name,
                        success=False,
                        error_message=f"HTTP {response.status_code}: {response.text[:200]}"
                    )

                data = response.json()
                jobs = data.get("jobs", [])
                for job in jobs[:limit]:
                    ext_id = str(job.get("id"))
                    title = (job.get("title") or "").strip()
                    company = (job.get("company_name") or "").strip()
                    url = (job.get("url") or "").strip()
                    desc = job.get("description") or ""

                    if not (ext_id and title and company and url):
                        continue

                    # Parse publication date
                    pub_date = None
                    if job.get("publication_date"):
                        try:
                            pub_date = datetime.fromisoformat(job["publication_date"].replace("Z", "+00:00"))
                        except Exception:
                            pub_date = None

                    records.append(ScrapedJobRecord(
                        source=self.source_name,
                        external_id=f"remotive-{ext_id}",
                        title=title,
                        company_name=company,
                        apply_url=url,
                        description_raw=desc,
                        location=job.get("candidate_required_location") or "Remote",
                        salary=job.get("salary") or None,
                        tags=job.get("tags") or [],
                        published_at=pub_date,
                        raw_data=job
                    ))

            logger.info(f"RemotiveCollector: successfully fetched {len(records)} jobs")
            return CollectorResult(
                source=self.source_name,
                success=True,
                jobs_collected=len(records),
                records=records
            )
        except Exception as e:
            logger.exception(f"RemotiveCollector encountered error: {e}")
            return CollectorResult(
                source=self.source_name,
                success=False,
                error_message=str(e),
                records=[]
            )
