import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.research import ResearchSource, SourceStatus
from app.models.orchestration import ResearchRun, ResearchTask, RunStatus, TaskStatus
from app.models.identity import Contact, ExternalIdentity
from app.services.discovery import SourceDiscoveryService
import logging
import json

logger = logging.getLogger("networkos")

class ResearchOrchestrator:
    @staticmethod
    async def create_research_plan(
        contact_id: str,
        triggered_by: str = "manual",
        db: AsyncSession = None,
        entity_type: str = "person",
        **kwargs
    ) -> str:
        if db is None and "db_session" in kwargs:
            db = kwargs["db_session"]
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
        
        c_res = await db.execute(select(Contact).where(Contact.id == contact_id))
        contact = c_res.scalars().first()
        
        i_res = await db.execute(select(ExternalIdentity).where(ExternalIdentity.contact_id == contact_id))
        identities = i_res.scalars().all()
        
        discovery = SourceDiscoveryService()

        for source in sources:
            if source.status != SourceStatus.ENABLED:
                continue
            
            if "person" not in (source.supported_entity_types or []):
                continue
                
            if source.requires_api_key and source.status == SourceStatus.REQUIRES_CONFIGURATION:
                continue

            tasks_meta = discovery.generate_queries(source, contact, identities)
            
            for meta in tasks_meta:
                task = ResearchTask(
                    id=str(uuid.uuid4()),
                    research_run_id=run_id,
                    source_id=source.id,
                    status=TaskStatus.PENDING,
                    priority=source.priority.value,
                    target_metadata=meta
                )
                db.add(task)

        await db.commit()
        return run_id
