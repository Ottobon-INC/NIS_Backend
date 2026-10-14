from sqlalchemy import Column, String, Text, DateTime
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
    name = Column(String, nullable=False)
    tagline = Column(String, nullable=True)
    category = Column(String, nullable=True)
    description = Column(Text, nullable=False)
    features = Column(Text, nullable=True)
    target_audience = Column(String, nullable=True)
    business_model = Column(String, nullable=True)
    status = Column(String, default="ACTIVE")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

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
