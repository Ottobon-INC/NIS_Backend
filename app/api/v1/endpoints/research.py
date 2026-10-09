from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.db.session import get_db
from app.models.research import ResearchSource, SourceStatus
from app.models.orchestration import ResearchRun, ResearchTask, TaskStatus, RunStatus
from app.schemas.research import ResearchSourceCreate, ResearchSourceUpdate, ResearchSourceInDB
from app.schemas.orchestration import ResearchRunOut, TaskProgress, ResearchTaskOut
from app.api.dependencies import get_current_admin, get_current_user
from fastapi import BackgroundTasks
import uuid
from pydantic import BaseModel

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

@router.get("/runs/{research_run_id}", response_model=ResearchRunOut)
async def get_research_run_status(
    research_run_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(ResearchRun).where(ResearchRun.id == research_run_id))
    run = res.scalars().first()
    if not run:
        raise HTTPException(404, "Run not found")
        
    t_res = await db.execute(select(ResearchTask).where(ResearchTask.research_run_id == research_run_id))
    tasks = t_res.scalars().all()
    
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
    failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
    pending = sum(1 for t in tasks if t.status in [TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING])
    
    progress = TaskProgress(total=total, completed=completed, failed=failed, pending=pending)
    task_outs = [ResearchTaskOut.model_validate(t) for t in tasks]
    
    return ResearchRunOut(
        id=run.id,
        contact_id=run.contact_id,
        status=run.status,
        progress=progress,
        tasks=task_outs
    )

class ManualWebResearchRequest(BaseModel):
    url: str
    entity_type: str

@router.post("/web")
async def manual_web_research(
    req: ManualWebResearchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    from app.services.web.url_security import validate_url_security, SSRError
    
    try:
        validate_url_security(req.url)
    except SSRError as e:
        raise HTTPException(400, detail={"success": False, "error": {"code": "BAD_REQUEST", "message": str(e)}})
        
    res = await db.execute(select(ResearchSource).where(ResearchSource.id == "general_web"))
    source = res.scalars().first()
    if not source:
        source = ResearchSource(
            id="general_web",
            name="General Public Website",
            provider_type="INTERNAL_HTTP",
            status=SourceStatus.ENABLED,
            supported_entity_types=["person", "company"],
            supported_intelligence_types=["profile", "company", "public_web"]
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
        
    run_id = str(uuid.uuid4())
    run = ResearchRun(
        id=run_id,
        contact_id=None,
        status=RunStatus.QUEUED,
        triggered_by=user["user_id"]
    )
    db.add(run)
    
    task_id = str(uuid.uuid4())
    task = ResearchTask(
        id=task_id,
        research_run_id=run_id,
        source_id=source.id,
        status=TaskStatus.PENDING,
        target_metadata={"target_url": req.url, "entity_type": req.entity_type},
        priority="P1"
    )
    db.add(task)
    await db.commit()
    
    from app.workers.research_worker import execute_task
    background_tasks.add_task(execute_task, task_id)
    
    return {"success": True, "research_run_id": run_id, "task_id": task_id}

