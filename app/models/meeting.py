import enum
from sqlalchemy import Column, String, Integer, DateTime, Enum as SAEnum, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, synonym
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

class FindingStatus(str, enum.Enum):
    AWAITING_VALIDATION = "AWAITING_VALIDATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EDITED = "EDITED"

class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True, default="ottobon", nullable=False)
    title = Column(String, nullable=False)
    contact_id = Column(String, ForeignKey("contacts.id", ondelete="SET NULL"), index=True, nullable=True)
    meeting_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(
        SAEnum(
            MeetingStatus,
            native_enum=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            validate_strings=True,
            create_constraint=False,
        ),
        default=MeetingStatus.SCHEDULED,
        nullable=False,
        index=True,
    )
    
    # Meeting intelligence & preparation
    raw_transcript = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    objectives = Column(JSON, default=list)
    suggested_topics = Column(JSON, default=list)
    recent_signals = Column(JSON, default=list)
    relationship_context = Column(JSON, nullable=True)
    extracted_needs = Column(JSON, default=list)
    action_items = Column(JSON, default=list)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now(), nullable=False)

    # Relationships
    contact = relationship("Contact", foreign_keys=[contact_id], lazy="selectin")
    findings = relationship("MeetingFinding", back_populates="meeting", cascade="all, delete-orphan", lazy="selectin")


class MeetingFinding(Base):
    __tablename__ = "meeting_findings"

    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True, default="ottobon", nullable=False)
    meeting_id = Column(String, ForeignKey("meetings.id", ondelete="CASCADE"), index=True, nullable=False)
    contact_id = Column(String, ForeignKey("contacts.id", ondelete="SET NULL"), index=True, nullable=True)
    finding_type = Column(
        SAEnum(
            FindingType,
            native_enum=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            validate_strings=True,
            create_constraint=False,
        ),
        default=FindingType.PROBLEM,
        nullable=False,
        index=True,
    )
    claim = Column(Text, nullable=False)
    evidence_quote = Column(Text, nullable=True)
    confidence = Column(Integer, default=80, nullable=False)
    status = Column(
        SAEnum(
            FindingStatus,
            native_enum=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            validate_strings=True,
            create_constraint=False,
        ),
        default=FindingStatus.AWAITING_VALIDATION,
        nullable=False,
        index=True,
    )
    validated_by = Column(String, nullable=True)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    opportunity_id = Column(String, ForeignKey("opportunities.id", ondelete="SET NULL"), index=True, nullable=True)
    trusted_context_id = Column(String, ForeignKey("trusted_contexts.id", ondelete="SET NULL"), index=True, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now(), nullable=False)

    # Synonyms for frontend and service property mapping
    content = synonym("claim")
    evidence = synonym("evidence_quote")

    # Relationships
    meeting = relationship("Meeting", back_populates="findings")
    contact = relationship("Contact", foreign_keys=[contact_id], lazy="selectin")
    opportunity = relationship("Opportunity", foreign_keys=[opportunity_id], lazy="selectin")
    trusted_context = relationship("TrustedContext", foreign_keys=[trusted_context_id], lazy="selectin")
