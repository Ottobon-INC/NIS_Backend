from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum, JSON
from sqlalchemy.sql import func
from app.db.base import Base
import enum

class RunStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"

class ResearchRun(Base):
    __tablename__ = "research_runs"
    id = Column(String, primary_key=True, index=True)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=True)
    status = Column(Enum(RunStatus), default=RunStatus.NOT_STARTED)
    triggered_by = Column(String)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    error_message = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class ResearchTask(Base):
    __tablename__ = "research_tasks"
    id = Column(String, primary_key=True, index=True)
    research_run_id = Column(String, ForeignKey("research_runs.id"))
    source_id = Column(String, ForeignKey("research_sources.id"))
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    priority = Column(String)
    target_metadata = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    error_message = Column(String)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
