from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base

class ScrapedJob(Base):
    __tablename__ = "scraped_jobs"

    id = Column(String, primary_key=True, index=True)
    organization_id = Column(String, nullable=False, default="org-1", index=True)
    source = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    opportunity_id = Column(String, ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Hash fingerprints for deduplication
    content_hash = Column(String(64), nullable=False, index=True)
    cross_source_hash = Column(String(64), nullable=False, index=True)
    
    # Core attributes
    title = Column(String, nullable=False)
    company_name = Column(String, nullable=False)
    normalized_company = Column(String, nullable=False)
    normalized_title = Column(String, nullable=False)
    apply_url = Column(String, nullable=False)
    canonical_apply_url = Column(String, nullable=False, index=True)
    location = Column(String, nullable=True)
    salary = Column(String, nullable=True)
    description_raw = Column(Text, nullable=True)
    description_clean = Column(Text, nullable=True)
    
    # Lifecycle & status tracking
    status = Column(String, nullable=False, default="ACTIVE", index=True)
    consecutive_missing_count = Column(Integer, nullable=False, default=0)
    published_at = Column(DateTime(timezone=True), nullable=True)
    last_scraped_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    raw_data = Column(JSON, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    opportunity = relationship("Opportunity", foreign_keys=[opportunity_id], lazy="selectin")
