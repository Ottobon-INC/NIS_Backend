from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
import uuid
import re

from app.db.session import get_db
from app.models.identity import Contact, ExternalIdentity
from app.models.orchestration import ResearchRun
from app.schemas.contacts import ContactCreateURL, ContactInDB, ContactUpdate, Contact360
from app.api.dependencies import get_current_user
from app.services.orchestrator import ResearchOrchestrator
from app.workers.research_worker import mock_research_background_task

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
        new_contact = Contact(
            id=contact_id,
            organization_id=user["organization_id"],
            profile_url=normalized_url
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

@router.get("", response_model=List[ContactInDB])
async def list_contacts(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    stmt = select(Contact).where(Contact.organization_id == user["organization_id"]).offset(skip).limit(limit)
    res = await db.execute(stmt)
    return res.scalars().all()

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
    stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    res = await db.execute(stmt)
    contact = res.scalars().first()
    if not contact:
        raise HTTPException(404, "Contact not found")
        
    await db.delete(contact)
    await db.commit()
    return {"success": True}

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
