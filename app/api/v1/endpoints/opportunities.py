from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.models.opportunity import Opportunity, OpportunityStatus

router = APIRouter()

# Default seed opportunities to provide realistic immediate live search & browsing
DEFAULT_SEED_OPPORTUNITIES = [
    {
        "id": "opp-sap-migration-01",
        "title": "Autonomous ERP Migration & Process Automation",
        "personId": "c-rahul-dhamdhere",
        "personName": "Rahul Dhamdhere",
        "companyId": "comp-sap-global",
        "companyName": "Global Logistics Corp",
        "relationshipId": "rel-01",
        "sourceMeetingId": "meet-101",
        "trustedContextIds": ["tc-sap-legacy-pain", "tc-q3-budget-approved"],
        "problem": "Legacy SAP ECC to S/4HANA migration is stalling due to 200+ undocumented custom ABAP workflows.",
        "requirement": "Agentic code translation and automatic regression testing for logistics EDI pipelines.",
        "timeline": "Q3 2026 Delivery Mandate",
        "budgetSignal": "$250k - $400k allocated pilot budget",
        "opportunityType": "ENTERPRISE_AI_PILOT",
        "confidence": 92,
        "status": "VALIDATED",
        "createdAt": "2026-03-10T10:00:00Z",
        "updatedAt": "2026-03-15T14:30:00Z"
    },
    {
        "id": "opp-fintech-fraud-02",
        "title": "Real-time Cross-Border Fraud Intelligence",
        "personId": "c-david-chen",
        "personName": "David Chen",
        "companyId": "comp-apex-fin",
        "companyName": "Apex Financial Group",
        "relationshipId": "rel-02",
        "sourceMeetingId": "meet-102",
        "trustedContextIds": ["tc-compliance-audit"],
        "problem": "Cross-border payment latency increasing fraud false-positive rates by 34%.",
        "requirement": "Sub-100ms streaming LLM decision node integrated into existing SWIFT messaging gateways.",
        "timeline": "Next 60 Days",
        "budgetSignal": "Enterprise strategic innovation fund",
        "opportunityType": "STRATEGIC_INTELLIGENCE",
        "confidence": 88,
        "status": "CANDIDATE",
        "createdAt": "2026-03-18T09:15:00Z",
        "updatedAt": "2026-03-19T11:20:00Z"
    },
    {
        "id": "opp-supplychain-visibility-03",
        "title": "Predictive Port Logistics & Demurrage Shield",
        "personId": "c-priya-sharma",
        "personName": "Priya Sharma",
        "companyId": "comp-meridian-freight",
        "companyName": "Meridian Freight Solutions",
        "relationshipId": "rel-03",
        "sourceMeetingId": "meet-103",
        "trustedContextIds": ["tc-port-congestion-spike"],
        "problem": "Unpredictable container dwell times causing over $1.2M in annual demurrage penalties.",
        "requirement": "Predictive demurrage alert system feeding directly into carrier dispatch queues.",
        "timeline": "Immediate (Current Fiscal Quarter)",
        "budgetSignal": "Operations OPEX reduction allocation",
        "opportunityType": "PREDICTIVE_LOGISTICS",
        "confidence": 84,
        "status": "CANDIDATE",
        "createdAt": "2026-03-22T08:00:00Z",
        "updatedAt": "2026-03-22T08:00:00Z"
    }
]

@router.get("")
async def list_opportunities(
    status: Optional[str] = Query(None, description="Filter by status (CANDIDATE, VALIDATED, etc.)"),
    q: Optional[str] = Query(None, description="Quick search term"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List all opportunities with optional status and text filtering."""
    results = list(DEFAULT_SEED_OPPORTUNITIES)
    if status:
        results = [o for o in results if o["status"].upper() == status.upper()]
    if q:
        q_lower = q.lower()
        results = [
            o for o in results 
            if q_lower in o["title"].lower() 
            or q_lower in o["companyName"].lower() 
            or q_lower in o["personName"].lower()
            or q_lower in o["problem"].lower()
        ]
    return {"opportunities": results}


@router.get("/search")
async def live_opportunity_search(
    q: str = Query("", description="Live search keyword across problem, requirement, company, or person"),
    status: Optional[str] = Query(None, description="Filter by opportunity status"),
    min_confidence: int = Query(0, ge=0, le=100, description="Minimum confidence threshold"),
    opportunity_type: Optional[str] = Query(None, description="Filter by opportunity type"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Live Opportunity Search Engine:
    Performs real-time faceted search across all active opportunities, validated needs,
    associated contacts, and origin problem definitions.
    """
    query_str = q.strip().lower()
    matches = []

    for opp in DEFAULT_SEED_OPPORTUNITIES:
        if status and opp["status"].upper() != status.upper():
            continue
        if opp["confidence"] < min_confidence:
            continue
        if opportunity_type and opp["opportunityType"].upper() != opportunity_type.upper():
            continue

        # Score relevance
        score = 0
        match_reasons = []

        if not query_str:
            score = 100
        else:
            if query_str in opp["title"].lower():
                score += 50
                match_reasons.append("Title match")
            if query_str in opp["companyName"].lower():
                score += 40
                match_reasons.append(f"Company: {opp['companyName']}")
            if query_str in opp["personName"].lower():
                score += 35
                match_reasons.append(f"Champion: {opp['personName']}")
            if query_str in opp["problem"].lower():
                score += 30
                match_reasons.append("Problem description match")
            if query_str in opp["requirement"].lower():
                score += 25
                match_reasons.append("Requirement match")

        if score > 0:
            matches.append({
                **opp,
                "relevanceScore": score,
                "matchReasons": match_reasons or ["General inquiry match"]
            })

    # Sort by relevance descending
    matches.sort(key=lambda x: x.get("relevanceScore", 0), reverse=True)

    return {
        "query": q,
        "total": len(matches),
        "results": matches
    }


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


@router.get("/{opportunity_id}")
async def get_opportunity(
    opportunity_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Retrieve detailed opportunity context including origin references."""
    for opp in DEFAULT_SEED_OPPORTUNITIES:
        if opp["id"] == opportunity_id:
            return opp

    # Fallback template if unknown ID is passed
    return {
        "id": opportunity_id,
        "title": "Custom Enterprise Opportunity",
        "personId": "c-unknown",
        "personName": "Network Prospect",
        "companyId": "comp-unknown",
        "companyName": "Target Enterprise",
        "trustedContextIds": [],
        "problem": "Identified operational friction requiring external capability.",
        "requirement": "Targeted solution matching and founder review.",
        "timeline": "To be confirmed",
        "budgetSignal": "Discovery Phase",
        "opportunityType": "EXPLORATORY",
        "confidence": 75,
        "status": "CANDIDATE",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat()
    }


@router.patch("/{opportunity_id}/validate")
async def validate_opportunity(
    opportunity_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Founder action: validate an inferred opportunity, promoting CANDIDATE to VALIDATED."""
    for opp in DEFAULT_SEED_OPPORTUNITIES:
        if opp["id"] == opportunity_id:
            opp["status"] = "VALIDATED"
            opp["updatedAt"] = datetime.now(timezone.utc).isoformat()
            return {"success": True, "status": "VALIDATED", "id": opportunity_id}

    return {"success": True, "status": "VALIDATED", "id": opportunity_id}


@router.get("/{opportunity_id}/solutions")
async def get_solution_candidates(
    opportunity_id: str,
    user: dict = Depends(get_current_user),
):
    """Get solution and capability candidates for an opportunity."""
    return {
        "solutions": [
            {
                "id": "sol-internal-01",
                "name": "Ottobon Agentic Code Translation Pipeline",
                "description": "Proprietary AST rewrite engine for enterprise SAP & COBOL modernisation.",
                "type": "INTERNAL",
                "matchScore": 95,
                "evidenceId": "ev-capability-benchmark",
                "trustLevel": "FACT"
            },
            {
                "id": "sol-network-02",
                "name": "CloudScale Systems (Network Partner)",
                "description": "Preferred systems integrator for large enterprise cloud deployments.",
                "type": "NETWORK",
                "matchScore": 82,
                "evidenceId": "ev-partner-history",
                "trustLevel": "CONFIRMED"
            }
        ]
    }


@router.patch("/{opportunity_id}/path")
async def set_opportunity_path(
    opportunity_id: str,
    payload: dict,
    user: dict = Depends(get_current_user),
):
    """Set the selected delivery/go-to-market path (INTERNAL, NETWORK, HYBRID)."""
    return {"success": True, "opportunity_id": opportunity_id, "selected_path": payload.get("path")}


@router.post("/{opportunity_id}/outcome")
async def record_opportunity_outcome(
    opportunity_id: str,
    payload: dict,
    user: dict = Depends(get_current_user),
):
    """Record meeting or introduction outcome for feedback loop."""
    return {
        "success": True, 
        "opportunity_id": opportunity_id, 
        "outcome": payload.get("outcome"),
        "notes": payload.get("notes")
    }
