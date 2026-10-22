import logging
from datetime import datetime
from typing import List, Optional
import httpx

from app.services.scraping.ports import ScraperPort, ScrapedJobRecord, CollectorResult

logger = logging.getLogger("networkos.scrapers.jobicy")

class JobicyCollector(ScraperPort):
    """
    Collects remote job opportunities from Jobicy's official public API.
    Docs: https://jobicy.com/api/v2/remote-jobs
    """
    ENDPOINT = "https://jobicy.com/api/v2/remote-jobs"
    HEADERS = {"User-Agent": "NetworkOS-JobCollector/1.0 (Commercial Opportunity Pipeline)"}

    @property
    def source_name(self) -> str:
        return "jobicy"

    async def scrape(self, limit: int = 50) -> CollectorResult:
        records: List[ScrapedJobRecord] = []
        try:
            async with httpx.AsyncClient(timeout=15.0, headers=self.HEADERS, follow_redirects=True) as client:
                response = await client.get(self.ENDPOINT, params={"count": min(limit, 50)})
                if response.status_code != 200:
                    logger.warning(f"Jobicy API returned status {response.status_code}")
                    return CollectorResult(
                        source=self.source_name,
                        success=False,
                        error_message=f"HTTP {response.status_code}: {response.text[:200]}"
                    )

                data = response.json()
                jobs = data.get("jobs", [])
                for job in jobs[:limit]:
                    job_id = str(job.get("id") or "")
                    title = (job.get("jobTitle") or "").strip()
                    company = (job.get("companyName") or "").strip()
                    url = (job.get("url") or "").strip()
                    desc = job.get("jobDescription") or job.get("jobExcerpt") or ""

                    if not (job_id and title and company and url):
                        continue

                    # Parse publication date
                    pub_date = None
                    if job.get("pubDate"):
                        try:
                            # Usually RFC-2822 or ISO format
                            pub_date = datetime.fromisoformat(job["pubDate"].replace("Z", "+00:00"))
                        except Exception:
                            pub_date = None

                    # Salary formulation
                    salary = None
                    min_sal = job.get("annualSalaryMin")
                    max_sal = job.get("annualSalaryMax")
                    cur = job.get("salaryCurrency") or "USD"
                    if min_sal and max_sal:
                        salary = f"{cur} {min_sal:,} - {max_sal:,}/yr"
                    elif min_sal:
                        salary = f"{cur} {min_sal:,}/yr"

                    records.append(ScrapedJobRecord(
                        source=self.source_name,
                        external_id=f"jobicy-{job_id}",
                        title=title,
                        company_name=company,
                        apply_url=url,
                        description_raw=desc,
                        location=job.get("jobGeo") or "Remote",
                        salary=salary,
                        tags=job.get("jobIndustry") or [],
                        published_at=pub_date,
                        raw_data=job
                    ))

            logger.info(f"JobicyCollector: successfully fetched {len(records)} jobs")
            return CollectorResult(
                source=self.source_name,
                success=True,
                jobs_collected=len(records),
                records=records
            )
        except Exception as e:
            logger.exception(f"JobicyCollector encountered error: {e}")
            return CollectorResult(
                source=self.source_name,
                success=False,
                error_message=str(e),
                records=[]
            )
