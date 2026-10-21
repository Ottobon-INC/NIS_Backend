from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
from app.models.research import SourcePriority, SourceStatus

class OpportunityStatus(str, Enum):
    HYPOTHESIS = "HYPOTHESIS"
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    ON_HOLD = "ON_HOLD"
    # Backward compatibility aliases
    PROPOSED_INTERNALLY = "PROPOSED_INTERNALLY"
    UNCERTAIN_IDENTITY = "UNCERTAIN_IDENTITY"


class ResearchSourceBase(BaseModel):
    name: str
    source_type: str
    priority: SourcePriority
    status: SourceStatus
    provider_type: str
    description: Optional[str] = None
    supported_entity_types: Optional[List[str]] = []
    supported_intelligence_types: Optional[List[str]] = []
    reliability_score: int = 50
    requires_api_key: bool = False
    requires_paid_license: bool = False

class ResearchSourceCreate(ResearchSourceBase):
    id: str

class ResearchSourceUpdate(BaseModel):
    status: Optional[SourceStatus] = None
    priority: Optional[SourcePriority] = None

class ResearchSourceInDB(ResearchSourceBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class ResearchJobCreate(BaseModel):
    linkedin_url: str = Field(..., description="LinkedIn profile URL to research")

class ResearchJobCreatedOut(BaseModel):
    job_id: str
    contact_id: str
    status: str
    message: str

class ProviderTaskSummary(BaseModel):
    task_id: str
    source_id: str
    source_name: str
    status: str
    target_query: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class ResearchJobStatusOut(BaseModel):
    job_id: str
    contact_id: Optional[str] = None
    status: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    pending_tasks: int
    records_discovered: int
    active_providers: List[str]
    completed_providers: List[str]
    failed_providers: List[Dict[str, str]]
    tasks: List[ProviderTaskSummary]

class SourceItemResult(BaseModel):
    source_id: str
    source_name: str
    status: str
    query: Optional[str] = None
    reference: Optional[str] = None
    records_count: int = 0
    snippet: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    identity_match_status: Optional[str] = None
    identity_match_confidence: Optional[int] = None

class ResearchJobSourcesOut(BaseModel):
    job_id: str
    total_sources: int
    sources: List[SourceItemResult]

class EvidenceItemOut(BaseModel):
    id: str
    claim: str
    evidence_type: str
    source_id: str
    source_reference: Optional[str] = None
    confidence: int
    retrieved_date: Optional[datetime] = None

class ResearchJobReportOut(BaseModel):
    job_id: str
    contact_id: str
    name: str
    title: str
    company: str
    full_markdown_report: str
    commercial_intelligence: Optional[Dict[str, Any]] = None
    evidence: List[EvidenceItemOut] = []
    sources_used: List[Dict[str, Any]] = []
    pipeline_stage: str

class EvidenceDetailOut(BaseModel):
    id: str
    contact_id: str
    claim: str
    evidence_type: str
    confidence: int
    identity_match_status: Optional[str] = None
    identity_match_confidence: Optional[int] = None
    identity_match_rationale: Optional[str] = None
    source_id: str
    source_name: str
    source_url: Optional[str] = None
    source_result_id: Optional[str] = None
    excerpt: Optional[str] = None
    publication_date: Optional[datetime] = None
    retrieved_date: Optional[datetime] = None

class OpportunityValidationIn(BaseModel):
    status: OpportunityStatus
    review_notes: Optional[str] = None
    confirmed_problem: Optional[str] = None
    confirmed_solution: Optional[str] = None

class OpportunityValidationOut(BaseModel):
    contact_id: str
    status: OpportunityStatus
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    can_validate: bool = True
    identity_gate_passed: bool = True
    identity_confidence: int = 0
    business_problem: Optional[str] = None
    capability_match: Optional[str] = None
    supporting_evidence_ids: List[str] = []
    assumptions: List[str] = []
    missing_information: List[str] = []
    observed_facts: List[str] = []
    inferred_pain_points: List[str] = []
