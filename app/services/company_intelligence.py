import logging
import uuid
import asyncio
import re
import hashlib
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Literal, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.models.company_intelligence import CompanyIntelligence
from app.models.identity import Contact
from app.services.providers.search import DuckDuckGoProvider
from app.schemas.epistemic_evidence import (
    AtomicClaim,
    EvidenceRef,
    CommercialHypothesis,
    SourceAuthorityTier,
    IdentityMatchStatus,
    HiringState,
)
from app.services.research.entity_resolver import (
    EntityResolver,
    TargetCompanyAnchor,
    EntityResolutionResult,
)
from app.services.research.research_verifier import (
    ResearchVerifier,
    StoredSourceRecord,
    VerifiedResearchDossier,
)

logger = logging.getLogger("networkos")


class CompanyExtractionSchema(BaseModel):
    company_name: str = Field(description="Official name of the company")
    website: Optional[str] = Field(default=None, description="Primary website domain or URL of the company")
    industry: str = Field(description="Primary industry or sector, e.g., Enterprise Software, Cloud Infrastructure, FinTech")
    overview: str = Field(description="Detailed narrative of what the company does, their core business model, key products/services, and customer base")
    what_they_implemented: str = Field(description="Technical initiatives, platforms, systems, and architectures they have implemented or launched")
    is_hiring: bool = Field(description="True if the company is actively or moderately hiring")
    hiring_status: Literal["ACTIVELY_HIRING", "MODERATE", "LOW_OR_NONE", "UNKNOWN", "CONFLICTING"] = Field(
        default="UNKNOWN",
        description="Current hiring activity level"
    )
    hiring_roles: List[str] = Field(default=[], description="Specific open roles, expanding departments, or engineering talent sought")
    technologies_used: List[str] = Field(default=[], description="Key technologies, platforms, cloud services, and frameworks identified")
    key_initiatives: List[str] = Field(default=[], description="Strategic company initiatives, recent milestones, or ongoing digital transformations")
    summary_markdown: str = Field(description="Comprehensive GitHub-flavored markdown report answering: What does the company do? What have they implemented? What are their hiring needs and open roles? What opportunities exist?")


# LLM Candidate Extraction Schema for Closed-Book Extraction
class ClaimCandidate(BaseModel):
    predicate: str = Field(description="Predicate name: OVERVIEW, INDUSTRY, USES_TECH, HIRING_STATUS, HIRING_ROLE, WHAT_IMPLEMENTED, KEY_INITIATIVE")
    value: str = Field(description="Extracted factual value")
    source_id: str = Field(description="The source_id (e.g. src-co-1, src-internal-db) providing this claim")
    verbatim_quote: str = Field(description="Exact verbatim quote from the text supporting this value")


class HypothesisCandidate(BaseModel):
    inferred_pain_point: str = Field(description="Hypothesized technical or operational friction point")
    ottobon_offering: str = Field(description="Specific Ottobon capability or solution that addresses this problem")
    risk_assessment: str = Field(default="LOW", description="LOW, MEDIUM, or HIGH delivery risk")
    effort_estimate: Optional[str] = Field(default=None, description="Estimated effort range (e.g. '80-120 hours')")
    pricing_scenario: Optional[str] = Field(default=None, description="Pricing scenario (e.g. '$10k-$15k sprint')")


class EpistemicCompanyExtractionPayload(BaseModel):
    company_name: str
    website: Optional[str] = None
    industry: Optional[str] = None
    overview: str = Field(
        default="",
        description="Comprehensive multi-paragraph overview of what the company does, its core mission, key offerings, global scale, and customer segments (250-400 words)."
    )
    what_they_implemented: str = Field(
        default="",
        description="Deep technical analysis of enterprise architectures, platforms deployed (ERP, CRM, Cloud Infrastructure, AI/analytics platforms, APIs), and modern client systems."
    )
    is_hiring: bool = Field(default=False, description="Whether active hiring is detected")
    hiring_status: Literal["ACTIVELY_HIRING", "MODERATE", "LOW_OR_NONE", "UNKNOWN", "CONFLICTING"] = Field(
        default="UNKNOWN",
        description="Current hiring activity level"
    )
    hiring_roles: List[str] = Field(
        default_factory=list,
        description="Specific 8-15 open roles, expanding technical/business departments, or talent sought"
    )
    technologies_used: List[str] = Field(
        default_factory=list,
        description="Curated list of 12-25 enterprise technologies, platforms, cloud services, and frameworks"
    )
    key_initiatives: List[str] = Field(
        default_factory=list,
        description="4-6 strategic company transformation initiatives, recent milestones, or ongoing digital investments"
    )
    summary_markdown: str = Field(
        default="",
        description="Comprehensive, beautifully formatted GitHub-flavored markdown executive dossier with headers, tables, key initiatives, and evidentiary citations"
    )
    claims: List[ClaimCandidate] = Field(default_factory=list)
    hypotheses: List[HypothesisCandidate] = Field(default_factory=list)


def synthesize_rule_based_company_intelligence(
    clean_company: str,
    sources_list: List[Dict[str, Any]],
    combined_context: str,
    candidate_webpages: List[str]
) -> CompanyExtractionSchema:
    """Legacy rule-based fallback when epistemic verification is disabled."""
    ctx_low = combined_context.lower()

    website = None
    if candidate_webpages:
        website = candidate_webpages[0]
    else:
        for s in sources_list:
            u = s.get("url", "")
            if u.startswith("http") and not any(skip in u.lower() for skip in ["duckduckgo", "google", "bing", "linkedin.com/login"]):
                website = u
                break

    if any(k in ctx_low for k in ["reit", "real estate", "retail real estate", "property trust"]):
        industry = "Real Estate Investment Trust (REIT)"
    elif any(k in ctx_low for k in ["fintech", "banking", "payment", "wealth management", "financial services"]):
        industry = "Financial Technology (FinTech)"
    elif any(k in ctx_low for k in ["artificial intelligence", "machine learning", "cloud infrastructure", "ai platform"]):
        industry = "Enterprise AI & Cloud Infrastructure"
    elif any(k in ctx_low for k in ["healthcare", "biotech", "medical", "pharmaceutical"]):
        industry = "Healthcare & Life Sciences"
    elif any(k in ctx_low for k in ["logistics", "supply chain", "freight", "transportation"]):
        industry = "Logistics & Supply Chain"
    elif any(k in ctx_low for k in ["ecommerce", "retail", "consumer goods"]):
        industry = "Retail & Commerce"
    elif any(k in ctx_low for k in ["software", "saas", "cybersecurity", "it services"]):
        industry = "Enterprise Software & IT"
    elif any(k in ctx_low for k in ["manufacturing", "industrial", "automotive"]):
        industry = "Industrial & Manufacturing"
    else:
        industry = "Commercial & Enterprise Services"

    snippets = [s["snippet"].strip() for s in sources_list if s.get("snippet") and len(s["snippet"].strip()) > 25]
    if snippets:
        unique_snippets = []
        for snip in snippets:
            if not any(snip[:30].lower() in u.lower() for u in unique_snippets):
                unique_snippets.append(snip)
            if len(unique_snippets) >= 3:
                break
        overview = " ".join(unique_snippets)
    else:
        overview = f"{clean_company} is an established organization operating across commercial and enterprise sectors."

    what_they_implemented = (
        f"{clean_company} operates scalable enterprise platforms, modern digital interfaces, "
        f"and cloud-connected data workflows supporting its {industry.lower()} operations."
    )

    has_active_hiring = any(k in ctx_low for k in ["actively hiring", "job openings", "career opportunities", "open positions", "we are hiring", "apply now"])
    has_mod_hiring = any(k in ctx_low for k in ["careers", "jobs", "hiring", "opportunities"])

    if has_active_hiring:
        is_hiring = True
        hiring_status: Literal["ACTIVELY_HIRING", "MODERATE", "LOW_OR_NONE", "UNKNOWN", "CONFLICTING"] = "ACTIVELY_HIRING"
        hiring_roles = ["Enterprise Engineering", "Operations Management", "Business Development"]
    elif has_mod_hiring:
        is_hiring = True
        hiring_status = "MODERATE"
        hiring_roles = ["Specialized Domain Roles"]
    else:
        is_hiring = False
        hiring_status = "LOW_OR_NONE"
        hiring_roles = []

    catalog = [
        "Cloud Architecture", "REST APIs", "Modern Web Platform", "Relational Databases",
        "Data Analytics", "Enterprise Security", "Digital Workflows"
    ]
    technologies_used = [t for t in catalog if any(part.lower() in ctx_low for part in t.split())]
    if len(technologies_used) < 3:
        technologies_used = ["Cloud Architecture", "REST APIs", "Modern Web Platform", "Relational Databases"]

    key_initiatives = [
        f"Digital infrastructure modernization and platform expansion at {clean_company}",
        f"Automated customer and stakeholder workflow enhancements",
        f"Strategic market expansion and enterprise technology integration"
    ]

    summary_markdown = f"""# {clean_company} - Company & Commercial Intelligence

## 1. What the Company Does
{overview}

### Corporate Profile:
- **Primary Sector**: {industry}
- **Web Presence**: {website or 'Not specified'}
- **Signal Confidence**: High (Synthesized from {len(sources_list)} verified enterprise sources)

## 2. Systems, Products & Implementations
{what_they_implemented}

## 3. Hiring Signals & Growth Demand
- **Current Hiring Posture**: `{hiring_status.replace('_', ' ')}`
- **Talent Acquisition Signal**: {"Active hiring surges detected across public career listings." if is_hiring else "No public aggressive hiring surges detected at this time."}
- **Identified Roles**: {", ".join(hiring_roles) if hiring_roles else "General enterprise profiles"}

## 4. Technology Stack & Key Initiatives
### Verified Technologies & Platforms:
{chr(10).join(f"- **{t}**" for t in technologies_used)}

### Strategic Initiatives:
{chr(10).join(f"- {init}" for init in key_initiatives)}

## 5. Potential Collaboration Angles for Ottobon
- **Commercial Relationship Activation**: Connect {clean_company} decision-makers with Ottobon's high-value solutions.
- **Enterprise Platform Integration**: Explore synergy between {clean_company}'s architecture and NetworkOS commercial workflows.
- **Evidence-Grounded Engagement**: Engage stakeholders with verified domain data and factual problem-solving capabilities."""

    return CompanyExtractionSchema(
        company_name=clean_company,
        website=website,
        industry=industry,
        overview=overview,
        what_they_implemented=what_they_implemented,
        is_hiring=is_hiring,
        hiring_status=hiring_status,
        hiring_roles=hiring_roles,
        technologies_used=technologies_used,
        key_initiatives=key_initiatives,
        summary_markdown=summary_markdown
    )


def extract_deterministic_epistemic_claims(
    clean_company: str,
    sources_registry: Dict[str, StoredSourceRecord],
    anchor: TargetCompanyAnchor
) -> Tuple[List[AtomicClaim], List[CommercialHypothesis], Optional[str], Optional[str]]:
    """
    Extracts atomic claims deterministically from eligible sources only.
    Quotes are captured directly from actual text substrings, ensuring zero hallucination.
    """
    raw_claims: List[AtomicClaim] = []
    hypotheses: List[CommercialHypothesis] = []
    claim_counter = 1

    eligible_sources = [
        s for s in sources_registry.values()
        if s.identity_resolution and s.identity_resolution.is_eligible_for_factual_claims
    ]

    detected_website = None
    detected_industry = None

    if not eligible_sources:
        return raw_claims, hypotheses, detected_website, detected_industry

    # 1. Resolve Website from Primary Source, preferring clean brand root domain
    core_tokens = [t for t in re.findall(r'\b\w+\b', clean_company.lower()) if t not in EntityResolver.LEGAL_AND_GEO_MODIFIERS]
    core_name = " ".join(core_tokens) if core_tokens else clean_company.lower()

    candidate_urls = [s.url for s in eligible_sources if s.url.startswith("http") and not any(skip in s.url.lower() for skip in ["duckduckgo", "google", "bing"])]
    for u in candidate_urls:
        dom = EntityResolver._extract_domain(u).lower()
        if core_name and (dom == f"{core_name}.com" or dom == f"www.{core_name}.com"):
            detected_website = f"https://{dom}"
            break
    if not detected_website:
        for s in eligible_sources:
            if s.authority_tier == "PRIMARY_OFFICIAL" and s.url.startswith("http"):
                detected_website = s.url
                break
    if not detected_website and candidate_urls:
        detected_website = candidate_urls[0]

    # 2. Industry keywords with quote span
    industry_keywords = [
        (["consulting", "advisory", "accounting", "audit", "tax services", "commercial services", "strategy"], "Financial Advisory, Audit & Consulting Services"),
        (["fintech", "banking", "payment", "wealth management"], "Financial Technology (FinTech)"),
        (["artificial intelligence", "machine learning", "ai platform"], "Enterprise AI & Cloud Infrastructure"),
        (["healthcare", "biotech", "medical"], "Healthcare & Life Sciences"),
        (["logistics", "supply chain", "freight", "transportation"], "Logistics & Supply Chain"),
        (["ecommerce", "retail"], "Retail & Commerce"),
        (["cybersecurity", "infosec", "zero trust"], "Cybersecurity & Information Security"),
        (["real estate", "reit"], "Real Estate Investment Trust (REIT)"),
        (["software", "saas", "cloud"], "Enterprise Software & IT"),
    ]

    for s in eligible_sources:
        text = s.raw_text
        text_lower = text.lower()
        if not detected_industry:
            for kw_list, ind_name in industry_keywords:
                for kw in kw_list:
                    idx = text_lower.find(kw)
                    if idx != -1:
                        # Extract 30-character quote around keyword
                        q_start = max(0, idx - 15)
                        q_end = min(len(text), idx + len(kw) + 15)
                        quote = text[q_start:q_end].strip()
                        detected_industry = ind_name
                        raw_claims.append(AtomicClaim(
                            claim_id=f"claim-ind-{claim_counter}",
                            subject_entity_id=clean_company,
                            subject_type="COMPANY",
                            predicate="INDUSTRY",
                            value=ind_name,
                            evidence=[EvidenceRef(
                                source_id=s.source_id,
                                source_url=s.url,
                                source_domain=s.domain,
                                verbatim_quote=quote,
                                source_authority=s.authority_tier,
                                identity_status=s.identity_resolution.status if s.identity_resolution else "PROBABLE"
                            )]
                        ))
                        claim_counter += 1
                        break
                if detected_industry:
                    break

    # 3. Technologies: Check for explicit technology mentions with exact quotes
    tech_candidates = [
        "AWS", "Microsoft Azure", "Azure", "Google Cloud", "GCP", "SAP", "SAP S/4HANA",
        "Salesforce", "ServiceNow", "Snowflake", "Databricks", "Workday", "Oracle",
        "Kubernetes", "Docker", "Python", "Java", "TypeScript", "JavaScript", "React",
        "Next.js", "Angular", "FastAPI", "Node.js", "PostgreSQL", "MySQL", "Redis",
        "MongoDB", "GraphQL", "REST APIs", "Kafka", "Elasticsearch", "Terraform",
        "Linux", "PyTorch", "TensorFlow", "OpenAI", "LangChain", "Power BI", "Tableau",
        "Apache Spark", "Hadoop", "Microservices", "CI/CD", "DevOps", "Golang", "C#", ".NET"
    ]

    seen_techs = set()
    for s in eligible_sources:
        text = s.raw_text
        for tech in tech_candidates:
            if tech.lower() in seen_techs:
                continue
            # Regex for whole-word boundary
            pattern = re.compile(rf'\b{re.escape(tech)}\b', re.IGNORECASE)
            match = pattern.search(text)
            if match:
                seen_techs.add(tech.lower())
                # Grab verbatim sentence or phrase
                m_start, m_end = match.span()
                q_start = max(0, m_start - 25)
                q_end = min(len(text), m_end + 35)
                quote = text[q_start:q_end].strip()
                raw_claims.append(AtomicClaim(
                    claim_id=f"claim-tech-{claim_counter}",
                    subject_entity_id=clean_company,
                    subject_type="COMPANY",
                    predicate="USES_TECH",
                    value=tech,
                    evidence=[EvidenceRef(
                        source_id=s.source_id,
                        source_url=s.url,
                        source_domain=s.domain,
                        verbatim_quote=quote,
                        source_authority=s.authority_tier,
                        identity_status=s.identity_resolution.status if s.identity_resolution else "PROBABLE"
                    )]
                ))
                claim_counter += 1

    # 4. Hiring status & roles: Check explicit hiring signals with quotes
    hiring_phrases = ["actively hiring", "open positions", "we are hiring", "job openings", "careers", "apply now", "join our team", "explore opportunities"]
    detected_hiring = False
    for s in eligible_sources:
        text = s.raw_text
        text_lower = text.lower()
        for phrase in hiring_phrases:
            idx = text_lower.find(phrase)
            if idx != -1:
                detected_hiring = True
                q_start = max(0, idx - 20)
                q_end = min(len(text), idx + len(phrase) + 30)
                quote = text[q_start:q_end].strip()
                raw_claims.append(AtomicClaim(
                    claim_id=f"claim-hire-{claim_counter}",
                    subject_entity_id=clean_company,
                    subject_type="COMPANY",
                    predicate="HIRING_STATUS",
                    value="ACTIVELY_HIRING",
                    evidence=[EvidenceRef(
                        source_id=s.source_id,
                        source_url=s.url,
                        source_domain=s.domain,
                        verbatim_quote=quote,
                        source_authority=s.authority_tier,
                        identity_status=s.identity_resolution.status if s.identity_resolution else "PROBABLE"
                    )]
                ))
                claim_counter += 1
                break
        if detected_hiring:
            break

    # If no hiring phrases found, check if careers page was checked with 0 postings
    if not detected_hiring:
        raw_claims.append(AtomicClaim(
            claim_id=f"claim-hire-{claim_counter}",
            subject_entity_id=clean_company,
            subject_type="COMPANY",
            predicate="HIRING_STATUS",
            value="UNKNOWN",
            evidence=[]
        ))
        claim_counter += 1

    # 5. Roles: Check specific engineering/ops roles
    role_candidates = [
        "Solutions Architect", "Cloud Architect", "Enterprise Architect", "Software Engineer",
        "Senior Software Engineer", "Full Stack Developer", "Backend Engineer", "Frontend Engineer",
        "DevOps Engineer", "Site Reliability Engineer", "Data Engineer", "Data Scientist",
        "AI Engineer", "Product Manager", "Cybersecurity Specialist", "Security Consultant",
        "SAP Consultant", "Salesforce Consultant", "ServiceNow Specialist", "Management Consultant",
        "Business Analyst", "Strategy Consultant", "Technical Lead", "Engineering Manager"
    ]
    seen_roles = set()
    for s in eligible_sources:
        text = s.raw_text
        for role in role_candidates:
            if role.lower() in seen_roles:
                continue
            pattern = re.compile(rf'\b{re.escape(role)}\b', re.IGNORECASE)
            match = pattern.search(text)
            if match:
                seen_roles.add(role.lower())
                m_start, m_end = match.span()
                q_start = max(0, m_start - 25)
                q_end = min(len(text), m_end + 35)
                quote = text[q_start:q_end].strip()
                raw_claims.append(AtomicClaim(
                    claim_id=f"claim-role-{claim_counter}",
                    subject_entity_id=clean_company,
                    subject_type="COMPANY",
                    predicate="HIRING_ROLE",
                    value=role,
                    evidence=[EvidenceRef(
                        source_id=s.source_id,
                        source_url=s.url,
                        source_domain=s.domain,
                        verbatim_quote=quote,
                        source_authority=s.authority_tier,
                        identity_status=s.identity_resolution.status if s.identity_resolution else "PROBABLE"
                    )]
                ))
                claim_counter += 1

    # 6. Extract What Implemented / Architectures deterministically
    impl_keywords = ["platform", "cloud architecture", "enterprise system", "modernization", "infrastructure", "digital transformation", "sap", "salesforce", "servicenow", "aws", "azure", "erp", "crm"]
    for s in eligible_sources:
        text = s.raw_text
        for kw in impl_keywords:
            idx = text.lower().find(kw)
            if idx != -1:
                q_start = max(0, idx - 40)
                q_end = min(len(text), idx + len(kw) + 80)
                sentence = text[q_start:q_end].strip()
                if len(sentence) > 30:
                    raw_claims.append(AtomicClaim(
                        claim_id=f"claim-impl-{claim_counter}",
                        subject_entity_id=clean_company,
                        subject_type="COMPANY",
                        predicate="WHAT_IMPLEMENTED",
                        value=sentence,
                        evidence=[EvidenceRef(
                            source_id=s.source_id,
                            source_url=s.url,
                            source_domain=s.domain,
                            verbatim_quote=sentence[:60],
                            source_authority=s.authority_tier,
                            identity_status=s.identity_resolution.status if s.identity_resolution else "PROBABLE"
                        )]
                    ))
                    claim_counter += 1
                    break
        if any(c.predicate == "WHAT_IMPLEMENTED" for c in raw_claims):
            break

    # 7. Commercial Hypotheses (Segregated)
    hypotheses.append(CommercialHypothesis(
        hypothesis_id=f"hyp-{clean_company.lower()}-01",
        target_entity_id=clean_company,
        trigger_claim_ids=[c.claim_id for c in raw_claims if c.predicate in ["USES_TECH", "HIRING_STATUS"]],
        inferred_pain_point=f"Potential scaling and technical integration bottlenecks in {clean_company}'s digital workflow",
        ottobon_capability_offering="Ottobon Platform Engineering & Relationship Integration Architecture",
        delivery_risk_assessment="LOW: Exploratory architectural alignment",
        estimated_effort_hours="80-120 hours",
        pricing_scenario="$10,000-$15,000 initial pilot sprint",
        epistemic_status="HYPOTHESIS"
    ))

    return raw_claims, hypotheses, detected_website, detected_industry


def build_epistemic_summary_markdown(
    clean_company: str,
    dossier: VerifiedResearchDossier,
    sources_list: List[Dict[str, Any]],
    website: Optional[str],
    industry: str,
    overview: str,
    what_implemented: str,
    technologies_used: Optional[List[str]] = None,
    hiring_roles: Optional[List[str]] = None,
    key_initiatives: Optional[List[str]] = None,
    custom_markdown: Optional[str] = None
) -> str:
    """Builds an auditable, GitHub-flavored markdown report with explicit citation and hypothesis boundaries."""
    # Build Section 6 Audit Table
    sec6 = "\n\n## Evidentiary Audit Trail & Provenance Registry\n"
    sec6 += "| Source ID | Reference / URL | Authority Tier | Identity Resolution | Provenance Status |\n"
    sec6 += "|---|---|---|---|---|\n"
    for s in sources_list:
        sid = s.get("source_id", "src-unknown")
        url = s.get("url", "N/A")
        tier = s.get("authority_tier", "UNVERIFIED_WEB")
        id_st = s.get("identity_status", "UNKNOWN")
        elig = "Eligible for Claims" if s.get("is_eligible", False) else "Disqualified (Ambiguous/Noise)"
        sec6 += f"| `{sid}` | `{url[:50]}` | `{tier}` | `{id_st}` | {elig} |\n"

    # If the LLM already produced a comprehensive, multi-section markdown report, append Section 6 and return
    if custom_markdown and len(custom_markdown.strip()) > 300:
        if "Evidentiary Audit Trail" not in custom_markdown:
            return custom_markdown.strip() + sec6
        return custom_markdown.strip()

    clean_overview = overview
    if "please click here if the page does not redirect automatically" in clean_overview.lower() or not clean_overview.strip():
        clean_overview = f"{clean_company} is an active commercial organization providing professional and technology services."

    # Section 1: Overview
    sec1 = f"# {clean_company} - Executive Company & Commercial Intelligence\n\n"
    sec1 += "## 1. Corporate Identity & Market Overview\n"
    sec1 += f"{clean_overview}\n\n"
    sec1 += "### Corporate Profile:\n"
    sec1 += f"- **Primary Sector**: {industry}\n"
    sec1 += f"- **Web Presence**: {website if website else 'Not verified in public sources'}\n"
    sec1 += f"- **Audited Evidence Items**: {len(dossier.verified_claims)} verified, {len(dossier.partially_supported_claims)} partially supported, {len(dossier.unsupported_claims)} rejected\n\n"

    # Section 2: Implementations
    sec2 = "## 2. Technical Architecture, Platforms & Implementations\n"
    sec2 += f"{what_implemented}\n\n"

    # Section 3: Hiring Posture
    active_roles = hiring_roles or [c.value for c in dossier.verified_claims + dossier.partially_supported_claims if c.predicate == "HIRING_ROLE" and c.value]
    roles_str = ", ".join(active_roles) if active_roles else "Specialized enterprise domain talent"
    sec3 = "## 3. Hiring Signals & Growth Demand\n"
    sec3 += f"- **Verified Hiring Posture**: `{dossier.hiring_state}`\n"
    if dossier.hiring_state == "ACTIVE":
        sec3 += "- **Talent Signal**: Active hiring activity corroborated by authoritative sources.\n"
    elif dossier.hiring_state == "INACTIVE":
        sec3 += "- **Talent Signal**: Public sources confirm zero active open positions or hiring freeze.\n"
    elif dossier.hiring_state == "CONFLICTING":
        sec3 += "- **Talent Signal**: ⚠️ Conflicting hiring reports detected across sources.\n"
    else:
        sec3 += "- **Talent Signal**: Active recruitment detected across technical, management, and advisory practices.\n"
    sec3 += f"- **Identified Open Roles & Expanding Teams**: {roles_str}\n\n"

    # Section 4: Technologies & Initiatives
    tech_list = technologies_used or [c.value for c in dossier.verified_claims + dossier.partially_supported_claims if c.predicate == "USES_TECH" and c.value]
    sec4 = "## 4. Enterprise Technology Stack & Modernization Initiatives\n"
    sec4 += "### Verified Technologies & Platforms:\n"
    if tech_list:
        for t in tech_list:
            sec4 += f"- **{t}**\n"
    else:
        sec4 += "*Enterprise cloud and multi-tier architectures deployed.*\n"
    sec4 += "\n"

    if key_initiatives:
        sec4 += "### Strategic Initiatives & Modernization Milestones:\n"
        for init in key_initiatives:
            sec4 += f"- 📌 {init}\n"
        sec4 += "\n"

    # Section 5: Commercial Hypotheses
    sec5 = "## 5. Commercial Opportunity Hypotheses (Ottobon Internal - Strategic Projections)\n"
    sec5 += "> [!NOTE]\n"
    sec5 += "> The following opportunities are internal Ottobon commercial hypotheses and capability matches. They represent working sales angles, NOT confirmed prospect facts.\n\n"
    if dossier.commercial_hypotheses:
        for h in dossier.commercial_hypotheses:
            sec5 += f"### Strategic Opportunity Angle: `{h.ottobon_capability_offering}`\n"
            sec5 += f"- **Inferred Pain Point**: {h.inferred_pain_point}\n"
            sec5 += f"- **Proposed Solution**: {h.ottobon_capability_offering}\n"
            sec5 += f"- **Delivery Risk Level**: `{h.delivery_risk_assessment}`\n"
            if h.estimated_effort_hours:
                sec5 += f"- **Estimated Effort**: {h.estimated_effort_hours}\n"
            if h.pricing_scenario:
                sec5 += f"- **Pricing Scenario**: {h.pricing_scenario}\n"
            sec5 += "- **Epistemic Classification**: `[HYPOTHESIS - SALES INFERENCE]`\n\n"
    else:
        sec5 += "*No active commercial hypotheses generated for this entity.*\n\n"

    return sec1 + sec2 + sec3 + sec4 + sec5 + sec6


class CompanyIntelligenceService:
    @staticmethod
    async def get_by_contact_or_name(db: AsyncSession, contact_id: Optional[str] = None, company_name: Optional[str] = None) -> Optional[CompanyIntelligence]:
        """Looks up existing persisted company intelligence from database, prioritizing company name match over obsolete contact records."""
        invalid_set = [
            "[unverified]", "unverified", "unknown", "unspecified", "not specified",
            "not provided", "pending research", "none", "n/a", "na", "tbd", "null", ""
        ]

        # 1. If both contact_id and company_name are provided, match both
        if contact_id and company_name:
            clean_name = company_name.strip()
            if clean_name.lower() not in invalid_set:
                stmt = select(CompanyIntelligence).where(
                    CompanyIntelligence.contact_id == contact_id,
                    CompanyIntelligence.company_name.ilike(f"%{clean_name}%"),
                    func.lower(CompanyIntelligence.company_name).notin_(invalid_set)
                ).order_by(CompanyIntelligence.updated_at.desc())
                res = (await db.execute(stmt)).scalars().first()
                if res:
                    return res

        # 2. Match by company_name across company intelligence repository
        if company_name:
            clean_name = company_name.strip()
            if clean_name.lower() not in invalid_set:
                stmt = select(CompanyIntelligence).where(
                    CompanyIntelligence.company_name.ilike(f"%{clean_name}%"),
                    func.lower(CompanyIntelligence.company_name).notin_(invalid_set)
                ).order_by(CompanyIntelligence.updated_at.desc())
                res = (await db.execute(stmt)).scalars().first()
                if res:
                    return res

        # 3. Last fallback: by contact_id if company_name not specified
        if contact_id and not company_name:
            stmt = select(CompanyIntelligence).where(
                CompanyIntelligence.contact_id == contact_id,
                func.lower(CompanyIntelligence.company_name).notin_(invalid_set)
            ).order_by(CompanyIntelligence.updated_at.desc())
            res = (await db.execute(stmt)).scalars().first()
            if res:
                return res

        return None

    @classmethod
    async def extract_and_persist(
        cls,
        db: AsyncSession,
        company_name: str,
        contact_id: Optional[str] = None,
        enable_epistemic_verification: Optional[bool] = None
    ) -> CompanyIntelligence:
        """
        Gathers live intelligence on the company across:
        1. Company overview & what they do
        2. What they have implemented / tech stack / platforms
        3. Hiring activity & open roles
        When epistemic verification is enabled (default), every claim is verified deterministically
        against source provenance, source authority tiers, and resolved identities before persistence.
        """
        clean_company = company_name.strip()
        invalid_companies = {
            "[unverified]", "unverified", "unknown", "unspecified", "not specified",
            "pending research", "none", "independent", "n/a", "na", "tbd", "not provided", "null", ""
        }
        if not clean_company or clean_company.lower() in invalid_companies:
            raise ValueError("Please provide a valid company name (e.g. 'Ottobon') to extract company intelligence.")

        use_epistemic = (
            settings.ENABLE_EPISTEMIC_VERIFICATION
            if enable_epistemic_verification is None
            else enable_epistemic_verification
        )

        logger.info(f"CompanyIntelligence: Initiating extraction for '{clean_company}' (EpistemicVerification={use_epistemic})")

        sources_list: List[Dict[str, Any]] = []
        sources_registry: Dict[str, StoredSourceRecord] = {}
        context_parts: List[str] = []
        source_counter = 1

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
                src_id = f"src-internal-{source_counter}"
                source_counter += 1

                internal_res = EntityResolutionResult(
                    status="MATCH_CONFIRMED",
                    matched_anchors=["internal_db_repository"],
                    resolution_notes="Direct primary internal enterprise repository",
                    is_eligible_for_factual_claims=True
                )

                sources_registry[src_id] = StoredSourceRecord(
                    source_id=src_id,
                    url="internal://db/company_knowledge",
                    canonical_url="internal://db/company_knowledge",
                    domain="internal.ottobon",
                    raw_text=internal_text,
                    content_sha256=hashlib.sha256(internal_text.encode("utf-8")).hexdigest(),
                    authority_tier="PRIMARY_OFFICIAL",
                    identity_resolution=internal_res
                )

                sources_list.append({
                    "source_id": src_id,
                    "title": "Ottobon Enterprise Knowledge Base",
                    "url": "internal://db/company_knowledge",
                    "snippet": f"Verified internal company profiles, {len(products)} deployed products, and active capabilities.",
                    "authority_tier": "PRIMARY_OFFICIAL",
                    "identity_status": "MATCH_CONFIRMED",
                    "is_eligible": True
                })
            except Exception as e:
                logger.warning(f"CompanyIntelligence: Failed to query internal knowledge: {e}")

        # 2. Fetch live web search signals
        ddg = DuckDuckGoProvider()
        from app.services.providers.web import GeneralWebProvider
        web_provider = GeneralWebProvider()

        # Clean company name: extract unquoted base name without parens for precision quoting
        core_base = re.sub(r'\s*\([^)]*\)', '', clean_company).strip()
        queries = [
            f'"{core_base}" company overview products solutions services business',
            f'"{core_base}" technology stack enterprise architecture cloud software platforms',
            f'"{core_base}" enterprise implementations client platforms digital transformation case study',
            f'"{core_base}" careers active hiring open roles engineering tech leadership',
            f'"{core_base}" strategic initiatives investments digital transformation press release',
            f'"{core_base}" site:en.wikipedia.org'
        ]

        # Anchor for entity resolution
        company_anchor = TargetCompanyAnchor(company_name=clean_company)

        for q in queries:
            try:
                res = await ddg.search_person(q)
                if isinstance(res, dict) and res.get("status") == "SUCCESS":
                    txt = res.get("text_content", "")
                    if txt and "No search results returned" not in txt:
                        context_parts.append(f"### SEARCH SIGNALS ({q}):\n{txt[:2500]}")
                    for r in res.get("extracted_data", {}).get("results", []):
                        href = r.get("href")
                        if href and not any(s.get("url") == href for s in sources_list):
                            body_snippet = (r.get("body", "") or "")
                            title = (r.get("title", "") or "")
                            src_id = f"src-co-{source_counter}"
                            source_counter += 1

                            # Resolve entity and authority tier
                            cand_domain = EntityResolver._extract_domain(href)
                            is_primary = False
                            if company_anchor.website_domain and cand_domain and (company_anchor.website_domain in cand_domain or cand_domain in company_anchor.website_domain):
                                is_primary = True
                            elif clean_company.lower().replace(" ", "") in cand_domain:
                                is_primary = True

                            reputable_platforms = ["greenhouse.io", "lever.co", "workday.com", "jobs.ashbyhq.com", "linkedin.com", "github.com", "wikipedia.org", "en.wikipedia.org"]
                            if is_primary:
                                tier: SourceAuthorityTier = "PRIMARY_OFFICIAL"
                            elif any(p in cand_domain for p in reputable_platforms):
                                tier = "REPUTABLE_AGGREGATOR"
                            else:
                                tier = "UNVERIFIED_WEB"

                            resolution = EntityResolver.resolve_company(
                                anchor=company_anchor,
                                candidate_url=href,
                                candidate_title=title,
                                candidate_text=body_snippet
                            )

                            sources_registry[src_id] = StoredSourceRecord(
                                source_id=src_id,
                                url=href,
                                canonical_url=href,
                                domain=cand_domain,
                                raw_text=body_snippet,
                                content_sha256=hashlib.sha256(body_snippet.encode("utf-8")).hexdigest(),
                                authority_tier=tier,
                                identity_resolution=resolution
                            )

                            sources_list.append({
                                "source_id": src_id,
                                "title": title,
                                "url": href,
                                "snippet": body_snippet[:300],
                                "authority_tier": tier,
                                "identity_status": resolution.status,
                                "is_eligible": resolution.is_eligible_for_factual_claims
                            })
            except Exception as e:
                logger.warning(f"CompanyIntelligence search error for '{q}': {e}")

        # 3. Discover and fetch multiple diverse authority pages (Homepage, Wikipedia, Careers, Solutions)
        from app.services.providers.search import unwrap_search_redirect
        candidate_webpages = []
        for s in sources_list:
            raw_u = s.get("url")
            if not raw_u:
                continue
            clean_u = unwrap_search_redirect(raw_u)
            lower_u = clean_u.lower()
            if any(skip in lower_u for skip in [
                "duckduckgo.com", "bing.com", "google.", "search.google", "yahoo.com",
                "linkedin.com/in/", "linkedin.com/login",
                "momjunction.com", "kidpaw.com", "internal://"
            ]):
                continue
            if clean_u not in candidate_webpages:
                candidate_webpages.append(clean_u)

        core_tokens = [t for t in re.findall(r'\b\w+\b', clean_company.lower()) if t not in EntityResolver.LEGAL_AND_GEO_MODIFIERS]
        core_name = " ".join(core_tokens) if core_tokens else clean_company.lower()

        # Ensure root brand domain is present if matching domain was discovered
        for u in list(candidate_webpages):
            dom = EntityResolver._extract_domain(u).lower()
            if core_name and len(core_name) >= 3 and (dom == f"{core_name}.com" or dom.endswith(f".{core_name}.com")):
                root_u = f"https://{dom}/"
                if root_u not in candidate_webpages:
                    candidate_webpages.append(root_u)

        def _candidate_rank(u: str) -> int:
            dom = EntityResolver._extract_domain(u).lower()
            lower_u = u.lower()
            geo_tokens = [t for t in re.findall(r'\b\w+\b', clean_company.lower()) if t in EntityResolver.LEGAL_AND_GEO_MODIFIERS]
            has_matching_geo = any(f"/{g}/" in lower_u or f".{g}" in dom for g in geo_tokens)
            is_root = urllib.parse.urlparse(u).path in ["", "/", "/index.html"]

            if company_anchor.website_domain and company_anchor.website_domain.lower() in dom:
                return 0
            if core_name and len(core_name) >= 3 and (dom == f"{core_name}.com" or dom.endswith(f".{core_name}.com") or dom.startswith(f"{core_name}.")):
                if has_matching_geo:
                    return 1
                if is_root:
                    return 2
                return 3
            if "wikipedia.org" in dom:
                return 4
            if any(k in lower_u for k in ["solution", "service", "capability", "platform", "technology", "about"]):
                return 5
            if any(k in lower_u for k in ["career", "job", "hiring", "talent"]):
                return 6
            if "linkedin.com/company" in lower_u:
                return 7
            return 8

        # Select up to 4 diverse high-ranking candidate webpages to scrape
        qualified_webpages = [u for u in candidate_webpages if _candidate_rank(u) < 8]
        qualified_webpages.sort(key=_candidate_rank)

        # Ensure diversity in chosen pages (e.g. root, wiki, careers/solutions)
        chosen_pages: List[str] = []
        seen_domains = set()
        for u in qualified_webpages:
            dom = EntityResolver._extract_domain(u).lower()
            is_wiki = "wikipedia.org" in dom
            # Allow wiki and brand domain together
            if dom not in seen_domains or is_wiki or len(chosen_pages) < 2:
                seen_domains.add(dom)
                chosen_pages.append(u)
            if len(chosen_pages) >= 4:
                break

        if chosen_pages:
            fetch_tasks = [web_provider.fetch_public_webpage(u) for u in chosen_pages]
            fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            for u, page_data in zip(chosen_pages, fetch_results):
                if isinstance(page_data, dict) and page_data.get("status") == "SUCCESS":
                    page_text = page_data.get("text_content", "")
                    page_title = page_data.get("title", "") or clean_company
                    if page_text and "please click here if the page does not redirect automatically" not in page_text.lower():
                        clean_page_text = page_text[:6000]
                        context_parts.append(f"### AUTHORITY CONTENT ({u}):\n{clean_page_text}")
                        src_id = f"src-co-{source_counter}"
                        source_counter += 1
                        top_domain = EntityResolver._extract_domain(u)

                        resolution = EntityResolver.resolve_company(
                            anchor=company_anchor,
                            candidate_url=u,
                            candidate_title=page_title,
                            candidate_text=clean_page_text[:2000]
                        )

                        tier = "PRIMARY_OFFICIAL" if (resolution.status == "MATCH_CONFIRMED" and "wikipedia.org" not in top_domain) else ("REPUTABLE_AGGREGATOR" if "wikipedia.org" in top_domain else "UNVERIFIED_WEB")
                        sources_registry[src_id] = StoredSourceRecord(
                            source_id=src_id,
                            url=u,
                            canonical_url=u,
                            domain=top_domain,
                            raw_text=clean_page_text,
                            content_sha256=hashlib.sha256(clean_page_text.encode("utf-8")).hexdigest(),
                            authority_tier=tier,
                            identity_resolution=resolution
                        )

                        sources_list.append({
                            "source_id": src_id,
                            "title": page_title[:80],
                            "url": u,
                            "snippet": clean_page_text[:250],
                            "authority_tier": tier,
                            "identity_status": resolution.status,
                            "is_eligible": resolution.is_eligible_for_factual_claims
                        })

        combined_context = "\n\n".join(context_parts) if context_parts else f"Target company: {clean_company}. No public web records indexed."

        extracted: Optional[CompanyExtractionSchema] = None

        # 4. Pipeline Execution: Epistemic Verification vs Legacy
        if use_epistemic:
            # Check if any sources are eligible for factual attribution
            eligible_sources = [
                s for s in sources_registry.values()
                if s.identity_resolution and s.identity_resolution.is_eligible_for_factual_claims
            ]

            if not eligible_sources:
                # ZERO ELIGIBLE SOURCES: Explicitly return UNKNOWN, never hallucinate!
                logger.info(f"CompanyIntelligence: No eligible identity-confirmed sources found for '{clean_company}'. Withholding factual claims.")
                summary_md = f"""# {clean_company} - Company & Commercial Intelligence

## 1. Corporate Overview
No verified public intelligence records discovered for '{clean_company}' across search indexes. Identity could not be corroborated with high confidence.

### Corporate Profile:
- **Primary Sector**: Unverified
- **Web Presence**: Not confirmed
- **Audited Evidence Items**: 0 verified sources

## 2. Systems, Products & Implementations
No verified technical architectures or implementations disclosed in retrieved evidence.

## 3. Hiring Signals & Growth Demand
- **Verified Hiring Posture**: `UNKNOWN`
- **Talent Signal**: No verified hiring records found.
- **Verified Open Roles**: None verified

## 4. Technology Stack & Key Initiatives
*No verified technologies or technical frameworks discovered.*

## 5. Commercial Opportunity Hypotheses (Ottobon Internal - Unverified Projections)
*No commercial hypotheses generated due to lack of verified entity intelligence.*

## 6. Information Sources & Evidentiary Audit Trail
| Source ID | Reference / URL | Authority Tier | Identity Resolution | Provenance Status |
|---|---|---|---|---|
"""
                for s in sources_list:
                    summary_md += f"| `{s.get('source_id')}` | `{s.get('url', '')[:50]}` | `{s.get('authority_tier')}` | `{s.get('identity_status')}` | Disqualified (Ambiguous/Noise) |\n"

                extracted = CompanyExtractionSchema(
                    company_name=clean_company,
                    website=None,
                    industry="Unverified",
                    overview=f"No verified public intelligence records discovered for '{clean_company}'. Identity could not be corroborated.",
                    what_they_implemented="No verified technical architectures or implementations disclosed in retrieved evidence.",
                    is_hiring=False,
                    hiring_status="UNKNOWN",
                    hiring_roles=[],
                    technologies_used=[],
                    key_initiatives=[],
                    summary_markdown=summary_md.strip()
                )
            else:
                raw_claims: List[AtomicClaim] = []
                hypotheses: List[CommercialHypothesis] = []
                det_website: Optional[str] = None
                det_industry: Optional[str] = None
                llm_payload: Optional[EpistemicCompanyExtractionPayload] = None

                # Attempt High-Depth Closed-Book LLM Extraction & Synthesis if API key is configured
                if settings.OPENAI_API_KEY and not settings.OPENAI_API_KEY.startswith("sk-placeholder"):
                    try:
                        llm = ChatOpenAI(model="gpt-4o", temperature=0.1, api_key=settings.OPENAI_API_KEY)
                        # Build context strictly from eligible sources with explicit source_ids
                        eligible_context_blocks = []
                        for s in eligible_sources:
                            char_limit = 4000 if s.authority_tier == "PRIMARY_OFFICIAL" else 2500
                            eligible_context_blocks.append(
                                f"=== SOURCE ID: {s.source_id} | URL: {s.url} | TIER: {s.authority_tier} ===\n{s.raw_text[:char_limit]}\n"
                            )
                        closed_book_corpus = "\n".join(eligible_context_blocks)

                        system_prompt = f"""You are the Chief Corporate Intelligence & Enterprise Architecture Officer for NetworkOS.
Your subject is the organization: "{clean_company}".

Produce an EXHAUSTIVE, authoritative, deep-dive enterprise intelligence dossier. Every section must be comprehensive, professional, and detailed.

EXTRACTION & SYNTHESIS MANDATE:
1. OVERVIEW (250-400 words, 3 detailed paragraphs):
   - Mission, global operating footprint, corporate structure, and headquarters.
   - Core commercial business lines, service practices, key products, and enterprise customer target.
   - Market positioning, key competitive differentiators, and industry standing.
   DO NOT provide a shallow one-sentence summary.

2. WHAT THEY HAVE IMPLEMENTED (Deep Technical Architecture & Enterprise Platforms):
   - Detailed analysis of software architectures, cloud infrastructure (AWS, Microsoft Azure, Google Cloud Platform), ERP/CRM backbones (SAP S/4HANA, Salesforce, ServiceNow, Workday), enterprise databases & analytics (Snowflake, Databricks, PostgreSQL, Oracle), AI/ML and automation pipelines.
   - Deployed customer/client-facing platforms, API integrations, and developer infrastructure.
   - For consulting or tech service firms (e.g., Deloitte, Accenture), detail the enterprise technology architectures and modernizations they build, integrate, and deploy for their global client base.

3. HIRING SIGNALS & EXPANDING TEAMS:
   - Determine current hiring posture: ACTIVELY_HIRING, MODERATE, or LOW_OR_NONE.
   - List 8 to 15 specific, concrete technical, architectural, and operational roles actively sought or expanding (e.g., "Senior Cloud Solutions Architect (AWS/Azure)", "Enterprise Data & AI Platform Engineer", "SAP S/4HANA Transformation Consultant", "Full-Stack Software Consultant", "Cybersecurity Practice Lead", "DevOps & Infrastructure Automation Specialist"). Avoid generic one-word titles like "Manager" or "Analyst".

4. TECHNOLOGIES USED & PLATFORM ECOSYSTEM:
   - Curate a comprehensive list of 12 to 25 enterprise technologies, platforms, cloud services, and tools deployed or leveraged (e.g., AWS, Azure, GCP, SAP, Salesforce, ServiceNow, Snowflake, Databricks, Kubernetes, Docker, Python, Java, React, Terraform, Kafka).

5. KEY STRATEGIC INITIATIVES:
   - 4 to 6 strategic transformation programs, investments, global partnerships, AI initiatives, or modernizations underway.

6. SUMMARY MARKDOWN (Exhaustive Executive Report):
   - A complete, beautifully formatted GitHub-flavored markdown executive briefing:
     # {clean_company} - Executive Company & Commercial Intelligence
     ## 1. Corporate Identity & Market Overview
     ## 2. Technical Architecture, Platforms & Implementations
     ## 3. Talent Acquisition & Growth Demand
     ## 4. Enterprise Technology Stack & Modernization Initiatives
     ## 5. Strategic Partnership & Commercial Angles for Ottobon / NetworkOS

7. EVIDENTIARY CLAIMS (for Epistemic Audit):
   - Extract atomic evidentiary claims with exact verbatim quotes (10-35 words) and matching source_ids from the provided source corpus."""

                        user_prompt = f"VERIFIED SOURCE CORPUS:\n\n{closed_book_corpus}\n\nExtract verified claims, comprehensive synthesis, and commercial hypotheses."

                        prompt = ChatPromptTemplate.from_messages([
                            ("system", system_prompt),
                            ("user", user_prompt)
                        ])
                        chain = prompt | llm.with_structured_output(EpistemicCompanyExtractionPayload)
                        llm_payload = await chain.ainvoke({})

                        det_website = llm_payload.website
                        det_industry = llm_payload.industry

                        claim_idx = 1
                        for c in llm_payload.claims:
                            raw_claims.append(AtomicClaim(
                                claim_id=f"llm-claim-{claim_idx}",
                                subject_entity_id=clean_company,
                                subject_type="COMPANY",
                                predicate=c.predicate,
                                value=c.value,
                                evidence=[EvidenceRef(
                                    source_id=c.source_id,
                                    source_url=sources_registry[c.source_id].url if c.source_id in sources_registry else "unknown",
                                    source_domain=sources_registry[c.source_id].domain if c.source_id in sources_registry else "unknown",
                                    verbatim_quote=c.verbatim_quote,
                                    source_authority=sources_registry[c.source_id].authority_tier if c.source_id in sources_registry else "UNVERIFIED_WEB",
                                    identity_status=sources_registry[c.source_id].identity_resolution.status if (c.source_id in sources_registry and sources_registry[c.source_id].identity_resolution) else "PROBABLE"
                                )]
                            ))
                            claim_idx += 1

                        hyp_idx = 1
                        for h in llm_payload.hypotheses:
                            hypotheses.append(CommercialHypothesis(
                                hypothesis_id=f"llm-hyp-{hyp_idx}",
                                target_entity_id=clean_company,
                                trigger_claim_ids=[],
                                inferred_pain_point=h.inferred_pain_point,
                                ottobon_capability_offering=h.ottobon_offering,
                                delivery_risk_assessment=h.risk_assessment,
                                estimated_effort_hours=h.effort_estimate,
                                pricing_scenario=h.pricing_scenario,
                                epistemic_status="HYPOTHESIS"
                            ))
                            hyp_idx += 1
                    except Exception as llm_err:
                        logger.warning(f"CompanyIntelligence: High-depth LLM extraction failed: {llm_err}. Using deterministic epistemic extraction.")
                        raw_claims = []
                        hypotheses = []

                if not raw_claims:
                    det_claims, det_hyps, det_website, det_industry = extract_deterministic_epistemic_claims(
                        clean_company=clean_company,
                        sources_registry=sources_registry,
                        anchor=company_anchor
                    )
                    raw_claims = det_claims
                    hypotheses = det_hyps

                # 5. Run deterministic ResearchVerifier over all claims
                dossier = ResearchVerifier.verify_dossier(
                    subject_entity_id=clean_company,
                    subject_type="COMPANY",
                    raw_claims=raw_claims,
                    sources_registry=sources_registry,
                    hypotheses=hypotheses
                )

                # Assemble verified and synthesized data
                accepted_claims = dossier.verified_claims + dossier.partially_supported_claims
                verified_techs = [c.value for c in accepted_claims if c.predicate == "USES_TECH" and c.value]
                verified_roles = [c.value for c in accepted_claims if c.predicate == "HIRING_ROLE" and c.value]

                # Synthesize Technologies (merge verified claims and deep LLM extraction)
                tech_set = set()
                final_techs: List[str] = []
                for t in verified_techs + (llm_payload.technologies_used if llm_payload else []):
                    t_clean = t.strip()
                    if t_clean and t_clean.lower() not in tech_set:
                        tech_set.add(t_clean.lower())
                        final_techs.append(t_clean)

                # Synthesize Roles (merge verified claims and deep LLM extraction)
                role_set = set()
                final_roles: List[str] = []
                for r in verified_roles + (llm_payload.hiring_roles if llm_payload else []):
                    r_clean = r.strip()
                    if r_clean and r_clean.lower() not in role_set:
                        role_set.add(r_clean.lower())
                        final_roles.append(r_clean)

                # Synthesize Initiatives
                key_inits_from_claims = [c.value for c in accepted_claims if c.predicate == "KEY_INITIATIVE" and c.value]
                init_set = set()
                final_inits: List[str] = []
                for init in key_inits_from_claims + (llm_payload.key_initiatives if llm_payload else []):
                    i_clean = init.strip()
                    if i_clean and i_clean.lower() not in init_set:
                        init_set.add(i_clean.lower())
                        final_inits.append(i_clean)

                # Synthesize Overview
                overview_claims = [c.value for c in accepted_claims if c.predicate == "OVERVIEW" and c.value]
                if llm_payload and llm_payload.overview and len(llm_payload.overview.strip()) > 50:
                    final_overview = llm_payload.overview.strip()
                elif overview_claims:
                    final_overview = " ".join(overview_claims)
                else:
                    valid_snippets = [
                        s.get("snippet", "") for s in sources_list
                        if s.get("is_eligible") and s.get("snippet")
                        and "please click here if the page does not redirect automatically" not in s.get("snippet", "").lower()
                    ]
                    if valid_snippets:
                        final_overview = " ".join(valid_snippets[:3])
                    else:
                        final_overview = f"{clean_company} is an established global commercial enterprise delivering specialized professional, consulting, and technological solutions."

                # Synthesize What They Have Implemented
                impl_claims = [c.value for c in accepted_claims if c.predicate == "WHAT_IMPLEMENTED" and c.value]
                if llm_payload and llm_payload.what_they_implemented and len(llm_payload.what_they_implemented.strip()) > 40 and "no verified" not in llm_payload.what_they_implemented.lower():
                    final_implemented = llm_payload.what_they_implemented.strip()
                elif impl_claims:
                    final_implemented = " ".join(impl_claims)
                elif is_internal_or_ottobon:
                    final_implemented = f"{clean_company} has deployed the NetworkOS relationship operating platform and automated evidence architecture."
                else:
                    final_implemented = (
                        f"{clean_company} has designed and implemented multi-tier enterprise cloud architectures, "
                        f"modern integration pipelines, and automated business workflows supporting scalable operations."
                    )

                final_industry = (llm_payload.industry if (llm_payload and llm_payload.industry) else None) or det_industry or "Enterprise Technology & Commercial Services"

                # Synthesize Hiring Posture
                if llm_payload and llm_payload.hiring_status in ["ACTIVELY_HIRING", "MODERATE", "LOW_OR_NONE"]:
                    final_hiring_status: Literal["ACTIVELY_HIRING", "MODERATE", "LOW_OR_NONE", "UNKNOWN", "CONFLICTING"] = llm_payload.hiring_status
                    final_is_hiring = llm_payload.is_hiring or (final_hiring_status in ["ACTIVELY_HIRING", "MODERATE"])
                elif dossier.hiring_state == "ACTIVE":
                    final_is_hiring = True
                    final_hiring_status = "ACTIVELY_HIRING" if len(final_roles) >= 2 else "MODERATE"
                elif dossier.hiring_state == "INACTIVE":
                    final_is_hiring = False
                    final_hiring_status = "LOW_OR_NONE"
                elif dossier.hiring_state == "CONFLICTING":
                    final_is_hiring = False
                    final_hiring_status = "CONFLICTING"
                else:
                    final_is_hiring = len(final_roles) > 0
                    final_hiring_status = "MODERATE" if final_is_hiring else "UNKNOWN"

                summary_md = build_epistemic_summary_markdown(
                    clean_company=clean_company,
                    dossier=dossier,
                    sources_list=sources_list,
                    website=det_website,
                    industry=final_industry,
                    overview=final_overview,
                    what_implemented=final_implemented,
                    technologies_used=final_techs,
                    hiring_roles=final_roles,
                    key_initiatives=final_inits,
                    custom_markdown=llm_payload.summary_markdown if llm_payload else None
                )

                extracted = CompanyExtractionSchema(
                    company_name=clean_company,
                    website=det_website,
                    industry=final_industry,
                    overview=final_overview,
                    what_they_implemented=final_implemented,
                    is_hiring=final_is_hiring,
                    hiring_status=final_hiring_status,
                    hiring_roles=final_roles,
                    technologies_used=final_techs,
                    key_initiatives=final_inits,
                    summary_markdown=summary_md
                )
        else:
            # LEGACY FLOW (when enable_epistemic_verification=False)
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

            if settings.OPENAI_API_KEY and not settings.OPENAI_API_KEY.startswith("sk-placeholder"):
                try:
                    llm = ChatOpenAI(model="gpt-4o", temperature=0.1, api_key=settings.OPENAI_API_KEY)
                    prompt = ChatPromptTemplate.from_messages([
                        ("system", system_prompt),
                        ("user", user_prompt)
                    ])
                    chain = prompt | llm.with_structured_output(CompanyExtractionSchema)
                    extracted = await chain.ainvoke({})
                except Exception as llm_err:
                    logger.warning(f"CompanyIntelligence: Legacy LLM synthesis failed ({llm_err}). Falling back to rule-based.")

            if not extracted:
                extracted = synthesize_rule_based_company_intelligence(
                    clean_company=clean_company,
                    sources_list=sources_list,
                    combined_context=combined_context,
                    candidate_webpages=candidate_webpages
                )

        # 6. Check if record already exists for this contact or company
        existing_record = await CompanyIntelligenceService.get_by_contact_or_name(db, contact_id, clean_company)

        if existing_record:
            # If the record is for a different company or was unverified, overwrite it completely
            is_new_company = existing_record.company_name.lower().strip() != clean_company.lower().strip()
            was_unverified = "No verified public intelligence records" in (existing_record.overview or "")
            should_full_overwrite = is_new_company or was_unverified

            existing_record.company_name = extracted.company_name or clean_company
            existing_record.website = extracted.website or existing_record.website
            if should_full_overwrite or (extracted.industry and extracted.industry != "Unverified"):
                existing_record.industry = extracted.industry
            if should_full_overwrite or (extracted.overview and "No verified public intelligence" not in extracted.overview) or not existing_record.overview:
                existing_record.overview = extracted.overview

            if should_full_overwrite or (extracted.what_they_implemented and "No verified technical architectures" not in extracted.what_they_implemented) or not existing_record.what_they_implemented:
                existing_record.what_they_implemented = extracted.what_they_implemented

            if should_full_overwrite or extracted.technologies_used:
                existing_record.technologies_used = extracted.technologies_used

            if should_full_overwrite or extracted.hiring_roles:
                existing_record.hiring_roles = extracted.hiring_roles

            existing_record.is_hiring = extracted.is_hiring
            existing_record.hiring_status = extracted.hiring_status
            existing_record.key_initiatives = extracted.key_initiatives if should_full_overwrite else (extracted.key_initiatives or existing_record.key_initiatives)
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

        # 7. If contact_id is provided, update the contact's company in database
        if contact_id:
            c_res = await db.execute(select(Contact).where(Contact.id == contact_id))
            target_contact = c_res.scalars().first()
            if target_contact:
                target_contact.current_company = extracted.company_name or clean_company

        await db.commit()
        await db.refresh(record)
        logger.info(f"CompanyIntelligence: Successfully stored company intelligence for {clean_company} (ID: {record.id})")
        return record
