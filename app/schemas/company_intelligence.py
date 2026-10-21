from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime

class CompanyIntelligenceOut(BaseModel):
    id: str
    contact_id: Optional[str] = None
    company_name: str
    website: Optional[str] = None
    industry: Optional[str] = None
    overview: Optional[str] = None
    what_they_implemented: Optional[str] = None
    is_hiring: bool = False
    hiring_status: str = "UNKNOWN"
    hiring_roles: Optional[List[str]] = None
    technologies_used: Optional[List[str]] = None
    key_initiatives: Optional[List[str]] = None
    summary_markdown: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class CompanyIntelligenceRequest(BaseModel):
    company_name: Optional[str] = None
