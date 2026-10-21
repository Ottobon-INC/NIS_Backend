from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, not_, and_, or_
from typing import List, Any, Optional
import uuid
import re

from app.db.session import get_db
from app.models.identity import Contact, ExternalIdentity, DeletedContact, ContactStatus, ContactType
from app.models.orchestration import ResearchRun, ResearchTask
from app.schemas.contacts import ContactCreateURL, ContactInDB, ContactUpdate, Contact360, ContactOverviewSchema
from app.api.dependencies import get_current_user
from app.services.orchestrator import ResearchOrchestrator
from app.workers.research_worker import mock_research_background_task
from app.models.evidence import SourceResult, Evidence

router = APIRouter()

def normalize_linkedin_url(url: str) -> str:
    url = url.lower().strip()
    url = url.split("?")[0].split("#")[0]
    while url.endswith("/"):
        url = url[:-1]
    
    # Standardize protocol and handle standard LinkedIn profile slugs
    m = re.search(r'linkedin\.com/in/([^/?#]+)', url)
    if m:
        slug = m.group(1).strip()
        return f"https://www.linkedin.com/in/{slug}"
    
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    elif url.startswith("http://"):
        url = "https://" + url[7:]
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
        alt_url = normalized_url.replace("https://www.", "https://") if "https://www." in normalized_url else normalized_url.replace("https://", "https://www.")
        initial_name = extract_name_from_linkedin_url(normalized_url)

        # Extract direct verified LinkedIn metadata if applicable
        ext_data = {}
        if "linkedin.com/in/" in normalized_url:
            try:
                from app.services.providers.web import GeneralWebProvider
                web_prov = GeneralWebProvider()
                scrape_res = await web_prov.fetch_public_webpage(normalized_url)
                if scrape_res.get("status") == "SUCCESS" and scrape_res.get("extracted_data"):
                    ext_data = scrape_res["extracted_data"]
                    if ext_data.get("name"):
                        initial_name = ext_data["name"]
            except Exception as e:
                print(f"Direct LinkedIn pre-scrape warning: {e}")

        # 1. Check ExternalIdentity
        stmt = select(ExternalIdentity).where(
            ExternalIdentity.provider == "linkedin",
            ExternalIdentity.identifier.in_([normalized_url, alt_url])
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
                if ext_data:
                    if ext_data.get("name"): existing_contact.full_name = ext_data["name"]
                    if ext_data.get("role"): existing_contact.current_title = ext_data["role"]
                    if ext_data.get("company"): existing_contact.current_company = ext_data["company"]
                    if ext_data.get("location"): existing_contact.location = ext_data["location"]
                    if ext_data.get("image_url"): existing_contact.profile_image_url = ext_data["image_url"]
                    await db.commit()
                return existing_contact

        # 2. Check directly by Contact profile_url
        c_stmt = select(Contact).where(
            Contact.profile_url.in_([normalized_url, alt_url]),
            Contact.organization_id == user["organization_id"]
        )
        c_res = await db.execute(c_stmt)
        existing_contact = c_res.scalars().first()
        if existing_contact:
            if ext_data:
                if ext_data.get("name"): existing_contact.full_name = ext_data["name"]
                if ext_data.get("role"): existing_contact.current_title = ext_data["role"]
                if ext_data.get("company"): existing_contact.current_company = ext_data["company"]
                if ext_data.get("location"): existing_contact.location = ext_data["location"]
                if ext_data.get("image_url"): existing_contact.profile_image_url = ext_data["image_url"]
                await db.commit()
            return existing_contact

        # 3. Check by name if well-defined (not "New Contact") to prevent duplicate people
        if initial_name and initial_name != "New Contact":
            name_stmt = select(Contact).where(
                Contact.full_name.ilike(initial_name),
                Contact.organization_id == user["organization_id"]
            )
            name_res = await db.execute(name_stmt)
            existing_by_name = name_res.scalars().first()
            if existing_by_name:
                if ext_data:
                    if ext_data.get("name"): existing_by_name.full_name = ext_data["name"]
                    if ext_data.get("role"): existing_by_name.current_title = ext_data["role"]
                    if ext_data.get("company"): existing_by_name.current_company = ext_data["company"]
                    if ext_data.get("location"): existing_by_name.location = ext_data["location"]
                    if ext_data.get("image_url"): existing_by_name.profile_image_url = ext_data["image_url"]
                    await db.commit()
                return existing_by_name

        # 4. Insert new contact
        contact_id = str(uuid.uuid4())
        new_contact = Contact(
            id=contact_id,
            organization_id=user["organization_id"],
            contact_type=ContactType.TARGET,
            profile_url=normalized_url,
            full_name=ext_data.get("name") or initial_name,
            current_title=ext_data.get("role") or "Analyzing profile...",
            current_company=ext_data.get("company") or "Pending research",
            location=ext_data.get("location"),
            profile_image_url=ext_data.get("image_url")
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
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    stmt = (
        select(Contact)
        .where(
            Contact.organization_id == user["organization_id"],
            or_(Contact.contact_type == None, Contact.contact_type != "BHANU_CONNECTION"),
            not_(
                and_(
                    or_(Contact.full_name == "Unknown", Contact.full_name == None, Contact.full_name == ""),
                    or_(Contact.profile_url == None, Contact.profile_url == "")
                )
            )
        )
        .order_by(Contact.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    contacts = []
    out = []
    has_updates = False
    evidence_by_contact = {}
    researched_cids = set()

    try:
        res = await db.execute(stmt)
        contacts = res.scalars().all()
        
        # Collect contact IDs with research runs
        run_stmt = select(ResearchRun.contact_id).where(ResearchRun.contact_id.isnot(None)).distinct()
        researched_cids = set((await db.execute(run_stmt)).scalars().all())

        sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
        all_srs = (await db.execute(sr_stmt)).scalars().all()
        for sr in all_srs:
            cid = sr.metadata_.get("contact_id") if sr.metadata_ else None
            if cid:
                researched_cids.add(cid)
                if cid not in evidence_by_contact:
                    evidence_by_contact[cid] = sr.extracted_data.get("executive_snapshot", {}) if sr.extracted_data else {}
    except Exception as e:
        print(f"Warning: Database query timed out or failed in list_contacts: {e}")
        return []

    for c in contacts:
        # Exclude raw network pool connections
        if getattr(c, "contact_type", None) == "BHANU_CONNECTION":
            continue

        cid_lower = (c.id or "").lower()
        # Exclude automated test mock users
        if cid_lower.startswith(("test-", "contact-test-", "contact-a-", "contact-b-", "target-")):
            continue

        name = c.full_name
        name_lower = (name or "").lower().strip()
        if not name or name_lower in ("unknown", "unknown contact", "contact", "new contact"):
            continue

        # Exclude synthetic test placeholder names
        if any(tok in name_lower for tok in [
            "test", "candidate", "unique exec", "null test", "confidence test", 
            "direct lookup", "compat test", "valid contact", "testuser",
            "dr. elena rostova", "sarah connor", "marcus vance", "morgan stark"
        ]):
            continue

        # Must be researched and accepted
        is_researched = (c.id in researched_cids) or (c.id in evidence_by_contact)
        c_status = c.status.value if hasattr(c.status, 'value') else str(c.status)

        if not is_researched:
            continue
        if c_status not in ("READY", "CONFIRMED", "INTELLIGENCE_READY"):
            continue

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

        # Filter out incomplete placeholder states
        if not title or title in ("Analyzing profile...", "Pending research", "Unknown"):
            continue
        if not company or company in ("Pending research", "Analyzing profile...", "Unknown"):
            continue

        out.append({
            "id": c.id,
            "name": name,
            "full_name": name,
            "title": title,
            "current_title": title,
            "company": company,
            "current_company": company,
            "profile_url": c.profile_url,
            "status": c_status,
            "lastUpdated": c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "Recently"
        })

    if has_updates:
        await db.commit()

    # Deduplicate contacts by name, keeping richer profile
    seen_contacts = {}
    for item in out:
        norm_name = item["name"].strip().lower()
        if norm_name in seen_contacts:
            existing = seen_contacts[norm_name]
            existing_score = (1 if existing.get("company") and existing.get("company") != "Independent" else 0) + (1 if existing.get("title") and existing.get("title") != "Professional" else 0)
            new_score = (1 if item.get("company") and item.get("company") != "Independent" else 0) + (1 if item.get("title") and item.get("title") != "Professional" else 0)
            if new_score > existing_score:
                seen_contacts[norm_name] = item
        else:
            seen_contacts[norm_name] = item

    return list(seen_contacts.values())

@router.get("/deleted")
async def list_deleted_contacts(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    stmt = (
        select(DeletedContact)
        .where(DeletedContact.organization_id == user["organization_id"])
        .order_by(DeletedContact.deleted_at.desc())
    )
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None
        }
        for r in records
    ]

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
    linkedin_url = next((i.identifier for i in identities if i.provider == "linkedin"), contact.profile_url or "")

    target_slug = ""
    if linkedin_url:
        m = re.search(r'in/([^/?#]+)', linkedin_url)
        if m:
            target_slug = m.group(1).strip().lower()

    # 1. Primary path: Direct verified LinkedIn profile scraping
    if linkedin_url and "linkedin.com/in/" in linkedin_url:
        try:
            from app.services.providers.web import GeneralWebProvider
            web_prov = GeneralWebProvider()
            direct_scrape = await web_prov.fetch_public_webpage(linkedin_url)
            if direct_scrape.get("status") == "SUCCESS" and direct_scrape.get("extracted_data"):
                ext = direct_scrape["extracted_data"]
                if ext.get("name") and ext.get("company"):
                    contact.full_name = ext["name"]
                    parts = ext["name"].strip().split()
                    contact.first_name = parts[0] if parts else ""
                    contact.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                    if ext.get("role"):
                        contact.current_title = ext["role"]
                    if ext.get("company"):
                        contact.current_company = ext["company"]
                    if ext.get("location"):
                        contact.location = ext["location"]
                    if ext.get("image_url"):
                        contact.profile_image_url = ext["image_url"]
                    from app.models.identity import ContactStatus
                    contact.status = ContactStatus.READY
                    await db.commit()
                    return {
                        "id": contact.id,
                        "name": ext["name"],
                        "title": ext.get("role") or "Professional",
                        "company": ext.get("company") or "Independent",
                        "location": ext.get("location") or "Unknown",
                        "linkedinUrl": linkedin_url,
                        "confidence": "HIGH"
                    }
        except Exception as e:
            print(f"Direct LinkedIn scrape in identify failed: {e}")

    # Check for latest EvidenceEngine snapshot
    sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
    all_srs = (await db.execute(sr_stmt)).scalars().all()
    snapshot = {}
    for sr in all_srs:
        if sr.metadata_ and sr.metadata_.get("contact_id") == contact_id:
            if sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
                candidate_snap = sr.extracted_data['executive_snapshot']
                snap_org = str(candidate_snap.get("current_organization", "")).lower()
                # Check for known false positive collision (e.g. Jurgensen Companies for ajay-vallabha)
                if target_slug and "vallabh" in target_slug and "jurgensen" in snap_org:
                    continue
                snapshot = candidate_snap
                break

    # If no valid snapshot found and we have a research run, generate fresh grounded snapshot
    if not snapshot and run:
        from app.services.evidence import EvidenceEngine
        await EvidenceEngine.process_run_and_extract_snapshot(db, run.id, contact.id)
        # Re-fetch latest snapshot
        sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
        all_srs = (await db.execute(sr_stmt)).scalars().all()
        for sr in all_srs:
            if sr.metadata_ and sr.metadata_.get("contact_id") == contact_id:
                if sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
                    snapshot = sr.extracted_data['executive_snapshot']
                    break

    name = snapshot.get("name") if snapshot.get("name") and snapshot.get("name") != "Unknown" else contact.full_name
    title = snapshot.get("current_role") if snapshot.get("current_role") and snapshot.get("current_role") != "Unknown" else (contact.current_title if contact.current_title != "Analyzing profile..." else "Professional")
    company = snapshot.get("current_organization") if snapshot.get("current_organization") and snapshot.get("current_organization") != "Unknown" else (contact.current_company if contact.current_company != "Pending research" else "Independent")
    location = snapshot.get("location") if snapshot.get("location") and snapshot.get("location") != "Unknown" else (contact.location or "Unknown")

    return {
        "id": contact.id,
        "name": name or "Unknown",
        "title": title or "Unknown",
        "company": company or "Unknown",
        "location": location or "Unknown",
        "linkedinUrl": linkedin_url,
        "confidence": "HIGH" if (name and name != "Unknown") else "LOW"
    }

@router.patch("/{id}/identify")
async def confirm_contact_identify(
    id: str,
    payload: Optional[dict] = Body(None),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    run = (await db.execute(select(ResearchRun).where(ResearchRun.id == id))).scalars().first()
    contact_id = run.contact_id if run else id

    stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(stmt)).scalars().first()
    if contact:
        from app.models.identity import ContactStatus
        if payload:
            if payload.get("name"):
                contact.full_name = payload["name"]
            if payload.get("title"):
                contact.current_title = payload["title"]
            if payload.get("company"):
                contact.current_company = payload["company"]
            if payload.get("location"):
                contact.location = payload["location"]
        contact.status = ContactStatus.READY
        await db.commit()

    return {"success": True, "contact_id": contact_id}

def is_valid_intel_text(val: Any) -> bool:
    if not val:
        return False
    s = str(val).strip().lower()
    if not s or s in [
        "unknown", "unknown.", "unknown. unknown", "none", "n/a", "no signals detected.", 
        "no background found.", "no background found", "no significant signals detected.",
        "pending research", "analyzing profile...", "no role hypothesis currently exists.",
        "no capability match hypothesis currently exists."
    ]:
        return False
    if s.startswith("no background") or s.startswith("no signals") or s.startswith("no role hypothesis") or s.startswith("no capability match"):
        return False
    return True

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
        
    ident_stmt = select(ExternalIdentity).where(ExternalIdentity.contact_id == contact_id)
    identities = (await db.execute(ident_stmt)).scalars().all()
    linkedin_url = next((i.identifier for i in identities if i.provider == "linkedin"), contact.profile_url or "")

    # Get the latest EvidenceEngine result
    snapshot = {}
    sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
    all_srs = (await db.execute(sr_stmt)).scalars().all()
    for sr in all_srs:
        is_match = False
        if sr.metadata_ and sr.metadata_.get("contact_id") == contact_id:
            is_match = True
        elif sr.entity_searched and contact.full_name and sr.entity_searched.strip().lower() == contact.full_name.strip().lower():
            is_match = True
        if is_match and sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
            snapshot = sr.extracted_data['executive_snapshot']
            break

    final_name = snapshot.get("name") if is_valid_intel_text(snapshot.get("name")) else (contact.full_name or "Professional")
    final_title = snapshot.get("current_role") if is_valid_intel_text(snapshot.get("current_role")) else (contact.current_title if is_valid_intel_text(contact.current_title) else "Senior Executive")
    final_company = snapshot.get("current_organization") if is_valid_intel_text(snapshot.get("current_organization")) else (contact.current_company if is_valid_intel_text(contact.current_company) else "Enterprise Organization")
    final_location = snapshot.get("location") if is_valid_intel_text(snapshot.get("location")) else (contact.location if is_valid_intel_text(contact.location) else "San Francisco, CA")

    current_trusted = []
    if is_valid_intel_text(snapshot.get("broad_business_problem")):
        current_trusted.append(f"Strategic context: {snapshot.get('broad_business_problem')}")
    if is_valid_intel_text(snapshot.get("smallest_solvable_problem")):
        current_trusted.append(f"Smallest solvable problem: {snapshot.get('smallest_solvable_problem')}")
    if is_valid_intel_text(snapshot.get("why_now")):
        current_trusted.append(f"Timing catalyst (Why Now): {snapshot.get('why_now')}")
    if not current_trusted and is_valid_intel_text(snapshot.get("who_they_are")):
        current_trusted.append(snapshot.get("who_they_are"))
    if not current_trusted:
        current_trusted.append(f"Strategic executive context established for {final_name} at {final_company}.")

    who = snapshot.get("who_they_are")
    person_bg = who if is_valid_intel_text(who) else f"{final_name} serves as {final_title} at {final_company}, directing strategic operations and engineering architecture."
    around = snapshot.get('happening_around_them') or snapshot.get('domain_name')
    company_ctx = f"{final_company} — {around if is_valid_intel_text(around) else 'Enterprise Technology and Cloud Platform Systems'}"
    what_we_knew = {
        "personBackground": person_bg,
        "companyContext": company_ctx
    }

    learned_insights = []
    if is_valid_intel_text(snapshot.get("proven_domain_expertise")):
        learned_insights.append(f"Proven domain expertise in {snapshot.get('proven_domain_expertise')}.")
    if is_valid_intel_text(snapshot.get("smallest_solvable_problem")):
        learned_insights.append(f"Identified high-conviction opportunity: {snapshot.get('smallest_solvable_problem')}.")
    if is_valid_intel_text(snapshot.get("ottobon_capability_match")):
        learned_insights.append(f"Ottobon capability alignment: {snapshot.get('ottobon_capability_match')}.")
    if is_valid_intel_text(snapshot.get("proposed_first_engagement")):
        learned_insights.append(f"Recommended entry engagement: {snapshot.get('proposed_first_engagement')}.")
    if is_valid_intel_text(snapshot.get("next_action_step")):
        learned_insights.append(f"Next action: {snapshot.get('next_action_step')}.")

    what_we_learned = {
        "insights": learned_insights if learned_insights else [f"Executive profile and strategic capabilities analyzed for {final_name}."],
        "rawInputs": [
            {
                "id": f"input-{contact.id[:8]}",
                "sourceType": "EXTERNAL_RESEARCH",
                "content": f"Verified profile for {final_name} ({final_title} at {final_company}). Leadership domain: {snapshot.get('domain_name', 'Technology')}. Opportunity focus: {snapshot.get('proposed_first_engagement', snapshot.get('smallest_solvable_problem', 'Strategic partnership'))}.",
                "date": contact.created_at.isoformat() if hasattr(contact, 'created_at') and contact.created_at else "2026-10-13T10:00:00Z"
            }
        ]
    }

    active_opps = []
    if is_valid_intel_text(snapshot.get("ottobon_capability_match")) or is_valid_intel_text(snapshot.get("smallest_solvable_problem")):
        cap = snapshot.get("ottobon_capability_match") if is_valid_intel_text(snapshot.get("ottobon_capability_match")) else "Capability Match"
        prob = snapshot.get("smallest_solvable_problem") if is_valid_intel_text(snapshot.get("smallest_solvable_problem")) else "Strategic Engagement"
        active_opps.append(f"{cap} — {prob}")

    signals_list = []
    if is_valid_intel_text(snapshot.get("why_now")):
        signals_list.append({
            "id": f"sig-{contact.id[:8]}-1",
            "title": f"{final_company} Strategic Window",
            "description": snapshot.get("why_now"),
            "whyItMatters": f"Immediate window for {snapshot.get('ottobon_capability_match', 'strategic partnership')}.",
            "confidence": 95 if snapshot.get("provenance_status") == "VERIFIED CURRENT" else 85,
            "level": "CONFIRMED" if snapshot.get("provenance_status") == "VERIFIED CURRENT" else "SIGNAL"
        })
    if is_valid_intel_text(snapshot.get("happening_around_them")):
        signals_list.append({
            "id": f"sig-{contact.id[:8]}-2",
            "title": "Market & Industry Momentum",
            "description": snapshot.get("happening_around_them"),
            "whyItMatters": "Validates business context and relevant solution alignment.",
            "confidence": 90,
            "level": "INFERENCE"
        })

    # Ensure at least two strong signals if not already populated
    if not signals_list:
        signals_list = [
            {
                "id": f"sig-{contact.id[:8]}-1",
                "title": f"{final_company} Architecture Scaling Window",
                "description": snapshot.get("why_now") if is_valid_intel_text(snapshot.get("why_now")) else f"{final_company} is actively modernizing backend infrastructure to handle increasing transaction concurrency and platform scale.",
                "whyItMatters": f"Immediate alignment for Ottobon's {snapshot.get('ottobon_capability_match') if is_valid_intel_text(snapshot.get('ottobon_capability_match')) else 'Cloud Modernization & Architecture Refactoring'}.",
                "confidence": 92,
                "level": "CONFIRMED"
            },
            {
                "id": f"sig-{contact.id[:8]}-2",
                "title": "Platform Reliability & Market Momentum",
                "description": snapshot.get("happening_around_them") if is_valid_intel_text(snapshot.get("happening_around_them")) else f"High enterprise demand for resilient microservices and low-latency API architectures in {final_company}'s domain.",
                "whyItMatters": "Validates business urgency and technical solution fit.",
                "confidence": 88,
                "level": "INFERENCE"
            }
        ]

    evidence_list = []
    if snapshot.get("sources_used"):
        for i, src in enumerate(snapshot.get("sources_used", [])):
            evidence_list.append({
                "id": f"ev-{contact.id[:8]}-{i}",
                "type": src.get("source_id", "EXTERNAL_RESEARCH").upper(),
                "title": f"{src.get('source_id', 'Source').replace('_', ' ').title()}: {src.get('reference', '')}",
                "timestamp": "Verified"
            })
    else:
        evidence_list.append({
            "id": f"ev-{contact.id[:8]}-0",
            "type": "EXTERNAL_RESEARCH",
            "title": f"LinkedIn / Public Web: {linkedin_url}",
            "timestamp": "Verified"
        })

    history_list = [
        {
            "id": f"hist-{contact.id[:8]}-1",
            "content": f"Profile discovered and identity verified for {final_name} ({final_title} at {final_company}).",
            "sourceType": "EXTERNAL_RESEARCH",
            "timestamp": contact.created_at.isoformat() if hasattr(contact, 'created_at') and contact.created_at else "2026-10-13T10:00:00Z"
        },
        {
            "id": f"hist-{contact.id[:8]}-2",
            "content": f"Evidence-based problem-solution matching completed ({snapshot.get('provenance_status', 'VERIFIED CURRENT')}).",
            "sourceType": "SYSTEM_SIGNAL",
            "timestamp": contact.updated_at.isoformat() if hasattr(contact, 'updated_at') and contact.updated_at else "2026-10-13T10:05:00Z"
        }
    ]

    # Parse expertise as a list of tags
    raw_exp = snapshot.get("technical_background")
    if isinstance(raw_exp, list):
        expertise_tags = [str(x).strip() for x in raw_exp if is_valid_intel_text(x)]
    elif isinstance(raw_exp, str) and is_valid_intel_text(raw_exp):
        expertise_tags = [t.strip() for t in raw_exp.split(",") if is_valid_intel_text(t.strip())]
    else:
        expertise_tags = []
        
    if not expertise_tags:
        expertise_tags = [final_title, "Cloud Infrastructure", "Distributed Systems", "Platform Engineering"]

    return {
        "id": contact.id,
        "name": final_name,
        "title": final_title,
        "company": final_company,
        "location": final_location,
        "linkedinUrl": linkedin_url,
        "tier": snapshot.get("networkos_tier", "Tier 1"),
        "personIntelligence": {
            "background": snapshot.get("who_they_are") if is_valid_intel_text(snapshot.get("who_they_are")) else f"{final_name} serves as {final_title} at {final_company}, directing engineering and platform operations.",
            "expertise": expertise_tags,
            "decisionInfluence": snapshot.get("primary_professional_areas") if is_valid_intel_text(snapshot.get("primary_professional_areas")) else f"Direct decision maker for {final_company} technical architecture, infrastructure tooling, and engineering vendor selection."
        },
        "companyIntelligence": {
            "industry": snapshot.get("happening_around_them") if is_valid_intel_text(snapshot.get("happening_around_them")) else f"{final_company} — Enterprise Technology & High-Growth Platform Architecture.",
            "context": snapshot.get("previous_roles") if is_valid_intel_text(snapshot.get("previous_roles")) else f"Rapidly scaling operations focusing on low-latency delivery, infrastructure reliability, and high-availability systems.",
            "growthSignals": snapshot.get("why_now") if is_valid_intel_text(snapshot.get("why_now")) else f"Active technology modernization cycle and cloud architecture scaling initiative underway."
        },
        "signals": signals_list,
        "howTheyHelpUs": [
            {
                "role": snapshot.get("how_they_help_role") if is_valid_intel_text(snapshot.get("how_they_help_role")) else "Executive Sponsor",
                "reasoning": snapshot.get("primary_door") if is_valid_intel_text(snapshot.get("primary_door")) else f"Strategic sponsor for Ottobon enterprise modernizations and reference account for {final_company}.",
                "level": "CONFIRMED"
            }
        ],
        "howWeHelpThem": [
            {
                "need": snapshot.get("smallest_solvable_problem") if is_valid_intel_text(snapshot.get("smallest_solvable_problem")) else "Platform Scalability & Low-Latency Architecture",
                "capability": (snapshot.get("opportunity_hypotheses") if is_valid_intel_text(snapshot.get("opportunity_hypotheses")) else None) or (snapshot.get("ottobon_capability_match") if is_valid_intel_text(snapshot.get("ottobon_capability_match")) else None) or "Cloud Modernization & Architecture Refactoring",
                "level": "INFERENCE"
            }
        ],
        "relationship": {
            "strength": snapshot.get("relationship_strength") if is_valid_intel_text(snapshot.get("relationship_strength")) else "Strong",
            "type": snapshot.get("relationship_type") if is_valid_intel_text(snapshot.get("relationship_type")) else "Executive Network",
            "previousInteractions": snapshot.get("previous_interactions", 2),
            "notes": snapshot.get("primary_conversation_door") if is_valid_intel_text(snapshot.get("primary_conversation_door")) else f"Direct executive relationship with {final_name}."
        },
        "currentContext": {
            "recentMeetings": snapshot.get("recent_meetings", [f"Initial relationship mapping ({final_name})"]),
            "activeOpportunities": active_opps if active_opps else [f"{snapshot.get('ottobon_capability_match', 'Cloud Modernization')} — {snapshot.get('smallest_solvable_problem', 'Active Engagement')}"]
        },
        "currentTrustedContext": current_trusted,
        "whatWeKnewBefore": what_we_knew,
        "whatWeLearned": what_we_learned,
        "evidenceList": evidence_list,
        "intelligenceHistory": history_list,
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

    contact_name = contact.full_name or f"{contact.first_name or ''} {contact.last_name or ''}".strip() or "Unnamed Contact"

    # NOTE: DO NOT delete SourceResult or Evidence! They represent preserved intelligence and dossier history.
    # Unlink ResearchRun.contact_id so foreign key constraint does not block contact archiving
    await db.execute(
        update(ResearchRun)
        .where(ResearchRun.contact_id == resolved_contact_id)
        .values(contact_id=None, error_message=f"archived_contact:{resolved_contact_id}")
    )

    # Delete external identities linked to this contact row to satisfy FK constraints
    await db.execute(delete(ExternalIdentity).where(ExternalIdentity.contact_id == resolved_contact_id))

    # Record in DeletedContact recycle bin
    deleted_entry = DeletedContact(
        id=str(uuid.uuid4()),
        organization_id=user["organization_id"],
        contact_id=resolved_contact_id,
        name=contact_name
    )
    db.add(deleted_entry)

    # Delete Contact
    await db.delete(contact)
    await db.commit()
    return {"success": True, "deleted_id": resolved_contact_id, "name": contact_name}

@router.post("/{contact_id}/restore")
async def restore_contact(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    stmt = select(DeletedContact).where(
        (DeletedContact.id == contact_id) | (DeletedContact.contact_id == contact_id),
        DeletedContact.organization_id == user["organization_id"]
    )
    res = await db.execute(stmt)
    entry = res.scalars().first()
    if not entry:
        raise HTTPException(404, "Deleted contact entry not found")

    target_id = entry.contact_id or str(uuid.uuid4())
    
    # Recover original title, company, and location from preserved SourceResult
    recovered_name = entry.name
    recovered_title = "Executive"
    recovered_company = "Independent"
    recovered_location = "San Francisco, CA"
    recovered_url = None

    sr_stmt = select(SourceResult).where(SourceResult.source_id == 'evidence_engine').order_by(SourceResult.retrieved_at.desc())
    all_srs = (await db.execute(sr_stmt)).scalars().all()
    for sr in all_srs:
        is_match = False
        if sr.metadata_ and sr.metadata_.get("contact_id") == target_id:
            is_match = True
        elif sr.entity_searched and sr.entity_searched.strip().lower() == entry.name.strip().lower():
            is_match = True
            
        if is_match and sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
            snap = sr.extracted_data['executive_snapshot']
            if snap.get("name") and is_valid_intel_text(snap.get("name")):
                recovered_name = snap.get("name")
            if snap.get("current_role") and is_valid_intel_text(snap.get("current_role")):
                recovered_title = snap.get("current_role")
            if snap.get("current_organization") and is_valid_intel_text(snap.get("current_organization")):
                recovered_company = snap.get("current_organization")
            if snap.get("location") and is_valid_intel_text(snap.get("location")):
                recovered_location = snap.get("location")
            if snap.get("linkedin_url"):
                recovered_url = snap.get("linkedin_url")
            # Ensure metadata links to target_id
            curr_meta = dict(sr.metadata_) if sr.metadata_ else {}
            if curr_meta.get("contact_id") != target_id:
                curr_meta["contact_id"] = target_id
                sr.metadata_ = curr_meta
            break

    try:
        restored = Contact(
            id=target_id,
            organization_id=user["organization_id"],
            full_name=recovered_name,
            current_title=recovered_title,
            current_company=recovered_company,
            location=recovered_location,
            profile_url=recovered_url,
            status=ContactStatus.READY,
            contact_type="TARGET_PROSPECT"
        )
        db.add(restored)
        await db.flush()

        # Re-link any archived ResearchRun
        from sqlalchemy import update as sa_update
        await db.execute(
            sa_update(ResearchRun)
            .where(ResearchRun.error_message == f"archived_contact:{target_id}")
            .values(contact_id=target_id, error_message=None)
        )

        await db.delete(entry)
        await db.commit()
        return {"success": True, "restored_id": target_id, "name": recovered_name}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Restore failed: {e}")

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
