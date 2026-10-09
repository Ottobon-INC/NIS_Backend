import os

files = {
    "app/api/dependencies.py": """from fastapi import Header, HTTPException, status

async def get_current_user(authorization: str = Header(default=None)):
    if not authorization or authorization != "Bearer mock-token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"success": False, "error": {"code": "UNAUTHORIZED", "message": "Not authenticated"}}
        )
    return {"user_id": "1", "role": "MEMBER"}

async def get_current_admin(authorization: str = Header(default=None)):
    if not authorization or authorization != "Bearer mock-admin-token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"success": False, "error": {"code": "FORBIDDEN", "message": "Admin access required"}}
        )
    return {"user_id": "2", "role": "ADMIN"}
""",
    "app/models/research.py": """from sqlalchemy import Column, String, Integer, Boolean, Enum, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base
import enum

class SourcePriority(str, enum.Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"

class SourceStatus(str, enum.Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    REQUIRES_CONFIGURATION = "REQUIRES_CONFIGURATION"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"

class ResearchSource(Base):
    __tablename__ = "research_sources"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    source_type = Column(String)
    priority = Column(Enum(SourcePriority), default=SourcePriority.P1)
    status = Column(Enum(SourceStatus), default=SourceStatus.DISABLED)
    provider_type = Column(String)
    description = Column(String)
    supported_entity_types = Column(JSON)
    supported_intelligence_types = Column(JSON)
    reliability_score = Column(Integer, default=50)
    requires_api_key = Column(Boolean, default=False)
    requires_paid_license = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
""",
    "app/models/evidence.py": """from sqlalchemy import Column, String, Integer, Enum, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base
import enum

class EvidenceType(str, enum.Enum):
    FACT = "FACT"
    SIGNAL = "SIGNAL"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"

class SourceResult(Base):
    __tablename__ = "source_results"
    id = Column(String, primary_key=True, index=True)
    source_id = Column(String, ForeignKey("research_sources.id"))
    query = Column(String)
    entity_searched = Column(String)
    retrieved_at = Column(DateTime(timezone=True), server_default=func.now())
    raw_reference = Column(String)
    status = Column(String)
    extracted_data = Column(JSON)
    metadata_ = Column("metadata", JSON)

class Evidence(Base):
    __tablename__ = "evidence"
    id = Column(String, primary_key=True, index=True)
    evidence_type = Column(Enum(EvidenceType))
    claim = Column(String)
    source_id = Column(String, ForeignKey("research_sources.id"))
    source_reference = Column(String)
    observed_date = Column(DateTime(timezone=True))
    retrieved_date = Column(DateTime(timezone=True), server_default=func.now())
    confidence = Column(Integer)
    source_result_id = Column(String, ForeignKey("source_results.id"))
    related_entity_id = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
""",
    "app/models/identity.py": """from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base

class Contact(Base):
    __tablename__ = "contacts"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    id = Column(String, primary_key=True, index=True)
    contact_id = Column(String, ForeignKey("contacts.id"))
    provider = Column(String)
    external_id = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
""",
    "app/models/company_knowledge.py": """from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
from app.db.base import Base

class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Service(Base):
    __tablename__ = "services"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    description = Column(Text)

class Product(Base):
    __tablename__ = "products"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    description = Column(Text)

class Capability(Base):
    __tablename__ = "capabilities"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    description = Column(Text)

class Expertise(Base):
    __tablename__ = "expertise"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)

class Industry(Base):
    __tablename__ = "industries"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)

class UseCase(Base):
    __tablename__ = "use_cases"
    id = Column(String, primary_key=True, index=True)
    name = Column(String)
    description = Column(Text)

class CaseStudy(Base):
    __tablename__ = "case_studies"
    id = Column(String, primary_key=True, index=True)
    title = Column(String)
    content = Column(Text)
""",
    "app/services/providers/base.py": """from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class ResearchProvider(ABC):
    @abstractmethod
    def get_provider_metadata(self) -> Dict[str, Any]:
        pass

    def search_person(self, query: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("search_person not supported by this provider")

    def search_company(self, query: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("search_company not supported by this provider")

    def fetch_person(self, identifier: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("fetch_person not supported by this provider")

    def fetch_company(self, identifier: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("fetch_company not supported by this provider")

    def fetch_signals(self, query: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("fetch_signals not supported by this provider")
""",
    "app/schemas/research.py": """from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.models.research import SourcePriority, SourceStatus

class ResearchSourceBase(BaseModel):
    name: str
    source_type: str
    priority: SourcePriority
    status: SourceStatus
    provider_type: str
    description: Optional[str] = None
    supported_entity_types: Optional[List[str]] = []
    supported_intelligence_types: Optional[List[str]] = []
    reliability_score: int = 50
    requires_api_key: bool = False
    requires_paid_license: bool = False

class ResearchSourceCreate(ResearchSourceBase):
    id: str

class ResearchSourceUpdate(BaseModel):
    status: Optional[SourceStatus] = None
    priority: Optional[SourcePriority] = None

class ResearchSourceInDB(ResearchSourceBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
""",
    "app/schemas/company_knowledge.py": """from pydantic import BaseModel
from typing import Optional

class CKBase(BaseModel):
    name: str
    description: Optional[str] = None

class CKCreate(CKBase):
    pass

class CKUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class CKInDB(CKBase):
    id: str
    class Config:
        from_attributes = True

class CaseStudyBase(BaseModel):
    title: str
    content: Optional[str] = None

class CaseStudyCreate(CaseStudyBase):
    pass

class CaseStudyInDB(CaseStudyBase):
    id: str
    class Config:
        from_attributes = True
""",
    "app/api/v1/endpoints/research.py": """from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.db.session import get_db
from app.models.research import ResearchSource
from app.schemas.research import ResearchSourceCreate, ResearchSourceUpdate, ResearchSourceInDB
from app.api.dependencies import get_current_admin

router = APIRouter()

@router.get("/sources", response_model=List[ResearchSourceInDB])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    result = await db.execute(select(ResearchSource))
    return result.scalars().all()

@router.post("/sources", response_model=ResearchSourceInDB)
async def create_source(
    source_in: ResearchSourceCreate,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    db_obj = ResearchSource(**source_in.model_dump())
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

@router.get("/sources/{source_id}", response_model=ResearchSourceInDB)
async def get_source(
    source_id: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    result = await db.execute(select(ResearchSource).where(ResearchSource.id == source_id))
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail={"success": False, "error": {"code": "NOT_FOUND", "message": "Source not found"}})
    return source

@router.put("/sources/{source_id}", response_model=ResearchSourceInDB)
async def update_source(
    source_id: str,
    source_update: ResearchSourceUpdate,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    result = await db.execute(select(ResearchSource).where(ResearchSource.id == source_id))
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail={"success": False, "error": {"code": "NOT_FOUND", "message": "Source not found"}})
    
    update_data = source_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(source, key, value)
        
    await db.commit()
    await db.refresh(source)
    return source
""",
    "app/api/v1/endpoints/company_knowledge.py": """from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
import uuid

from app.db.session import get_db
from app.models.company_knowledge import Service, Product, Capability, Expertise, Industry, UseCase, CaseStudy
from app.schemas.company_knowledge import CKCreate, CKUpdate, CKInDB, CaseStudyCreate, CaseStudyInDB
from app.api.dependencies import get_current_admin

router = APIRouter()

def create_crud_router(model_class, schema_create, schema_update, schema_response, prefix: str):
    r = APIRouter(prefix=prefix)
    
    @r.get("/", response_model=List[schema_response])
    async def get_all(db: AsyncSession = Depends(get_db), admin: dict = Depends(get_current_admin)):
        res = await db.execute(select(model_class))
        return res.scalars().all()
        
    @r.post("/", response_model=schema_response)
    async def create_item(item: schema_create, db: AsyncSession = Depends(get_db), admin: dict = Depends(get_current_admin)):
        obj = model_class(id=str(uuid.uuid4()), **item.model_dump())
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj
        
    @r.get("/{item_id}", response_model=schema_response)
    async def get_item(item_id: str, db: AsyncSession = Depends(get_db), admin: dict = Depends(get_current_admin)):
        res = await db.execute(select(model_class).where(model_class.id == item_id))
        obj = res.scalars().first()
        if not obj: raise HTTPException(404, detail={"success": False, "error": {"code": "NOT_FOUND", "message": "Item not found"}})
        return obj
        
    @r.put("/{item_id}", response_model=schema_response)
    async def update_item(item_id: str, item: schema_update, db: AsyncSession = Depends(get_db), admin: dict = Depends(get_current_admin)):
        res = await db.execute(select(model_class).where(model_class.id == item_id))
        obj = res.scalars().first()
        if not obj: raise HTTPException(404, detail={"success": False, "error": {"code": "NOT_FOUND", "message": "Item not found"}})
        for k, v in item.model_dump(exclude_unset=True).items():
            setattr(obj, k, v)
        await db.commit()
        await db.refresh(obj)
        return obj
        
    @r.delete("/{item_id}")
    async def delete_item(item_id: str, db: AsyncSession = Depends(get_db), admin: dict = Depends(get_current_admin)):
        res = await db.execute(select(model_class).where(model_class.id == item_id))
        obj = res.scalars().first()
        if not obj: raise HTTPException(404, detail={"success": False, "error": {"code": "NOT_FOUND", "message": "Item not found"}})
        await db.delete(obj)
        await db.commit()
        return {"success": True}
        
    return r

router.include_router(create_crud_router(Service, CKCreate, CKUpdate, CKInDB, "/services"))
router.include_router(create_crud_router(Product, CKCreate, CKUpdate, CKInDB, "/products"))
router.include_router(create_crud_router(Capability, CKCreate, CKUpdate, CKInDB, "/capabilities"))
router.include_router(create_crud_router(Expertise, CKCreate, CKUpdate, CKInDB, "/expertise"))
router.include_router(create_crud_router(Industry, CKCreate, CKUpdate, CKInDB, "/industries"))
router.include_router(create_crud_router(UseCase, CKCreate, CKUpdate, CKInDB, "/use_cases"))
router.include_router(create_crud_router(CaseStudy, CaseStudyCreate, CaseStudyCreate, CaseStudyInDB, "/case_studies"))
""",
    "tests/api/test_research.py": """import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient):
    resp = await client.get("/api/v1/research/sources")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

@pytest.mark.asyncio
async def test_crud_source(client: AsyncClient):
    headers = {"Authorization": "Bearer mock-admin-token"}
    # Create
    resp = await client.post("/api/v1/research/sources", json={
        "id": "github",
        "name": "GitHub",
        "source_type": "Technical",
        "priority": "P0",
        "status": "ENABLED",
        "provider_type": "api",
        "requires_api_key": True
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "github"
    assert data["priority"] == "P0"
    
    # Get
    resp = await client.get("/api/v1/research/sources/github", headers=headers)
    assert resp.status_code == 200
    
    # Update
    resp = await client.put("/api/v1/research/sources/github", json={
        "status": "DISABLED",
        "priority": "P1"
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "DISABLED"
    assert resp.json()["priority"] == "P1"
""",
    "tests/api/test_company_knowledge.py": """import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_crud_services(client: AsyncClient):
    headers = {"Authorization": "Bearer mock-admin-token"}
    # Create
    resp = await client.post("/api/v1/knowledge/services/", json={
        "name": "Cloud Migration",
        "description": "Migrating to AWS"
    }, headers=headers)
    assert resp.status_code == 200
    item_id = resp.json()["id"]
    
    # Get
    resp = await client.get(f"/api/v1/knowledge/services/{item_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Cloud Migration"
    
    # Update
    resp = await client.put(f"/api/v1/knowledge/services/{item_id}", json={
        "name": "Cloud Strategy"
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Cloud Strategy"
    
    # Delete
    resp = await client.delete(f"/api/v1/knowledge/services/{item_id}", headers=headers)
    assert resp.status_code == 200
""",
    "tests/api/test_provider.py": """import pytest
from app.services.providers.base import ResearchProvider

class MockProvider(ResearchProvider):
    def get_provider_metadata(self):
        return {"id": "mock"}

def test_provider_interface_unsupported_methods():
    provider = MockProvider()
    with pytest.raises(NotImplementedError):
        provider.search_person("John")
"""
}

# Ensure directories exist and write files
for filepath, content in files.items():
    directory = os.path.dirname(filepath)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

print("Part 2 foundation successfully scaffolded.")
