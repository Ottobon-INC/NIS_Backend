import enum
from typing import Optional
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, synonym
from app.db.base import Base

class OpportunityStatus(str, enum.Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    SOLUTION_MATCHING = "SOLUTION_MATCHING"
    PATH_DEFINED = "PATH_DEFINED"
    PIPELINE = "PIPELINE"
    OUTCOME = "OUTCOME"

class OpportunityLifecycleStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    MATCH_REVIEW = "MATCH_REVIEW"
    QUALIFIED = "QUALIFIED"
    ACTIVE = "ACTIVE"
    WON = "WON"
    LOST = "LOST"
    REJECTED = "REJECTED"
    ON_HOLD = "ON_HOLD"
    EXPIRED = "EXPIRED"

class Opportunity(Base):
    __tablename__ = "opportunities"

    def __init__(self, **kwargs):
        # Allow person_id as alias for contact_id
        if "person_id" in kwargs and "contact_id" not in kwargs:
            kwargs["contact_id"] = kwargs.pop("person_id")
        elif "person_id" in kwargs:
            kwargs.pop("person_id")

        # Unmapped attributes for in-memory or backward compatibility
        self._person_name = kwargs.pop("person_name", None)
        self._relationship_id = kwargs.pop("relationship_id", None)
        self._source_meeting_id = kwargs.pop("source_meeting_id", None)
        self._outcome_status = kwargs.pop("outcome_status", None)
        self._outcome_notes = kwargs.pop("outcome_notes", None)

        # Allow selected_path as alias for delivery_path
        if "selected_path" in kwargs and "delivery_path" not in kwargs:
            kwargs["delivery_path"] = kwargs.pop("selected_path")

        kwargs.setdefault("status", OpportunityLifecycleStatus.DISCOVERED)
        super().__init__(**kwargs)

    # Database-backed columns matching PostgreSQL schema
    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True, default="ottobon")
    owner_user_id = Column(String, nullable=True)
    contact_id = Column(String, ForeignKey("contacts.id"), index=True, nullable=True)
    company_name = Column(String, nullable=False)
    company_id = Column(String, ForeignKey("company_profiles.id"), nullable=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    problem = Column(Text, nullable=False)
    requirement = Column(Text, nullable=False)
    opportunity_type = Column(String, default="ENTERPRISE_AI_PILOT")
    status = Column(
        SAEnum(
            OpportunityLifecycleStatus,
            native_enum=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            validate_strings=True,
            create_constraint=False,
        ),
        default=OpportunityLifecycleStatus.DISCOVERED,
        nullable=False,
        index=True,
    )
    confidence = Column(Integer, default=50)
    timeline = Column(String, nullable=True)
    budget_signal = Column(String, nullable=True)
    
    # Matching and routing
    matched_product_id = Column(String, ForeignKey("products.id"), nullable=True)
    matched_product_name = Column(String, nullable=True)
    match_score = Column(Integer, nullable=True)
    match_rationale = Column(Text, nullable=True)

    # Delivery path and selected capability/solution
    delivery_path = Column(String, nullable=True, index=True)  # INTERNAL, NETWORK, HYBRID
    selected_solution_id = Column(String, nullable=True)

    # Traceability & evidence
    supporting_evidence_ids = Column(JSON, default=list)
    trusted_context_ids = Column(JSON, default=list)
    review_notes = Column(Text, nullable=True)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    # Relationships
    contact = relationship("Contact", foreign_keys=[contact_id], lazy="selectin")

    # Synonym and unmapped compatibility properties
    person_id = synonym("contact_id")
    selected_path = synonym("delivery_path")

    @property
    def person_name(self) -> Optional[str]:
        if getattr(self, "_person_name", None):
            return self._person_name
        if hasattr(self, "contact") and self.contact and getattr(self.contact, "full_name", None):
            return self.contact.full_name
        return None

    @person_name.setter
    def person_name(self, val: Optional[str]):
        self._person_name = val

    @property
    def relationship_id(self) -> Optional[str]:
        return getattr(self, "_relationship_id", None)

    @relationship_id.setter
    def relationship_id(self, val: Optional[str]):
        self._relationship_id = val

    @property
    def source_meeting_id(self) -> Optional[str]:
        return getattr(self, "_source_meeting_id", None)

    @source_meeting_id.setter
    def source_meeting_id(self, val: Optional[str]):
        self._source_meeting_id = val

    @property
    def outcome_status(self) -> Optional[str]:
        return getattr(self, "_outcome_status", None)

    @outcome_status.setter
    def outcome_status(self, val: Optional[str]):
        self._outcome_status = val

    @property
    def outcome_notes(self) -> Optional[str]:
        return getattr(self, "_outcome_notes", None)

    @outcome_notes.setter
    def outcome_notes(self, val: Optional[str]):
        self._outcome_notes = val
