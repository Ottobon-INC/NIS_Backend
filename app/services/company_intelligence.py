import logging
import uuid
import asyncio
from typing import Dict, Any, Optional, List, Literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.models.company_intelligence import CompanyIntelligence
from app.models.identity import Contact
from app.services.providers.search import DuckDuckGoProvider

logger = logging.getLogger("networkos")

class CompanyExtractionSchema(BaseModel):
    company_name: str = Field(description="Official name of the company")
    website: Optional[str] = Field(default=None, description="Primary website domain or URL of the company")
    industry: str = Field(description="Primary industry or sector, e.g., Enterprise Software, Cloud Infrastructure, FinTech")
    overview: str = Field(description="Detailed narrative of what the company does, their core business model, key products/services, and customer base")
    what_they_implemented: str = Field(description="Technical initiatives, platforms, systems, and architectures they have implemented or launched")
    is_hiring: bool = Field(description="True if the company is actively or moderately hiring")
    hiring_status: Literal["ACTIVELY_HIRING", "MODERATE", "LOW_OR_NONE", "UNKNOWN"] = Field(
        description="Current hiring activity level"
    )
    hiring_roles: List[str] = Field(default=[], description="Specific open roles, expanding departments, or engineering talent sought")
    technologies_used: List[str] = Field(default=[], description="Key technologies, platforms, cloud services, and frameworks identified")
    key_initiatives: List[str] = Field(default=[], description="Strategic company initiatives, recent milestones, or ongoing digital transformations")
    summary_markdown: str = Field(description="Comprehensive GitHub-flavored markdown report answering: What does the company do? What have they implemented? What are their hiring needs and open roles? What opportunities exist?")

class CompanyIntelligenceService:
    @staticmethod
    async def get_by_contact_or_name(db: AsyncSession, contact_id: Optional[str] = None, company_name: Optional[str] = None) -> Optional[CompanyIntelligence]:
        """Looks up existing persisted company intelligence from database, ignoring unverified placeholder records."""
        if contact_id:
            stmt = select(CompanyIntelligence).where(
                CompanyIntelligence.contact_id == contact_id,
                ~CompanyIntelligence.company_name.in_(["[UNVERIFIED]", "UNKNOWN", "Unknown", "Pending research", "None"])
            ).order_by(CompanyIntelligence.updated_at.desc())
            res = (await db.execute(stmt)).scalars().first()
            if res:
                return res

        if company_name:
            clean_name = company_name.strip()
            if clean_name.lower() not in ["[unverified]", "unverified", "unknown", "pending research", "none", ""]:
                stmt = select(CompanyIntelligence).where(
                    CompanyIntelligence.company_name.ilike(f"%{clean_name}%"),
                    ~CompanyIntelligence.company_name.in_(["[UNVERIFIED]", "UNKNOWN", "Unknown", "Pending research", "None"])
                ).order_by(CompanyIntelligence.updated_at.desc())
                res = (await db.execute(stmt)).scalars().first()
                if res:
                    return res

        return None

    @staticmethod
    async def extract_and_persist(
        db: AsyncSession,
        company_name: str,
        contact_id: Optional[str] = None
    ) -> CompanyIntelligence:
        """
        Gathers live intelligence on the company across:
        1. Company overview & what they do
        2. What they have implemented / tech stack / platforms
        3. Hiring activity & open roles
        Synthesizes with GPT-4o and permanently stores in the database.
        """
        clean_company = company_name.strip()
        if not clean_company or clean_company.lower() in [
            "[unverified]", "unverified", "unknown", "pending research", "none", "independent", "n/a", ""
        ]:
            raise ValueError("Please provide a valid company name (e.g. 'Ottobon') to extract company intelligence.")

        logger.info(f"CompanyIntelligence: Initiating deep extraction for '{clean_company}'")

        sources_list: List[Dict[str, Any]] = []
        context_parts: List[str] = []

        # 1. Check for internal enterprise knowledge (Ottobon / NetworkOS / related)
        is_internal_or_ottobon = any(k in clean_company.lower() for k in ["ottobon", "networkos", "autobahn"])
        if is_internal_or_ottobon:
            try:
                from sqlalchemy import text
                profiles = (await db.execute(text("SELECT name, description FROM company_profiles"))).fetchall()
                products = (await db.execute(text("SELECT name, description FROM products"))).fetchall()
                services = (await db.execute(text("SELECT name, description FROM services"))).fetchall()
                capabilities = (await db.execute(text("SELECT name, description FROM capabilities"))).fetchall()

                internal_text = "### VERIFIED INTERNAL ENTERPRISE REPOSITORY:\n"
                for p in profiles:
                    internal_text += f"- Company Profile: {p[0]}: {p[1]}\n"
                if products:
                    internal_text += "\n### IMPLEMENTED PRODUCTS & PLATFORMS:\n"
                    for pr in products:
                        internal_text += f"- Product: {pr[0]}: {pr[1]}\n"
                if services:
                    internal_text += "\n### ENTERPRISE SERVICES & INTEGRATIONS:\n"
                    for sv in services:
                        internal_text += f"- Service: {sv[0]}: {sv[1]}\n"
                if capabilities:
                    internal_text += "\n### CAPABILITIES & ARCHITECTURES:\n"
                    for cp in capabilities:
                        internal_text += f"- Capability: {cp[0]}: {cp[1]}\n"

                context_parts.append(internal_text)
                sources_list.append({
                    "title": "Ottobon Enterprise Knowledge Base",
                    "url": "internal://db/company_knowledge",
                    "snippet": f"Verified internal company profiles, {len(products)} deployed products, and active capabilities."
                })
            except Exception as e:
                logger.warning(f"CompanyIntelligence: Failed to query internal knowledge: {e}")

        # 2. Fetch live web search signals
        ddg = DuckDuckGoProvider()
        from app.services.providers.web import GeneralWebProvider
        web_provider = GeneralWebProvider()

        queries = [
            f"{clean_company} software technology",
            f"{clean_company} products services overview",
            f"{clean_company} careers hiring jobs",
            f"{clean_company} company website"
        ]

        for q in queries:
            try:
                res = await ddg.search_person(q)
                if isinstance(res, dict) and res.get("status") == "SUCCESS":
                    txt = res.get("text_content", "")
                    if txt and "No search results returned" not in txt:
                        context_parts.append(f"### SEARCH SIGNALS ({q}):\n{txt[:1500]}")
                    for r in res.get("extracted_data", {}).get("results", []):
                        href = r.get("href")
                        if href and not any(s.get("url") == href for s in sources_list):
                            sources_list.append({
                                "title": r.get("title"),
                                "url": href,
                                "snippet": r.get("body", "")[:200]
                            })
            except Exception as e:
                logger.warning(f"CompanyIntelligence search error for '{q}': {e}")

        # 3. If a direct homepage/domain is discovered, fetch the landing page
        candidate_webpages = [
            s["url"] for s in sources_list
            if s.get("url") and not any(skip in s["url"].lower() for skip in ["duckduckgo.com", "linkedin.com/login", "momjunction.com", "kidpaw.com"])
        ]
        if candidate_webpages:
            top_webpage = candidate_webpages[0]
            try:
                page_data = await web_provider.fetch_public_webpage(top_webpage)
                if page_data and page_data.get("status") == "SUCCESS":
                    page_text = page_data.get("text_content", "")
                    if page_text:
                        context_parts.append(f"### PRIMARY WEBSITE CONTENT ({top_webpage}):\n{page_text[:3000]}")
            except Exception as e:
                logger.warning(f"CompanyIntelligence webpage fetch error for '{top_webpage}': {e}")

        combined_context = "\n\n".join(context_parts) if context_parts else f"Target company: {clean_company}. No public web records indexed."

        # 4. Prompt LLM to synthesize structured intelligence
        system_prompt = f"""You are an elite corporate intelligence analyst for Ottobon / NetworkOS.
Analyze the provided company context for the organization: "{clean_company}".

Extract accurate, factual intelligence:
1. WHAT THEY DO: Their core business model, key products/services, and customer target.
2. WHAT THEY HAVE IMPLEMENTED: The technical architectures, modernizations, tools, and platforms they have built or deployed.
3. HIRING ACTIVITY: Whether they are hiring (actively, moderately, or not detected) and which specific roles/departments are expanding.
4. KEY INITIATIVES & TECH STACK: Technologies used and ongoing strategic developments.

Write a rich, beautifully formatted markdown report for `summary_markdown` answering:
# {clean_company} - Company & Commercial Intelligence
## 1. What the Company Does
## 2. Systems, Products & Implementations
## 3. Hiring Signals & Growth Demand
## 4. Technology Stack & Key Initiatives
## 5. Potential Collaboration Angles for Ottobon

Ground your analysis strictly in the provided context and pre-trained enterprise domain knowledge for {clean_company}. Do not hallucinate URLs or facts."""

        user_prompt = f"Company Context:\n\n{combined_context}\n\nAnalyze and extract structured company intelligence."

        llm = ChatOpenAI(model="gpt-4o", temperature=0.1, api_key=settings.OPENAI_API_KEY)
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", user_prompt)
        ])
        chain = prompt | llm.with_structured_output(CompanyExtractionSchema)

        extracted: CompanyExtractionSchema = await chain.ainvoke({})

        # 5. Check if record already exists for this contact or company
        existing_record = await CompanyIntelligenceService.get_by_contact_or_name(db, contact_id, clean_company)

        if existing_record:
            existing_record.company_name = extracted.company_name or clean_company
            existing_record.website = extracted.website or existing_record.website
            existing_record.industry = extracted.industry
            existing_record.overview = extracted.overview
            existing_record.what_they_implemented = extracted.what_they_implemented
            existing_record.is_hiring = extracted.is_hiring
            existing_record.hiring_status = extracted.hiring_status
            existing_record.hiring_roles = extracted.hiring_roles
            existing_record.technologies_used = extracted.technologies_used
            existing_record.key_initiatives = extracted.key_initiatives
            existing_record.summary_markdown = extracted.summary_markdown
            existing_record.sources = sources_list
            record = existing_record
        else:
            record_id = str(uuid.uuid4())
            record = CompanyIntelligence(
                id=record_id,
                contact_id=contact_id,
                company_name=extracted.company_name or clean_company,
                website=extracted.website,
                industry=extracted.industry,
                overview=extracted.overview,
                what_they_implemented=extracted.what_they_implemented,
                is_hiring=extracted.is_hiring,
                hiring_status=extracted.hiring_status,
                hiring_roles=extracted.hiring_roles,
                technologies_used=extracted.technologies_used,
                key_initiatives=extracted.key_initiatives,
                summary_markdown=extracted.summary_markdown,
                sources=sources_list
            )
            db.add(record)

        # 6. If contact_id is provided, update the contact's company in database
        if contact_id:
            c_res = await db.execute(select(Contact).where(Contact.id == contact_id))
            target_contact = c_res.scalars().first()
            if target_contact:
                target_contact.current_company = extracted.company_name or clean_company

        await db.commit()
        await db.refresh(record)
        logger.info(f"CompanyIntelligence: Successfully stored company intelligence for {clean_company} (ID: {record.id})")
        return record
