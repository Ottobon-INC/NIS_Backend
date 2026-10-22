from datetime import datetime
from typing import List, Optional, Any, Dict, Union
from pydantic import BaseModel, Field, model_validator


class MeetingCreateIn(BaseModel):
    title: str = Field(..., min_length=1, description="Title or topic of the meeting")
    contact_id: Optional[str] = Field(None, description="Contact ID associated with this meeting")
    meeting_date: Optional[datetime] = Field(None, description="Scheduled or actual meeting date")
    raw_transcript: Optional[str] = Field(None, description="Optional initial transcript or notes")
    objectives: Optional[List[str]] = Field(default_factory=list, description="Planned meeting objectives")
    suggested_topics: Optional[List[str]] = Field(default_factory=list, description="Suggested discussion topics")


class MeetingBriefOut(BaseModel):
    meetingId: str
    id: str
    contactId: Optional[str] = None
    contactName: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    meetingDate: Optional[str] = None
    objective: Optional[str] = None
    objectives: List[str] = Field(default_factory=list)
    talkingPoints: List[str] = Field(default_factory=list)
    suggestedTopics: List[str] = Field(default_factory=list)
    recentSignals: List[str] = Field(default_factory=list)
    relationshipContext: Optional[Union[str, Dict[str, Any]]] = None

    class Config:
        from_attributes = True


class MeetingCaptureIn(BaseModel):
    transcript: Optional[str] = Field(None, description="Raw conversation transcript")
    notes: Optional[str] = Field(None, description="Raw founder or meeting notes")
    audioUrl: Optional[str] = Field(None, description="Optional audio file URL for record keeping")


class MeetingCaptureOut(BaseModel):
    meetingId: str
    jobId: str
    status: str = "EXTRACTED"
    capturedAt: str
    extractedNeedsCount: int
    opportunityId: Optional[str] = None


class MeetingFindingOut(BaseModel):
    id: str
    type: str = "PROBLEM"
    claim: str
    content: str
    evidenceQuote: Optional[str] = None
    evidence: Optional[str] = None
    confidence: int = 80
    status: str = "AWAITING_VALIDATION"
    trustLevel: Optional[str] = None
    sourceMeetingId: str
    contactId: Optional[str] = None
    opportunityId: Optional[str] = None
    trustedContextId: Optional[str] = None
    validatedBy: Optional[str] = None
    validatedAt: Optional[str] = None

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        
        # Read from SQLAlchemy model attributes
        finding_id = getattr(data, "id", "")
        meeting_id = getattr(data, "meeting_id", "")
        contact_id = getattr(data, "contact_id", None)
        raw_type = getattr(data, "finding_type", "PROBLEM")
        ftype = raw_type.value if hasattr(raw_type, "value") else str(raw_type or "PROBLEM")
        
        claim_val = getattr(data, "claim", "") or getattr(data, "content", "")
        evidence_val = getattr(data, "evidence_quote", None) or getattr(data, "evidence", None)
        confidence_val = getattr(data, "confidence", 80)
        
        raw_status = getattr(data, "status", "AWAITING_VALIDATION")
        status_val = raw_status.value if hasattr(raw_status, "value") else str(raw_status or "AWAITING_VALIDATION")
        
        val_by = getattr(data, "validated_by", None)
        val_at_raw = getattr(data, "validated_at", None)
        val_at = val_at_raw.isoformat() if val_at_raw and hasattr(val_at_raw, "isoformat") else (str(val_at_raw) if val_at_raw else None)
        
        opp_id = getattr(data, "opportunity_id", None)
        tc_id = getattr(data, "trusted_context_id", None)

        trust_level = "CONFIRMED" if status_val in ("CONFIRMED", "EDITED") else "INFERENCE"

        return {
            "id": finding_id,
            "type": ftype,
            "claim": claim_val,
            "content": claim_val,
            "evidenceQuote": evidence_val,
            "evidence": evidence_val,
            "confidence": confidence_val,
            "status": status_val,
            "trustLevel": trust_level,
            "sourceMeetingId": meeting_id,
            "contactId": contact_id,
            "opportunityId": opp_id,
            "trustedContextId": tc_id,
            "validatedBy": val_by,
            "validatedAt": val_at,
        }


class MeetingIntelligenceOut(BaseModel):
    meetingId: str
    contactId: Optional[str] = None
    findings: List[MeetingFindingOut] = Field(default_factory=list)


class MeetingFindingValidationIn(BaseModel):
    status: str = Field(..., description="Validation status: CONFIRMED, REJECTED, or EDITED")
    content: Optional[str] = Field(None, description="Updated content if editing finding")
    newContent: Optional[str] = Field(None, description="Alias for content")
    correction_note: Optional[str] = Field(None, description="Audit reason for edit/confirmation")


class MeetingFindingValidationOut(BaseModel):
    success: bool = True
    finding: Optional[MeetingFindingOut] = None
    trustedContextId: Optional[str] = None
    opportunityId: Optional[str] = None


class MeetingItemOut(BaseModel):
    id: str
    organizationId: str
    title: str
    contactId: Optional[str] = None
    contactName: Optional[str] = None
    company: Optional[str] = None
    meetingDate: Optional[str] = None
    status: str
    summary: Optional[str] = None
    hasTranscript: bool = False
    findingsCount: int = 0
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def normalize_meeting(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data
        
        meeting_id = getattr(data, "id", "")
        org_id = getattr(data, "organization_id", "")
        title = getattr(data, "title", "")
        contact_id = getattr(data, "contact_id", None)
        
        contact = getattr(data, "contact", None)
        contact_name = contact.full_name if contact and hasattr(contact, "full_name") else None
        company = contact.current_company if contact and hasattr(contact, "current_company") else None
        
        m_date_raw = getattr(data, "meeting_date", None)
        m_date = m_date_raw.isoformat() if m_date_raw and hasattr(m_date_raw, "isoformat") else None
        
        status_raw = getattr(data, "status", "SCHEDULED")
        status_val = status_raw.value if hasattr(status_raw, "value") else str(status_raw or "SCHEDULED")
        
        summary = getattr(data, "summary", None)
        transcript = getattr(data, "raw_transcript", None)
        has_transcript = bool(transcript and transcript.strip())
        
        findings = getattr(data, "findings", None)
        findings_count = len(findings) if findings is not None else 0
        
        created_raw = getattr(data, "created_at", None)
        created_at = created_raw.isoformat() if created_raw and hasattr(created_raw, "isoformat") else None
        
        updated_raw = getattr(data, "updated_at", None)
        updated_at = updated_raw.isoformat() if updated_raw and hasattr(updated_raw, "isoformat") else None

        return {
            "id": meeting_id,
            "organizationId": org_id,
            "title": title,
            "contactId": contact_id,
            "contactName": contact_name,
            "company": company,
            "meetingDate": m_date,
            "status": status_val,
            "summary": summary,
            "hasTranscript": has_transcript,
            "findingsCount": findings_count,
            "createdAt": created_at,
            "updatedAt": updated_at,
        }
