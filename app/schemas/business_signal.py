from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Literal
import enum
from pydantic import BaseModel, Field

from app.schemas.epistemic_evidence import IdentityMatchStatus, SourceAuthorityTier


class SignalType(str, enum.Enum):
    OPERATIONAL_CHALLENGE = "OPERATIONAL_CHALLENGE"
    SERVICE_DISRUPTION = "SERVICE_DISRUPTION"
    SCALING_BOTTLENECK = "SCALING_BOTTLENECK"
    REGULATORY_COMPLIANCE = "REGULATORY_COMPLIANCE"
    PROCESS_INEFFICIENCY = "PROCESS_INEFFICIENCY"
    HIRING_INITIATIVE = "HIRING_INITIATIVE"
    CORPORATE_EXPANSION = "CORPORATE_EXPANSION"
    GENERAL_ANNOUNCEMENT = "GENERAL_ANNOUNCEMENT"
    TECHNICAL_ADOPTION = "TECHNICAL_ADOPTION"


class SignalClassification(str, enum.Enum):
    DIRECT_PROBLEM_EVIDENCE = "DIRECT_PROBLEM_EVIDENCE"
    CONTEXTUAL_SIGNAL = "CONTEXTUAL_SIGNAL"
    POTENTIAL_INFERENCE = "POTENTIAL_INFERENCE"
    UNRELIABLE_OR_MISATTRIBUTED = "UNRELIABLE_OR_MISATTRIBUTED"


class SignalFreshness(str, enum.Enum):
    FRESH = "FRESH"          # < 180 days: Recent operational or corporate signal
    AGING = "AGING"          # 180 - 365 days: Aging but potentially relevant context
    STALE = "STALE"          # > 365 days: Historical; cannot establish an active operational problem
    UNDATED = "UNDATED"      # Date unstated in source; never fabricated or guessed


class SignalDiscoveryQuery(BaseModel):
    query_text: str
    intent: str
    target_company: str
    source_type: str = "general_web"


class BusinessSignal(BaseModel):
    """
    Structured model for a discovered operational or contextual business signal.
    Captures provenance, publication vs discovery dates, identity association,
    and cautious classification without equating a signal with a verified problem.
    """
    signal_id: str
    signal_type: SignalType
    classification: SignalClassification
    factual_description: str
    source_url: str
    source_title: Optional[str] = None
    publisher_domain: str
    publication_date: Optional[datetime] = None  # Original publication/event date (never fabricated)
    discovery_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    quoted_passage: str
    target_company: str
    entity_association_status: IdentityMatchStatus = "PROBABLE"
    evidence_record_id: Optional[str] = None
    confidence: int = 70  # 0 to 100
    relevance_rationale: str
    explicitly_states_problem: bool = False
    freshness_status: SignalFreshness = SignalFreshness.UNDATED
    is_stale: bool = False
    canonical_url: Optional[str] = None
    content_fingerprint: Optional[str] = None
    metadata_: Dict[str, Any] = Field(default_factory=dict)
