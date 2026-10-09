from sqlalchemy import Column, String, Integer, Enum, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base
import enum

class EvidenceType(str, enum.Enum):
    FACT = "FACT"
    SIGNAL = "SIGNAL"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"

class SourceResult(Base):
    __tablename__ = "source_results"
    id = Column(String, primary_key=True, index=True)
    source_id = Column(String, ForeignKey("research_sources.id"))
    research_task_id = Column(String, ForeignKey("research_tasks.id"), nullable=True)
    query = Column(String)
    entity_searched = Column(String)
    retrieved_at = Column(DateTime(timezone=True), server_default=func.now())
    raw_reference = Column(String)
    status = Column(String)
    extracted_data = Column(JSON)
    metadata_ = Column("metadata", JSON)

class Evidence(Base):
    __tablename__ = "evidence"
    id = Column(String, primary_key=True, index=True)
    evidence_type = Column(Enum(EvidenceType))
    claim = Column(String)
    source_id = Column(String, ForeignKey("research_sources.id"))
    source_reference = Column(String)
    observed_date = Column(DateTime(timezone=True))
    retrieved_date = Column(DateTime(timezone=True), server_default=func.now())
    confidence = Column(Integer)
    source_result_id = Column(String, ForeignKey("source_results.id"))
    related_entity_id = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
