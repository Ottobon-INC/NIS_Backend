from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.models.research import SourcePriority, SourceStatus

class ResearchSourceBase(BaseModel):
    name: str
    source_type: str
    priority: SourcePriority
    status: SourceStatus
    provider_type: str
    description: Optional[str] = None
    supported_entity_types: Optional[List[str]] = []
    supported_intelligence_types: Optional[List[str]] = []
    reliability_score: int = 50
    requires_api_key: bool = False
    requires_paid_license: bool = False

class ResearchSourceCreate(ResearchSourceBase):
    id: str

class ResearchSourceUpdate(BaseModel):
    status: Optional[SourceStatus] = None
    priority: Optional[SourcePriority] = None

class ResearchSourceInDB(ResearchSourceBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
