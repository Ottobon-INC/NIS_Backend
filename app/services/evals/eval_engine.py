import uuid
import logging
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.evals import EvalRun
from app.models.identity import Contact
from app.models.orchestration import ResearchRun
from app.schemas.evals import (
    EvaluationBadge,
    EvaluationDimensionDetail,
    EvalRunResponse,
)
from app.services.evals.citation_evaluator import CitationEvaluator
from app.services.evals.identity_evaluator import IdentityEvaluator
from app.services.evals.grounding_evaluator import GroundingEvaluator
from app.services.evals.faithfulness_evaluator import FaithfulnessEvaluator
from app.services.evals.solution_evaluator import SolutionEvaluator

logger = logging.getLogger("networkos")


def _compute_status(score: float, pass_thresh: float, warn_thresh: float) -> str:
    if score >= pass_thresh:
        return "PASS"
    if score >= warn_thresh:
        return "WARNING"
    return "FAIL"


def _compute_badge(overall: float, tier: str) -> EvaluationBadge:
    pct = round(overall, 1)
    if pct >= 95.0:
        return EvaluationBadge(label="Grounded", percentage=pct, color="green", tier=tier)
    if pct >= 80.0:
        return EvaluationBadge(label="Supported Inference", percentage=pct, color="amber", tier=tier)
    return EvaluationBadge(label="Unverified", percentage=pct, color="red", tier=tier)


def _evaluate_retrieval_precision(
    snapshot_dict: Dict[str, Any],
    sources_registry: Optional[Dict[str, Any]] = None
) -> Tuple[float, Dict[str, Any]]:
    """
    Evaluates accuracy & relevance of retrieved data sources used to build the dossier.
    """
    sources = snapshot_dict.get("sources_used") or []
    issues: List[str] = []

    if not sources and sources_registry:
        seen = set()
        for rec in sources_registry.values():
            rid = getattr(rec, "source_id", None) or id(rec)
            if rid in seen:
                continue
            seen.add(rid)
            id_res = getattr(rec, "identity_resolution", None)
            match_st = getattr(id_res, "status", "PROBABLE") if id_res else "PROBABLE"
            conf = getattr(id_res, "confidence", 60.0) if id_res else 60.0
            sources.append({
                "source_id": getattr(rec, "source_id", "unknown"),
                "status": "SUCCESS",
                "identity_match_status": match_st,
                "identity_match_confidence": conf
            })

    total = len(sources)
    if total == 0:
        return 0.0, {
            "retrieval_precision_pct": 0.0,
            "total_sources": 0,
            "confirmed_sources": 0,
            "probable_sources": 0,
            "uncertain_sources": 0,
            "issues": ["No external sources retrieved for this contact"]
        }

    confirmed = 0
    probable = 0
    uncertain = 0
    conf_sum = 0.0

    for src in sources:
        st = str(src.get("identity_match_status", "UNCERTAIN")).upper()
        conf = float(src.get("identity_match_confidence", 50.0) or 50.0)
        conf_sum += conf
        if st in ["CONFIRMED", "MATCH_CONFIRMED"]:
            confirmed += 1
        elif st == "PROBABLE":
            probable += 1
        else:
            uncertain += 1

    relevant_weighted = confirmed + (0.75 * probable) + (0.25 * uncertain)
    precision_ratio = (relevant_weighted / total) * 100.0
    avg_conf = conf_sum / total
    score = round(min(100.0, max(0.0, (0.6 * precision_ratio) + (0.4 * avg_conf))), 1)

    if uncertain > confirmed + probable:
        issues.append(f"{uncertain}/{total} retrieved sources have uncertain identity alignment")

    return score, {
        "retrieval_precision_pct": score,
        "total_sources": total,
        "confirmed_sources": confirmed,
        "probable_sources": probable,
        "uncertain_sources": uncertain,
        "issues": issues
    }


class EvalEngine:
    """
    Central orchestrator for NetworkOS AI Evaluation & Verification.
    Runs deterministic and LLM-as-a-judge audits and computes composite accuracy percentages.
    """

    @classmethod
    def build_dimensions(
        cls,
        identity_score: float,
        citation_score: float,
        grounding_score: float,
        faithfulness_score: float,
        solution_score: float,
        detailed_findings: Dict[str, Any]
    ) -> List[EvaluationDimensionDetail]:
        id_d = detailed_findings.get("identity", {})
        cite_d = detailed_findings.get("citation", {})
        ground_d = detailed_findings.get("grounding", {})
        faith_d = detailed_findings.get("faithfulness", {})
        sol_d = detailed_findings.get("solution", {})
        ret_d = detailed_findings.get("retrieval", {})

        ret_score = float(ret_d.get("retrieval_precision_pct", identity_score))
        total_src = ret_d.get("total_sources", 0)
        conf_src = ret_d.get("confirmed_sources", 0)

        valid_c = len(cite_d.get("valid_citations", []))
        total_c = cite_d.get("total_citations_found", 0)

        dims = [
            EvaluationDimensionDetail(
                dimension_name="Data Retrieval Relevance",
                score=round(ret_score, 1),
                target_threshold=85.0,
                status=_compute_status(ret_score, 85.0, 65.0),
                summary=f"{conf_src}/{total_src} retrieved sources firmly confirmed for target entity." if total_src else "No retrieval records audited.",
                issues_detected=ret_d.get("issues", [])
            ),
            EvaluationDimensionDetail(
                dimension_name="Identity Verification",
                score=round(identity_score, 1),
                target_threshold=90.0,
                status=_compute_status(identity_score, 90.0, 70.0),
                summary=f"Identity status: {id_d.get('resolution_status', 'UNKNOWN')} (Confidence: {id_d.get('raw_resolver_confidence', identity_score)}%).",
                issues_detected=id_d.get("issues", [])
            ),
            EvaluationDimensionDetail(
                dimension_name="Citation Authenticity",
                score=round(citation_score, 1),
                target_threshold=100.0,
                status=_compute_status(citation_score, 95.0, 80.0),
                summary=f"{valid_c}/{total_c} inline citations verified against retrieved sources." if total_c else "Zero inline citations detected.",
                issues_detected=(
                    [f"Fabricated citation keys: {', '.join(cite_d.get('fabricated_citations', []))}"]
                    if cite_d.get("fabricated_citations") else []
                )
            ),
            EvaluationDimensionDetail(
                dimension_name="Problem Grounding",
                score=round(grounding_score, 1),
                target_threshold=85.0,
                status=_compute_status(grounding_score, 85.0, 70.0),
                summary=f"Problem tier: {ground_d.get('problem_epistemic_status', 'N/A')} ({ground_d.get('citations_count', 0)} citations).",
                issues_detected=ground_d.get("issues", [])
            ),
            EvaluationDimensionDetail(
                dimension_name="Synthesis Faithfulness",
                score=round(faithfulness_score, 1),
                target_threshold=95.0,
                status=_compute_status(faithfulness_score, 90.0, 75.0),
                summary=f"{faith_d.get('verified_claims_count', 0)}/{faith_d.get('total_claims_checked', 0)} factual claims entailed by sources ({faith_d.get('evaluation_mode', 'AUDITED')}).",
                issues_detected=[f"Unsupported claim: {h}" for h in faith_d.get("hallucinations", [])[:3]]
            ),
            EvaluationDimensionDetail(
                dimension_name="Solution Alignment",
                score=round(solution_score, 1),
                target_threshold=90.0,
                status=_compute_status(solution_score, 85.0, 70.0),
                summary=f"Capability fit: {sol_d.get('capability_match', 'N/A')} (Risk: {sol_d.get('risk_level', 'MEDIUM')}).",
                issues_detected=sol_d.get("issues", [])
            ),
        ]
        return dims

    @classmethod
    def to_response(cls, eval_run: EvalRun) -> EvalRunResponse:
        findings = eval_run.detailed_findings or {}
        dims = cls.build_dimensions(
            identity_score=eval_run.identity_accuracy_score,
            citation_score=eval_run.citation_validity_score,
            grounding_score=eval_run.grounding_score,
            faithfulness_score=eval_run.faithfulness_score,
            solution_score=eval_run.solution_alignment_score,
            detailed_findings=findings
        )
        badge = _compute_badge(eval_run.overall_accuracy_score, eval_run.evaluation_tier)

        return EvalRunResponse(
            id=eval_run.id,
            contact_id=eval_run.contact_id,
            research_run_id=eval_run.research_run_id,
            overall_accuracy_score=eval_run.overall_accuracy_score,
            identity_accuracy_score=eval_run.identity_accuracy_score,
            citation_validity_score=eval_run.citation_validity_score,
            grounding_score=eval_run.grounding_score,
            faithfulness_score=eval_run.faithfulness_score,
            solution_alignment_score=eval_run.solution_alignment_score,
            total_claims_evaluated=eval_run.total_claims_evaluated,
            verified_claims_count=eval_run.verified_claims_count,
            hallucinated_claims_count=eval_run.hallucinated_claims_count,
            badge=badge,
            dimensions=dims,
            detailed_findings=findings,
            created_at=eval_run.created_at.isoformat() if eval_run.created_at else None
        )

    @classmethod
    async def evaluate_dossier(
        cls,
        db: Optional[AsyncSession],
        contact_id: Optional[str],
        research_run_id: Optional[str],
        snapshot_dict: Dict[str, Any],
        sources_registry: Optional[Dict[str, Any]] = None,
        contact_name: Optional[str] = None,
        contact_company: Optional[str] = None,
        enable_llm_judge: bool = True,
        persist: bool = True
    ) -> EvalRunResponse:
        """
        Executes full 5+1 dimensional evaluation pipeline, persists EvalRun if db & persist=True,
        and returns an EvalRunResponse ready for API/UI consumption.
        """
        snapshot = snapshot_dict or {}
        evidence_map = snapshot.get("evidence_map") or {}
        report_md = snapshot.get("full_markdown_report", "")

        # 1. Deterministic Citation Audit (20%)
        citation_score, citation_details = CitationEvaluator.evaluate(
            markdown_text=report_md,
            sources_registry=sources_registry,
            evidence_map=evidence_map
        )

        # 2. Identity Resolution Audit (25%)
        identity_score, identity_details = IdentityEvaluator.evaluate(
            snapshot_dict=snapshot,
            sources_registry=sources_registry,
            contact_name=contact_name,
            contact_company=contact_company
        )

        # 3. Problem Grounding Audit (20%)
        grounding_score, grounding_details = GroundingEvaluator.evaluate(
            snapshot_dict=snapshot,
            sources_registry=sources_registry
        )

        # 4. Solution Alignment Audit (15%)
        solution_score, solution_details = SolutionEvaluator.evaluate(
            snapshot_dict=snapshot
        )

        # 5. Retrieval Precision Audit (informational observability)
        retrieval_score, retrieval_details = _evaluate_retrieval_precision(
            snapshot_dict=snapshot,
            sources_registry=sources_registry
        )

        # 6. Faithfulness NLI Audit via gpt-4o-mini (20%)
        faithfulness_score, faithfulness_details = await FaithfulnessEvaluator.evaluate(
            snapshot_dict=snapshot,
            sources_registry=sources_registry,
            citation_score=citation_score,
            enable_llm_judge=enable_llm_judge and bool(settings.OPENAI_API_KEY)
        )

        # Weighted Composite Score (0.0 - 100.0)
        overall_score = round(
            (0.25 * identity_score)
            + (0.20 * citation_score)
            + (0.20 * grounding_score)
            + (0.20 * faithfulness_score)
            + (0.15 * solution_score),
            1
        )

        eval_mode = str(faithfulness_details.get("evaluation_mode", ""))
        eval_tier = "HYBRID_VERIFIED" if "LLM_JUDGE" in eval_mode else "DETERMINISTIC_ONLY"

        total_claims = int(faithfulness_details.get("total_claims_checked", 0))
        verified_claims = int(faithfulness_details.get("verified_claims_count", 0))
        hallucinated_claims = int(faithfulness_details.get("hallucinated_claims_count", 0))

        detailed_findings: Dict[str, Any] = {
            "retrieval": retrieval_details,
            "identity": identity_details,
            "citation": citation_details,
            "grounding": grounding_details,
            "faithfulness": faithfulness_details,
            "solution": solution_details
        }

        valid_contact_id = contact_id
        valid_run_id = research_run_id

        if persist and db is not None and isinstance(db, AsyncSession):
            try:
                if valid_run_id:
                    run_row = (await db.execute(select(ResearchRun.id).where(ResearchRun.id == valid_run_id))).scalar_one_or_none()
                    if not run_row:
                        valid_run_id = None
                if valid_contact_id:
                    contact_row = (await db.execute(select(Contact.id).where(Contact.id == valid_contact_id))).scalar_one_or_none()
                    if not contact_row:
                        valid_contact_id = None
            except Exception:
                pass

        eval_record = EvalRun(
            id=f"eval-{uuid.uuid4().hex[:10]}",
            contact_id=valid_contact_id,
            research_run_id=valid_run_id,
            overall_accuracy_score=overall_score,
            identity_accuracy_score=round(identity_score, 1),
            citation_validity_score=round(citation_score, 1),
            grounding_score=round(grounding_score, 1),
            faithfulness_score=round(faithfulness_score, 1),
            solution_alignment_score=round(solution_score, 1),
            total_claims_evaluated=total_claims,
            verified_claims_count=verified_claims,
            hallucinated_claims_count=hallucinated_claims,
            evaluation_tier=eval_tier,
            detailed_findings=detailed_findings
        )

        if persist and db is not None:
            try:
                db.add(eval_record)
                await db.flush()
            except Exception as e:
                logger.warning(f"EvalEngine: Failed to persist EvalRun (continuing with computed metrics): {e}")

        return cls.to_response(eval_record)
