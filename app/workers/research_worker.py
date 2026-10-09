import logging
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
