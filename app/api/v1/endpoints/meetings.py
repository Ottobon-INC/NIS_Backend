from fastapi import APIRouter, Depends, HTTPException, Query, Body, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.services.meeting_service import MeetingService
from app.models.meeting import MeetingStatus
from app.schemas.meeting import (
    MeetingCreateIn,
    MeetingBriefOut,
    MeetingCaptureIn,
    MeetingCaptureOut,
    MeetingIntelligenceOut,
    MeetingFindingValidationIn,
    MeetingFindingValidationOut,
    MeetingItemOut,
)

router = APIRouter()


@router.post("", response_model=MeetingItemOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreateIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Creates a new meeting record scoped to the authenticated organization."""
    org_id = user.get("organization_id", "ottobon")
    meeting = await MeetingService.create_meeting(
        db=db,
        organization_id=org_id,
        payload=payload,
        user=user,
    )
    return MeetingItemOut.model_validate(meeting)


@router.get("", response_model=List[MeetingItemOut])
async def list_meetings(
    contact_id: Optional[str] = Query(None, description="Optional contact ID filter"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Lists all meetings for the authenticated organization."""
    org_id = user.get("organization_id", "ottobon")
    meetings = await MeetingService.list_meetings(
        db=db,
        organization_id=org_id,
        contact_id=contact_id,
    )
    return [MeetingItemOut.model_validate(m) for m in meetings]


@router.get("/jobs/{job_id}/status")
async def get_capture_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Checks the status of meeting intelligence extraction for the given meeting ID / job ID.
    Compatible with frontend CaptureStatus polling contract.
    """
    org_id = user.get("organization_id", "ottobon")
    meeting = await MeetingService.get_meeting_by_id(db, org_id, job_id)
    
    is_extracted = meeting.status in (MeetingStatus.ANALYZED, MeetingStatus.COMPLETED) or len(meeting.findings or []) > 0
    return {
        "id": job_id,
        "status": "EXTRACTED" if is_extracted else "PROCESSING",
        "opportunityId": meeting.findings[0].opportunity_id if meeting.findings and meeting.findings[0].opportunity_id else None,
    }


@router.get("/{meeting_id}", response_model=MeetingItemOut)
async def get_meeting(
    meeting_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Retrieves meeting metadata and preparation details."""
    org_id = user.get("organization_id", "ottobon")
    meeting = await MeetingService.get_meeting_by_id(db, org_id, meeting_id)
    return MeetingItemOut.model_validate(meeting)


@router.get("/{meeting_id}/brief", response_model=MeetingBriefOut)
async def get_meeting_brief(
    meeting_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Returns the pre-meeting executive brief, strategic angles, and recommended talking points."""
    org_id = user.get("organization_id", "ottobon")
    return await MeetingService.get_meeting_brief(
        db=db,
        organization_id=org_id,
        meeting_id=meeting_id,
    )


@router.post("/{meeting_id}/capture", response_model=MeetingCaptureOut)
async def upload_meeting_notes(
    meeting_id: str,
    notes: Optional[str] = Query(None, description="Optional notes query parameter"),
    payload: Optional[MeetingCaptureIn] = Body(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Capture meeting raw transcript or founder notes to trigger structured intelligence extraction.
    Accepts text via JSON body or notes query parameter.
    """
    org_id = user.get("organization_id", "ottobon")
    
    # Resolve transcript text from body or query
    transcript_text = None
    if payload:
        transcript_text = payload.transcript or payload.notes
    if not transcript_text and notes:
        transcript_text = notes

    if not transcript_text or not transcript_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Transcript or notes must be provided"
        )

    return await MeetingService.capture_meeting_notes(
        db=db,
        organization_id=org_id,
        meeting_id=meeting_id,
        transcript_text=transcript_text,
        user=user,
    )


@router.get("/{meeting_id}/intelligence", response_model=MeetingIntelligenceOut)
async def get_meeting_intelligence(
    meeting_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Returns AI-extracted candidate problems, requirements, and people findings awaiting founder review."""
    org_id = user.get("organization_id", "ottobon")
    return await MeetingService.get_meeting_intelligence(
        db=db,
        organization_id=org_id,
        meeting_id=meeting_id,
    )


@router.patch("/{meeting_id}/intelligence/{finding_id}", response_model=MeetingFindingValidationOut)
async def validate_finding(
    meeting_id: str,
    finding_id: str,
    payload: MeetingFindingValidationIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Validates, edits, confirms, or rejects a candidate meeting finding.
    Confirmed/edited findings are automatically propagated to Trusted Context and the Opportunity Engine.
    """
    org_id = user.get("organization_id", "ottobon")
    return await MeetingService.validate_finding(
        db=db,
        organization_id=org_id,
        meeting_id=meeting_id,
        finding_id=finding_id,
        payload=payload,
        user=user,
    )
