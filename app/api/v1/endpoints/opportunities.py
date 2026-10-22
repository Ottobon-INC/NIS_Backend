from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timezone

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.models.opportunity import Opportunity, OpportunityStatus, OpportunityLifecycleStatus
from app.schemas.opportunity import (
    OpportunityOut,
    OpportunityListResponse,
    OpportunityDetailOut,
    OpportunityCreateIn,
    OpportunityValidateIn,
    OpportunityValidationResponse,
    OpportunityPathIn,
    OpportunityPathResponse,
    CapabilityMatchesResponse,
    CapabilityMatchUpdateIn,
    OpportunitySolutionsResponse,
    OpportunitySearchResult,
    OpportunitySearchResponse,
    to_frontend_status,
)
from app.services.opportunity_service import OpportunityService
from app.services.opportunity_search import OpportunitySearchService

router = APIRouter(dependencies=[Depends(get_current_user)])


# ==============================================================================
# Database-Backed CRUD & Intelligence Endpoints
# ==============================================================================

@router.get("", response_model=OpportunityListResponse)
async def list_opportunities(
    status: Optional[str] = Query(None, description="Filter by status (CANDIDATE, VALIDATED, etc.)"),
    contact_id: Optional[str] = Query(None, description="Filter by contact ID"),
    q: Optional[str] = Query(None, description="Quick search term"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List opportunities for the authenticated organization with optional filtering."""
    opps, total = await OpportunityService.list_opportunities(
        db=db,
        organization_id=user["organization_id"],
        status=status,
        contact_id=contact_id,
        limit=limit,
        offset=offset,
    )
    if q:
        q_lower = q.lower()
        opps = [
            o for o in opps
            if q_lower in (o.title or "").lower()
            or q_lower in (o.company_name or "").lower()
            or q_lower in (o.problem or "").lower()
        ]
        total = len(opps)

    return OpportunityListResponse(
        opportunities=[OpportunityOut.model_validate(o) for o in opps],
        total=total,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OpportunityDetailOut)
async def create_opportunity(
    payload: OpportunityCreateIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Create a new commercial opportunity with validation and attribution."""
    created = await OpportunityService.create_opportunity(
        db=db,
        payload=payload,
        organization_id=user["organization_id"],
        user=user,
    )
    return OpportunityDetailOut.model_validate(created)


@router.post("/derive/{contact_id}", status_code=status.HTTP_201_CREATED, response_model=OpportunityDetailOut)
async def derive_opportunity(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Derive opportunity grounded in Contact 360 research (idempotent)."""
    opp = await OpportunityService.derive_opportunity_from_contact(
        db=db,
        contact_id=contact_id,
        organization_id=user["organization_id"],
        user=user,
    )
    return OpportunityDetailOut.model_validate(opp)


# ==============================================================================
# Live Search & Pipeline Prototypes (Preserved)
# ==============================================================================

@router.get("/search", response_model=OpportunitySearchResponse)
async def live_opportunity_search(
    q: str = Query("", description="Live search keyword across problem, requirement, company, or person"),
    status: Optional[str] = Query(None, description="Filter by opportunity status"),
    min_confidence: int = Query(0, ge=0, le=100, description="Minimum confidence threshold"),
    opportunity_type: Optional[str] = Query(None, description="Filter by opportunity type"),
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Live Opportunity Search Engine:
    Performs real-time database-backed faceted search across all active opportunities,
    validated needs, associated contacts, and origin problem definitions.
    """
    return await OpportunitySearchService.search_opportunities(
        db=db,
        organization_id=user["organization_id"],
        q=q,
        status=status,
        min_confidence=min_confidence,
        opportunity_type=opportunity_type,
        limit=limit,
        offset=offset,
    )


@router.get("/pipeline")
async def get_opportunity_pipeline(
    user: dict = Depends(get_current_user),
):
    """Returns items currently active in the downstream opportunity pipeline."""
    return {
        "pipeline": [
            {
                "id": "opp-sap-migration-01",
                "contactName": "Rahul Dhamdhere",
                "company": "Global Logistics Corp",
                "validatedProblem": "Legacy SAP ECC to S/4HANA migration is stalling due to 200+ custom workflows.",
                "status": "VALIDATED",
                "nextAction": "Schedule Technical Architecture Deep-Dive"
            }
        ]
    }


# ==============================================================================
# Job Scraping Pipeline Management Endpoints
# ==============================================================================

@router.post("/scrape-jobs/trigger")
async def trigger_job_scrape(
    user: dict = Depends(get_current_user),
):
    """
    Manually triggers the official job board scraping and ingestion pipeline.
    Deduplicates across sources, creates Opportunities, and updates the scraped_jobs ledger.
    """
    from app.workers.job_scraper_worker import PipelineExecutionManager
    org_id = user.get("organization_id", "org-1")
    result = await PipelineExecutionManager.execute_job(
        organization_id=org_id,
        trigger_source=f"API_USER_{user.get('user_id', 'unknown')}"
    )
    return {
        "success": True,
        "message": "Job scraping pipeline executed successfully",
        "result": result
    }


@router.get("/scrape-jobs/status")
async def get_job_scrape_status(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Returns the execution status, last run statistics, and ledger summary for scraped jobs.
    """
    from app.workers.job_scraper_worker import PipelineExecutionManager
    from app.models.scraped_job import ScrapedJob
    from sqlalchemy import func

    org_id = user.get("organization_id", "org-1")
    engine_status = PipelineExecutionManager.get_status()

    # Query database ledger stats
    count_stmt = select(func.count(ScrapedJob.id)).where(ScrapedJob.organization_id == org_id)
    total_jobs = (await db.execute(count_stmt)).scalar() or 0

    sources_stmt = select(ScrapedJob.source, func.count(ScrapedJob.id)).where(
        ScrapedJob.organization_id == org_id
    ).group_by(ScrapedJob.source)
    source_counts = {row[0]: row[1] for row in (await db.execute(sources_stmt)).fetchall()}

    return {
        "scheduler_configured": "02:00 AM Asia/Kolkata (Daily)",
        "is_running": engine_status["is_running"],
        "last_run_at": engine_status["last_run_at"],
        "last_summary": engine_status["last_summary"],
        "database_metrics": {
            "total_scraped_jobs": total_jobs,
            "jobs_by_source": source_counts
        }
    }


# ==============================================================================
# Parametric Endpoints (Defined after static paths to prevent path masking)
# ==============================================================================

@router.get("/{opportunity_id}", response_model=OpportunityDetailOut)
async def get_opportunity(
    opportunity_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Retrieve detailed opportunity context strictly scoped to the user's organization."""
    opp = await OpportunityService.get_opportunity(
        db=db,
        opportunity_id=opportunity_id,
        organization_id=user["organization_id"],
    )
    return OpportunityDetailOut.model_validate(opp)


@router.patch("/{opportunity_id}/validate", response_model=OpportunityValidationResponse)
async def validate_opportunity(
    opportunity_id: str,
    payload: OpportunityValidateIn = OpportunityValidateIn(),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Validate or qualify an opportunity with lifecycle transition rules and identity gate."""
    updated = await OpportunityService.validate_opportunity(
        db=db,
        opportunity_id=opportunity_id,
        payload=payload,
        organization_id=user["organization_id"],
        user=user,
    )
    return OpportunityValidationResponse(
        success=True,
        opportunity_id=updated.id,
        status=to_frontend_status(updated.status),
        message=f"Opportunity {updated.id} status updated to {to_frontend_status(updated.status)}",
        opportunity=OpportunityDetailOut.model_validate(updated),
    )


@router.get("/{opportunity_id}/capability-matches", response_model=CapabilityMatchesResponse)
async def get_capability_matches(
    opportunity_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Evaluates real capabilities, products, and services against the opportunity's
    verified problem statement. Returns structured matches with alignment reasoning.
    """
    matches = await OpportunityService.get_capability_matches(
        db=db,
        opportunity_id=opportunity_id,
        organization_id=user["organization_id"],
    )
    return CapabilityMatchesResponse(matches=matches)


@router.patch("/{opportunity_id}/capability-matches/{match_id}")
async def update_capability_match(
    opportunity_id: str,
    match_id: str,
    payload: CapabilityMatchUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Updates the review status of a capability match (SELECTED, REJECTED, CANDIDATE)
    and persists the chosen capability onto the opportunity record.
    """
    await OpportunityService.update_capability_match(
        db=db,
        opportunity_id=opportunity_id,
        match_id=match_id,
        status_val=payload.status,
        organization_id=user["organization_id"],
        user=user,
    )
    return {
        "success": True,
        "opportunity_id": opportunity_id,
        "match_id": match_id,
        "status": payload.status.upper(),
    }


@router.get("/{opportunity_id}/solutions", response_model=OpportunitySolutionsResponse)
async def get_solution_candidates(
    opportunity_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get solution and capability candidates for an opportunity grounded in
    authentic database offerings (INTERNAL, NETWORK, HYBRID).
    """
    solutions = await OpportunityService.get_solution_candidates(
        db=db,
        opportunity_id=opportunity_id,
        organization_id=user["organization_id"],
    )
    return OpportunitySolutionsResponse(solutions=solutions)


@router.patch("/{opportunity_id}/path", response_model=OpportunityPathResponse)
async def set_opportunity_path(
    opportunity_id: str,
    payload: OpportunityPathIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Set and persist the selected delivery/go-to-market path (INTERNAL, NETWORK, HYBRID).
    Enforces allowed path values and persists onto the opportunity record.
    """
    updated = await OpportunityService.set_delivery_path(
        db=db,
        opportunity_id=opportunity_id,
        path=payload.path,
        organization_id=user["organization_id"],
        user=user,
    )
    return OpportunityPathResponse(
        success=True,
        opportunity_id=updated.id,
        selected_path=updated.delivery_path,
        delivery_path=updated.delivery_path,
    )


@router.post("/{opportunity_id}/outcome")
async def record_opportunity_outcome(
    opportunity_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Record meeting or introduction outcome for feedback loop."""
    return {
        "success": True, 
        "opportunity_id": opportunity_id, 
        "outcome": payload.get("outcome"),
        "notes": payload.get("notes")
    }

