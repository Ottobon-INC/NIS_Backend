import enum
from sqlalchemy import Column, String, Integer, DateTime, Enum, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base

class OpportunityStatus(str, enum.Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    SOLUTION_MATCHING = "SOLUTION_MATCHING"
    PATH_DEFINED = "PATH_DEFINED"
    PIPELINE = "PIPELINE"
    OUTCOME = "OUTCOME"

class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True, default="ottobon")
    title = Column(String, nullable=False)
    person_id = Column(String, ForeignKey("contacts.id"), index=True, nullable=True)
    person_name = Column(String)
    company_id = Column(String, nullable=True)
    company_name = Column(String)
    relationship_id = Column(String, nullable=True)
    source_meeting_id = Column(String, nullable=True)
    trusted_context_ids = Column(JSONB, default=list)
    problem = Column(Text)
    requirement = Column(Text)
    timeline = Column(String, nullable=True)
    budget_signal = Column(String, nullable=True)
    opportunity_type = Column(String, default="ENTERPRISE_AI_PILOT")
    confidence = Column(Integer, default=85)
    status = Column(Enum(OpportunityStatus), default=OpportunityStatus.CANDIDATE, index=True)
    
    # Matching and routing
    selected_path = Column(String, nullable=True)  # INTERNAL, NETWORK, HYBRID
    selected_solution_id = Column(String, nullable=True)
    outcome_status = Column(String, nullable=True)
    outcome_notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
