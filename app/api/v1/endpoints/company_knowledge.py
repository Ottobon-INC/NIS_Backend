from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
import uuid

from app.db.session import get_db
from app.models.company_knowledge import CompanyProfile, Service, Product, Capability, Expertise, Industry, UseCase, CaseStudy
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

@router.get("/profile", response_model=CKInDB)
async def get_company_profile(db: AsyncSession = Depends(get_db), admin: dict = Depends(get_current_admin)):
    res = await db.execute(select(CompanyProfile).limit(1))
    profile = res.scalars().first()
    if not profile:
        raise HTTPException(404, detail={"success": False, "error": {"code": "NOT_FOUND", "message": "Profile not found"}})
    return profile

@router.put("/profile", response_model=CKInDB)
async def update_company_profile(profile_in: CKUpdate, db: AsyncSession = Depends(get_db), admin: dict = Depends(get_current_admin)):
    res = await db.execute(select(CompanyProfile).limit(1))
    profile = res.scalars().first()
    if not profile:
        import uuid
        profile = CompanyProfile(id=str(uuid.uuid4()), name="NetworkOS Company", description="Default")
        db.add(profile)
    for k, v in profile_in.model_dump(exclude_unset=True).items():
        setattr(profile, k, v)
    await db.commit()
    await db.refresh(profile)
    return profile

router.include_router(create_crud_router(Service, CKCreate, CKUpdate, CKInDB, "/services"))
router.include_router(create_crud_router(Product, CKCreate, CKUpdate, CKInDB, "/products"))
router.include_router(create_crud_router(Capability, CKCreate, CKUpdate, CKInDB, "/capabilities"))
router.include_router(create_crud_router(Expertise, CKCreate, CKUpdate, CKInDB, "/expertise"))
router.include_router(create_crud_router(Industry, CKCreate, CKUpdate, CKInDB, "/industries"))
router.include_router(create_crud_router(UseCase, CKCreate, CKUpdate, CKInDB, "/use_cases"))
router.include_router(create_crud_router(CaseStudy, CaseStudyCreate, CaseStudyCreate, CaseStudyInDB, "/case_studies"))
