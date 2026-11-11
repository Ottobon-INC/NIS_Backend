from typing import Optional, Any, Dict
from datetime import datetime
from sqlalchemy import String, Integer, Enum, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.base import Base
import enum

class EvidenceType(str, enum.Enum):
    FACT = "FACT"
    SIGNAL = "SIGNAL"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"

class ProblemEpistemicStatus(str, enum.Enum):
    EVIDENCE_GROUNDED = "EVIDENCE_GROUNDED"
    SUPPORTED_INFERENCE = "SUPPORTED_INFERENCE"
    HYPOTHESIS_ONLY = "HYPOTHESIS_ONLY"
    NO_OBSERVED_PROBLEM = "NO_OBSERVED_PROBLEM"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

class SourceResult(Base):
    __tablename__ = "source_results"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("research_sources.id"), nullable=True)
    research_task_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("research_tasks.id"), nullable=True)
    query: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    entity_searched: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    retrieved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    raw_reference: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    extracted_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[Optional[Dict[str, Any]]] = mapped_column("metadata", JSON, nullable=True)

class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    evidence_type: Mapped[Optional[EvidenceType]] = mapped_column(Enum(EvidenceType), nullable=True)
    claim: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("research_sources.id"), nullable=True)
    source_reference: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    observed_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_result_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("source_results.id"), nullable=True)
    related_entity_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
