import logging
from datetime import datetime, timezone
from typing import List, Optional
import httpx

from app.services.scraping.ports import ScraperPort, ScrapedJobRecord, CollectorResult

logger = logging.getLogger("networkos.scrapers.arbeitnow")

class ArbeitnowCollector(ScraperPort):
    """
    Collects jobs from Arbeitnow's official public API.
    Docs: https://www.arbeitnow.com/api/job-board-api
    """
    ENDPOINT = "https://www.arbeitnow.com/api/job-board-api"
    HEADERS = {"User-Agent": "NetworkOS-JobCollector/1.0 (Commercial Opportunity Pipeline)"}

    @property
    def source_name(self) -> str:
        return "arbeitnow"

    async def scrape(self, limit: int = 50) -> CollectorResult:
        records: List[ScrapedJobRecord] = []
        try:
            async with httpx.AsyncClient(timeout=15.0, headers=self.HEADERS, follow_redirects=True) as client:
                response = await client.get(self.ENDPOINT)
                if response.status_code != 200:
                    logger.warning(f"Arbeitnow API returned status {response.status_code}")
                    return CollectorResult(
                        source=self.source_name,
                        success=False,
                        error_message=f"HTTP {response.status_code}: {response.text[:200]}"
                    )

                data = response.json()
                jobs = data.get("data", [])
                for job in jobs[:limit]:
                    slug = str(job.get("slug") or "")
                    title = (job.get("title") or "").strip()
                    company = (job.get("company_name") or "").strip()
                    url = (job.get("url") or "").strip()
                    desc = job.get("description") or ""

                    if not (slug and title and company and url):
                        continue

                    # Parse timestamp (epoch seconds or ISO string)
                    pub_date = None
                    raw_created = job.get("created_at")
                    if isinstance(raw_created, (int, float)):
                        pub_date = datetime.fromtimestamp(raw_created, tz=timezone.utc)
                    elif isinstance(raw_created, str):
                        try:
                            pub_date = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
                        except Exception:
                            pub_date = None

                    loc = job.get("location") or ("Remote" if job.get("remote") else "Hybrid")

                    records.append(ScrapedJobRecord(
                        source=self.source_name,
                        external_id=f"arbeitnow-{slug}",
                        title=title,
                        company_name=company,
                        apply_url=url,
                        description_raw=desc,
                        location=loc,
                        salary=None, # Arbeitnow rarely specifies structured salary
                        tags=job.get("tags") or [],
                        published_at=pub_date,
                        raw_data=job
                    ))

            logger.info(f"ArbeitnowCollector: successfully fetched {len(records)} jobs")
            return CollectorResult(
                source=self.source_name,
                success=True,
                jobs_collected=len(records),
                records=records
            )
        except Exception as e:
            logger.exception(f"ArbeitnowCollector encountered error: {e}")
            return CollectorResult(
                source=self.source_name,
                success=False,
                error_message=str(e),
                records=[]
            )
