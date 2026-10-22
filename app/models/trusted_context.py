"""
Trusted Context SQLAlchemy Model.
NetworkOS Module: Founder-Confirmed Intelligence & Verified Ground Truth.

Represents immutable/versioned ground truth that has passed founder validation
to serve as the bedrock for Opportunity Engine, Capability Matching, and Network Introductions.
"""

import enum
from typing import Optional, List, Dict, Any
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Boolean, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class TrustedContextType(str, enum.Enum):
    PROBLEM = "PROBLEM"
    REQUIREMENT = "REQUIREMENT"
    PERSON = "PERSON"
    SIGNAL = "SIGNAL"


class TrustedContext(Base):
    __tablename__ = "trusted_contexts"

    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True, default="ottobon", nullable=False)
    contact_id = Column(String, ForeignKey("contacts.id", ondelete="CASCADE"), index=True, nullable=False)
    type = Column(String, default="PROBLEM", nullable=False, index=True)
    content = Column(Text, nullable=False)
    evidence = Column(Text, nullable=True)
    evidence_id = Column(String, nullable=True)
    source_meeting_id = Column(String, nullable=True)
    current_version = Column(Integer, default=1, nullable=False)
    history = Column(JSON, default=list, nullable=False)

    # Provenance and founder confirmation
    is_confirmed = Column(Boolean, default=True, nullable=False)
    confirmed_by = Column(String, nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    confidence = Column(Integer, default=100, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationship
    contact = relationship("Contact", foreign_keys=[contact_id], lazy="selectin")
