import enum
from typing import Optional, Any, Dict
from datetime import datetime, date
from sqlalchemy import String, DateTime, ForeignKey, Enum, Integer, Boolean, Date, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class ContactStatus(str, enum.Enum):
    NEW = "NEW"
    RESEARCHING = "RESEARCHING"
    READY = "READY"


class ContactType(str, enum.Enum):
    TARGET = "TARGET"               # A person admin is researching (VP John)
    BHANU_CONNECTION = "BHANU_CONNECTION"  # Someone from Bhanu's LinkedIn CSV


class CardStatus(str, enum.Enum):
    PROCESSING = "PROCESSING"   # scraping/analysis in progress
    DRAFT = "DRAFT"             # intelligence ready, not yet reviewed
    REVIEWED = "REVIEWED"       # admin has reviewed it
    ACTIONABLE = "ACTIONABLE"   # marked as worth pursuing
    ARCHIVED = "ARCHIVED"       # no longer relevant


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)

    # --- Role discriminator ---
    # TARGET = person being researched (VP John)
    # BHANU_CONNECTION = person from Bhanu's LinkedIn CSV
    contact_type: Mapped[str] = mapped_column(String, default=ContactType.TARGET, nullable=False, index=True)

    # --- Core identity (shared by both types) ---
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    current_title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    current_company: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    company_website: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    profile_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    profile_image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # --- Research pipeline status (TARGET only) ---
    status: Mapped[ContactStatus] = mapped_column(Enum(ContactStatus), default=ContactStatus.NEW, nullable=False)

    # --- Intelligence card review (TARGET only) ---
    # Lifecycle: PROCESSING → DRAFT → REVIEWED → ACTIONABLE | ARCHIVED
    card_status: Mapped[str] = mapped_column(String, default=CardStatus.PROCESSING, nullable=False)
    admin_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    founder_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    founder_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    founder_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Route (TARGET only) ---
    # Stores the best matched route as JSONB — sufficient for V1 single-hop routing.
    # Shape: { "route_type": "COMPANY_MATCH", "via_contact_id": "abc",
    #          "via_name": "Priya Sharma", "via_title": "VP Ops",
    #          "via_company": "Global Logistics", "confidence": 0.85,
    #          "reasoning": "Works in same division as target" }
    best_route: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # --- Bhanu's relationship context (BHANU_CONNECTION only) ---
    # 1=Met once, 2=Acquaintance, 3=Professional colleague,
    # 4=Trusted contact, 5=Close friend
    relationship_strength: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reachability: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    best_channel: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    relationship_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    connected_since: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_scored: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    import_batch_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    contact_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("contacts.id"), nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    identifier_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    identifier: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
