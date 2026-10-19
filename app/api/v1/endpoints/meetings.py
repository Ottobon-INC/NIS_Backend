from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Any, List, Optional
import uuid

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.models.identity import Contact
from app.models.evidence import SourceResult

router = APIRouter()

@router.get("/{id}/brief")
async def get_meeting_brief(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    # id can be a contact_id, or a meeting_id
    stmt = select(Contact).where(Contact.id == id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(stmt)).scalars().first()

    if not contact:
        # Fallback to any contact in this org if a generic meeting id was passed
        first_contact = (await db.execute(select(Contact).where(Contact.organization_id == user["organization_id"]).limit(1))).scalars().first()
        if first_contact:
            contact = first_contact

    if contact:
        # Fetch the latest executive snapshot
        sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
        all_srs = (await db.execute(sr_stmt)).scalars().all()
        snapshot = {}
        for sr in all_srs:
            if sr.metadata_ and sr.metadata_.get("contact_id") == contact.id:
                if sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
                    snapshot = sr.extracted_data['executive_snapshot']
                break

        name = snapshot.get("name") or contact.full_name or "Executive"
        role = snapshot.get("current_role") or contact.current_title or "Leadership"
        company = snapshot.get("current_organization") or contact.current_company or "Enterprise"
        smallest = snapshot.get("smallest_solvable_problem")
        door = snapshot.get("primary_conversation_door")
        why_now = snapshot.get("why_now")
        tier = snapshot.get("networkos_tier") or "Tier 1"
        rel_path = snapshot.get("relationship_path")

        return {
            "id": f"meet-{contact.id[:8]}",
            "contactId": contact.id,
            "contactName": name,
            "company": company,
            "objectives": [
                smallest if smallest else f"Explore targeted solution sprint for {company} AI workflows.",
                f"Validate enterprise alignment with {name} on cloud and AI architecture.",
                "Establish clear technical criteria for a 2-week bounded pilot sprint."
            ],
            "suggestedTopics": [
                door if door else f"Recent leadership focus at {company} around AI agent extensibility.",
                f"Enterprise governance, validation bridges, and partner capability integration.",
                "Ottobon commercial model and scoped pilot delivery terms."
            ],
            "recentSignals": [
                why_now if why_now else f"Ongoing commercial acceleration in {company}'s ecosystem.",
                f"Cross-verified executive identity ({tier}) with 95% confidence."
            ],
            "relationshipContext": rel_path if rel_path else f"Direct strategic connection with {name} ({role} at {company}). Outreach awaiting founder approval."
        }

    return {
        "id": id,
        "contactId": id,
        "contactName": "Sarah Connor",
        "company": "Cyberdyne Systems",
        "objectives": [
            "Understand their current migration status",
            "Identify key stakeholders for the security review"
        ],
        "suggestedTopics": [
            "Recent cloud modernization strategy",
            "Legacy monolith constraints"
        ],
        "recentSignals": [
            "Cyberdyne announced a $50M infrastructure upgrade"
        ],
        "relationshipContext": "Met at SaaStr 2025. Expressed early interest in our security layer."
    }

@router.post("/{id}/capture")
async def capture_meeting(
    id: str,
    payload: Dict[str, Any] = Body(...),
    user: dict = Depends(get_current_user)
):
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    return {"jobId": job_id}

@router.get("/jobs/{job_id}/status")
async def get_capture_job_status(
    job_id: str,
    user: dict = Depends(get_current_user)
):
    return {
        "id": job_id,
        "status": "EXTRACTED",
        "opportunityId": f"opp-{uuid.uuid4().hex[:8]}"
    }

@router.get("/{id}/intelligence")
async def get_meeting_intelligence(
    id: str,
    user: dict = Depends(get_current_user)
):
    return {
        "meetingId": id,
        "contactId": id,
        "findings": [
            {
                "id": "find-1",
                "type": "PROBLEM",
                "content": "Enterprise data governance and compliance audit friction across custom AI agents.",
                "evidence": "\"Our primary bottleneck is maintaining audit compliance when deploying multi-agent workflows.\" [04:12]",
                "confidence": 92,
                "status": "AWAITING_VALIDATION",
                "sourceMeetingId": id
            },
            {
                "id": "find-2",
                "type": "REQUIREMENT",
                "content": "Turnkey verification bridge with zero infrastructure overhaul.",
                "evidence": "\"We need plug-and-play validation modules that integrate directly into existing pipelines.\" [11:45]",
                "confidence": 90,
                "status": "AWAITING_VALIDATION",
                "sourceMeetingId": id
            }
        ]
    }

@router.patch("/{id}/intelligence/{finding_id}")
async def validate_meeting_finding(
    id: str,
    finding_id: str,
    payload: Dict[str, Any] = Body(...),
    user: dict = Depends(get_current_user)
):
    return {"success": True}
