import logging
import asyncio
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.session import AsyncSessionLocal
from app.models.orchestration import ResearchTask, TaskStatus, ResearchRun, RunStatus
from app.models.evidence import SourceResult
from app.models.research import ResearchSource
from app.models.identity import Contact, ContactStatus

from app.services.providers.web import GeneralWebProvider
from app.services.providers.search import DuckDuckGoProvider
from app.services.providers.github import GitHubProvider
from app.services.providers.academic import AcademicResearchProvider
from app.services.providers.company_web import CompanyWebsiteProvider
from app.services.providers.news_public import NewsPublicProvider
from app.services.providers.agent_reach import AgentReachProvider

from app.services.identity import IdentityResolver
from app.services.evidence import EvidenceEngine
from app.services.company_intelligence import CompanyIntelligenceService

logger = logging.getLogger("networkos")

PROVIDER_REGISTRY = {
    "general_web": GeneralWebProvider(),
    "duckduckgo": DuckDuckGoProvider(),
    "github": GitHubProvider(),
    "academic_openalex": AcademicResearchProvider(),
    "company_web": CompanyWebsiteProvider(),
    "news_public": NewsPublicProvider(),
    "agent_reach": AgentReachProvider()
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
            task.error_message = f"Provider '{task.source_id}' not found in registry"
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return
            
        provider = PROVIDER_REGISTRY[source.id]
        
        try:
            target_meta = task.target_metadata or {}
            target_url = target_meta.get("target_url") or target_meta.get("query")
            agent_reach_target = target_meta.get("agent_reach_target")
            
            # Execute with per-task timeout
            async def run_provider():
                if agent_reach_target and hasattr(provider, "search_target"):
                    return await provider.search_target(agent_reach_target, target_url)
                elif hasattr(provider, "search_person") and source.id in ["github", "academic_openalex", "company_web", "news_public", "duckduckgo"]:
                    return await provider.search_person(target_url)
                elif target_url and hasattr(provider, "fetch_public_webpage"):
                    return await provider.fetch_public_webpage(target_url)
                elif hasattr(provider, "search_person"):
                    return await provider.search_person(target_url or "")
                else:
                    return {"status": "SKIPPED", "error": "No valid method found for provider"}

            result = await asyncio.wait_for(run_provider(), timeout=18.0)
                
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
                    "raw_data": result.get("extracted_data") or result.get("text_content"),
                    "records_count": result.get("records_count", 1 if result.get("status") == "SUCCESS" else 0)
                } if result.get("status") == "SUCCESS" else {},
                metadata_={
                    "http_status": result.get("http_status"),
                    "content_type": result.get("content_type"),
                    "error": result.get("error"),
                    "angle": target_meta.get("angle", "GENERAL")
                }
            )
            db.add(sr)
            await db.flush()
            
            if result.get("status") == "SUCCESS":
                task.status = TaskStatus.COMPLETED
                
                run_res = await db.execute(select(ResearchRun).where(ResearchRun.id == task.research_run_id))
                run = run_res.scalars().first()
                if run and run.contact_id:
                    await IdentityResolver.process_source_result(db, run.contact_id, sr)
            else:
                task.status = TaskStatus.FAILED
                task.error_message = result.get("error", result.get("status"))

        except asyncio.TimeoutError:
            task.status = TaskStatus.FAILED
            task.error_message = "Provider request timed out after 18 seconds"
            logger.warning(f"Task {task_id} on {source.id} timed out")
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            logger.exception(f"Error executing task {task_id} on {source.id}")
            
        task.completed_at = datetime.now(timezone.utc)
        await db.commit()

async def execute_research_run(run_id: str):
    logger.info(f"Background worker started for ResearchRun: {run_id}")
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(ResearchTask).where(ResearchTask.research_run_id == run_id))
        tasks = res.scalars().all()
        task_ids = [t.id for t in tasks]

        run_obj = (await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))).scalars().first()
        if run_obj:
            run_obj.status = RunStatus.RUNNING
            run_obj.started_at = datetime.now(timezone.utc)
            await db.commit()

    if not task_ids:
        logger.warning(f"No tasks found for run {run_id}")
        return

    # Execute tasks with bounded concurrency (semaphore=4)
    semaphore = asyncio.Semaphore(4)

    async def sem_execute(tid):
        async with semaphore:
            await execute_task(tid)

    # Launch all tasks concurrently, catching any individual exceptions
    await asyncio.gather(*(sem_execute(tid) for tid in task_ids), return_exceptions=True)

    # Finish run and generate AI report
    async with AsyncSessionLocal() as db:
        run_res = await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))
        run = run_res.scalars().first()
        if run:
            tasks_res = await db.execute(select(ResearchTask).where(ResearchTask.research_run_id == run_id))
            all_tasks = tasks_res.scalars().all()

            completed_count = sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED)
            failed_count = sum(1 for t in all_tasks if t.status == TaskStatus.FAILED)

            if completed_count > 0:
                run.status = RunStatus.COMPLETED if failed_count == 0 else RunStatus.PARTIAL
                # Trigger Evidence Engine Report Synthesis
                if run.contact_id:
                    try:
                        await EvidenceEngine.process_run_and_extract_snapshot(db, run_id, run.contact_id)
                    except Exception as ee_err:
                        logger.error(f"EvidenceEngine snapshot extraction failed for run {run_id}: {ee_err}", exc_info=True)
                    # Update contact status to READY
                    c_res = await db.execute(select(Contact).where(Contact.id == run.contact_id))
                    contact = c_res.scalars().first()
                    if contact:
                        contact.status = ContactStatus.READY
                        invalid_orgs = {
                            "unknown", "pending research", "independent", "[unverified]", "unverified",
                            "unspecified", "not specified", "not provided", "tbd", "none", "n/a", "na", "null", ""
                        }
                        clean_co = (contact.current_company or "").strip()
                        if clean_co and clean_co.lower() not in invalid_orgs:
                            try:
                                logger.info(f"ResearchWorker: Auto-triggering Company Intelligence for '{clean_co}' (Contact ID: {contact.id})")
                                await CompanyIntelligenceService.extract_and_persist(
                                    db=db,
                                    company_name=clean_co,
                                    contact_id=contact.id
                                )
                            except Exception as ci_err:
                                logger.warning(f"ResearchWorker: Auto-extraction of Company Intelligence failed for '{clean_co}': {ci_err}")
            else:
                run.status = RunStatus.FAILED
                run.error_message = "All research source providers failed to retrieve information."

            run.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(f"ResearchRun {run_id} finished with status: {run.status}")

# Alias for backwards compatibility
mock_research_background_task = execute_research_run
