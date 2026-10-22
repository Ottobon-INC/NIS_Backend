from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, model_validator
from app.models.opportunity import OpportunityLifecycleStatus

# ==============================================================================
# Explicit Status Compatibility Mapping
# ==============================================================================
# The backend lifecycle defines 10 states (DISCOVERED, SOURCE_VERIFIED, MATCH_REVIEW,
# QUALIFIED, ACTIVE, WON, LOST, REJECTED, ON_HOLD, EXPIRED).
# The frontend UI (OpportunityWorkspace & OpportunityDetailWorkspace) operates on:
# CANDIDATE, VALIDATED, SOLUTION_MATCHING, PATH_DEFINED, PIPELINE, OUTCOME.
#
# These bi-directional mappings guarantee zero silent status mismatches.
# ==============================================================================

BACKEND_TO_FRONTEND_STATUS: Dict[OpportunityLifecycleStatus, str] = {
    OpportunityLifecycleStatus.DISCOVERED: "CANDIDATE",
    OpportunityLifecycleStatus.SOURCE_VERIFIED: "CANDIDATE",
    OpportunityLifecycleStatus.MATCH_REVIEW: "CANDIDATE",
    OpportunityLifecycleStatus.QUALIFIED: "VALIDATED",
    OpportunityLifecycleStatus.ACTIVE: "PIPELINE",
    OpportunityLifecycleStatus.WON: "OUTCOME",
    OpportunityLifecycleStatus.LOST: "OUTCOME",
    OpportunityLifecycleStatus.REJECTED: "REJECTED",
    OpportunityLifecycleStatus.ON_HOLD: "ON_HOLD",
    OpportunityLifecycleStatus.EXPIRED: "EXPIRED",
}

FRONTEND_TO_BACKEND_STATUS: Dict[str, OpportunityLifecycleStatus] = {
    # Frontend aliases
    "CANDIDATE": OpportunityLifecycleStatus.DISCOVERED,
    "VALIDATED": OpportunityLifecycleStatus.QUALIFIED,
    "SOLUTION_MATCHING": OpportunityLifecycleStatus.MATCH_REVIEW,
    "PATH_DEFINED": OpportunityLifecycleStatus.QUALIFIED,
    "PIPELINE": OpportunityLifecycleStatus.ACTIVE,
    "OUTCOME": OpportunityLifecycleStatus.WON,
    # Direct backend names accepted interchangeably
    "DISCOVERED": OpportunityLifecycleStatus.DISCOVERED,
    "SOURCE_VERIFIED": OpportunityLifecycleStatus.SOURCE_VERIFIED,
    "MATCH_REVIEW": OpportunityLifecycleStatus.MATCH_REVIEW,
    "QUALIFIED": OpportunityLifecycleStatus.QUALIFIED,
    "ACTIVE": OpportunityLifecycleStatus.ACTIVE,
    "WON": OpportunityLifecycleStatus.WON,
    "LOST": OpportunityLifecycleStatus.LOST,
    "REJECTED": OpportunityLifecycleStatus.REJECTED,
    "ON_HOLD": OpportunityLifecycleStatus.ON_HOLD,
    "EXPIRED": OpportunityLifecycleStatus.EXPIRED,
}

def to_frontend_status(status_val: Any) -> str:
    """Safely converts backend enum or string to frontend OpportunityStatus."""
    if isinstance(status_val, OpportunityLifecycleStatus):
        return BACKEND_TO_FRONTEND_STATUS.get(status_val, "CANDIDATE")
    if isinstance(status_val, str):
        # Check if already a known frontend status
        if status_val in FRONTEND_TO_BACKEND_STATUS:
            be_enum = FRONTEND_TO_BACKEND_STATUS[status_val]
            return BACKEND_TO_FRONTEND_STATUS.get(be_enum, status_val)
    return "CANDIDATE"

def to_backend_status(status_str: str) -> OpportunityLifecycleStatus:
    """Safely converts frontend or backend status string to canonical OpportunityLifecycleStatus enum."""
    cleaned = (status_str or "").strip().upper()
    if cleaned in FRONTEND_TO_BACKEND_STATUS:
        return FRONTEND_TO_BACKEND_STATUS[cleaned]
    raise ValueError(
        f"Invalid status '{status_str}'. Allowed values: {sorted(list(FRONTEND_TO_BACKEND_STATUS.keys()))}"
    )


def _normalize_opportunity_input(data: Any) -> Any:
    """
    Normalizes an incoming SQLAlchemy model or dictionary into a clean dictionary
    compatible with both OpportunityOut and OpportunityDetailOut.
    """
    if data is None:
        return data

    is_orm = hasattr(data, "__dict__") or not isinstance(data, dict)

    def get_val(orm_attr: str, dict_keys: List[str], default: Any = None) -> Any:
        if is_orm:
            val = getattr(data, orm_attr, None)
            if val is not None:
                return val
            for dk in dict_keys:
                val = getattr(data, dk, None)
                if val is not None:
                    return val
            return default
        else:
            for dk in dict_keys:
                if dk in data and data[dk] is not None:
                    return data[dk]
            return default

    # Entity identifiers
    opp_id = get_val("id", ["id"], "")
    title = get_val("title", ["title"], "")
    contact_id = get_val("contact_id", ["contact_id", "personId", "person_id"], "")
    company_id = get_val("company_id", ["company_id", "companyId"], "")
    company_name = get_val("company_name", ["company_name", "companyName"], "")

    # Person Name resolution
    contact_obj = getattr(data, "contact", None) if is_orm else None
    person_name = ""
    if contact_obj and getattr(contact_obj, "full_name", None):
        person_name = contact_obj.full_name
    else:
        person_name = get_val(
            "person_name",
            ["personName", "person_name", "contact_name"],
            f"{company_name} Executive" if company_name else "Target Executive"
        )

    # Dates to ISO string
    c_at = get_val("created_at", ["created_at", "createdAt"])
    u_at = get_val("updated_at", ["updated_at", "updatedAt"])
    r_at = get_val("reviewed_at", ["reviewed_at", "reviewedAt"])
    v_until = get_val("valid_until", ["valid_until", "validUntil"])

    c_at_str = c_at.isoformat() if isinstance(c_at, datetime) else str(c_at or datetime.now(timezone.utc).isoformat())
    u_at_str = u_at.isoformat() if isinstance(u_at, datetime) else str(u_at or datetime.now(timezone.utc).isoformat())
    r_at_str = r_at.isoformat() if isinstance(r_at, datetime) else (str(r_at) if r_at else None)
    v_until_str = v_until.isoformat() if isinstance(v_until, datetime) else (str(v_until) if v_until else None)

    # Status resolution
    raw_status = get_val("status", ["status", "lifecycle_status", "lifecycleStatus"])
    fe_status = to_frontend_status(raw_status)
    be_status = None
    if isinstance(raw_status, OpportunityLifecycleStatus):
        be_status = raw_status
    elif isinstance(raw_status, str):
        try:
            be_status = to_backend_status(raw_status)
        except ValueError:
            be_status = OpportunityLifecycleStatus.DISCOVERED

    # Array fields
    raw_tc_ids = get_val("trusted_context_ids", ["trusted_context_ids", "trustedContextIds"], [])
    raw_ev_ids = get_val("supporting_evidence_ids", ["supporting_evidence_ids", "supportingEvidenceIds"], [])
    clean_ev_ids = [str(x) for x in (raw_ev_ids if isinstance(raw_ev_ids, list) else [])]

    # Process linked scraped jobs
    raw_jobs = get_val("scraped_jobs", ["scraped_jobs", "scrapedJobs"], []) or []
    scraped_jobs_list = []
    for j in raw_jobs:
        if hasattr(j, "apply_url"):
            j_apply = j.apply_url
            j_id = getattr(j, "id", "")
            j_src = getattr(j, "source", "")
            j_ext = getattr(j, "external_id", "")
            j_canon = getattr(j, "canonical_apply_url", None)
            j_loc = getattr(j, "location", None)
            j_sal = getattr(j, "salary", None)
            j_stat = getattr(j, "status", None)
            j_pub = getattr(j, "published_at", None)
            j_pub_str = j_pub.isoformat() if isinstance(j_pub, datetime) else (str(j_pub) if j_pub else None)
        elif isinstance(j, dict):
            j_apply = j.get("apply_url") or j.get("applyUrl") or ""
            j_id = j.get("id", "")
            j_src = j.get("source", "")
            j_ext = j.get("external_id") or j.get("externalId") or ""
            j_canon = j.get("canonical_apply_url") or j.get("canonicalApplyUrl")
            j_loc = j.get("location")
            j_sal = j.get("salary")
            j_stat = j.get("status")
            j_pub = j.get("published_at") or j.get("publishedAt")
            j_pub_str = str(j_pub) if j_pub else None
        else:
            continue

        scraped_jobs_list.append({
            "id": str(j_id),
            "source": str(j_src),
            "externalId": str(j_ext),
            "applyUrl": str(j_apply),
            "canonicalApplyUrl": str(j_canon) if j_canon else None,
            "location": str(j_loc) if j_loc else None,
            "salary": str(j_sal) if j_sal else None,
            "status": str(j_stat) if j_stat else "ACTIVE",
            "publishedAt": j_pub_str,
        })
        if j_apply and str(j_apply) not in clean_ev_ids:
            clean_ev_ids.append(str(j_apply))

    # Extract apply_url
    apply_url = None
    for item in clean_ev_ids:
        if str(item).startswith("http://") or str(item).startswith("https://"):
            apply_url = str(item)
            break
    if not apply_url and scraped_jobs_list:
        apply_url = scraped_jobs_list[0].get("applyUrl")
    if not apply_url:
        desc_text = get_val("description", ["description"], "") or ""
        import re
        match = re.search(r"(?:Direct Apply|Apply|URL):\s*(https?://[^\s\n\r\)]+)", desc_text, re.IGNORECASE)
        if match:
            apply_url = match.group(1).strip()

    return {
        "id": str(opp_id),
        "title": str(title),
        "personId": str(contact_id or ""),
        "personName": str(person_name or ""),
        "companyId": str(company_id or "c-1"),
        "companyName": str(company_name or ""),
        "relationshipId": get_val("relationship_id", ["relationshipId", "relationship_id"]),
        "sourceMeetingId": get_val("source_meeting_id", ["sourceMeetingId", "source_meeting_id"]),
        "trustedContextIds": [str(x) for x in (raw_tc_ids if isinstance(raw_tc_ids, list) else [])],
        "problem": str(get_val("problem", ["problem"], "")),
        "requirement": str(get_val("requirement", ["requirement"], "")),
        "timeline": get_val("timeline", ["timeline"]),
        "budgetSignal": get_val("budget_signal", ["budgetSignal", "budget_signal"]),
        "opportunityType": str(get_val("opportunity_type", ["opportunityType", "opportunity_type"], "Digital Transformation")),
        "confidence": int(get_val("confidence", ["confidence"], 50)),
        "status": fe_status,
        "createdAt": c_at_str,
        "updatedAt": u_at_str,
        "lifecycleStatus": be_status,
        "supportingEvidenceIds": clean_ev_ids,
        "applyUrl": apply_url,
        "scrapedJobs": scraped_jobs_list,
        # Detail fields passed through for OpportunityDetailOut
        "description": get_val("description", ["description"]),
        "organizationId": str(get_val("organization_id", ["organization_id", "organizationId"], "org-1")),
        "ownerUserId": get_val("owner_user_id", ["owner_user_id", "ownerUserId"]),
        "matchedProductId": get_val("matched_product_id", ["matched_product_id", "matchedProductId"]),
        "matchedProductName": get_val("matched_product_name", ["matched_product_name", "matchedProductName"]),
        "matchScore": get_val("match_score", ["match_score", "matchScore"]),
        "matchRationale": get_val("match_rationale", ["match_rationale", "matchRationale"]),
        "deliveryPath": get_val("delivery_path", ["delivery_path", "deliveryPath", "selected_path", "selectedPath"]),
        "selectedSolutionId": get_val("selected_solution_id", ["selected_solution_id", "selectedSolutionId"]),
        "reviewNotes": get_val("review_notes", ["review_notes", "reviewNotes"]),
        "reviewedBy": get_val("reviewed_by", ["reviewed_by", "reviewedBy"]),
        "reviewedAt": r_at_str,
        "validUntil": v_until_str,
        # Search fields passed through for OpportunitySearchResult
        "relevanceScore": get_val("relevanceScore", ["relevanceScore", "relevance_score"], 100),
        "matchReasons": get_val("matchReasons", ["matchReasons", "match_reasons"], []),
    }


# ==============================================================================
# Opportunity Output Schemas (1:1 Frontend Alignment)
# ==============================================================================

class OpportunityOut(BaseModel):
    """
    1:1 compatible output schema for the frontend Opportunity TypeScript interface:
    export interface Opportunity {
      id: string;
      title: string;
      personId: string;
      personName: string;
      companyId: string;
      companyName: string;
      relationshipId?: string;
      sourceMeetingId?: string;
      trustedContextIds: string[];
      problem: string;
      requirement: string;
      timeline?: string;
      budgetSignal?: string;
      opportunityType: string;
      confidence: number;
      status: OpportunityStatus;
      createdAt: string;
      updatedAt: string;
    }
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    title: str
    personId: str = ""
    personName: str = ""
    companyId: str = ""
    companyName: str = ""
    relationshipId: Optional[str] = None
    sourceMeetingId: Optional[str] = None
    trustedContextIds: List[str] = Field(default_factory=list)
    problem: str
    requirement: str
    timeline: Optional[str] = None
    budgetSignal: Optional[str] = None
    opportunityType: str
    confidence: int
    status: str
    createdAt: str
    updatedAt: str
    # Full transparency of canonical backend state
    lifecycleStatus: Optional[OpportunityLifecycleStatus] = None
    deliveryPath: Optional[str] = None
    selectedSolutionId: Optional[str] = None
    supportingEvidenceIds: List[str] = Field(default_factory=list)
    applyUrl: Optional[str] = None
    description: Optional[str] = None
    scrapedJobs: List[Dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        return _normalize_opportunity_input(data)


class OpportunityListResponse(BaseModel):
    """Container schema for opportunity list endpoints."""
    opportunities: List[OpportunityOut]
    total: int


class OpportunityDetailOut(OpportunityOut):
    """
    Extends OpportunityOut with deep commercial intelligence, product matching,
    evidence citations, review metadata, and workspace attribution.
    """
    description: Optional[str] = None
    organizationId: str = ""
    ownerUserId: Optional[str] = None

    # Product matching linkage
    matchedProductId: Optional[str] = None
    matchedProductName: Optional[str] = None
    matchScore: Optional[int] = None
    matchRationale: Optional[str] = None

    # Evidence traceability & review audit
    supportingEvidenceIds: List[str] = Field(default_factory=list)
    reviewNotes: Optional[str] = None
    reviewedBy: Optional[str] = None
    reviewedAt: Optional[str] = None
    validUntil: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        return _normalize_opportunity_input(data)


class OpportunitySearchResult(OpportunityOut):
    """Schema for live opportunity search results with relevance scoring and match reasoning."""
    relevanceScore: int = 100
    matchReasons: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        return _normalize_opportunity_input(data)


class OpportunitySearchResponse(BaseModel):
    """Schema for live opportunity search responses."""
    query: str = ""
    total: int = 0
    results: List[OpportunitySearchResult] = Field(default_factory=list)


# ==============================================================================
# Opportunity Input Schemas
# ==============================================================================

class OpportunityCreateIn(BaseModel):
    """Request payload for manual or signal-driven opportunity creation."""
    title: str = Field(..., min_length=3, max_length=200, description="Commercial opportunity headline")
    company_name: str = Field(..., min_length=1, max_length=200, description="Target enterprise or company name")
    problem: str = Field(..., min_length=5, description="Underlying business pain point or operational bottleneck")
    requirement: str = Field(..., min_length=5, description="Explicit or inferred capability requirement")
    opportunity_type: str = Field(default="DIGITAL_TRANSFORMATION", min_length=2, description="Opportunity category")

    # Optional entity linkages
    contact_id: Optional[str] = Field(default=None, description="Linked contact ID if person-derived")
    company_id: Optional[str] = Field(default=None, description="Linked company profile ID")

    # Optional commercial details
    description: Optional[str] = None
    timeline: Optional[str] = None
    budget_signal: Optional[str] = None
    confidence: int = Field(default=50, ge=0, le=100, description="Confidence score between 0 and 100")
    status: Optional[str] = Field(default="DISCOVERED", description="Initial lifecycle status")
    valid_until: Optional[datetime] = None

    # Optional pre-computed product match
    matched_product_id: Optional[str] = None
    matched_product_name: Optional[str] = None
    match_score: Optional[int] = Field(default=None, ge=0, le=100)
    match_rationale: Optional[str] = None

    # Optional delivery path & capability selection
    delivery_path: Optional[str] = Field(default=None, description="Delivery path ('INTERNAL', 'NETWORK', 'HYBRID')")
    selected_solution_id: Optional[str] = Field(default=None, description="Selected solution or capability ID")

    # Provenance
    supporting_evidence_ids: Optional[List[str]] = Field(default_factory=list)
    trusted_context_ids: Optional[List[str]] = Field(default_factory=list)


class OpportunityValidateIn(BaseModel):
    """
    Request schema for opportunity validation / qualification.
    Accepts both frontend 'VALIDATED' and canonical backend 'QUALIFIED' / 'REJECTED' / 'ON_HOLD'.
    """
    status: str = Field(default="VALIDATED", description="Target status ('VALIDATED', 'QUALIFIED', 'REJECTED', 'ON_HOLD')")
    review_notes: Optional[str] = Field(default=None, description="Human reviewer justification notes")
    confirmed_problem: Optional[str] = None
    confirmed_solution: Optional[str] = None


class OpportunityValidationResponse(BaseModel):
    """Response returned upon successful opportunity validation."""
    success: bool = True
    opportunity_id: str
    status: str
    message: Optional[str] = None
    opportunity: Optional[OpportunityDetailOut] = None


# ==============================================================================
# Delivery Path & Solution / Capability Matching Schemas
# ==============================================================================

SUPPORTED_DELIVERY_PATHS = {"INTERNAL", "NETWORK", "HYBRID"}

class OpportunityPathIn(BaseModel):
    path: str = Field(..., description="Selected delivery path ('INTERNAL', 'NETWORK', 'HYBRID')")


class OpportunityPathResponse(BaseModel):
    success: bool = True
    opportunity_id: str
    selected_path: str
    delivery_path: str


class CapabilityItem(BaseModel):
    id: str
    name: str
    category: str = "PRODUCT"
    description: str = ""
    relevantExpertise: List[str] = Field(default_factory=list)
    evidenceSource: str = "Ottobon Catalog"


class MatchReasoning(BaseModel):
    problemAlignment: str = "STRONG"
    requirementAlignment: str = "STRONG"
    technologyAlignment: str = "STRONG"
    industryAlignment: str = "STRONG"
    overallExplanation: str


class CapabilityMatchOut(BaseModel):
    id: str
    opportunityId: str
    capabilityId: str
    capability: CapabilityItem
    status: str = "CANDIDATE"  # CANDIDATE, SELECTED, REJECTED
    reasoning: MatchReasoning
    evidenceIds: List[str] = Field(default_factory=list)
    confidence: int = 85


class CapabilityMatchesResponse(BaseModel):
    matches: List[CapabilityMatchOut]


class CapabilityMatchUpdateIn(BaseModel):
    status: str = Field(..., description="Target status ('CANDIDATE', 'SELECTED', 'REJECTED')")


class SolutionCandidateOut(BaseModel):
    id: str
    name: str
    description: str
    type: str  # INTERNAL, NETWORK, HYBRID
    matchScore: int
    trustLevel: str = "FACT"
    evidenceId: Optional[str] = None


class OpportunitySolutionsResponse(BaseModel):
    solutions: List[SolutionCandidateOut]

