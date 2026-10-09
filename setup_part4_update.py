import os

files = {
    "app/models/evidence.py": """from sqlalchemy import Column, String, Integer, Enum, DateTime, JSON, ForeignKey
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
""",
    "app/models/orchestration.py": """from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum, JSON
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
""",
    "app/workers/research_worker.py": """import logging
import asyncio
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.session import AsyncSessionLocal
from app.models.orchestration import ResearchTask, TaskStatus
from app.models.evidence import SourceResult
from app.models.research import ResearchSource
from app.services.providers.web import GeneralWebProvider

logger = logging.getLogger("networkos")

PROVIDER_REGISTRY = {
    "general_web": GeneralWebProvider()
}

async def execute_task(task_id: str):
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(ResearchTask).where(ResearchTask.id == task_id))
        task = res.scalars().first()
        if not task:
            logger.error(f"Task {task_id} not found")
            return
            
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        await db.commit()
        
        s_res = await db.execute(select(ResearchSource).where(ResearchSource.id == task.source_id))
        source = s_res.scalars().first()
        
        if not source or source.id not in PROVIDER_REGISTRY:
            task.status = TaskStatus.FAILED
            task.error_message = "Provider not found"
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return
            
        provider = PROVIDER_REGISTRY[source.id]
        
        try:
            target_url = task.target_metadata.get("target_url") if task.target_metadata else None
            
            if target_url and hasattr(provider, "fetch_public_webpage"):
                result = await provider.fetch_public_webpage(target_url)
                
                sr = SourceResult(
                    id=str(uuid.uuid4()),
                    research_task_id=task.id,
                    source_id=source.id,
                    query=target_url,
                    raw_reference=result.get("final_url", target_url),
                    status=result.get("status", "ERROR"),
                    extracted_data={
                        "title": result.get("title"),
                        "meta_description": result.get("meta_description"),
                        "text": result.get("text_content")
                    } if result.get("status") == "SUCCESS" else {},
                    metadata_={
                        "http_status": result.get("http_status"),
                        "content_type": result.get("content_type"),
                        "error": result.get("error")
                    }
                )
                db.add(sr)
                
                if result.get("status") == "SUCCESS":
                    task.status = TaskStatus.COMPLETED
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = result.get("error", result.get("status"))
            else:
                task.status = TaskStatus.SKIPPED
                task.error_message = "No target URL or unsupported capability"
                
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            logger.exception(f"Error executing task {task_id}")
            
        task.completed_at = datetime.now(timezone.utc)
        await db.commit()

async def mock_research_background_task(run_id: str):
    logger.info(f"Background task queued for ResearchRun: {run_id}")
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(ResearchTask).where(ResearchTask.research_run_id == run_id, ResearchTask.status == TaskStatus.PENDING))
        tasks = res.scalars().all()
        
    for task in tasks:
        await execute_task(task.id)
"""
}

# Ensure directories exist and write files
for filepath, content in files.items():
    directory = os.path.dirname(filepath)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

print("Part 4 model/worker updates successfully scaffolded.")
