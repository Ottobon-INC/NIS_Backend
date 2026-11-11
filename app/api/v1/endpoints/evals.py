import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, or_
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.models.evals import EvalRun
from app.models.identity import Contact, ContactStatus, ContactType
from app.models.evidence import SourceResult
from app.models.orchestration import ResearchRun, ResearchTask
from app.schemas.evals import EvalRunResponse
from app.services.evals import EvalEngine

logger = logging.getLogger("networkos")
router = APIRouter()


class EvalBatchResult(BaseModel):
    evaluated_count: int
    total_eval_runs: int
    average_accuracy_score: float


class EvalSummaryResponse(BaseModel):
    total_evaluated_contacts: int
    average_overall_accuracy: float
    average_identity_accuracy: float
    average_citation_validity: float
    average_grounding_score: float
    average_faithfulness_score: float
    average_solution_alignment: float
    badge_distribution: Dict[str, int]
    recent_runs: List[EvalRunResponse]


async def _load_contact_snapshot_and_sources(
    db: AsyncSession,
    contact_id: str
) -> tuple[Contact, Optional[str], Dict[str, Any], Dict[str, Any]]:
    contact = (await db.execute(select(Contact).where(Contact.id == contact_id))).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail=f"Contact '{contact_id}' not found")

    # Find latest research run
    run_stmt = (
        select(ResearchRun)
        .where(ResearchRun.contact_id == contact_id)
        .order_by(desc(ResearchRun.created_at))
    )
    latest_run = (await db.execute(run_stmt)).scalars().first()
    run_id = latest_run.id if latest_run else None

    # Find latest evidence_engine snapshot for this contact
    sr_stmt = select(SourceResult).where(SourceResult.source_id == "evidence_engine").order_by(desc(SourceResult.retrieved_at))
    all_engine_srs = (await db.execute(sr_stmt)).scalars().all()
    snapshot: Dict[str, Any] = {}
    engine_sr: Optional[SourceResult] = None

    for sr in all_engine_srs:
        if sr.metadata_ and sr.metadata_.get("contact_id") == contact_id:
            engine_sr = sr
            if sr.extracted_data and "executive_snapshot" in sr.extracted_data:
                snapshot = dict(sr.extracted_data["executive_snapshot"])
            break

    if not snapshot:
        # Build minimal snapshot from contact attributes if not yet synthesized
        snapshot = {
            "name": contact.full_name or "Unknown",
            "current_role": contact.current_title or "Unknown",
            "current_organization": contact.current_company or "Unknown",
            "location": contact.location or "Unknown",
            "provenance_status": "UNVERIFIED",
            "problem_epistemic_status": "NO_OBSERVED_PROBLEM",
            "broad_business_problem": None,
            "smallest_solvable_problem": None,
            "problem_evidence_references": [],
            "structured_problem_references": [],
            "identity_confidence": 50.0,
            "identity_resolution_status": "PROBABLE",
            "full_markdown_report": "",
            "sources_used": []
        }

    # Gather raw retrieved sources for NLI context
    sources_registry: Dict[str, Any] = {}
    if run_id:
        task_rows = (await db.execute(select(ResearchTask).where(ResearchTask.research_run_id == run_id))).scalars().all()
        task_ids = [t.id for t in task_rows]
        if task_ids:
            raw_srs = (await db.execute(select(SourceResult).where(SourceResult.research_task_id.in_(task_ids)))).scalars().all()
            for idx, r in enumerate(raw_srs, 1):
                if r.source_id == "evidence_engine":
                    continue
                r_meta = r.metadata_ or {}
                ex_data = r.extracted_data or {}
                txt = ex_data.get("text") or ex_data.get("snippet") or ex_data.get("markdown") or ""
                title = ex_data.get("title") or r.query or r.source_id
                sources_registry[f"E{idx}"] = {
                    "source_id": r.source_id,
                    "title": title,
                    "raw_text": txt,
                    "identity_match_status": r_meta.get("identity_match_status", "PROBABLE"),
                    "identity_match_confidence": r_meta.get("identity_match_confidence", 60.0),
                }

    return contact, run_id, snapshot, {"sources_registry": sources_registry, "engine_sr": engine_sr}


@router.get("/contact/{contact_id}", response_model=EvalRunResponse)
async def get_contact_evaluation(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Returns the latest AI Evaluation metrics & accuracy breakdown for a contact.
    Computes an on-demand evaluation if none exists yet.
    """
    stmt = (
        select(EvalRun)
        .where(EvalRun.contact_id == contact_id)
        .order_by(desc(EvalRun.created_at))
    )
    existing = (await db.execute(stmt)).scalars().first()
    if existing:
        return EvalEngine.to_response(existing)

    # On-demand evaluation fallback using existing snapshot/sources
    contact, run_id, snapshot, extra = await _load_contact_snapshot_and_sources(db, contact_id)
    eval_res = await EvalEngine.evaluate_dossier(
        db=db,
        contact_id=contact_id,
        research_run_id=run_id,
        snapshot_dict=snapshot,
        sources_registry=extra["sources_registry"],
        contact_name=contact.full_name,
        contact_company=contact.current_company,
        enable_llm_judge=False,  # Fast zero-latency first view
        persist=True
    )
    await db.commit()
    return eval_res


@router.post("/evaluate/{contact_id}", response_model=EvalRunResponse)
async def run_contact_evaluation(
    contact_id: str,
    use_llm_judge: bool = Query(True, description="Enable gpt-4o-mini NLI faithfulness judge"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Triggers a fresh AI Evaluation run on a contact's synthesized intelligence dossier
    and persists updated accuracy metrics.
    """
    contact, run_id, snapshot, extra = await _load_contact_snapshot_and_sources(db, contact_id)
    eval_res = await EvalEngine.evaluate_dossier(
        db=db,
        contact_id=contact_id,
        research_run_id=run_id,
        snapshot_dict=snapshot,
        sources_registry=extra["sources_registry"],
        contact_name=contact.full_name,
        contact_company=contact.current_company,
        enable_llm_judge=use_llm_judge,
        persist=True
    )

    engine_sr: Optional[SourceResult] = extra.get("engine_sr")
    if engine_sr and engine_sr.extracted_data and "executive_snapshot" in engine_sr.extracted_data:
        updated_snap = dict(engine_sr.extracted_data["executive_snapshot"])
        updated_snap["ai_evaluation"] = eval_res.model_dump()
        engine_sr.extracted_data = {**engine_sr.extracted_data, "executive_snapshot": updated_snap}
        flag_modified(engine_sr, "extracted_data")

    await db.commit()
    return eval_res


@router.get("/summary", response_model=EvalSummaryResponse)
async def get_eval_summary(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Returns workspace-wide AI evaluation accuracy averages and badge breakdown.
    """
    stmt = select(EvalRun).order_by(desc(EvalRun.created_at))
    all_runs = list((await db.execute(stmt)).scalars().all())

    # Deduplicate to latest eval per contact
    latest_by_contact: Dict[str, EvalRun] = {}
    for er in all_runs:
        key = er.contact_id or er.id
        if key not in latest_by_contact:
            latest_by_contact[key] = er

    runs = list(latest_by_contact.values())
    n = len(runs)

    if n == 0:
        return EvalSummaryResponse(
            total_evaluated_contacts=0,
            average_overall_accuracy=0.0,
            average_identity_accuracy=0.0,
            average_citation_validity=0.0,
            average_grounding_score=0.0,
            average_faithfulness_score=0.0,
            average_solution_alignment=0.0,
            badge_distribution={"green": 0, "amber": 0, "red": 0},
            recent_runs=[]
        )

    green = sum(1 for r in runs if r.overall_accuracy_score >= 95.0)
    amber = sum(1 for r in runs if 80.0 <= r.overall_accuracy_score < 95.0)
    red = sum(1 for r in runs if r.overall_accuracy_score < 80.0)

    return EvalSummaryResponse(
        total_evaluated_contacts=n,
        average_overall_accuracy=round(sum(r.overall_accuracy_score for r in runs) / n, 1),
        average_identity_accuracy=round(sum(r.identity_accuracy_score for r in runs) / n, 1),
        average_citation_validity=round(sum(r.citation_validity_score for r in runs) / n, 1),
        average_grounding_score=round(sum(r.grounding_score for r in runs) / n, 1),
        average_faithfulness_score=round(sum(r.faithfulness_score for r in runs) / n, 1),
        average_solution_alignment=round(sum(r.solution_alignment_score for r in runs) / n, 1),
        badge_distribution={"green": green, "amber": amber, "red": red},
        recent_runs=[EvalEngine.to_response(r) for r in runs[:15]]
    )


@router.post("/evaluate-batch", response_model=EvalBatchResult)
async def evaluate_missing_contacts(
    use_llm_judge: bool = Query(False, description="Enable gpt-4o-mini NLI judge across batch"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Audits all researched contacts that do not yet have a persisted EvalRun record
    using single-pass bulk preloading for sub-second execution.
    """
    existing_ids_res = await db.execute(select(EvalRun.contact_id).where(EvalRun.contact_id.isnot(None)))
    evaluated_contact_ids = set(existing_ids_res.scalars().all())

    contacts_stmt = select(Contact).where(
        or_(Contact.card_status.is_(None), Contact.card_status != "ARCHIVED"),
        or_(
            Contact.status.in_([ContactStatus.RESEARCHING, ContactStatus.READY]),
            Contact.contact_type.in_([ContactType.TARGET, "TARGET_PROSPECT"])
        )
    )
    contacts_res = await db.execute(contacts_stmt)
    all_contacts = list(contacts_res.scalars().all())

    # Preload latest evidence_engine snapshots once
    sr_stmt = select(SourceResult).where(SourceResult.source_id == "evidence_engine").order_by(desc(SourceResult.retrieved_at))
    all_engine_srs = list((await db.execute(sr_stmt)).scalars().all())
    snapshot_by_contact: Dict[str, Dict[str, Any]] = {}
    for sr in all_engine_srs:
        cid = sr.metadata_.get("contact_id") if sr.metadata_ else None
        if cid and cid not in snapshot_by_contact and sr.extracted_data and "executive_snapshot" in sr.extracted_data:
            snapshot_by_contact[cid] = dict(sr.extracted_data["executive_snapshot"])

    new_eval_records: List[EvalRun] = []
    for c in all_contacts:
        if c.id in evaluated_contact_ids:
            continue
        if c.id.startswith(("test-", "contact-a-", "contact-b-", "contact-other-", "contact-test-", "c-foreign-", "c-err-")):
            continue
        try:
            snap = snapshot_by_contact.get(c.id) or {
                "name": c.full_name or "Unknown",
                "current_role": c.current_title or "Unknown",
                "current_organization": c.current_company or "Unknown",
                "location": c.location or "Unknown",
                "provenance_status": "UNVERIFIED",
                "problem_epistemic_status": "NO_OBSERVED_PROBLEM",
                "broad_business_problem": None,
                "smallest_solvable_problem": None,
                "problem_evidence_references": [],
                "structured_problem_references": [],
                "identity_confidence": 50.0,
                "identity_resolution_status": "PROBABLE",
                "full_markdown_report": "",
                "sources_used": []
            }
            eval_res = await EvalEngine.evaluate_dossier(
                db=None,
                contact_id=c.id,
                research_run_id=None,
                snapshot_dict=snap,
                sources_registry=None,
                contact_name=c.full_name,
                contact_company=c.current_company,
                enable_llm_judge=use_llm_judge,
                persist=False
            )
            new_eval_records.append(
                EvalRun(
                    id=eval_res.id,
                    contact_id=c.id,
                    research_run_id=None,
                    overall_accuracy_score=eval_res.overall_accuracy_score,
                    identity_accuracy_score=eval_res.identity_accuracy_score,
                    citation_validity_score=eval_res.citation_validity_score,
                    grounding_score=eval_res.grounding_score,
                    faithfulness_score=eval_res.faithfulness_score,
                    solution_alignment_score=eval_res.solution_alignment_score,
                    total_claims_evaluated=eval_res.total_claims_evaluated,
                    verified_claims_count=eval_res.verified_claims_count,
                    hallucinated_claims_count=eval_res.hallucinated_claims_count,
                    evaluation_tier=eval_res.badge.tier,
                    detailed_findings=eval_res.detailed_findings
                )
            )
        except Exception as e:
            logger.warning(f"Batch eval skipped contact {c.id}: {e}")

    if new_eval_records:
        db.add_all(new_eval_records)
        await db.commit()

    all_evals = list((await db.execute(select(EvalRun))).scalars().all())
    avg = round(sum(r.overall_accuracy_score for r in all_evals) / len(all_evals), 1) if all_evals else 0.0

    return EvalBatchResult(
        evaluated_count=len(new_eval_records),
        total_eval_runs=len(all_evals),
        average_accuracy_score=avg
    )
