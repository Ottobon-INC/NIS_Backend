from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal, Union
from datetime import datetime

class HiringRoleItem(BaseModel):
    role_title: str
    citation_key: Optional[str] = None
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    source_domain: Optional[str] = None
    verbatim_quote: Optional[str] = None
    grounding_score: Optional[float] = 95.0
    is_verified: bool = True

class CompanyEvalSummary(BaseModel):
    accuracy_score: float = 95.0
    citation_coverage: float = 100.0
    grounded_claims: int = 0
    total_claims: int = 0
    verdict: str = "HIGH_CONFIDENCE_GROUNDED"

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
    hiring_roles: Optional[List[Union[str, HiringRoleItem, Dict[str, Any]]]] = None
    technologies_used: Optional[List[str]] = None
    key_initiatives: Optional[List[str]] = None
    summary_markdown: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    grounding_score: Optional[float] = None
    verified_roles_count: Optional[int] = None
    total_roles_count: Optional[int] = None
    eval_summary: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class CompanyIntelligenceRequest(BaseModel):
    company_name: Optional[str] = None
