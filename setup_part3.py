import os
import textwrap

files = {
    "app/api/dependencies.py": """from fastapi import Header, HTTPException, status

async def get_current_user(authorization: str = Header(default=None)):
    if not authorization or authorization != "Bearer mock-token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": {"code": "UNAUTHORIZED", "message": "Not authenticated"}}
        )
    return {"user_id": "1", "role": "MEMBER", "organization_id": "org-1"}

async def get_current_admin(authorization: str = Header(default=None)):
    if not authorization or authorization != "Bearer mock-admin-token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"success": False, "error": {"code": "FORBIDDEN", "message": "Admin access required"}}
        )
    return {"user_id": "2", "role": "ADMIN", "organization_id": "org-1"}
""",
    "app/models/identity.py": """from sqlalchemy import Column, String, DateTime, ForeignKey, Enum
from sqlalchemy.sql import func
from app.db.base import Base
import enum

class ContactStatus(str, enum.Enum):
    NEW = "NEW"
    RESEARCHING = "RESEARCHING"
    READY = "READY"

class Contact(Base):
    __tablename__ = "contacts"
    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, index=True)
    first_name = Column(String)
    last_name = Column(String)
    full_name = Column(String)
    current_title = Column(String)
    current_company = Column(String)
    email = Column(String)
    phone = Column(String)
    location = Column(String)
    profile_url = Column(String)
    profile_image_url = Column(String)
    status = Column(Enum(ContactStatus), default=ContactStatus.NEW)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    id = Column(String, primary_key=True, index=True)
    contact_id = Column(String, ForeignKey("contacts.id"))
    provider = Column(String)
    identifier_type = Column(String)
    identifier = Column(String, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
""",
    "app/models/orchestration.py": """from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum
from sqlalchemy.sql import func
from app.db.base import Base
import enum

class RunStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"

class ResearchRun(Base):
    __tablename__ = "research_runs"
    id = Column(String, primary_key=True, index=True)
    contact_id = Column(String, ForeignKey("contacts.id"))
    status = Column(Enum(RunStatus), default=RunStatus.NOT_STARTED)
    triggered_by = Column(String)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    error_message = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class ResearchTask(Base):
    __tablename__ = "research_tasks"
    id = Column(String, primary_key=True, index=True)
    research_run_id = Column(String, ForeignKey("research_runs.id"))
    source_id = Column(String, ForeignKey("research_sources.id"))
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING)
    priority = Column(String)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    error_message = Column(String)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
""",
    "app/schemas/contacts.py": """from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.models.identity import ContactStatus

class ContactCreateURL(BaseModel):
    linkedin_url: str

class ContactUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    current_title: Optional[str] = None
    current_company: Optional[str] = None

class ContactInDB(BaseModel):
    id: str
    organization_id: str
    full_name: Optional[str] = None
    profile_url: Optional[str] = None
    status: ContactStatus
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class Contact360(BaseModel):
    contact: ContactInDB
    identities: List[dict] = []
    research_runs: List[dict] = []
""",
    "app/schemas/orchestration.py": """from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.models.orchestration import RunStatus, TaskStatus

class TaskProgress(BaseModel):
    total: int
    completed: int
    failed: int
    pending: int

class ResearchTaskOut(BaseModel):
    id: str
    source_id: str
    status: TaskStatus
    class Config:
        from_attributes = True

class ResearchRunOut(BaseModel):
    id: str
    contact_id: str
    status: RunStatus
    progress: Optional[TaskProgress] = None
    tasks: List[ResearchTaskOut] = []
    class Config:
        from_attributes = True
""",
    "app/services/orchestrator.py": """import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.research import ResearchSource, SourceStatus
from app.models.orchestration import ResearchRun, ResearchTask, RunStatus, TaskStatus
import logging

logger = logging.getLogger("networkos")

class ResearchOrchestrator:
    @staticmethod
    async def create_research_plan(contact_id: str, triggered_by: str, db: AsyncSession) -> str:
        run_id = str(uuid.uuid4())
        run = ResearchRun(
            id=run_id,
            contact_id=contact_id,
            triggered_by=triggered_by,
            status=RunStatus.QUEUED
        )
        db.add(run)

        result = await db.execute(select(ResearchSource))
        sources = result.scalars().all()

        for source in sources:
            if source.status != SourceStatus.ENABLED:
                continue
            
            if "person" not in (source.supported_entity_types or []):
                continue
                
            if source.requires_api_key and source.status == SourceStatus.REQUIRES_CONFIGURATION:
                continue

            task = ResearchTask(
                id=str(uuid.uuid4()),
                research_run_id=run_id,
                source_id=source.id,
                status=TaskStatus.PENDING,
                priority=source.priority.value
            )
            db.add(task)

        await db.commit()
        return run_id
""",
    "app/workers/research_worker.py": """import logging
import asyncio

logger = logging.getLogger("networkos")

async def mock_research_background_task(run_id: str):
    logger.info(f"Background task queued for ResearchRun: {run_id}")
    await asyncio.sleep(0.1)
    logger.info(f"Research tasks for {run_id} dispatched to queues.")
""",
    "app/api/v1/endpoints/contacts.py": """from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
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

@router.post("/", response_model=ContactInDB)
async def create_contact_from_linkedin(
    data: ContactCreateURL,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
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

@router.get("/", response_model=List[ContactInDB])
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
""",
    "tests/api/test_orchestration.py": """import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_contact_creation_and_research(client: AsyncClient):
    headers = {"Authorization": "Bearer mock-token"}
    
    resp = await client.post("/api/v1/contacts/", json={
        "linkedin_url": "https://linkedin.com/in/testuser/"
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    contact_id = data["id"]
    
    resp2 = await client.post("/api/v1/contacts/", json={
        "linkedin_url": "https://www.linkedin.com/in/testuser"
    }, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] == contact_id
    
    resp = await client.post(f"/api/v1/contacts/{contact_id}/research", headers=headers)
    assert resp.status_code == 200
    run_id = resp.json()["research_run_id"]
    
    resp = await client.get(f"/api/v1/research/runs/{run_id}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "QUEUED"
    assert "progress" in data
"""
}

for filepath, content in files.items():
    directory = os.path.dirname(filepath)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

print("Part 3 foundation successfully scaffolded.")
