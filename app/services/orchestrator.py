import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.research import ResearchSource, SourceStatus
from app.models.orchestration import ResearchRun, ResearchTask, RunStatus, TaskStatus
import logging

logger = logging.getLogger("networkos")

class ResearchOrchestrator:
    @staticmethod
    async def create_research_plan(contact_id: str, triggered_by: str, db: AsyncSession) -> str:
        run_id = str(uuid.uuid4())
        run = ResearchRun(
            id=run_id,
            contact_id=contact_id,
            triggered_by=triggered_by,
            status=RunStatus.QUEUED
        )
        db.add(run)

        result = await db.execute(select(ResearchSource))
        sources = result.scalars().all()

        for source in sources:
            if source.status != SourceStatus.ENABLED:
                continue
            
            if "person" not in (source.supported_entity_types or []):
                continue
                
            if source.requires_api_key and source.status == SourceStatus.REQUIRES_CONFIGURATION:
                continue

            task = ResearchTask(
                id=str(uuid.uuid4()),
                research_run_id=run_id,
                source_id=source.id,
                status=TaskStatus.PENDING,
                priority=source.priority.value
            )
            db.add(task)

        await db.commit()
        return run_id
