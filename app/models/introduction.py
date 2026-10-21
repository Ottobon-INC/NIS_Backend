import enum
from sqlalchemy import Column, String, DateTime, Enum, Text, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base

class IntroStatus(str, enum.Enum):
    DRAFTED = "DRAFTED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    DISPATCHED = "DISPATCHED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"

class IntroductionDraft(Base):
    __tablename__ = "introduction_drafts"

    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True, default="ottobon")
    opportunity_id = Column(String, ForeignKey("opportunities.id"), index=True, nullable=True)
    target_contact_id = Column(String, ForeignKey("contacts.id"), index=True)
    connector_contact_id = Column(String, ForeignKey("contacts.id"), index=True, nullable=True)
    
    channel = Column(String, default="EMAIL")  # EMAIL, LINKEDIN, WHATSAPP
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=False)
    status = Column(Enum(IntroStatus), default=IntroStatus.DRAFTED)
    
    tone = Column(String, default="warm_professional")
    founder_notes = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    outcome_feedback = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
