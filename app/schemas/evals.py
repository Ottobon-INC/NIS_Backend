from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class EvaluationBadge(BaseModel):
    label: str = Field(description="e.g. Grounded, High Accuracy, Unverified")
    percentage: float = Field(description="Overall composite accuracy percentage 0.0 - 100.0")
    color: str = Field(description="green, amber, or red")
    tier: str = Field(default="HYBRID_VERIFIED")

class EvaluationDimensionDetail(BaseModel):
    dimension_name: str
    score: float
    target_threshold: float
    status: str = Field(description="PASS, WARNING, or FAIL")
    summary: str
    issues_detected: List[str] = Field(default_factory=list)

class EvalRunResponse(BaseModel):
    id: str
    contact_id: Optional[str] = None
    research_run_id: Optional[str] = None
    overall_accuracy_score: float
    identity_accuracy_score: float
    citation_validity_score: float
    grounding_score: float
    faithfulness_score: float
    solution_alignment_score: float
    total_claims_evaluated: int
    verified_claims_count: int
    hallucinated_claims_count: int
    badge: EvaluationBadge
    dimensions: List[EvaluationDimensionDetail] = Field(default_factory=list)
    detailed_findings: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None

