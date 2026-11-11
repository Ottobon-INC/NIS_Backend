from typing import Optional, Any, Dict
from datetime import datetime
from sqlalchemy import String, Float, Integer, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.db.base import Base

class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    contact_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True, index=True)
    research_run_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=True, index=True)

    # Core Composite & Dimension Accuracy Scores (0.0 to 100.0)
    overall_accuracy_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    identity_accuracy_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    citation_validity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    grounding_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    faithfulness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    solution_alignment_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Claim & Citation Counts
    total_claims_evaluated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verified_claims_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hallucinated_claims_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    evaluation_tier: Mapped[str] = mapped_column(String, default="HYBRID_VERIFIED", nullable=False)
    detailed_findings: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

