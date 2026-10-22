"""
Pydantic Schemas for Trusted Context Domain.
1:1 compatible with Frontend TrustedContext TypeScript interfaces while providing
robust backend validation, multi-version historical tracking, and founder confirmation metadata.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict, model_validator


class TrustedContextVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    version: int
    content: str
    timestamp: str
    updatedBy: Optional[str] = None
    correctionNote: Optional[str] = None


class TrustedContextItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    contactId: str
    type: str = "PROBLEM"
    currentVersion: int = 1
    content: str
    evidence: str = ""
    evidenceId: Optional[str] = None
    sourceMeetingId: str = ""
    history: List[TrustedContextVersionOut] = Field(default_factory=list)
    isConfirmed: bool = True
    confirmedBy: Optional[str] = None
    confirmedAt: Optional[str] = None
    confidence: int = 100
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if data is None:
            return data
        is_orm = hasattr(data, "__dict__") or not isinstance(data, dict)

        def get_v(attr: str, dict_keys: List[str], default: Any = None) -> Any:
            if is_orm:
                val = getattr(data, attr, None)
                if val is not None:
                    return val
                for k in dict_keys:
                    val = getattr(data, k, None)
                    if val is not None:
                        return val
                return default
            else:
                for k in dict_keys:
                    if k in data and data[k] is not None:
                        return data[k]
                return default

        c_at = get_v("created_at", ["created_at", "createdAt"])
        u_at = get_v("updated_at", ["updated_at", "updatedAt"])
        conf_at = get_v("confirmed_at", ["confirmed_at", "confirmedAt"])

        c_at_str = c_at.isoformat() if isinstance(c_at, datetime) else (str(c_at) if c_at else None)
        u_at_str = u_at.isoformat() if isinstance(u_at, datetime) else (str(u_at) if u_at else None)
        conf_at_str = conf_at.isoformat() if isinstance(conf_at, datetime) else (str(conf_at) if conf_at else None)

        raw_history = get_v("history", ["history"], [])
        norm_history = []
        if isinstance(raw_history, list):
            for h in raw_history:
                if isinstance(h, dict):
                    ts = h.get("timestamp")
                    if isinstance(ts, datetime):
                        ts = ts.isoformat()
                    norm_history.append({
                        "version": h.get("version", 1),
                        "content": h.get("content", ""),
                        "timestamp": str(ts or ""),
                        "updatedBy": h.get("updated_by") or h.get("updatedBy"),
                        "correctionNote": h.get("correction_note") or h.get("correctionNote"),
                    })

        return {
            "id": str(get_v("id", ["id"], "")),
            "contactId": str(get_v("contact_id", ["contact_id", "contactId"], "")),
            "type": str(get_v("type", ["type"], "PROBLEM")).upper(),
            "currentVersion": int(get_v("current_version", ["current_version", "currentVersion"], 1)),
            "content": str(get_v("content", ["content"], "")),
            "evidence": str(get_v("evidence", ["evidence"], "") or ""),
            "evidenceId": get_v("evidence_id", ["evidence_id", "evidenceId"]),
            "sourceMeetingId": str(get_v("source_meeting_id", ["source_meeting_id", "sourceMeetingId"], "") or ""),
            "history": norm_history,
            "isConfirmed": bool(get_v("is_confirmed", ["is_confirmed", "isConfirmed"], True)),
            "confirmedBy": get_v("confirmed_by", ["confirmed_by", "confirmedBy"]),
            "confirmedAt": conf_at_str,
            "confidence": int(get_v("confidence", ["confidence"], 100)),
            "createdAt": c_at_str,
            "updatedAt": u_at_str,
        }


class TrustedContextListResponse(BaseModel):
    items: List[TrustedContextItemOut]
    total: int


class TrustedContextCreateIn(BaseModel):
    contact_id: Optional[str] = Field(default=None, description="Associated Contact ID")
    type: str = Field(default="PROBLEM", description="Context category (PROBLEM, REQUIREMENT, PERSON, SIGNAL)")
    content: str = Field(..., min_length=3, description="Verified ground truth claim or insight")
    evidence: Optional[str] = Field(default=None, description="Direct supporting citation or excerpt")
    evidence_id: Optional[str] = Field(default=None, description="Linked Evidence record ID")
    source_meeting_id: Optional[str] = Field(default=None, description="Linked meeting ID")
    confidence: Optional[int] = Field(default=100, ge=0, le=100)
    is_confirmed: Optional[bool] = Field(default=True, description="Founder-confirmed flag")


class TrustedContextUpdateIn(BaseModel):
    content: str = Field(..., min_length=1, description="Updated or corrected context statement")
    evidence: Optional[str] = Field(default=None, description="Optional updated supporting evidence")
    correction_note: Optional[str] = Field(default=None, description="Reason for correction or audit note")


class TrustedContextUpdateResponse(BaseModel):
    success: bool = True
    item: Optional[TrustedContextItemOut] = None
    message: Optional[str] = None
