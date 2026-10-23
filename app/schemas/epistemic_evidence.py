from datetime import datetime, timezone
from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, Field

SourceAuthorityTier = Literal[
    "PRIMARY_OFFICIAL",      # Official company website, careers portal, SEC/regulatory filing, verified LinkedIn company page
    "REPUTABLE_AGGREGATOR", # Verified job platforms (Greenhouse, Lever, Workday, WWR, Jobicy), tier-1 news, academic registries
    "UNVERIFIED_WEB"        # General web search snippets, blogs, aggregators, SEO scrapers
]

IdentityMatchStatus = Literal[
    "MATCH_CONFIRMED",      # High confidence exact identity match (verified domain, direct slug, email)
    "PROBABLE",             # Strong multi-signal match (name + company + title alignment, no conflict)
    "AMBIGUOUS",            # Multiple candidates or conflicting affiliation signals detected
    "UNMATCHED"             # Source does not match target executive/company
]

EpistemicStatus = Literal[
    "VERIFIED",             # Provenance confirmed + Primary/Reputable source + Confirmed identity + No contradictions
    "PARTIALLY_SUPPORTED",  # Provenance confirmed, but source is unverified web, or identity is probable, or corroboration is weak
    "CONFLICTING",          # Contradicted by another equally valid source in the same timeframe
    "UNSUPPORTED",          # Quote missing in source text, invalid source reference, or identity ambiguous
    "UNKNOWN",              # Explicit lack of evidence in retrieved corpus
    "HYPOTHESIS"            # Commercial/sales inference or solution proposal (internal Ottobon projection)
]

HiringState = Literal[
    "ACTIVE",               # Verified current open roles detected on authoritative feed/careers page
    "INACTIVE",             # Official careers page checked with 0 open positions or explicitly stated not hiring
    "UNKNOWN",              # No verifiable careers or hiring signals present in retrieved corpus
    "CONFLICTING"           # One source claims hiring freeze while another lists fresh postings
]


class EvidenceRef(BaseModel):
    """Immutable reference to an exact textual span and its source provenance."""
    source_id: str
    source_url: str
    canonical_url: Optional[str] = None
    source_domain: str
    content_sha256: Optional[str] = None
    retrieval_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verbatim_quote: str
    char_offset_start: Optional[int] = None
    char_offset_end: Optional[int] = None
    source_authority: SourceAuthorityTier = "UNVERIFIED_WEB"
    identity_status: IdentityMatchStatus = "PROBABLE"


class ObservableAuditSignals(BaseModel):
    """Observable properties used to derive epistemic status deterministically without guessing."""
    corroboration_count: int = 0
    has_primary_source: bool = False
    has_reputable_source: bool = False
    identity_match_confirmed: bool = False
    freshest_evidence_date: Optional[datetime] = None
    has_contradictory_evidence: bool = False


class AtomicClaim(BaseModel):
    """An independently testable, single-predicate factual assertion."""
    claim_id: str
    subject_entity_id: str
    subject_type: Literal["EXECUTIVE", "COMPANY"]
    predicate: str                      # e.g., "CURRENT_ROLE", "CURRENT_COMPANY", "USES_TECH", "HIRING_STATUS", "LOCATION"
    value: Optional[str] = None         # None represents explicit unknown/unverified
    epistemic_status: EpistemicStatus = "UNKNOWN"
    epistemic_rationale: str = ""
    signals: ObservableAuditSignals = Field(default_factory=ObservableAuditSignals)
    evidence: List[EvidenceRef] = Field(default_factory=list)


class CommercialHypothesis(BaseModel):
    """
    Explicitly separated commercial sales proposal and pain point inference.
    NEVER to be conflated with or presented as a verified fact about the prospect.
    """
    hypothesis_id: str
    target_entity_id: str
    trigger_claim_ids: List[str] = Field(default_factory=list)
    inferred_pain_point: str
    ottobon_capability_offering: str
    delivery_risk_assessment: str
    estimated_effort_hours: Optional[str] = None
    pricing_scenario: Optional[str] = None
    epistemic_status: Literal["HYPOTHESIS"] = "HYPOTHESIS"
