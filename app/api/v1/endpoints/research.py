from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Dict, Any, Optional
import uuid
import re
from datetime import datetime, timezone

from app.db.session import get_db
from app.models.research import ResearchSource, SourceStatus
from app.models.orchestration import ResearchRun, ResearchTask, TaskStatus, RunStatus
from app.models.identity import Contact, ExternalIdentity, ContactStatus
from app.models.evidence import SourceResult, Evidence

from app.schemas.research import (
    ResearchSourceCreate,
    ResearchSourceUpdate,
    ResearchSourceInDB,
    ResearchJobCreate,
    ResearchJobCreatedOut,
    ResearchJobStatusOut,
    ResearchJobSourcesOut,
    ResearchJobReportOut,
    ProviderTaskSummary,
    SourceItemResult,
    EvidenceItemOut
)
from app.api.dependencies import get_current_admin, get_current_user
from app.services.orchestrator import ResearchOrchestrator
from app.workers.research_worker import execute_research_run, execute_task

from app.services.identity import canonicalize_linkedin_url, extract_name_from_linkedin_slug

router = APIRouter()

def validate_linkedin_url(url: str) -> str:
    """Validates and canonicalizes a LinkedIn profile URL."""
    try:
        return canonicalize_linkedin_url(url)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

extract_name_from_slug = extract_name_from_linkedin_slug

# =========================================================================
# RESEARCH JOBS API (MULTI-SOURCE PERSON INTELLIGENCE)
# =========================================================================

@router.post("/jobs", response_model=ResearchJobCreatedOut)
async def create_research_job(
    req: ResearchJobCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Submits a LinkedIn profile URL, validates input, extracts candidate name,
    initializes Contact and ExternalIdentity, builds multi-source plan,
    and launches background workers across all enabled providers.
    """
    normalized_url = validate_linkedin_url(req.linkedin_url)
    org_id = user.get("organization_id", "org-1")

    # 1. Check if an external identity already exists with this LinkedIn URL
    ident_stmt = select(ExternalIdentity).where(
        ExternalIdentity.provider == "linkedin",
        ExternalIdentity.identifier == normalized_url
    )
    ident_res = await db.execute(ident_stmt)
    identity = ident_res.scalars().first()

    if identity and identity.contact_id:
        contact_stmt = select(Contact).where(Contact.id == identity.contact_id)
        contact = (await db.execute(contact_stmt)).scalars().first()
    else:
        contact = None

    extracted_name = extract_name_from_slug(normalized_url)

    # 2. If contact doesn't exist, create it
    if not contact:
        contact_id = str(uuid.uuid4())
        contact = Contact(
            id=contact_id,
            organization_id=org_id,
            full_name=extracted_name,
            current_title="Analyzing profile...",
            current_company="Pending research",
            profile_url=normalized_url,
            status=ContactStatus.NEW
        )
        db.add(contact)
        await db.flush()

        identity = ExternalIdentity(
            id=str(uuid.uuid4()),
            contact_id=contact.id,
            provider="linkedin",
            identifier_type="profile_url",
            identifier=normalized_url
        )
        db.add(identity)
        await db.commit()
    else:
        # Update name if was placeholder
        if (not contact.full_name or contact.full_name in ["Unknown", "New Contact"]) and extracted_name != "New Contact":
            contact.full_name = extracted_name
            await db.commit()

    # 3. Create Multi-Source Research Plan
    run_id = await ResearchOrchestrator.create_research_plan(
        contact_id=contact.id,
        triggered_by=user["user_id"],
        db=db
    )

    # 4. Enqueue background execution across all providers
    background_tasks.add_task(execute_research_run, run_id)

    return ResearchJobCreatedOut(
        job_id=run_id,
        contact_id=contact.id,
        status="QUEUED",
        message="Research job successfully created across all enabled providers"
    )

@router.get("/jobs/{job_id}", response_model=ResearchJobStatusOut)
async def get_research_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Returns live progress, per-provider status (active, completed, failed),
    and records discovered for a research job.
    """
    # Resolve run by run_id or contact_id
    run_res = await db.execute(select(ResearchRun).where(ResearchRun.id == job_id))
    run = run_res.scalars().first()
    if not run:
        # Try finding most recent run for contact_id
        run_res = await db.execute(
            select(ResearchRun).where(ResearchRun.contact_id == job_id).order_by(ResearchRun.created_at.desc())
        )
        run = run_res.scalars().first()

    if not run:
        raise HTTPException(status_code=404, detail="Research job not found")

    tasks_res = await db.execute(select(ResearchTask).where(ResearchTask.research_run_id == run.id))
    tasks = tasks_res.scalars().all()

    sources_res = await db.execute(select(ResearchSource))
    sources_dict = {s.id: s.name for s in sources_res.scalars().all()}

    # Also sum discovered records count from source_results
    sr_res = await db.execute(
        select(SourceResult).where(SourceResult.research_task_id.in_([t.id for t in tasks]))
    ) if tasks else None
    source_results = sr_res.scalars().all() if sr_res else []

    records_discovered = 0
    for sr in source_results:
        ed = sr.extracted_data or {}
        records_discovered += ed.get("records_count", 1 if sr.status == "SUCCESS" else 0)

    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
    failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
    pending = sum(1 for t in tasks if t.status in [TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING])

    active_providers = [sources_dict.get(t.source_id, t.source_id) for t in tasks if t.status == TaskStatus.RUNNING]
    completed_providers = [sources_dict.get(t.source_id, t.source_id) for t in tasks if t.status == TaskStatus.COMPLETED]
    failed_providers = [
        {"provider": sources_dict.get(t.source_id, t.source_id), "error": t.error_message or "Unknown failure"}
        for t in tasks if t.status == TaskStatus.FAILED
    ]

    task_summaries = []
    for t in tasks:
        t_meta = t.target_metadata or {}
        query_val = t_meta.get("query") or t_meta.get("target_url")
        task_summaries.append(ProviderTaskSummary(
            task_id=t.id,
            source_id=t.source_id,
            source_name=sources_dict.get(t.source_id, t.source_id),
            status=t.status.value if hasattr(t.status, 'value') else str(t.status),
            target_query=query_val,
            error=t.error_message,
            started_at=t.started_at,
            completed_at=t.completed_at
        ))

    return ResearchJobStatusOut(
        job_id=run.id,
        contact_id=run.contact_id,
        status=run.status.value if hasattr(run.status, 'value') else str(run.status),
        total_tasks=total,
        completed_tasks=completed,
        failed_tasks=failed,
        pending_tasks=pending,
        records_discovered=records_discovered,
        active_providers=active_providers,
        completed_providers=completed_providers,
        failed_providers=failed_providers,
        tasks=task_summaries
    )

@router.get("/jobs/{job_id}/sources", response_model=ResearchJobSourcesOut)
async def get_research_job_sources(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """Returns all source retrieval attempts, status, references, and extracted evidence."""
    run_res = await db.execute(select(ResearchRun).where(ResearchRun.id == job_id))
    run = run_res.scalars().first()
    if not run:
        run_res = await db.execute(
            select(ResearchRun).where(ResearchRun.contact_id == job_id).order_by(ResearchRun.created_at.desc())
        )
        run = run_res.scalars().first()

    if not run:
        raise HTTPException(status_code=404, detail="Research job not found")

    tasks_res = await db.execute(select(ResearchTask).where(ResearchTask.research_run_id == run.id))
    tasks = tasks_res.scalars().all()
    task_ids = [t.id for t in tasks]

    sources_res = await db.execute(select(ResearchSource))
    sources_dict = {s.id: s.name for s in sources_res.scalars().all()}

    results_out: List[SourceItemResult] = []
    if task_ids:
        srs = (await db.execute(select(SourceResult).where(SourceResult.research_task_id.in_(task_ids)))).scalars().all()
        for sr in srs:
            ed = sr.extracted_data or {}
            meta = sr.metadata_ or {}
            snippet = ed.get("text") or ed.get("text_content") or ed.get("meta_description") or ""
            if snippet:
                snippet = snippet[:350]

            results_out.append(SourceItemResult(
                source_id=sr.source_id,
                source_name=sources_dict.get(sr.source_id, sr.source_id.title()),
                status=sr.status,
                query=sr.query,
                reference=sr.raw_reference,
                records_count=ed.get("records_count", 1 if sr.status == "SUCCESS" else 0),
                snippet=snippet,
                retrieved_at=sr.retrieved_at,
                identity_match_status=meta.get("identity_match_status"),
                identity_match_confidence=meta.get("identity_match_confidence")
            ))

    return ResearchJobSourcesOut(
        job_id=run.id,
        total_sources=len(results_out),
        sources=results_out
    )

@router.get("/jobs/{job_id}/report", response_model=ResearchJobReportOut)
async def get_research_job_report(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """Returns the consolidated person report, atomic evidence items, and commercial opportunity analysis."""
    run_res = await db.execute(select(ResearchRun).where(ResearchRun.id == job_id))
    run = run_res.scalars().first()
    if not run:
        run_res = await db.execute(
            select(ResearchRun).where(ResearchRun.contact_id == job_id).order_by(ResearchRun.created_at.desc())
        )
        run = run_res.scalars().first()

    if not run:
        raise HTTPException(status_code=404, detail="Research job not found")

    contact = (await db.execute(select(Contact).where(Contact.id == run.contact_id))).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Get latest evidence_engine snapshot
    sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
    all_srs = (await db.execute(sr_stmt)).scalars().all()
    snapshot = {}
    for sr in all_srs:
        if sr.metadata_ and sr.metadata_.get("contact_id") == contact.id:
            if sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
                snapshot = sr.extracted_data['executive_snapshot']
            break

    # Get atomic evidence claims
    ev_stmt = select(Evidence).where(Evidence.related_entity_id == contact.id).order_by(Evidence.confidence.desc())
    ev_items = (await db.execute(ev_stmt)).scalars().all()

    evidence_outs = [
        EvidenceItemOut(
            id=e.id,
            claim=e.claim,
            evidence_type=e.evidence_type.value if hasattr(e.evidence_type, 'value') else str(e.evidence_type),
            source_id=e.source_id,
            source_reference=e.source_reference,
            confidence=e.confidence,
            retrieved_date=e.retrieved_date
        ) for e in ev_items
    ]

    report_md = snapshot.get("full_markdown_report") or f"# Person Intelligence Report: {contact.full_name}\n\n*Research in progress...*"

    return ResearchJobReportOut(
        job_id=run.id,
        contact_id=contact.id,
        name=contact.full_name or snapshot.get("name", "Unknown"),
        title=contact.current_title or snapshot.get("current_role", "Unknown"),
        company=contact.current_company or snapshot.get("current_organization", "Unknown"),
        full_markdown_report=report_md,
        commercial_intelligence=snapshot,
        evidence=evidence_outs,
        sources_used=snapshot.get("sources_used", []),
        pipeline_stage="PROPOSED" if snapshot.get("pipeline_stage") in ["QUALIFIED", "VALIDATED"] else snapshot.get("pipeline_stage", "PROPOSED")
    )


@router.post("/jobs/{job_id}/retry")
async def retry_failed_research_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """Retries eligible failed or incomplete providers for a research job."""
    run_res = await db.execute(select(ResearchRun).where(ResearchRun.id == job_id))
    run = run_res.scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="Research job not found")

    tasks_res = await db.execute(
        select(ResearchTask).where(
            ResearchTask.research_run_id == run.id,
            ResearchTask.status.in_([TaskStatus.FAILED, TaskStatus.SKIPPED])
        )
    )
    failed_tasks = tasks_res.scalars().all()

    if not failed_tasks:
        return {"success": True, "message": "No failed tasks to retry", "retried_count": 0}

    for t in failed_tasks:
        t.status = TaskStatus.PENDING
        t.retry_count = (t.retry_count or 0) + 1
        t.error_message = None

    run.status = RunStatus.RUNNING
    await db.commit()

    background_tasks.add_task(execute_research_run, run.id)

    return {
        "success": True,
        "message": f"Successfully queued {len(failed_tasks)} failed provider tasks for retry",
        "retried_count": len(failed_tasks)
    }

# =========================================================================
# EXISTING RESEARCH SOURCES MANAGEMENT ENDPOINTS (PRESERVED)
# =========================================================================

@router.get("/sources", response_model=List[ResearchSourceInDB])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    result = await db.execute(select(ResearchSource))
    return result.scalars().all()

@router.post("/sources", response_model=ResearchSourceInDB)
async def create_source(
    source_in: ResearchSourceCreate,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    db_obj = ResearchSource(**source_in.model_dump())
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

@router.get("/sources/{source_id}", response_model=ResearchSourceInDB)
async def get_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    result = await db.execute(select(ResearchSource).where(ResearchSource.id == source_id))
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail={"success": False, "error": {"code": "NOT_FOUND", "message": "Source not found"}})
    return source

@router.put("/sources/{source_id}", response_model=ResearchSourceInDB)
async def update_source(
    source_id: str,
    source_update: ResearchSourceUpdate,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    result = await db.execute(select(ResearchSource).where(ResearchSource.id == source_id))
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail={"success": False, "error": {"code": "NOT_FOUND", "message": "Source not found"}})

    update_data = source_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(source, key, value)

    await db.commit()
    await db.refresh(source)
    return source

@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    result = await db.execute(select(ResearchSource).where(ResearchSource.id == source_id))
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail={"success": False, "error": {"code": "NOT_FOUND", "message": "Source not found"}})
    await db.delete(source)
    await db.commit()
    return {"success": True, "message": "Source deleted"}

@router.get("/runs/{research_run_id}")
async def get_research_run_status_legacy(
    research_run_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    # Delegate to get_research_job_status
    return await get_research_job_status(research_run_id, db, user)
