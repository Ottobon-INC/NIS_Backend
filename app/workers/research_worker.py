import logging
import asyncio
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.session import AsyncSessionLocal
from app.models.orchestration import ResearchTask, TaskStatus, ResearchRun, RunStatus
from app.models.evidence import SourceResult
from app.models.research import ResearchSource
from app.services.providers.web import GeneralWebProvider
from app.services.providers.search import DuckDuckGoProvider
from app.services.providers.agent_reach import AgentReachProvider
from app.services.identity import IdentityResolver
from app.services.evidence import EvidenceEngine

logger = logging.getLogger("networkos")

from app.services.providers.base import ResearchProvider
from app.core.agent_reach_cli import AgentReachCLI

class SimpleSearchProvider(ResearchProvider):
    def __init__(self, source_id: str, search_suffix: str = ""):
        self.source_id = source_id
        self.search_suffix = search_suffix

    def get_provider_metadata(self):
        return {"source_id": self.source_id}

    async def fetch_public_webpage(self, url: str):
        query = f"{url} {self.search_suffix}".strip()
        try:
            target = "github" if self.source_id == "github" else "web"
            res = await AgentReachCLI.execute_search(target, query)
            if res.get("status") == "SUCCESS" and res.get("data", {}).get("raw_text"):
                return {
                    "status": "SUCCESS",
                    "final_url": f"https://duckduckgo.com/?q={query}",
                    "http_status": 200,
                    "content_type": "text/plain",
                    "title": f"Results for {query}",
                    "text_content": res["data"]["raw_text"][:30000]
                }
            return {
                "status": "SUCCESS",
                "final_url": f"https://duckduckgo.com/?q={query}",
                "http_status": 200,
                "content_type": "text/plain",
                "title": f"Summary for {query}",
                "text_content": f"Information context for {query}"
            }
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def search_person(self, query: str): raise NotImplementedError()
    def search_company(self, query: str): raise NotImplementedError()
    def fetch_person(self, identifier: str): raise NotImplementedError()
    def fetch_company(self, identifier: str): raise NotImplementedError()
    def fetch_signals(self, query: str): raise NotImplementedError()

PROVIDER_REGISTRY = {
    "general_web": GeneralWebProvider(),
    "duckduckgo": DuckDuckGoProvider(),
    "agent_reach": AgentReachProvider(),
    "github": SimpleSearchProvider("github"),
    "company_web": SimpleSearchProvider("company_web", "company leadership"),
    "news_public": SimpleSearchProvider("news_public", "news executive"),
    "academic_openalex": SimpleSearchProvider("academic_openalex", "publications research")
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
            target_meta: Dict[str, Any] = getattr(task, "target_metadata", None) or {}
            target_url = target_meta.get("target_url")
            agent_reach_target = target_meta.get("agent_reach_target")
            
            if agent_reach_target and hasattr(provider, "search_target"):
                search_query = str(target_url or target_meta.get("query") or "")
                result = await provider.search_target(agent_reach_target, search_query)
            elif target_url and hasattr(provider, "fetch_public_webpage"):
                result = await provider.fetch_public_webpage(target_url)
            else:
                result = {"status": "SKIPPED", "error": "No valid method found for provider"}
                
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
                    "text": result.get("text_content"),
                    "raw_data": result.get("extracted_data") # used by AgentReach searches
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
                
                run_res = await db.execute(select(ResearchRun).where(ResearchRun.id == task.research_run_id))
                run = run_res.scalars().first()
                if run:
                    await IdentityResolver.process_source_result(db, run.contact_id, sr)
            else:
                task.status = TaskStatus.FAILED
                task.error_message = result.get("error", result.get("status"))

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            logger.exception(f"Error executing task {task_id}")
            
        task.completed_at = datetime.now(timezone.utc)
        await db.commit()


async def mock_research_background_task(run_id: str):
    logger.info(f"Background task queued for ResearchRun: {run_id}")
    try:
        async with AsyncSessionLocal() as db:
            run_res = await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))
            run = run_res.scalars().first()
            if run:
                run.status = RunStatus.RUNNING
                run.started_at = datetime.now(timezone.utc)
                await db.commit()

            res = await db.execute(select(ResearchTask).where(ResearchTask.research_run_id == run_id, ResearchTask.status == TaskStatus.PENDING))
            tasks = res.scalars().all()
            
        for task in tasks:
            try:
                await execute_task(task.id)
            except Exception as task_err:
                logger.error(f"Task {task.id} failed with error: {task_err}")
            
        async with AsyncSessionLocal() as db:
            run_res = await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))
            run = run_res.scalars().first()
            if run:
                # Trigger Evidence Engine
                await EvidenceEngine.process_run_and_extract_snapshot(db, run_id, run.contact_id)
                
                run.status = RunStatus.COMPLETED
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception as e:
        logger.error(f"mock_research_background_task error: {e}", exc_info=True)
        async with AsyncSessionLocal() as db:
            run_res = await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))
            run = run_res.scalars().first()
            if run:
                run.status = RunStatus.PARTIAL
                run.error_message = str(e)
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
