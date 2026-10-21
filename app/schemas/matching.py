from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class EvidenceStatus(str, Enum):
    VERIFIED_FACT = "VERIFIED_FACT"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"

class ProblemType(str, Enum):
    EXPLICIT_PROBLEM = "EXPLICIT_PROBLEM"
    INFERRED_HYPOTHESIS = "INFERRED_HYPOTHESIS"

class MatchingOutcome(str, Enum):
    MATCH_FOUND = "MATCH_FOUND"
    NO_MATCH_FOUND = "NO_MATCH_FOUND"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    NEEDS_VALIDATION = "NEEDS_VALIDATION"

class ProblemItem(BaseModel):
    id: str
    title: str
    problem_type: ProblemType
    evidence_status: EvidenceStatus
    business_summary: str
    supporting_evidence: List[str]
    likely_business_impact: Optional[str] = None
    ai_interpretation: Optional[str] = None
    missing_information: Optional[str] = None
    validation_questions: List[str] = Field(default_factory=list)

class SolutionCandidate(BaseModel):
    offering_id: str
    offering_name: str
    offering_type: str  # "SERVICE" | "PRODUCT"
    addressed_problem_id: str
    addressed_problem_title: str
    relevant_capabilities: List[str]
    covered_capabilities: List[str]
    missing_capabilities: List[str]
    supporting_evidence: str
    unverified_assumptions: List[str]
    required_info_before_recommending: List[str]

class CompanyProfileAnalysis(BaseModel):
    company_name: str
    industry: str
    business_model: str
    operating_context: str
    products_and_services: List[str] = Field(default_factory=list)
    technology_stack: List[str] = Field(default_factory=list)
    business_objectives: List[str] = Field(default_factory=list)
    operational_constraints: List[str] = Field(default_factory=list)
    explicit_problems: List[ProblemItem] = Field(default_factory=list)
    inferred_hypotheses: List[ProblemItem] = Field(default_factory=list)
    unknowns_and_missing: List[str] = Field(default_factory=list)
    source_filename: str

class CompanyMatchingResult(BaseModel):
    company_name: str
    source_filename: str
    company_summary: str
    business_context: str
    problems_analyzed: List[ProblemItem]
    candidate_solutions: List[SolutionCandidate]
    matching_outcome: MatchingOutcome
    matching_rationale: str
    capability_gaps: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    validation_questions: List[str] = Field(default_factory=list)
    recommended_next_step: str

class ProductMatchItem(BaseModel):
    product_id: str
    product_name: str
    category: str
    tagline: str
    match_score: int  # 0 to 100
    alignment_level: str  # STRONG | MODERATE | WEAK | NONE
    addressed_problem: str
    why_this_product_solves_it: str
    relevant_features: List[str]
    target_audience_fit: str
    assumptions_or_prerequisites: List[str] = Field(default_factory=list)
    suggested_first_step: str

class SemanticProblemMatchRequest(BaseModel):
    problem_text: str
    connection_id: Optional[str] = None
    connection_name: Optional[str] = None
    connection_company: Optional[str] = None
    connection_title: Optional[str] = None

class SemanticProductMatchResponse(BaseModel):
    connection_id: Optional[str] = None
    connection_name: Optional[str] = None
    connection_company: Optional[str] = None
    connection_title: Optional[str] = None
    identified_problem: str
    problem_domain: str
    matching_outcome: MatchingOutcome = MatchingOutcome.NO_MATCH_FOUND
    suggested_status: str  # "MATCH FOUND" | "No matches found" | "Insufficient Information" | "Needs Validation"
    matches: List[ProductMatchItem] = Field(default_factory=list)
    rationale: str
    relevant_evidence: List[str] = Field(default_factory=list)
    supported_capabilities: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    unverified_hypotheses: List[str] = Field(default_factory=list)
    validation_questions: List[str] = Field(default_factory=list)
    recommended_next_step: Optional[str] = None
    capability_gap: Optional[str] = None
    proposed_solution: Optional[str] = None
