from sqlalchemy import Column, String, DateTime, ForeignKey, Enum
from sqlalchemy.sql import func
from app.db.base import Base
import enum

class ContactStatus(str, enum.Enum):
    NEW = "NEW"
    RESEARCHING = "RESEARCHING"
    READY = "READY"

class Contact(Base):
    __tablename__ = "contacts"
    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True)
    first_name = Column(String)
    last_name = Column(String)
    full_name = Column(String)
    current_title = Column(String)
    current_company = Column(String)
    email = Column(String)
    phone = Column(String)
    location = Column(String)
    profile_url = Column(String)
    profile_image_url = Column(String)
    status = Column(Enum(ContactStatus), default=ContactStatus.NEW)
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
