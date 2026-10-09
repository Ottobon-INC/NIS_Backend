from sqlalchemy import Column, String, Integer, Boolean, Enum, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base
import enum

class SourcePriority(str, enum.Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"

class SourceStatus(str, enum.Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    REQUIRES_CONFIGURATION = "REQUIRES_CONFIGURATION"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"

class ResearchSource(Base):
    __tablename__ = "research_sources"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    source_type = Column(String)
    priority = Column(Enum(SourcePriority), default=SourcePriority.P1)
    status = Column(Enum(SourceStatus), default=SourceStatus.DISABLED)
    provider_type = Column(String)
    description = Column(String)
    supported_entity_types = Column(JSON)
    supported_intelligence_types = Column(JSON)
    reliability_score = Column(Integer, default=50)
    requires_api_key = Column(Boolean, default=False)
    requires_paid_license = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
