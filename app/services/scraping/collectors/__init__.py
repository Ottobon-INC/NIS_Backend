from app.services.scraping.collectors.remotive import RemotiveCollector
from app.services.scraping.collectors.arbeitnow import ArbeitnowCollector
from app.services.scraping.collectors.jobicy import JobicyCollector
from app.services.scraping.collectors.wwr_rss import WeWorkRemotelyCollector

DEFAULT_COLLECTORS = [
    RemotiveCollector(),
    ArbeitnowCollector(),
    JobicyCollector(),
    WeWorkRemotelyCollector()
]

__all__ = [
    "RemotiveCollector",
    "ArbeitnowCollector",
    "JobicyCollector",
    "WeWorkRemotelyCollector",
    "DEFAULT_COLLECTORS"
]
