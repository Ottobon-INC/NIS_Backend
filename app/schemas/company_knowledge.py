from pydantic import BaseModel
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
