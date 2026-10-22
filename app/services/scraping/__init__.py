from app.services.scraping.ports import (
    ScraperPort,
    ScrapedJobRecord,
    CollectorResult,
    IngestionStatus
)
from app.services.scraping.ingestion_service import JobIngestionService
from app.services.scraping.collectors import (
    RemotiveCollector,
    ArbeitnowCollector,
    JobicyCollector,
    WeWorkRemotelyCollector,
    DEFAULT_COLLECTORS
)

__all__ = [
    "ScraperPort",
    "ScrapedJobRecord",
    "CollectorResult",
    "IngestionStatus",
    "JobIngestionService",
    "RemotiveCollector",
    "ArbeitnowCollector",
    "JobicyCollector",
    "WeWorkRemotelyCollector",
    "DEFAULT_COLLECTORS"
]
