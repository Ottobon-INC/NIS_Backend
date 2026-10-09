from pydantic import BaseModel
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
