from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class IngestionStatus(str, Enum):
    NEW = "NEW"
    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"
    FAILED = "FAILED"

class ScrapedJobRecord(BaseModel):
    """Canonical standardized job record returned by all collectors."""
    source: str = Field(..., description="Source identifier, e.g. remotive, arbeitnow, jobicy, weworkremotely")
    external_id: str = Field(..., description="Stable job ID from the source")
    title: str = Field(..., min_length=1, description="Official job title")
    company_name: str = Field(..., min_length=1, description="Employing company or enterprise name")
    apply_url: str = Field(..., min_length=4, description="Direct application URL or job posting link")
    description_raw: str = Field(default="", description="Original job description (HTML or markdown)")
    location: Optional[str] = Field(default="Remote", description="Location or remote eligibility")
    salary: Optional[str] = Field(default=None, description="Disclosed compensation or salary range")
    tags: List[str] = Field(default_factory=list, description="Skill tags or categories")
    published_at: Optional[datetime] = Field(default=None, description="Publication timestamp if available")
    raw_data: Optional[Dict[str, Any]] = Field(default=None, description="Original source JSON or RSS entry")

class CollectorResult(BaseModel):
    source: str
    success: bool
    jobs_collected: int = 0
    error_message: Optional[str] = None
    records: List[ScrapedJobRecord] = Field(default_factory=list)

class ScraperPort(ABC):
    """Abstract collector interface that all job source scrapers must implement."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this data source."""
        pass

    @abstractmethod
    async def scrape(self, limit: int = 50) -> CollectorResult:
        """
        Asynchronously fetches and normalizes jobs from the permitted public source.
        Must handle its own timeouts, rate-limits, and errors safely.
        """
        pass
