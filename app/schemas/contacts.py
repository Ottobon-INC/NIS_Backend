from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.models.identity import ContactStatus

class ContactCreateURL(BaseModel):
    linkedin_url: str

class ContactUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    current_title: Optional[str] = None
    current_company: Optional[str] = None

class ContactInDB(BaseModel):
    id: str
    organization_id: str
    name: Optional[str] = None
    full_name: Optional[str] = None
    title: Optional[str] = None
    current_title: Optional[str] = None
    company: Optional[str] = None
    current_company: Optional[str] = None
    profile_url: Optional[str] = None
    status: ContactStatus
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ContactOverviewSchema(BaseModel):
    id: str
    name: str
    full_name: Optional[str] = None
    title: str
    current_title: Optional[str] = None
    company: str
    current_company: Optional[str] = None
    profile_url: Optional[str] = None
    status: str
    contact_type: Optional[str] = None
    lastUpdated: str

class Contact360(BaseModel):
    contact: ContactInDB
    identities: List[dict] = []
    research_runs: List[dict] = []
