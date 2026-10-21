from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime, timezone
import uuid

from app.db.session import get_db
from app.api.dependencies import get_current_user

router = APIRouter()

@router.get("/{meeting_id}/brief")
async def get_meeting_brief(
    meeting_id: str,
    user: dict = Depends(get_current_user),
):
    """Returns the pre-meeting executive brief, strategic angles, and recommended talking points."""
    return {
        "meetingId": meeting_id,
        "contactName": "Rahul Dhamdhere",
        "title": "VP Engineering & Enterprise Architecture",
        "company": "Global Logistics Corp",
        "meetingDate": "2026-03-24T15:00:00Z",
        "objective": "Explore autonomous ABAP migration pilot for Q3 deliverables.",
        "talkingPoints": [
            "Acknowledge recent public modernization milestone at Global Logistics.",
            "Address specific technical bottleneck around custom SAP ECC table dependencies.",
            "Propose a 3-week sandbox proof-of-concept with zero production downtime."
        ],
        "relationshipContext": {
            "strength": 4,
            "connectedVia": "Bhanu (Alumni / Professional)",
            "lastInteraction": "SAP Summit 2024"
        }
    }


@router.post("/{meeting_id}/capture")
async def upload_meeting_notes(
    meeting_id: str,
    notes: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """Capture meeting raw transcript or founder notes to trigger AI intelligence extraction."""
    return {
        "meetingId": meeting_id,
        "status": "PROCESSING",
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "extractedNeedsCount": 3
    }


@router.get("/{meeting_id}/intelligence")
async def get_meeting_intelligence(
    meeting_id: str,
    user: dict = Depends(get_current_user),
):
    """Returns AI-extracted problems, requirements, and people findings awaiting founder review."""
    return {
        "meetingId": meeting_id,
        "findings": [
            {
                "id": "f-1",
                "type": "PROBLEM",
                "claim": "Team is struggling with legacy SAP ECC custom code regression.",
                "evidenceQuote": "'We have 200 custom ABAP programs with zero active documentation.'",
                "trustLevel": "INFERENCE"
            },
            {
                "id": "f-2",
                "type": "REQUIREMENT",
                "claim": "Target solution must run on-premise or in sovereign VPC.",
                "evidenceQuote": "'Data privacy policy forbids sending core ERP schemas outside EU boundary.'",
                "trustLevel": "CONFIRMED"
            }
        ]
    }
