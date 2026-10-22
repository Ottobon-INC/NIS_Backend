import logging
import re
from datetime import datetime
from typing import List, Optional
import feedparser
import httpx

from app.services.scraping.ports import ScraperPort, ScrapedJobRecord, CollectorResult

logger = logging.getLogger("networkos.scrapers.weworkremotely")

class WeWorkRemotelyCollector(ScraperPort):
    """
    Collects remote engineering and product jobs from We Work Remotely public RSS feeds.
    Feeds:
      - Backend Programming: https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss
      - Full-Stack Programming: https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss
    """
    FEEDS = [
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss"
    ]
    HEADERS = {"User-Agent": "NetworkOS-JobCollector/1.0 (RSS Ingestion Pipeline)"}

    @property
    def source_name(self) -> str:
        return "weworkremotely"

    async def scrape(self, limit: int = 50) -> CollectorResult:
        records: List[ScrapedJobRecord] = []
        seen_ids = set()

        try:
            async with httpx.AsyncClient(timeout=15.0, headers=self.HEADERS, follow_redirects=True) as client:
                for feed_url in self.FEEDS:
                    if len(records) >= limit:
                        break
                    try:
                        resp = await client.get(feed_url)
                        if resp.status_code != 200:
                            logger.warning(f"WWR feed {feed_url} returned {resp.status_code}")
                            continue

                        feed = feedparser.parse(resp.text)
                        for entry in feed.entries:
                            if len(records) >= limit:
                                break

                            entry_id = getattr(entry, "id", None) or getattr(entry, "link", "")
                            if not entry_id or entry_id in seen_ids:
                                continue
                            seen_ids.add(entry_id)

                            # WWR titles are usually formatted: "Company Name: Job Title"
                            raw_title = getattr(entry, "title", "").strip()
                            company = "Remote Enterprise"
                            title = raw_title
                            if ":" in raw_title:
                                parts = raw_title.split(":", 1)
                                company = parts[0].strip()
                                title = parts[1].strip()

                            apply_url = getattr(entry, "link", "").strip()
                            desc = getattr(entry, "description", "") or getattr(entry, "summary", "")

                            # Extract publication date
                            pub_date = None
                            if hasattr(entry, "published_parsed") and entry.published_parsed:
                                try:
                                    pub_date = datetime(*entry.published_parsed[:6])
                                except Exception:
                                    pub_date = None

                            # Safe external_id extraction from link or guid
                            # e.g., https://weworkremotely.com/remote-jobs/acme-senior-engineer-12345
                            match = re.search(r"/remote-jobs/([^/?#]+)", apply_url)
                            ext_id = match.group(1) if match else re.sub(r"[^\w-]", "", entry_id)[-32:]

                            records.append(ScrapedJobRecord(
                                source=self.source_name,
                                external_id=f"wwr-{ext_id}",
                                title=title,
                                company_name=company,
                                apply_url=apply_url,
                                description_raw=desc,
                                location="Remote",
                                salary=None,
                                tags=["Engineering", "Remote"],
                                published_at=pub_date,
                                raw_data={"title": raw_title, "link": apply_url, "id": entry_id}
                            ))
                    except Exception as feed_err:
                        logger.warning(f"Error parsing WWR feed {feed_url}: {feed_err}")
                        continue

            logger.info(f"WeWorkRemotelyCollector: successfully parsed {len(records)} jobs")
            return CollectorResult(
                source=self.source_name,
                success=True,
                jobs_collected=len(records),
                records=records
            )
        except Exception as e:
            logger.exception(f"WeWorkRemotelyCollector encountered error: {e}")
            return CollectorResult(
                source=self.source_name,
                success=False,
                error_message=str(e),
                records=[]
            )
