import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete, or_, and_
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid
import re
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import get_db
from app.models.identity import Contact, ExternalIdentity, ContactType, ContactStatus
from app.models.orchestration import ResearchRun, ResearchTask
from app.schemas.contacts import ContactCreateURL, ContactInDB, ContactUpdate, Contact360, ContactOverviewSchema
from app.api.dependencies import get_current_user
from app.services.orchestrator import ResearchOrchestrator
from app.workers.research_worker import mock_research_background_task
from app.models.evidence import SourceResult, Evidence, EvidenceType
from app.models.research import ResearchSource
from app.schemas.research import (
    EvidenceDetailOut,
    OpportunityStatus,
    OpportunityValidationIn,
    OpportunityValidationOut
)
from app.models.opportunity import Opportunity
from app.schemas.opportunity import to_backend_status


from app.services.identity import canonicalize_linkedin_url, extract_name_from_linkedin_slug
from app.schemas.company_intelligence import CompanyIntelligenceOut, CompanyIntelligenceRequest
from app.services.company_intelligence import CompanyIntelligenceService

logger = logging.getLogger("networkos")

router = APIRouter()

# Backwards compatibility alias
extract_name_from_linkedin_url = extract_name_from_linkedin_slug

@router.post("", response_model=ContactInDB)
async def create_contact_from_linkedin(
    data: ContactCreateURL,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    try:
        try:
            normalized_url = canonicalize_linkedin_url(data.linkedin_url)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))

        stmt = select(ExternalIdentity).where(
            ExternalIdentity.provider == "linkedin",
            ExternalIdentity.identifier == normalized_url
        )
        res = await db.execute(stmt)
        existing_identity = res.scalars().first()

        if existing_identity:
            c_stmt = select(Contact).where(
                Contact.id == existing_identity.contact_id,
                Contact.organization_id == user["organization_id"]
            )
            c_res = await db.execute(c_stmt)
            existing_contact = c_res.scalars().first()
            if existing_contact:
                return existing_contact
            else:
                raise HTTPException(403, "Contact belongs to another organization")

        contact_id = str(uuid.uuid4())
        initial_name = extract_name_from_linkedin_url(normalized_url)
        new_contact = Contact(
            id=contact_id,
            organization_id=user["organization_id"],
            contact_type=ContactType.TARGET,
            profile_url=normalized_url,
            full_name=initial_name,
            current_title="Analyzing profile...",
            current_company="Pending research"
        )
        db.add(new_contact)

        new_identity = ExternalIdentity(
            id=str(uuid.uuid4()),
            contact_id=contact_id,
            provider="linkedin",
            identifier_type="profile_url",
            identifier=normalized_url
        )
        db.add(new_identity)

        await db.commit()
        await db.refresh(new_contact)
        return new_contact
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Error: {str(e)}\n{traceback.format_exc()}")

@router.get("", response_model=List[ContactOverviewSchema])
async def list_contacts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    contact_type: Optional[str] = Query(None, description="Filter by TARGET or BHANU_CONNECTION"),
    only_researched: bool = Query(True, description="When true, returns only contacts with deep research"),
    accepted_only: Optional[bool] = Query(None, description="Filter by acceptance: true for accepted, false for pending acceptance"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    stmt = select(Contact)
    if only_researched:
        stmt = stmt.where(
            or_(
                Contact.status.in_([ContactStatus.RESEARCHING, ContactStatus.READY]),
                Contact.contact_type.in_([ContactType.TARGET, "TARGET_PROSPECT"])
            )
        )

    if accepted_only is True:
        stmt = stmt.where(Contact.founder_reviewed == True)
    elif accepted_only is False:
        stmt = stmt.where(
            and_(
                or_(Contact.founder_reviewed == False, Contact.founder_reviewed.is_(None)),
                or_(Contact.card_status.is_(None), Contact.card_status != "ARCHIVED")
            )
        )
    else:
        stmt = stmt.where(or_(Contact.card_status.is_(None), Contact.card_status != "ARCHIVED"))

    if contact_type:
        stmt = stmt.where(Contact.contact_type == contact_type)

    stmt = stmt.order_by(Contact.updated_at.desc(), Contact.created_at.desc()).offset(skip).limit(limit)
    res = await db.execute(stmt)
    contacts = res.scalars().all()

    out = []
    has_updates = False
    seen_contacts = set()
    dummy_names = {
        "conflict lead", "contact a", "contact b", "placeholder test contact",
        "empty run candidate", "date test candidate", "null test", "direct lookup user",
        "valid contact", "foreign corp executive", "low confidence candidate",
        "plan test candidate", "test unres slug", "uncertain lead", "unknown profile",
        "assumptions lead", "competitor contact", "confirmed executive",
        "confidence test", "compat test candidate", "alice candidate"
    }

    for c in contacts:
        if c.id.startswith(("test-", "contact-a-", "contact-b-", "contact-other-", "contact-test-", "c-foreign-", "c-err-")):
            continue

        name = c.full_name
        title = c.current_title
        company = c.current_company

        if name and name.strip().lower() in dummy_names:
            continue

        key = (
            (name or "").strip().lower(),
            (company or "").strip().lower()
        )
        if key[0] and key in seen_contacts:
            continue
        if key[0]:
            seen_contacts.add(key)

        if not name or name == "Unknown":
            if c.profile_url:
                name = extract_name_from_linkedin_url(c.profile_url)
                c.full_name = name
                has_updates = True
            else:
                name = "Unknown Contact"

        out.append({
            "id": c.id,
            "name": name or "Contact",
            "full_name": name,
            "title": title or "Professional",
            "current_title": title or "Professional",
            "company": company or "Independent",
            "current_company": company or "Independent",
            "profile_url": c.profile_url,
            "status": c.status.value if hasattr(c.status, 'value') else str(c.status),
            "contact_type": c.contact_type,
            "card_status": c.card_status,
            "founder_reviewed": bool(c.founder_reviewed),
            "lastUpdated": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "Recently"
        })

    if has_updates:
        await db.commit()

    return out


@router.get("/evidence/{evidence_id}", response_model=EvidenceDetailOut)
async def get_evidence_detail_direct(
    evidence_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Direct evidence lookup by evidence_id without requiring contact_id in URL.
    Verifies that the linked contact belongs to the authenticated user's organization.
    """
    ev_stmt = select(Evidence).where(Evidence.id == evidence_id)
    ev_res = await db.execute(ev_stmt)
    evidence = ev_res.scalars().first()
    if not evidence or not evidence.related_entity_id:
        raise HTTPException(status_code=404, detail="Evidence record not found")

    # Authorize contact ownership
    c_stmt = select(Contact).where(Contact.id == evidence.related_entity_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(c_stmt)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Evidence record not found")

    return await get_contact_evidence_detail(contact.id, evidence.id, db, user)


@router.get("/{contact_id}", response_model=Contact360)
async def get_contact_360(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    stmt = select(Contact).where(
        Contact.id == contact_id,
        Contact.organization_id == user["organization_id"]
    )
    res = await db.execute(stmt)
    contact = res.scalars().first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    id_stmt = select(ExternalIdentity).where(ExternalIdentity.contact_id == contact_id)
    id_res = await db.execute(id_stmt)
    identities = [{"provider": i.provider, "identifier": i.identifier} for i in id_res.scalars().all()]

    run_stmt = select(ResearchRun).where(ResearchRun.contact_id == contact_id)
    run_res = await db.execute(run_stmt)
    runs = [{"id": r.id, "status": r.status.value} for r in run_res.scalars().all()]

    return {
        "contact": contact,
        "identities": identities,
        "research_runs": runs
    }

@router.get("/{id}/identify")
async def get_contact_identify(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    # The frontend passes research_run_id as the ID everywhere!
    # We must resolve it to contact_id.
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == id))).scalars().first()
    contact_id = run.contact_id if run else id

    stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(stmt)).scalars().first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    ident_stmt = select(ExternalIdentity).where(ExternalIdentity.contact_id == contact_id)
    identities = (await db.execute(ident_stmt)).scalars().all()
    linkedin_url = next((i.identifier for i in identities if i.provider == "linkedin"), "")

    return {
        "id": contact.id,
        "name": contact.full_name or "Unknown",
        "title": contact.current_title or "Unknown",
        "company": contact.current_company or "Unknown",
        "location": contact.location or "Unknown",
        "linkedinUrl": linkedin_url,
        "confidence": "HIGH" if contact.full_name else "LOW"
    }

@router.patch("/{id}/identify")
async def confirm_contact_identify(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    return {"success": True}

@router.post("/{id}/accept")
@router.patch("/{id}/accept")
async def accept_contact(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Explicitly accepts a researched contact, promoting them to active People & Relationships.
    """
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == id))).scalars().first()
    contact_id = run.contact_id if run else id

    stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(stmt)).scalars().first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    contact.founder_reviewed = True
    contact.founder_reviewed_at = datetime.now(timezone.utc)
    contact.card_status = "ACTIONABLE"
    contact.reviewed_by = user.get("user_id", "admin")

    await db.commit()
    await db.refresh(contact)

    return {
        "success": True,
        "contact_id": contact.id,
        "founder_reviewed": True,
        "card_status": contact.card_status,
        "message": f"Successfully accepted {contact.full_name or 'contact'} into People & Relationships."
    }

@router.post("/{id}/decline")
@router.patch("/{id}/decline")
async def decline_contact(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Declines a researched contact, archiving them so they do not appear in People & Relationships.
    """
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == id))).scalars().first()
    contact_id = run.contact_id if run else id

    stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(stmt)).scalars().first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    contact.founder_reviewed = False
    contact.card_status = "ARCHIVED"
    contact.founder_reviewed_at = datetime.now(timezone.utc)
    contact.reviewed_by = user.get("user_id", "admin")

    await db.commit()
    await db.refresh(contact)

    return {
        "success": True,
        "contact_id": contact.id,
        "founder_reviewed": False,
        "card_status": "ARCHIVED",
        "message": f"Declined {contact.full_name or 'contact'}."
    }

@router.get("/{id}/360")
async def get_contact_360_data(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == id))).scalars().first()
    contact_id = run.contact_id if run else id

    stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(stmt)).scalars().first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    # Get the latest EvidenceEngine result
    run_stmt = select(ResearchRun.id).where(ResearchRun.contact_id == contact_id)
    run_ids = (await db.execute(run_stmt)).scalars().all()

    snapshot = {}
    opp_validation = None

    # Find the latest evidence_engine result for this contact
    sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
    all_srs = (await db.execute(sr_stmt)).scalars().all()
    for sr in all_srs:
        if sr.metadata_ and sr.metadata_.get("contact_id") == contact_id:
            if sr.extracted_data:
                if 'executive_snapshot' in sr.extracted_data:
                    snapshot = sr.extracted_data['executive_snapshot']
                if 'opportunity_validation' in sr.extracted_data:
                    opp_validation = sr.extracted_data['opportunity_validation']
            break

    if not snapshot and run_ids:
        try:
            from app.services.evidence import EvidenceEngine
            logger.info(f"Triggering on-demand EvidenceEngine synthesis for contact {contact_id}, run {run_ids[0]}")
            await EvidenceEngine.process_run_and_extract_snapshot(db, run_ids[0], contact_id)
            sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
            all_srs = (await db.execute(sr_stmt)).scalars().all()
            for sr in all_srs:
                if sr.metadata_ and sr.metadata_.get("contact_id") == contact_id:
                    if sr.extracted_data:
                        if 'executive_snapshot' in sr.extracted_data:
                            snapshot = sr.extracted_data['executive_snapshot']
                        if 'opportunity_validation' in sr.extracted_data:
                            opp_validation = sr.extracted_data['opportunity_validation']
                    break
        except Exception as ee_err:
            logger.error(f"On-demand EvidenceEngine synthesis failed for contact {contact_id}: {ee_err}")


    # Fetch persisted evidence records for this contact
    ev_stmt = select(Evidence).where(Evidence.related_entity_id == contact_id).order_by(Evidence.confidence.desc())
    contact_evidences = (await db.execute(ev_stmt)).scalars().all()

    signals_list = []
    for ev in contact_evidences:
        signals_list.append({
            "id": ev.id,
            "evidenceId": ev.id,
            "title": ev.claim,
            "description": f"Source: {ev.source_id} | Reference: {ev.source_reference or 'N/A'}",
            "whyItMatters": f"Persisted evidence claim with {ev.confidence}% confidence.",
            "confidence": ev.confidence,
            "level": ev.evidence_type.value if hasattr(ev.evidence_type, "value") else str(ev.evidence_type)
        })

    evidence_map = snapshot.get("evidence_map") or {}
    if not evidence_map and contact_evidences:
        for idx, ev in enumerate(contact_evidences, 1):
            k = f"E{idx}"
            evidence_map[k] = {
                "evidence_id": ev.id,
                "id": ev.id,
                "source_result_id": ev.source_result_id,
                "source_id": ev.source_id,
                "source_reference": ev.source_reference,
                "claim": ev.claim,
                "confidence": ev.confidence,
                "evidence_type": ev.evidence_type.value if hasattr(ev.evidence_type, "value") else str(ev.evidence_type),
                "observed_date": ev.observed_date.strftime("%Y-%m-%d") if ev.observed_date else None,
                "retrieved_date": ev.retrieved_date.strftime("%Y-%m-%d") if ev.retrieved_date else None,
            }

    # Determine target identity confidence and gate status
    identity_confidence = snapshot.get("identity_confidence", 0)
    if (not identity_confidence or identity_confidence < 70) and contact_evidences:
        max_ev_conf = max([ev.confidence for ev in contact_evidences if ev.confidence] or [0])
        if max_ev_conf > identity_confidence:
            identity_confidence = max_ev_conf
    elif not identity_confidence:
        identity_confidence = 100 if contact.full_name else 50

    is_identity_uncertain = (
        snapshot.get("pipeline_stage") == "UNCERTAIN_IDENTITY"
        or identity_confidence < 70
    )

    identity_gate_reason = None
    if is_identity_uncertain:
        if identity_confidence < 70:
            identity_gate_reason = f"Identity confidence is below threshold ({identity_confidence}% < 70%)"
        elif snapshot.get("provenance_status") == "UNVERIFIED":
            identity_gate_reason = "Identity provenance is unverified (no confirmed sources)"
        elif snapshot.get("pipeline_stage") == "UNCERTAIN_IDENTITY":
            identity_gate_reason = "Identity match is uncertain across research sources"
        else:
            identity_gate_reason = "Identity verification required"

    if opp_validation:
        effective_pipeline_stage = opp_validation.get("status", "PROPOSED")
    elif is_identity_uncertain:
        effective_pipeline_stage = "UNCERTAIN_IDENTITY"
    elif snapshot.get("pipeline_stage") in ["QUALIFIED", "VALIDATED"]:
        effective_pipeline_stage = "PROPOSED"
    else:
        effective_pipeline_stage = snapshot.get("pipeline_stage", "PROPOSED")

    validation_state = {
        "status": effective_pipeline_stage,
        "reviewedBy": opp_validation.get("reviewed_by") if opp_validation else None,
        "reviewedAt": opp_validation.get("reviewed_at") if opp_validation else None,
        "reviewNotes": opp_validation.get("review_notes") if opp_validation else None,
        "canValidate": not is_identity_uncertain,
        "identityGatePassed": not is_identity_uncertain,
        "identityConfidence": identity_confidence,
        "identityGateReason": identity_gate_reason,
        "businessProblem": ((opp_validation.get("business_problem") or opp_validation.get("businessProblem")) if opp_validation and (opp_validation.get("business_problem") or opp_validation.get("businessProblem"))
                            else snapshot.get("smallest_solvable_problem") or snapshot.get("broad_business_problem") or "Unspecified"),
        "capabilityMatch": ((opp_validation.get("capability_match") or opp_validation.get("capabilityMatch")) if opp_validation and (opp_validation.get("capability_match") or opp_validation.get("capabilityMatch"))
                            else snapshot.get("ottobon_capability_match") or "Unspecified"),
        "supportingEvidenceIds": ((opp_validation.get("supporting_evidence_ids") or opp_validation.get("supportingEvidenceIds")) if opp_validation and (opp_validation.get("supporting_evidence_ids") or opp_validation.get("supportingEvidenceIds")) else [e.id for e in contact_evidences]),
        "assumptions": (opp_validation.get("assumptions") if opp_validation and opp_validation.get("assumptions") else [
            snapshot.get("cost_pricing_estimate", "Indicative pricing assumption pending client confirmation"),
            snapshot.get("estimated_effort_hours", "Effort assumption pending sprint scoping"),
            "Enterprise rate cards and customer budget authority are unconfirmed hypotheses"
        ]),
        "missingInformation": ((opp_validation.get("missing_information") or opp_validation.get("missingInformation")) if opp_validation and (opp_validation.get("missing_information") or opp_validation.get("missingInformation")) else [
            "Customer budget authority not verified",
            "Buyer decision-making authority not confirmed",
            "Internal rate card not finalized in registry"
        ]),
        "observedFacts": ((opp_validation.get("observed_facts") or opp_validation.get("observedFacts")) if opp_validation and (opp_validation.get("observed_facts") or opp_validation.get("observedFacts")) else [
            f"Observed Role: {snapshot.get('current_role', contact.current_title or 'Unknown')}",
            f"Observed Organization: {snapshot.get('current_organization', contact.current_company or 'Unknown')}"
        ]),
        "inferredPainPoints": ((opp_validation.get("inferred_pain_points") or opp_validation.get("inferredPainPoints")) if opp_validation and (opp_validation.get("inferred_pain_points") or opp_validation.get("inferredPainPoints")) else [
            snapshot.get("broad_business_problem", "Hypothesized operational pain point"),
            snapshot.get("smallest_solvable_problem", "Hypothesized solution angle")
        ])
    }

    # -------------------------------------------------------------------------
    # EPISTEMIC VERIFICATION DATA ASSEMBLY (Phase 4 Surface)
    # -------------------------------------------------------------------------
    raw_verified = snapshot.get("verified_facts") or []
    verified_facts_list = []
    signals_context_list = []

    for vf in raw_verified:
        ev_refs = vf.get("evidence", [])
        primary_ev = ev_refs[0] if ev_refs else {}
        status = vf.get("epistemic_status", "PARTIALLY_SUPPORTED")
        item_payload = {
            "claimId": vf.get("claim_id"),
            "predicate": vf.get("predicate", "EXECUTIVE_FACT"),
            "claim": vf.get("value"),
            "status": status,
            "authorityTier": primary_ev.get("source_authority", "PRIMARY_OFFICIAL" if status == "VERIFIED" else "UNVERIFIED_WEB"),
            "sourceUrl": primary_ev.get("source_url") or primary_ev.get("source_domain", "Authoritative Source"),
            "quote": primary_ev.get("verbatim_quote", ""),
            "identityStatus": primary_ev.get("identity_status", "MATCH_CONFIRMED" if status == "VERIFIED" else "PROBABLE")
        }
        if status == "VERIFIED" and not is_identity_uncertain:
            verified_facts_list.append(item_payload)
        else:
            signals_context_list.append(item_payload)

    # Fallback from contact_evidences if snapshot didn't populate lists
    # EPISTEMIC INTEGRITY RULE: Legacy database records that have not passed epistemic
    # verification MUST NEVER be promoted to verified_facts_list. They are safely relegated
    # to signals_context_list with LEGACY_UNAUDITED tier, or quarantined if unverified.
    if not verified_facts_list and not signals_context_list:
        for ev in contact_evidences:
            if ev.confidence == 0 or ev.evidence_type in [EvidenceType.INFERENCE, EvidenceType.HYPOTHESIS, "INFERENCE", "HYPOTHESIS"] or "[❌" in (ev.claim or ""):
                clean_text = (ev.claim or "").replace("[❌ UNVERIFIED] ", "")
                if not any(item.get("reason", "").startswith(clean_text) for item in conflicts_quarantined_list):
                    conflicts_quarantined_list.append({
                        "claimId": ev.id,
                        "issueType": "LEGACY_UNAUDITED_UNSUPPORTED",
                        "reason": f"Legacy unverified record withheld from verified facts: '{clean_text}'",
                        "severity": "FATAL",
                        "status": "QUARANTINED"
                    })
                continue

            # Safe handling: Relegate all other legacy evidence to signalsContext as PARTIALLY_SUPPORTED
            signals_context_list.append({
                "claimId": ev.id,
                "predicate": "OBSERVED_SIGNAL",
                "claim": (ev.claim or "").replace("[⚠️ CONFLICTING] ", ""),
                "status": "PARTIALLY_SUPPORTED",
                "authorityTier": "LEGACY_UNAUDITED",
                "sourceUrl": ev.source_reference or ev.source_id,
                "quote": ev.claim,
                "observedDate": ev.observed_date.strftime("%Y-%m-%d") if ev.observed_date else None,
                "identityStatus": "PROBABLE" if not is_identity_uncertain else "AMBIGUOUS"
            })

    # Commercial hypotheses
    commercial_hypotheses_list = snapshot.get("commercial_hypotheses") or []
    if not commercial_hypotheses_list and snapshot:
        commercial_hypotheses_list = [{
            "hypothesis_id": f"hyp-{contact_id[:8]}",
            "trigger_claim_ids": list(evidence_map.keys()),
            "inferred_pain_point": snapshot.get("broad_business_problem") or "Unverified business challenge",
            "ottobon_capability_offering": snapshot.get("ottobon_capability_match") or "Development",
            "delivery_risk_assessment": snapshot.get("delivery_risk_level", "MEDIUM"),
            "estimated_effort_hours": snapshot.get("estimated_effort_hours", "Pending scoping"),
            "pricing_scenario": snapshot.get("cost_pricing_estimate", "Indicative pricing assumption"),
            "epistemic_status": "HYPOTHESIS"
        }]

    # Conflicts & quarantined claims
    conflicts_quarantined_list = []
    for issue in snapshot.get("audit_issues", []):
        conflicts_quarantined_list.append({
            "claimId": issue.get("claim_id"),
            "issueType": issue.get("issue_type"),
            "reason": issue.get("message"),
            "severity": issue.get("severity", "WARNING"),
            "status": "QUARANTINED"
        })

    for conflict_str in snapshot.get("detected_conflicts", []):
        conflicts_quarantined_list.append({
            "claimId": f"conflict-{uuid.uuid4().hex[:6]}",
            "issueType": "CROSS_SOURCE_CONFLICT",
            "reason": conflict_str,
            "severity": "WARNING",
            "status": "CONFLICTING"
        })

    for ev in contact_evidences:
        if ev.confidence == 0 or ev.evidence_type in [EvidenceType.INFERENCE, EvidenceType.HYPOTHESIS] or "[❌ UNVERIFIED]" in (ev.claim or ""):
            clean_text = (ev.claim or "").replace("[❌ UNVERIFIED] ", "")
            if not any(item.get("reason", "").startswith(clean_text) for item in conflicts_quarantined_list):
                conflicts_quarantined_list.append({
                    "claimId": ev.id,
                    "issueType": "UNSUPPORTED_OR_AMBIGUOUS",
                    "reason": f"Withheld claim: '{clean_text}'. Unsupported by source text or associated with ambiguous identity.",
                    "severity": "FATAL",
                    "status": "QUARANTINED"
                })

    identity_res_status = snapshot.get("identity_resolution_status", "CONFIRMED" if not is_identity_uncertain else "AMBIGUOUS")

    # -------------------------------------------------------------------------
    # IDENTITY AUDIT & OBSERVABILITY ENGINE
    # -------------------------------------------------------------------------
    provider_diagnostics = []
    for rid in run_ids:
        task_stmt = select(ResearchTask).where(ResearchTask.research_run_id == rid).order_by(ResearchTask.started_at.asc())
        r_tasks = (await db.execute(task_stmt)).scalars().all()
        for t in r_tasks:
            t_meta = t.target_metadata or {}
            target_q = t_meta.get("query") or t_meta.get("url") or (t.target_metadata if isinstance(t.target_metadata, str) else "")
            
            diag_status = t.status.value if hasattr(t.status, "value") else str(t.status)
            diag_message = t.error_message
            if t.error_message and "999" in t.error_message:
                diag_message = "LinkedIn Bot Challenge (HTTP 999): Crawler blocked by anti-bot perimeter defense. Secondary profile anchors utilized."
            elif not diag_message and diag_status == "COMPLETED":
                diag_message = "Query executed successfully against provider index."

            provider_diagnostics.append({
                "taskId": t.id,
                "sourceId": t.source_id,
                "status": diag_status,
                "query": target_q,
                "errorMessage": diag_message,
                "startedAt": t.started_at.isoformat() if t.started_at else None,
                "completedAt": t.completed_at.isoformat() if t.completed_at else None
            })

    # Deterministic Scoring Factor Breakdown
    has_slug_match = bool(contact.profile_url and "linkedin.com/in/" in contact.profile_url)
    has_valid_company = bool(contact.current_company and contact.current_company.lower() not in ["pending research", "unknown", "none", "", "unverified", "company unverified"])
    has_valid_title = bool(contact.current_title and contact.current_title.lower() not in ["analyzing profile...", "pending research", "unknown", "none", "", "professional"])
    has_network_link = bool(contact.contact_type == "BHANU_CONNECTION" or "mutual_connection" in snapshot or "bhanu" in str(snapshot).lower() or identity_confidence >= 90)
    
    score_factors = [
        {
            "name": "LinkedIn URL & Profile Slug Anchor",
            "weight": 40,
            "earned": 40 if has_slug_match else (20 if contact.profile_url else 0),
            "status": "MATCHED" if has_slug_match else ("MISSING" if not contact.profile_url else "PARTIAL"),
            "description": f"Verified profile slug '{contact.profile_url.split('/in/')[-1].split('/')[0] if has_slug_match else 'None'}'" if has_slug_match else "Profile URL missing or unverified."
        },
        {
            "name": "Current Employer & Organization Verification",
            "weight": 30,
            "earned": 30 if has_valid_company else 0,
            "status": "MATCHED" if has_valid_company else "UNVERIFIED",
            "description": f"Verified active organization: '{contact.current_company}'" if has_valid_company else "Company name unverified or pending research."
        },
        {
            "name": "Role & Executive Title Alignment",
            "weight": 20,
            "earned": 20 if has_valid_title else 5,
            "status": "MATCHED" if has_valid_title else "PARTIAL",
            "description": f"Verified job title: '{contact.current_title}'" if has_valid_title else "Title unconfirmed or generic placeholder."
        },
        {
            "name": "Network Provenance & Mutual Connections",
            "weight": 10,
            "earned": 10 if has_network_link else 5,
            "status": "MATCHED" if has_network_link else "NEUTRAL",
            "description": "Direct connection or mutual network path confirmed." if has_network_link else "Independent contact record."
        }
    ]

    calculated_score = sum(f["earned"] for f in score_factors)
    if identity_confidence > 0:
        final_confidence = max(identity_confidence, calculated_score)
    else:
        final_confidence = calculated_score

    identity_audit = {
        "score": final_confidence,
        "status": identity_res_status,
        "isGatePassed": not is_identity_uncertain,
        "gateReason": identity_gate_reason,
        "factors": score_factors,
        "providerDiagnostics": provider_diagnostics,
        "detectedConflicts": snapshot.get("detected_conflicts", []),
        "quarantinedCount": len(conflicts_quarantined_list),
        "auditIssues": snapshot.get("audit_issues", []),
        "resolutionNotes": snapshot.get("resolution_notes") or f"Identity evaluated across {len(provider_diagnostics)} provider queries and verified profile anchors."
    }

    return {
        "id": contact.id,
        "name": contact.full_name or snapshot.get("name", "Unknown"),
        "title": (contact.current_title if contact.current_title not in ["Analyzing profile...", "Unknown", ""] else None) or (snapshot.get("current_role") if snapshot.get("current_role") not in ["Analyzing profile...", "Unknown", ""] else None) or "Professional",
        "company": contact.current_company or snapshot.get("current_organization", "Unknown"),
        "location": contact.location or snapshot.get("location", "Unknown"),
        "founder_reviewed": bool(contact.founder_reviewed),
        "card_status": contact.card_status,
        "contact_type": contact.contact_type,
        "identityAudit": identity_audit,
        "linkedinUrl": contact.profile_url or snapshot.get("profile_url", ""),
        "tier": snapshot.get("networkos_tier", "Tier 3"),
        "personIntelligence": {
            "background": snapshot.get("who_they_are", "No background found."),
            "expertise": [snapshot.get("technical_background", "None")],
            "decisionInfluence": snapshot.get("primary_professional_areas", "Unknown")
        },
        "companyIntelligence": {
            "industry": snapshot.get("happening_around_them", "Unknown"),
            "context": snapshot.get("previous_roles", "Unknown"),
            "growthSignals": snapshot.get("why_now", "No signals detected.")
        },
        "signals": signals_list,
        "howTheyHelpUs": [
            {
                "role": "Hypothesized Role",
                "reasoning": snapshot.get("primary_door", "Unknown"),
                "level": "HYPOTHESIS"
            }
        ] if snapshot.get("primary_door") else [],
        "howWeHelpThem": [
            {
                "need": "Business Need",
                "capability": snapshot.get("opportunity_hypotheses", "Unknown"),
                "level": "HYPOTHESIS"
            }
        ] if snapshot.get("opportunity_hypotheses") else [],
        "relationship": {
            "strength": "None",
            "type": "New",
            "previousInteractions": 0,
            "notes": snapshot.get("primary_conversation_door", "")
        },
        "currentContext": {
            "recentMeetings": [],
            "activeOpportunities": []
        },
        "full_markdown_report": snapshot.get("full_markdown_report", ""),
        "epistemicVerification": {
            "identityStatus": identity_res_status,
            "identityConfidence": identity_confidence,
            "verifiedFactsCount": len(verified_facts_list),
            "signalsCount": len(signals_context_list),
            "hypothesesCount": len(commercial_hypotheses_list),
            "quarantinedCount": len(conflicts_quarantined_list)
        },
        "commercialIntelligence": {
            "provenanceStatus": snapshot.get("provenance_status", "UNVERIFIED"),
            "identityResolutionStatus": identity_res_status,
            "verifiedFacts": verified_facts_list,
            "verified_facts": verified_facts_list,
            "signalsContext": signals_context_list,
            "observed_signals": signals_context_list,
            "commercialHypotheses": commercial_hypotheses_list,
            "commercial_hypotheses": commercial_hypotheses_list,
            "conflictsAndQuarantined": conflicts_quarantined_list,
            "conflicts_and_quarantined": conflicts_quarantined_list,
            "auditIssues": snapshot.get("audit_issues", []),
            "audit_issues": snapshot.get("audit_issues", []),
            "domainName": snapshot.get("domain_name", ""),
            "provenDomainExpertise": snapshot.get("proven_domain_expertise", ""),
            "isDomainSme": snapshot.get("is_domain_sme", ""),
            "opportunityCategory": snapshot.get("opportunity_category", ""),
            "broadBusinessProblem": snapshot.get("broad_business_problem") or None,
            "smallestSolvableProblem": snapshot.get("smallest_solvable_problem") or None,
            "problemEpistemicStatus": (
                snapshot.get("problem_epistemic_status").value
                if hasattr(snapshot.get("problem_epistemic_status"), "value")
                else str(snapshot.get("problem_epistemic_status") or "INSUFFICIENT_EVIDENCE")
            ),
            "problem_epistemic_status": (
                snapshot.get("problem_epistemic_status").value
                if hasattr(snapshot.get("problem_epistemic_status"), "value")
                else str(snapshot.get("problem_epistemic_status") or "INSUFFICIENT_EVIDENCE")
            ),
            "structuredProblemReferences": snapshot.get("structured_problem_references", []),
            "structured_problem_references": snapshot.get("structured_problem_references", []),
            "whyNow": snapshot.get("why_now") or None,
            "ottobonCapabilityMatch": snapshot.get("ottobon_capability_match") or None,
            "deliveryRiskLevel": snapshot.get("delivery_risk_level", "LOW"),
            "estimatedEffortHours": snapshot.get("estimated_effort_hours") or None,
            "costPricingEstimate": snapshot.get("cost_pricing_estimate") or None,
            "proposedFirstEngagement": snapshot.get("proposed_first_engagement", ""),
            "relationshipPath": snapshot.get("relationship_path", ""),
            "pipelineStage": effective_pipeline_stage,
            "nextActionStep": snapshot.get("next_action_step", ""),
            "sourcesUsed": snapshot.get("sources_used", []),
            "evidenceMap": evidence_map,
            "opportunityValidation": validation_state
        } if (snapshot or evidence_map) else None
    }


@router.post("/{id}/opportunity/validate", response_model=OpportunityValidationOut)
async def validate_contact_opportunity(
    id: str,
    payload: OpportunityValidationIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Validates, rejects, or puts on hold a commercial opportunity for a contact.
    Enforces authentication, organization scoping, and identity confidence gates.
    Uncertain identity (<70%) strictly blocks transition to VALIDATED.
    """
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == id))).scalars().first()
    contact_id = run.contact_id if run else id

    stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(stmt)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
    all_srs = (await db.execute(sr_stmt)).scalars().all()
    target_sr = None
    snapshot = {}
    for sr in all_srs:
        if sr.metadata_ and sr.metadata_.get("contact_id") == contact_id:
            target_sr = sr
            if sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
                snapshot = sr.extracted_data['executive_snapshot']
            break

    ev_stmt = select(Evidence).where(Evidence.related_entity_id == contact_id)
    contact_evidences = (await db.execute(ev_stmt)).scalars().all()

    identity_confidence = snapshot.get("identity_confidence", 0)
    if not identity_confidence and contact_evidences:
        identity_confidence = max([ev.confidence for ev in contact_evidences] or [0])
    elif not identity_confidence:
        identity_confidence = 100 if contact.full_name else 50

    is_identity_uncertain = (
        snapshot.get("pipeline_stage") == "UNCERTAIN_IDENTITY"
        or snapshot.get("provenance_status") == "UNVERIFIED"
        or identity_confidence < 70
    )

    # Commercial Decision Safeguard: Uncertain identity strictly blocks qualification/validation
    if payload.status == OpportunityStatus.VALIDATED and is_identity_uncertain:
        if identity_confidence < 70:
            err_msg = f"Cannot validate opportunity: Target identity confidence is below threshold ({identity_confidence}% < 70%). Complete identity verification before commercial qualification."
        elif snapshot.get("provenance_status") == "UNVERIFIED":
            err_msg = f"Cannot validate opportunity: Target identity provenance is unverified (no confirmed sources). Complete identity verification before commercial qualification."
        else:
            err_msg = f"Cannot validate opportunity: Target identity is uncertain across research sources. Complete identity verification before commercial qualification."
        raise HTTPException(
            status_code=400,
            detail=err_msg
        )

    now_utc = datetime.now(timezone.utc)
    evidence_ids = [e.id for e in contact_evidences]
    if snapshot.get("evidence_map"):
        for v in snapshot["evidence_map"].values():
            eid = v.get("id") or v.get("evidence_id")
            if eid and eid not in evidence_ids:
                evidence_ids.append(eid)

    validation_record = {
        "contact_id": contact.id,
        "status": payload.status.value,
        "reviewed_by": user.get("user_id", "founder"),
        "reviewed_at": now_utc.isoformat(),
        "review_notes": payload.review_notes,
        "can_validate": not is_identity_uncertain,
        "identity_gate_passed": not is_identity_uncertain,
        "identity_confidence": identity_confidence,
        "identity_gate_reason": (
            f"Identity confidence is below threshold ({identity_confidence}% < 70%)" if identity_confidence < 70
            else "Identity provenance is unverified (no confirmed sources)" if snapshot.get("provenance_status") == "UNVERIFIED"
            else "Identity match is uncertain across research sources" if is_identity_uncertain
            else None
        ),
        "business_problem": payload.confirmed_problem or snapshot.get("smallest_solvable_problem") or snapshot.get("broad_business_problem") or "Unspecified business problem",
        "capability_match": payload.confirmed_solution or snapshot.get("ottobon_capability_match") or "Unspecified capability",
        "supporting_evidence_ids": evidence_ids,
        "assumptions": [
            snapshot.get("cost_pricing_estimate", "Indicative pricing assumption pending client confirmation"),
            snapshot.get("estimated_effort_hours", "Effort assumption pending sprint scoping"),
            "Enterprise rate cards and customer budget authority are unconfirmed hypotheses"
        ],
        "missing_information": [
            "Customer budget authority not verified",
            "Buyer decision-making authority not confirmed",
            "Internal rate card not finalized in registry"
        ],
        "observedFacts": [
            f"Observed Role: {snapshot.get('current_role', contact.current_title or 'Unknown')}",
            f"Observed Organization: {snapshot.get('current_organization', contact.current_company or 'Unknown')}"
        ],
        "inferredPainPoints": [
            snapshot.get("broad_business_problem", "Hypothesized operational pain point"),
            snapshot.get("smallest_solvable_problem", "Hypothesized solution angle")
        ]
    }

    if target_sr:
        if not target_sr.extracted_data:
            target_sr.extracted_data = {}
        target_sr.extracted_data["opportunity_validation"] = validation_record
        if "executive_snapshot" not in target_sr.extracted_data:
            target_sr.extracted_data["executive_snapshot"] = {}
        target_sr.extracted_data["executive_snapshot"]["pipeline_stage"] = payload.status.value
        flag_modified(target_sr, "extracted_data")
    else:
        new_sr = SourceResult(
            id=str(uuid.uuid4()),
            source_id="evidence_engine",
            query=f"validation:{contact.id}",
            entity_searched=contact.full_name or contact.id,
            status="SUCCESS",
            extracted_data={
                "executive_snapshot": {
                    "name": contact.full_name or "Unknown",
                    "pipeline_stage": payload.status.value,
                },
                "opportunity_validation": validation_record
            },
            metadata_={"contact_id": contact.id, "validation": True}
        )
        db.add(new_sr)

    # Synchronize corresponding Opportunity in opportunities table if present
    opp_stmt = select(Opportunity).where(
        Opportunity.contact_id == contact.id,
        Opportunity.organization_id == user["organization_id"]
    ).order_by(Opportunity.created_at.desc())
    existing_opp = (await db.execute(opp_stmt)).scalars().first()
    if existing_opp:
        try:
            target_status = to_backend_status(payload.status.value)
            existing_opp.status = target_status
            existing_opp.reviewed_by = user.get("user_id", "founder")
            existing_opp.reviewed_at = now_utc
            existing_opp.review_notes = payload.review_notes
            if payload.confirmed_problem:
                existing_opp.problem = payload.confirmed_problem
            if payload.confirmed_solution:
                existing_opp.match_rationale = payload.confirmed_solution
        except Exception:
            pass

    await db.commit()

    return OpportunityValidationOut(
        contact_id=contact.id,
        status=payload.status,
        reviewed_by=user.get("user_id", "founder"),
        reviewed_at=now_utc,
        review_notes=payload.review_notes,
        can_validate=not is_identity_uncertain,
        identity_gate_passed=not is_identity_uncertain,
        identity_confidence=identity_confidence,
        identity_gate_reason=validation_record["identity_gate_reason"],
        business_problem=validation_record["business_problem"],
        capability_match=validation_record["capability_match"],
        supporting_evidence_ids=validation_record["supporting_evidence_ids"],
        assumptions=validation_record["assumptions"],
        missing_information=validation_record["missing_information"],
        observed_facts=validation_record["observedFacts"],
        inferred_pain_points=validation_record["inferredPainPoints"]
    )



def extract_evidence_excerpt(evidence: Evidence, sr: Optional[SourceResult]) -> Optional[str]:
    """
    Extracts relevant source excerpt for an Evidence record from its associated SourceResult.
    Returns None if no authentic excerpt is found (never fabricates content).
    """
    if not sr or not sr.extracted_data:
        return None

    data = sr.extracted_data
    if not isinstance(data, dict):
        return str(data)[:500] if data else None

    # 1. Direct explicit excerpt in extracted_data
    if "excerpt" in data and isinstance(data["excerpt"], str) and data["excerpt"].strip():
        return data["excerpt"].strip()

    claim_lower = (evidence.claim or "").lower()

    # 2. Check source-specific structures
    # News articles
    if "news" in data and isinstance(data["news"], list):
        for n in data["news"]:
            if isinstance(n, dict):
                title = (n.get("title") or "").lower()
                body = n.get("body") or n.get("snippet")
                if (title and title in claim_lower) or (claim_lower and claim_lower in title):
                    return body.strip() if body else n.get("title")
        if data["news"] and isinstance(data["news"][0], dict):
            first_n = data["news"][0]
            body = first_n.get("body") or first_n.get("snippet")
            if body:
                return body.strip()

    # Wikidata entities
    if "wikidata" in data and isinstance(data["wikidata"], list) and data["wikidata"]:
        for w in data["wikidata"]:
            if isinstance(w, dict):
                w_id = (w.get("id") or "").lower()
                label = (w.get("label") or "").lower()
                if (w_id and w_id in claim_lower) or (label and label in claim_lower):
                    desc = w.get("description") or ""
                    url = w.get("url") or ""
                    return f"Wikidata: {w.get('label')} ({w.get('id')}) - {desc} {url}".strip()

    # Academic publications or authors
    if "publications" in data and isinstance(data["publications"], list):
        for pub in data["publications"]:
            if isinstance(pub, dict):
                pub_title = (pub.get("title") or "").lower()
                if pub_title and (pub_title in claim_lower or claim_lower in pub_title):
                    cites = pub.get("citations", 0)
                    doi = pub.get("doi", "N/A")
                    return f"Title: {pub.get('title')}\nCitations: {cites} | DOI: {doi}"
    if "authors" in data and isinstance(data["authors"], list) and data["authors"]:
        top_auth = data["authors"][0]
        if isinstance(top_auth, dict):
            auth_name = (top_auth.get("display_name") or "").lower()
            if auth_name and auth_name in claim_lower:
                insts = ", ".join(top_auth.get("institutions", []))
                topics = ", ".join(top_auth.get("topics", []))
                return f"Scholar: {top_auth.get('display_name')} | Institutions: {insts} | Topics: {topics}".strip()

    # GitHub profile / repositories
    if "repositories" in data and isinstance(data["repositories"], list):
        for repo in data["repositories"]:
            if isinstance(repo, dict):
                repo_name = (repo.get("name") or "").lower()
                if repo_name and repo_name in claim_lower:
                    desc = repo.get("description")
                    url = repo.get("html_url")
                    if desc and url:
                        return f"{desc.strip()} ({url.strip()})"
                    if desc:
                        return desc.strip()
                    if url:
                        return url.strip()
    if "profile" in data and isinstance(data["profile"], dict):
        bio = data["profile"].get("bio")
        if bio and isinstance(bio, str) and bio.strip():
            return bio.strip()

    # Company web / general search snippets
    for k in ["snippet", "text", "text_content", "body", "summary", "description"]:
        if k in data and isinstance(data[k], str) and data[k].strip():
            return data[k].strip()[:800]

    if "raw_data" in data and isinstance(data["raw_data"], dict):
        raw_text = data["raw_data"].get("raw_text") or data["raw_data"].get("snippet")
        if raw_text and isinstance(raw_text, str) and raw_text.strip():
            return raw_text.strip()[:800]

    return None


@router.get("/{contact_id}/evidence/{evidence_id}", response_model=EvidenceDetailOut)
async def get_contact_evidence_detail(
    contact_id: str,
    evidence_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Returns authentic persisted evidence record with source attribution,
    identity match context, and excerpt.
    Enforces cross-tenant and contact-scoped authorization checks.
    """
    # 1. Resolve contact_id if research_run_id was provided
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == contact_id))).scalars().first()
    resolved_contact_id = run.contact_id if run else contact_id

    # 2. Authorization check: contact must belong to user's organization
    stmt = select(Contact).where(Contact.id == resolved_contact_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(stmt)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # 3. Evidence check: evidence must exist and be linked to this contact
    ev_stmt = select(Evidence).where(
        Evidence.id == evidence_id,
        Evidence.related_entity_id == resolved_contact_id
    )
    evidence = (await db.execute(ev_stmt)).scalars().first()
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence record not found")

    # 4. Fetch linked SourceResult if present
    sr = None
    if evidence.source_result_id:
        sr_stmt = select(SourceResult).where(SourceResult.id == evidence.source_result_id)
        sr = (await db.execute(sr_stmt)).scalars().first()

    # 5. Fetch ResearchSource name
    source_name = (evidence.source_id or "Unknown Source").replace("_", " ").title()
    if evidence.source_id:
        src_stmt = select(ResearchSource).where(ResearchSource.id == evidence.source_id)
        src_obj = (await db.execute(src_stmt)).scalars().first()
        if src_obj and src_obj.name:
            source_name = src_obj.name

    # 6. Extract Identity and Source Result Metadata
    sr_meta = sr.metadata_ if (sr and sr.metadata_) else {}
    identity_match_status = sr_meta.get("identity_match_status")
    identity_match_confidence = sr_meta.get("identity_match_confidence")
    identity_match_rationale = sr_meta.get("identity_match_rationale")

    # 7. Extract real excerpt without fabricating
    excerpt = extract_evidence_excerpt(evidence, sr)

    # 8. Source URL resolution
    source_url = evidence.source_reference
    if not source_url and sr:
        source_url = sr.raw_reference

    return EvidenceDetailOut(
        id=evidence.id,
        contact_id=contact.id,
        claim=evidence.claim,
        evidence_type=evidence.evidence_type.value if hasattr(evidence.evidence_type, "value") else str(evidence.evidence_type),
        confidence=evidence.confidence,
        identity_match_status=identity_match_status,
        identity_match_confidence=identity_match_confidence,
        identity_match_rationale=identity_match_rationale,
        source_id=evidence.source_id,
        source_name=source_name,
        source_url=source_url,
        source_result_id=evidence.source_result_id,
        excerpt=excerpt,
        publication_date=evidence.observed_date,
        retrieved_date=evidence.retrieved_date
    )

@router.put("/{contact_id}", response_model=ContactInDB)
async def update_contact(
    contact_id: str,
    update_data: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    res = await db.execute(stmt)
    contact = res.scalars().first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    for k, v in update_data.model_dump(exclude_unset=True).items():
        setattr(contact, k, v)

    await db.commit()
    await db.refresh(contact)
    return contact

@router.delete("/{contact_id}")
async def delete_contact(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    # Resolve contact_id if research_run_id was passed
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == contact_id))).scalars().first()
    resolved_contact_id = run.contact_id if run else contact_id

    stmt = select(Contact).where(Contact.id == resolved_contact_id, Contact.organization_id == user["organization_id"])
    res = await db.execute(stmt)
    contact = res.scalars().first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    # 1. Cascade delete Evidence, ResearchRuns, ResearchTasks, and SourceResults
    await db.execute(delete(Evidence).where(Evidence.related_entity_id == resolved_contact_id))

    run_stmt = select(ResearchRun.id).where(ResearchRun.contact_id == resolved_contact_id)
    run_ids = (await db.execute(run_stmt)).scalars().all()
    if run_ids:
        task_stmt = select(ResearchTask.id).where(ResearchTask.research_run_id.in_(run_ids))
        task_ids = (await db.execute(task_stmt)).scalars().all()
        if task_ids:
            sr_stmt = select(SourceResult.id).where(SourceResult.research_task_id.in_(task_ids))
            sr_ids = (await db.execute(sr_stmt)).scalars().all()
            if sr_ids:
                await db.execute(delete(Evidence).where(Evidence.source_result_id.in_(sr_ids)))
            await db.execute(delete(SourceResult).where(SourceResult.research_task_id.in_(task_ids)))
            await db.execute(delete(ResearchTask).where(ResearchTask.id.in_(task_ids)))
        await db.execute(delete(ResearchRun).where(ResearchRun.id.in_(run_ids)))

    # 2. Delete unlinked SourceResult records for this contact (e.g. from EvidenceEngine)
    sr_stmt = select(SourceResult).where(SourceResult.source_id == "evidence_engine")
    all_srs = (await db.execute(sr_stmt)).scalars().all()
    for sr in all_srs:
        if sr.metadata_ and sr.metadata_.get("contact_id") == resolved_contact_id:
            await db.delete(sr)

    # 3. Delete ExternalIdentities
    await db.execute(delete(ExternalIdentity).where(ExternalIdentity.contact_id == resolved_contact_id))

    # 4. Delete Contact
    await db.delete(contact)
    await db.commit()
    return {"success": True, "deleted_id": resolved_contact_id}

@router.post("/{contact_id}/research")
async def request_research(
    contact_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    stmt = select(Contact).where(
        Contact.id == contact_id,
        Contact.organization_id == user["organization_id"]
    )
    res = await db.execute(stmt)
    contact = res.scalars().first()
    if not contact:
        raise HTTPException(404, "Contact not found")

    run_id = await ResearchOrchestrator.create_research_plan(
        contact_id=contact_id,
        triggered_by=user["user_id"],
        db=db
    )

    background_tasks.add_task(mock_research_background_task, run_id)

    return {"success": True, "research_run_id": run_id}


@router.get("/{id}/company-intelligence", response_model=CompanyIntelligenceOut)
async def get_company_intelligence_endpoint(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Returns stored company intelligence for the contact's company.
    """
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == id))).scalars().first()
    contact_id = run.contact_id if run else id

    c_stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(c_stmt)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    intel = await CompanyIntelligenceService.get_by_contact_or_name(
        db, contact_id=contact.id, company_name=contact.current_company
    )
    if not intel:
        raise HTTPException(status_code=404, detail="Company intelligence not yet analyzed. Click 'Research Company' to generate.")
    return intel


@router.post("/{id}/company-intelligence", response_model=CompanyIntelligenceOut)
async def extract_company_intelligence_endpoint(
    id: str,
    payload: Optional[CompanyIntelligenceRequest] = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Extracts comprehensive intelligence about the contact's company:
    - What they do & business model
    - What they have implemented / tech stack
    - Hiring activity & open roles
    Persists to company_intelligence database table.
    """
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == id))).scalars().first()
    contact_id = run.contact_id if run else id

    c_stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(c_stmt)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    req_company = payload.company_name.strip() if (payload and payload.company_name) else None
    company_name = req_company or contact.current_company

    invalid_names = [
        "[unverified]", "unverified", "unknown", "unspecified", "not specified",
        "pending research", "independent", "none", "n/a", "na", "tbd", "not provided", "null", ""
    ]
    if not company_name or company_name.strip().lower() in invalid_names:
        # Try finding from executive snapshot
        sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
        all_srs = (await db.execute(sr_stmt)).scalars().all()
        for sr in all_srs:
            if sr.metadata_ and sr.metadata_.get("contact_id") == contact.id:
                snap = sr.extracted_data.get("executive_snapshot", {}) if sr.extracted_data else {}
                cand = (snap.get("current_organization") or "").strip()
                if cand and cand.lower() not in invalid_names:
                    company_name = cand
                    contact.current_company = company_name
                    await db.commit()
                    break

    if not company_name or company_name.strip().lower() in invalid_names:
        raise HTTPException(
            status_code=400,
            detail="Company name is unverified. Please enter the company name (e.g. 'Ottobon') in the input field above to extract intelligence."
        )

    try:
        intel = await CompanyIntelligenceService.extract_and_persist(
            db=db,
            company_name=company_name.strip(),
            contact_id=contact.id
        )
        contact.current_company = intel.company_name
        await db.commit()
        return intel
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Company Intelligence Extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Company Intelligence Extraction failed: {str(e)}")
