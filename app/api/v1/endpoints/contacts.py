from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete
from typing import List
import uuid
import re

from app.db.session import get_db
from app.models.identity import Contact, ExternalIdentity, ContactType
from app.models.orchestration import ResearchRun, ResearchTask
from app.schemas.contacts import ContactCreateURL, ContactInDB, ContactUpdate, Contact360, ContactOverviewSchema
from app.api.dependencies import get_current_user
from app.services.orchestrator import ResearchOrchestrator
from app.workers.research_worker import mock_research_background_task
from app.models.evidence import SourceResult

router = APIRouter()

def normalize_linkedin_url(url: str) -> str:
    url = url.lower().strip()
    if url.endswith("/"):
        url = url[:-1]
    if url.startswith("http://"):
        url = url.replace("http://", "https://")
    if "linkedin.com/in/" in url and not url.startswith("https://"):
        url = "https://" + url
    return url

def extract_name_from_linkedin_url(url: str) -> str:
    m = re.search(r'in/([^/?#]+)', url)
    if m:
        slug = m.group(1).split('-')
        clean_parts = [p for p in slug if not (p.isdigit() or (len(p) > 10 and any(c.isdigit() for c in p)))]
        if clean_parts:
            return " ".join(p.capitalize() for p in clean_parts)
    return "New Contact"

@router.post("", response_model=ContactInDB)
async def create_contact_from_linkedin(
    data: ContactCreateURL,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    try:
        normalized_url = normalize_linkedin_url(data.linkedin_url)

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
    limit: int = Query(50, ge=1, le=100),
    contact_type: str = Query(ContactType.TARGET, description="Filter by TARGET or BHANU_CONNECTION"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    stmt = (
        select(Contact)
        .where(
            Contact.organization_id == user["organization_id"],
            Contact.contact_type == contact_type
        )
        .offset(skip)
        .limit(limit)
    )
    res = await db.execute(stmt)
    contacts = res.scalars().all()
    
    out = []
    has_updates = False
    
    sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
    all_srs = (await db.execute(sr_stmt)).scalars().all()
    evidence_by_contact = {}
    for sr in all_srs:
        cid = sr.metadata_.get("contact_id") if sr.metadata_ else None
        if cid and cid not in evidence_by_contact:
            evidence_by_contact[cid] = sr.extracted_data.get("executive_snapshot", {}) if sr.extracted_data else {}

    for c in contacts:
        name = c.full_name
        title = c.current_title
        company = c.current_company
        
        snap = evidence_by_contact.get(c.id, {})
        if snap:
            if (not name or name == "Unknown") and snap.get("name") and snap.get("name") != "Unknown":
                name = snap.get("name")
                c.full_name = name
                has_updates = True
            if (not title or title == "Analyzing profile..." or title == "Unknown") and snap.get("current_role") and snap.get("current_role") != "Unknown":
                title = snap.get("current_role")
                c.current_title = title
                has_updates = True
            if (not company or company == "Pending research" or company == "Unknown") and snap.get("current_organization") and snap.get("current_organization") != "Unknown":
                company = snap.get("current_organization")
                c.current_company = company
                has_updates = True

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
            "lastUpdated": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "Recently"
        })

    if has_updates:
        await db.commit()

    return out

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
    if run_ids:
        from app.models.orchestration import ResearchTask
        task_stmt = select(ResearchTask.id).where(ResearchTask.research_run_id.in_(run_ids))
        task_ids = (await db.execute(task_stmt)).scalars().all()
        
        # We also need to check source_results that have source_id='evidence_engine' 
        # (they might not have a research_task_id depending on how we saved it)
        # In EvidenceEngine we saved it without research_task_id, but it's global
        # Let's just find the latest evidence_engine result
        # Filter by contact_id inside the metadata JSON
        # For simplicity since it's JSONB, we can use a raw SQL cast or just fetch the most recent and filter in Python
        sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
        all_srs = (await db.execute(sr_stmt)).scalars().all()
        for sr in all_srs:
            if sr.metadata_ and sr.metadata_.get("contact_id") == contact_id:
                if sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
                    snapshot = sr.extracted_data['executive_snapshot']
                break


    return {
        "id": contact.id,
        "name": contact.full_name or snapshot.get("name", "Unknown"),
        "title": contact.current_title or snapshot.get("current_role", "Unknown"),
        "company": contact.current_company or snapshot.get("current_organization", "Unknown"),
        "location": contact.location or snapshot.get("location", "Unknown"),
        "linkedinUrl": "",
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
        "signals": [],
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
        "commercialIntelligence": {
            "provenanceStatus": snapshot.get("provenance_status", "UNVERIFIED"),
            "domainName": snapshot.get("domain_name", ""),
            "provenDomainExpertise": snapshot.get("proven_domain_expertise", ""),
            "isDomainSme": snapshot.get("is_domain_sme", ""),
            "opportunityCategory": snapshot.get("opportunity_category", ""),
            "broadBusinessProblem": snapshot.get("broad_business_problem", ""),
            "smallestSolvableProblem": snapshot.get("smallest_solvable_problem", ""),
            "whyNow": snapshot.get("why_now", ""),
            "ottobonCapabilityMatch": snapshot.get("ottobon_capability_match", ""),
            "deliveryRiskLevel": snapshot.get("delivery_risk_level", "LOW"),
            "estimatedEffortHours": snapshot.get("estimated_effort_hours", ""),
            "costPricingEstimate": snapshot.get("cost_pricing_estimate", ""),
            "proposedFirstEngagement": snapshot.get("proposed_first_engagement", ""),
            "relationshipPath": snapshot.get("relationship_path", ""),
            "pipelineStage": snapshot.get("pipeline_stage", "QUALIFIED"),
            "nextActionStep": snapshot.get("next_action_step", ""),
            "sourcesUsed": snapshot.get("sources_used", [])
        } if snapshot else None
    }

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

    # 1. Cascade delete ResearchRuns, ResearchTasks, and SourceResults
    run_stmt = select(ResearchRun.id).where(ResearchRun.contact_id == resolved_contact_id)
    run_ids = (await db.execute(run_stmt)).scalars().all()
    if run_ids:
        task_stmt = select(ResearchTask.id).where(ResearchTask.research_run_id.in_(run_ids))
        task_ids = (await db.execute(task_stmt)).scalars().all()
        if task_ids:
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
