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

class ProductBase(BaseModel):
    name: str
    tagline: Optional[str] = None
    category: Optional[str] = None
    description: str
    features: Optional[str] = None
    target_audience: Optional[str] = None
    business_model: Optional[str] = None
    status: Optional[str] = "ACTIVE"

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    tagline: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    features: Optional[str] = None
    target_audience: Optional[str] = None
    business_model: Optional[str] = None
    status: Optional[str] = None

class ProductInDB(ProductBase):
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
