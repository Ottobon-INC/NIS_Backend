import enum
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum, Integer, Boolean, Date, Text
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

    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True)

    # --- Role discriminator ---
    # TARGET = person being researched (VP John)
    # BHANU_CONNECTION = person from Bhanu's LinkedIn CSV
    contact_type = Column(String, default=ContactType.TARGET, nullable=False, index=True)

    # --- Core identity (shared by both types) ---
    first_name = Column(String)
    last_name = Column(String)
    full_name = Column(String)
    current_title = Column(String)
    current_company = Column(String)
    company_website = Column(String)        # for TARGET: scraped company site
    email = Column(String)
    phone = Column(String)
    location = Column(String)
    profile_url = Column(String)            # LinkedIn URL (quick access; also in external_identities)
    profile_image_url = Column(String)

    # --- Research pipeline status (TARGET only) ---
    status = Column(Enum(ContactStatus), default=ContactStatus.NEW)

    # --- Intelligence card review (TARGET only) ---
    # Lifecycle: PROCESSING → DRAFT → REVIEWED → ACTIONABLE | ARCHIVED
    card_status = Column(String, default=CardStatus.PROCESSING)
    admin_notes = Column(Text)
    reviewed_by = Column(String)            # admin user id who last reviewed
    founder_reviewed = Column(Boolean, default=False)
    founder_notes = Column(Text)
    founder_reviewed_at = Column(DateTime(timezone=True))

    # --- Route (TARGET only) ---
    best_route = Column(JSONB)

    # --- Bhanu's relationship context (BHANU_CONNECTION only) ---
    # 1=Met once, 2=Acquaintance, 3=Professional colleague,
    # 4=Trusted contact, 5=Close friend
    relationship_strength = Column(Integer)             # 1–5
    reachability = Column(String)                       # HIGH | MEDIUM | LOW | UNKNOWN
    best_channel = Column(String)                       # EMAIL | LINKEDIN | WHATSAPP | PHONE
    relationship_notes = Column(Text)                   # "Met at SAP Summit 2022"
    connected_since = Column(Date)                      # "Connected On" from LinkedIn CSV
    is_scored = Column(Boolean, default=False, index=True)  # has admin scored this yet?
    import_batch_id = Column(String, index=True)        # which CSV upload session
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    id = Column(String, primary_key=True, index=True)
    contact_id = Column(String, ForeignKey("contacts.id"))
    provider = Column(String)
    identifier_type = Column(String)
    identifier = Column(String, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DeletedContact(Base):
    __tablename__ = "deleted_contacts"
    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True)
    contact_id = Column(String, nullable=True)
    name = Column(String, nullable=False)
    deleted_at = Column(DateTime(timezone=True), server_default=func.now())

