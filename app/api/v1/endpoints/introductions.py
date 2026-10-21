from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime, timezone
import uuid

from app.db.session import get_db
from app.api.dependencies import get_current_user

router = APIRouter()

DEFAULT_INTROS = [
    {
        "id": "draft-01",
        "opportunityId": "opp-sap-migration-01",
        "targetName": "Rahul Dhamdhere",
        "targetTitle": "VP Engineering",
        "targetCompany": "Global Logistics Corp",
        "connectorName": "Bhanu (Founder)",
        "channel": "EMAIL",
        "subject": "Quick intro / Autonomous SAP Migration discussion",
        "body": "Hi Rahul,\n\nFollowing up on our exchange at the Summit, I wanted to reconnect regarding the ABAP custom workflow modernization challenges you mentioned. We've developed an agentic translation pipeline specifically designed to de-risk S/4HANA migrations with zero downtime.\n\nWould you have 15 minutes next Tuesday to review how we've benchmarked this?\n\nBest,\nBhanu",
        "tone": "warm_professional",
        "status": "DRAFTED",
        "createdAt": "2026-03-20T10:00:00Z"
    }
]

@router.get("/drafts")
async def list_introduction_drafts(
    user: dict = Depends(get_current_user),
):
    """List pending introduction drafts awaiting founder review."""
    return {"drafts": DEFAULT_INTROS}


@router.get("/drafts/{draft_id}")
async def get_introduction_draft(
    draft_id: str,
    user: dict = Depends(get_current_user),
):
    """Retrieve introduction draft detail."""
    for d in DEFAULT_INTROS:
        if d["id"] == draft_id:
            return d
    return DEFAULT_INTROS[0]


@router.patch("/drafts/{draft_id}/approve")
async def approve_introduction_draft(
    draft_id: str,
    payload: Optional[dict] = None,
    user: dict = Depends(get_current_user),
):
    """Founder action: explicitly approve the calibrated introduction message."""
    return {
        "success": True, 
        "draft_id": draft_id, 
        "status": "APPROVED",
        "approvedAt": datetime.now(timezone.utc).isoformat()
    }


@router.post("/drafts/{draft_id}/send")
async def dispatch_introduction(
    draft_id: str,
    user: dict = Depends(get_current_user),
):
    """Dispatch introduction via selected channel (Email, LinkedIn, WhatsApp)."""
    return {
        "success": True,
        "draft_id": draft_id,
        "status": "DISPATCHED",
        "dispatchedAt": datetime.now(timezone.utc).isoformat()
    }
