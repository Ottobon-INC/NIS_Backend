from sqlalchemy import Column, String, Text, DateTime, Boolean, JSON, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base

class CompanyIntelligence(Base):
    __tablename__ = "company_intelligence"
    id = Column(String, primary_key=True, index=True)
    contact_id = Column(String, ForeignKey("contacts.id", ondelete="SET NULL"), index=True, nullable=True)
    company_name = Column(String, index=True, nullable=False)
    website = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    overview = Column(Text, nullable=True)                  # What they are doing (core mission, products, services)
    what_they_implemented = Column(Text, nullable=True)     # What have they implemented (tech stack, systems, architectures)
    is_hiring = Column(Boolean, default=False)
    hiring_status = Column(String, default="UNKNOWN")       # "ACTIVELY_HIRING" | "MODERATE" | "LOW_OR_NONE" | "UNKNOWN"
    hiring_roles = Column(JSON, nullable=True)              # List of open roles / departments
    technologies_used = Column(JSON, nullable=True)         # Technologies, platforms & tools
    key_initiatives = Column(JSON, nullable=True)           # Strategic initiatives & recent projects
    summary_markdown = Column(Text, nullable=True)          # Detailed analytical markdown report
    sources = Column(JSON, nullable=True)                   # References and URLs searched
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
