import enum
from sqlalchemy import Column, String, Integer, DateTime, Enum, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base

class MeetingStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    ANALYZED = "ANALYZED"

class FindingType(str, enum.Enum):
    PROBLEM = "PROBLEM"
    REQUIREMENT = "REQUIREMENT"
    PEOPLE = "PEOPLE"
    SIGNAL = "SIGNAL"

class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True, default="ottobon")
    title = Column(String, nullable=False)
    contact_id = Column(String, ForeignKey("contacts.id"), index=True)
    meeting_date = Column(DateTime(timezone=True))
    status = Column(Enum(MeetingStatus), default=MeetingStatus.SCHEDULED)
    
    # Meeting intelligence
    raw_transcript = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    extracted_needs = Column(JSONB, default=list)
    action_items = Column(JSONB, default=list)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class MeetingFinding(Base):
    __tablename__ = "meeting_findings"

    id = Column(String, primary_key=True, index=True)
    meeting_id = Column(String, ForeignKey("meetings.id"), index=True)
    finding_type = Column(Enum(FindingType), default=FindingType.PROBLEM)
    claim = Column(Text, nullable=False)
    evidence_quote = Column(Text, nullable=True)
    is_confirmed = Column(String, default="INFERENCE")  # INFERENCE, CONFIRMED, DISMISSED
    created_at = Column(DateTime(timezone=True), server_default=func.now())
