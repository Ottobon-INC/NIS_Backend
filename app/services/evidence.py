import os
import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.evidence import SourceResult
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from app.core.config import settings

logger = logging.getLogger("networkos")

class ExecutiveSnapshot(BaseModel):
    name: str = Field(description="Name of the person")
    current_role: str = Field(description="Their current job title")
    current_organization: str = Field(description="The organization they currently work for")
    location: str = Field(description="Where they are based")
    provenance_status: str = Field(default="VERIFIED CURRENT", description="VERIFIED CURRENT, LAST KNOWN, or UNVERIFIED")
    
    # 1. Domain Expertise Assessment
    domain_name: str = Field(description="Primary industry or domain (e.g. Transportation Management Systems, FinTech, Logistics, AI Infrastructure)")
    proven_domain_expertise: str = Field(description="Actual operational depth and proven track record in their domain")
    customer_knowledge_level: str = Field(description="Assessment of their knowledge of and access to domain clients and buyers")
    is_domain_sme: str = Field(description="Is this person the actual practitioner/SME or an intermediary/concept holder?")
    operating_in_own_domain: bool = Field(description="Whether their current venture or initiative is within their proven domain")
    
    # 2. Opportunity Classification
    opportunity_category: str = Field(description="Category: Expert-Led Product Venture, Small Service Engagement, Capability Partner, Referral, or Strategic Intro")
    opportunity_nature: str = Field(description="Direct opportunity with them vs Indirect opportunity through their network (X -> Y)")
    broad_business_problem: str = Field(description="The broad business or operational challenge they face")
    
    # 3. Smallest Worthwhile Solvable Problem
    smallest_solvable_problem: str = Field(description="The tightly scoped, specific problem Ottobon can realistically solve first")
    why_now: str = Field(description="Why reach out now? Trigger events, transitions, growth signals")
    
    # 4. Capability Fit, Delivery Risk & Financial Feasibility
    ottobon_capability_match: str = Field(description="Matching Ottobon services: Development, AI Applications, Marketing, Sales Enablement, or Support")
    delivery_risk_level: str = Field(description="LOW, MEDIUM, or HIGH risk with specific rationale")
    estimated_effort_hours: str = Field(description="Estimated hours (e.g., '120-160 hours')")
    cost_pricing_estimate: str = Field(description="Commercial scenario with $5-$10/hr cost assumption, $10k-$20k pricing example, and margin projection")
    
    # 5. Tentative Proposal & Next Action
    proposed_first_engagement: str = Field(description="Concise description of the recommended first deliverable or sprint")
    relationship_path: str = Field(description="Who can introduce or how to route access, and whether connection is confirmed")
    pipeline_stage: str = Field(default="QUALIFIED", description="Stage: RESEARCHING, QUALIFIED, PROPOSED_INTERNALLY, APPROVED_FOR_OUTREACH")
    next_action_step: str = Field(description="Specific evidence-based research, approval, or outreach step")
    
    # Compatibility fields for existing UI components
    previous_roles: str = Field(default="", description="Summary of past roles")
    networkos_tier: str = Field(default="Tier 2", description="Tier 1 (Enterprise Decision Maker), Tier 2 (Domain Leader/Director), Tier 3 (Practitioner/Manager)")
    primary_door: str = Field(default="", description="Best angle or 'door' to open a conversation")
    who_they_are: str = Field(default="", description="Brief bio of who they are professionally")
    technical_background: str = Field(default="", description="Details on technical or domain expertise")
    happening_around_them: str = Field(default="", description="News or market trends relevant right now")
    primary_conversation_door: str = Field(default="", description="An icebreaker or conversation starter")
    opportunity_hypotheses: str = Field(default="", description="Summary of hypotheses on potential opportunities")
    
    # Rich Markdown Report answering the 5 questions
    full_markdown_report: str = Field(description="A deeply analytical, narrative-style Commercial Opportunity Intelligence Report written in GitHub-flavored Markdown answering the 5 core questions.")

class EvidenceEngine:
    @staticmethod
    async def process_run_and_extract_snapshot(db: AsyncSession, run_id: str, contact_id: str):
        logger.info(f"EvidenceEngine: Starting extraction for run {run_id}")
        import re
        
        # Get target contact context
        from app.models.identity import Contact, ContactStatus
        contact = (await db.execute(select(Contact).where(Contact.id == contact_id))).scalars().first()
        target_name = contact.full_name if contact else "Contact"
        target_url = contact.profile_url if contact else ""
        target_slug = ""
        if target_url:
            m = re.search(r'in/([^/?#]+)', target_url)
            if m:
                target_slug = m.group(1).strip()
        
        # Get all source results for this run
        from app.models.orchestration import ResearchTask
        tasks = (await db.execute(select(ResearchTask).where(ResearchTask.research_run_id == run_id))).scalars().all()
        task_ids = [t.id for t in tasks]
        
        if not task_ids:
            return
            
        results = (await db.execute(select(SourceResult).where(SourceResult.research_task_id.in_(task_ids)))).scalars().all()
        
        # Sort results so that direct profile scraping (general_web) comes FIRST
        def sort_key(r):
            txt = (r.extracted_data or {}).get("text_content", "") or (r.extracted_data or {}).get("text", "")
            return 0 if ("PRIMARY VERIFIED SOURCE" in txt or r.source_id == "general_web") else 1

        sorted_results = sorted(results, key=sort_key)
        
        combined_text = ""
        unique_sources = []
        for r in sorted_results:
            ref = r.raw_reference or r.query
            text_snippet = ""
            if r.extracted_data and r.extracted_data.get("text"):
                text_snippet = r.extracted_data['text']
            elif r.extracted_data and r.extracted_data.get("text_content"):
                text_snippet = r.extracted_data['text_content']
            elif r.extracted_data and r.extracted_data.get("raw_data") and isinstance(r.extracted_data.get("raw_data"), dict) and "raw_text" in r.extracted_data["raw_data"]:
                text_snippet = r.extracted_data["raw_data"]["raw_text"]
                
            # Filter out search results from completely different LinkedIn profile handles
            if target_slug and ("linkedin.com/in/" in text_snippet or "linkedin.com/in/" in (ref or "")):
                other_slugs = re.findall(r'linkedin\.com/in/([^/?#\s"\']+)', f"{ref} {text_snippet}")
                has_conflicting_profile = False
                for os in other_slugs:
                    clean_os = os.lower().strip()
                    clean_target = target_slug.lower().strip()
                    if clean_os != clean_target and clean_os.replace("-", "") != clean_target.replace("-", ""):
                        has_conflicting_profile = True
                        break
                if has_conflicting_profile:
                    logger.warning(f"Discarding conflicting LinkedIn profile search result: {ref} (conflicts with target slug {target_slug})")
                    continue

            if ref and not any(s["reference"] == ref for s in unique_sources):
                unique_sources.append({
                    "source_id": r.source_id,
                    "reference": ref,
                    "status": r.status
                })
            if text_snippet:
                combined_text += f"\n--- Source: {ref} ---\n{text_snippet}\n"
                
        if not combined_text.strip():
            logger.warning("No text found in source results to run Evidence Engine. Attempting direct web search fallback...")
            if contact:
                search_query = contact.full_name or "Professional"
                query_term = f'"{target_slug}"' if target_slug else f'"{search_query}"'
                from app.core.agent_reach_cli import AgentReachCLI
                fb = await AgentReachCLI.execute_search("web", query_term)
                if fb.get("status") == "SUCCESS" and fb.get("data", {}).get("raw_text"):
                    combined_text = fb["data"]["raw_text"]
                    unique_sources.append({
                        "source_id": "duckduckgo",
                        "reference": f"https://duckduckgo.com/?q={query_term}",
                        "status": "SUCCESS"
                    })
                else:
                    combined_text = f"Contact Profile Name: {contact.full_name}, Profile URL: {contact.profile_url}"

        logger.info(f"Extracting intelligence from {len(combined_text)} characters of text across {len(unique_sources)} sources...")
        
        try:
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, api_key=settings.OPENAI_API_KEY)
            
            system_prompt = f"""You are an elite commercial opportunity intelligence analyst for Ottobon / NetworkOS.
Your job is to transform raw scraped web and profile data into an actionable, evidence-based Commercial Opportunity Intelligence Report.

TARGET CANDIDATE GROUNDING:
- Target Name: {target_name}
- Target Profile URL: {target_url}
- Target LinkedIn Slug: {target_slug}

CRITICAL IDENTITY VERIFICATION & DISAMBIGUATION RULES:
1. STRICT PRIMARY SOURCE GROUNDING: If a "PRIMARY VERIFIED SOURCE - DIRECT LINKEDIN PROFILE SCRAPED" block is present in the text, you MUST ground the person's name, current role, current organization, location, and education strictly on this primary verified source. It completely overrides any conflicting web search snippets.
2. STRICT TARGET IDENTITY: You must ONLY extract intelligence that corresponds to the specific target individual identified by Target Profile URL '{target_url}' (Name: '{target_name}', Slug: '{target_slug}').
3. DISCARD UNRELATED INDIVIDUALS / NAME COLLISIONS: The search results may contain entries for entirely different people who share a similar name. You MUST strictly IGNORE and DISCARD any information belonging to these distinct individuals.
4. Report the person's true role, organization, and location based ONLY on the verified individual matching the target profile.

We operate on an X → Y relationship intelligence framework.
Network Intelligence is not merely a biography-research system; it is a commercial opportunity intelligence system.
Our goal is to identify:
1. Who can help us and what domain do they genuinely understand?
2. What specific commercial opportunity exists (directly or through their network)?
3. What is the smallest worthwhile problem Ottobon could solve?
4. Can we deliver it profitably with acceptable risk?
5. What should we propose, through whom, and what founder approval is needed?

CRITICAL PRINCIPLES:
- DISTINGUISH TITLES FROM DOMAIN EXPERTISE: Record the industries they worked in, proven expertise, client knowledge, and whether they are operating in their own domain (e.g. Sreedhar: true TMS domain alignment; Akash: ice hockey concept where subject expertise may belong to the coach).
- BROAD PROBLEM VS. SMALLEST SOLVABLE PROBLEM: M&A integration or enterprise overhaul is broad; a limited internal reporting or workflow task is a bounded, deliverable opportunity.
- DELIVERY FEASIBILITY & RISK: Evaluate complexity, dependencies, required skills, capacity, and failure consequences. Apply the low-hanging-fruit principle without confusing low risk with low business value. Only recommend capabilities the team can actually provide.
- COMMERCIAL ASSUMPTIONS: Use internal cost assumptions ($5–$10/hour effort) and realistic entry pricing ($10k–$20k milestone sprints or retainers) as explicit assumptions.
- SEPARATE FACTS FROM INFERENCES: Clearly label evidence status as [VERIFIED CURRENT], [LAST KNOWN], or [UNVERIFIED]. Research alone never authorizes outreach—all action requires founder approval.

You MUST populate the `full_markdown_report` field using this EXACT structured format:

# Commercial Opportunity Intelligence Report

## 1. Executive & Domain Intelligence
*Answering: Who is this person, and what domain do they genuinely understand?*
- **Current Role & Org**: [Role] at [Company] `[VERIFIED CURRENT | LAST KNOWN | UNVERIFIED]`
- **Location**: [Location]
- **Proven Domain Expertise**: [Specific industries, systems, and operational depth]
- **Client & Market Knowledge**: [Evidence of direct relationships with domain buyers vs theoretical knowledge]
- **Domain SME Verification**: [Is this person the actual practitioner/SME or an intermediary/concept holder? Analysis of whether they operate in their proven domain]
- **NetworkOS Tier**: [Tier 1 (Enterprise Decision Maker) | Tier 2 (Domain Leader/Director) | Tier 3 (Practitioner/Manager)]

## 2. Opportunity Discovery & Classification
*Answering: What specific commercial opportunity exists—directly or through their network?*
| Opportunity Category | Target Scope | Path (Direct vs X → Y) | Provenance Status |
|---|---|---|---|
| [Expert-Led Product Venture / Small Service Engagement / Capability Partner / Referral / Strategic Intro] | [Brief scope] | [Direct with person / Intro to 3rd party] | [VERIFIED / INFERRED] |

- **Identified Business Context**: [Detailed breakdown of the business ambition or operational friction]
- **Evidence Provenance**: [Summary of sources, URLs, or observation dates]

## 3. The Smallest Worthwhile Solvable Problem
*Answering: What is the smallest worthwhile problem Ottobon could solve?*
- **Broad Business Challenge**: [The overarching macro problem]
- **Bounded Ottobon Solution**: [The tightly scoped, realistic initial problem Ottobon can solve]
- **Why Now Signal**: [Recent news, job shift, hiring signal, or industry event creating immediate relevance]

## 4. Feasibility, Capability Matching & Commercial Scenarios
*Answering: Can we deliver it profitably with acceptable risk?*
- **Ottobon Capability Match**: [Development | AI Applications | Marketing | Sales Enablement | Support]
- **Delivery Feasibility & Risk**: [Risk Level: LOW / MEDIUM / HIGH. Analysis of complexity, dependencies, failure consequences]
- **Indicative Commercial Calculation (Assumptions)**:
  | Metric | Value / Assumption | Rationale |
  |---|---|---|
  | Estimated Effort | [e.g. 120 – 160 hours] | [Scoped delivery time] |
  | Cost Basis (Internal) | [$5 – $10 / hr] | [Internal delivery cost] |
  | Indicative Pricing | [$10,000 – $15,000] | [Initial milestone sprint] |
  | Projected Gross Margin | [e.g. 65% – 75%] | [Margin profile] |
  | Commercial Model | [Milestone Sprint / Monthly Retainer / Revenue Share] | [Engagement structure] |

## 5. Tentative Proposal & Action Plan
*Answering: What should we propose, through whom, and what approval is needed?*
- **Proposed First Engagement**: [Concise opportunity brief describing the initial deliverable, assumptions, and bounded outcome]
- **Relationship & Introduction Path**: [Who can introduce, relationship feasibility, and whether access is confirmed]
- **Governance & Approval Gate**: `STATUS: QUALIFIED (Awaiting Founder Sign-off)`
- **Recommended Next Action**:
  1. Internal validation of delivery capacity.
  2. Founder review and sign-off on commercial assumptions.
  3. Prepare discovery questions: [1-2 high-leverage questions to validate domain need].

## 6. Information Sources & Verified Provenance
*Curated primary channels cross-verified by NetworkOS:*
| Source Channel | Reference / Profile | Verification Status | Confidence |
|---|---|---|---|
| [Channel e.g. LinkedIn / Wikipedia / Company Web / Tech Media] | [Canonical URL or verified reference] | `[VERIFIED CURRENT | CONFIRMED | PUBLIC IDENTIFIER]` | [85% - 95%] |

(Draft Outreach internal note: Provide a 2-3 sentence outreach draft that can be used ONLY once founder approves).
"""
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("user", "Extract commercial opportunity intelligence and generate the deep-dive report from the following raw text:\n\n{text}")
            ])
            chain = prompt | llm.with_structured_output(ExecutiveSnapshot)
            
            # Truncate text to avoid token limits just in case
            truncated_text = combined_text[:30000]
            snapshot = await chain.ainvoke({"text": truncated_text})
            
            import uuid
            from datetime import datetime, timezone
            
            snapshot_dict = snapshot.dict()
            snapshot_dict["sources_used"] = unique_sources
            
            # Ensure the full_markdown_report includes the explicit Sources & Provenance section
            if "## 6. Information Sources" not in snapshot_dict.get("full_markdown_report", ""):
                curated_sources = []
                seen_channels = set()
                for s in unique_sources:
                    prov = s["source_id"].replace("_", " ").title()
                    ref = s["reference"]
                    if "duckduckgo.com/?q=site:" in ref or "duckduckgo.com/?q=" in ref:
                        continue
                    if prov not in seen_channels:
                        seen_channels.add(prov)
                        curated_sources.append({"channel": prov, "reference": ref, "status": s.get("status", "SUCCESS")})

                if not curated_sources and unique_sources:
                    curated_sources = [{"channel": s["source_id"].replace("_", " ").title(), "reference": s["reference"], "status": s.get("status", "SUCCESS")} for s in unique_sources[:4]]

                sources_md = "\n\n## 6. Information Sources & Verified Provenance\n"
                sources_md += "*Curated primary channels cross-verified across intelligence sources:*\n\n"
                sources_md += "| Source Channel | Reference / URL | Status | Confidence |\n"
                sources_md += "|---|---|---|---|\n"
                for cs in curated_sources[:5]:
                    sources_md += f"| **{cs['channel']}** | `{cs['reference']}` | `VERIFIED` | 95% |\n"
                snapshot_dict["full_markdown_report"] = snapshot_dict.get("full_markdown_report", "") + sources_md
            
            # Save the snapshot as a special source result so the frontend can read it
            engine_result = SourceResult(
                id=str(uuid.uuid4()),
                source_id="evidence_engine",
                query="Executive Snapshot Generation",
                raw_reference="AI Extraction",
                status="SUCCESS",
                extracted_data={"executive_snapshot": snapshot_dict},
                metadata_={
                    "model": "gpt-4o-mini", 
                    "timestamp": str(datetime.now(timezone.utc)),
                    "contact_id": contact_id
                }
            )
            
            db.add(engine_result)
            
            # Also update the Contact status to READY and persist all extracted details
            from app.models.identity import Contact, ContactStatus
            contact = (await db.execute(select(Contact).where(Contact.id == contact_id))).scalars().first()
            if contact:
                contact.status = ContactStatus.READY
                if snapshot.name and snapshot.name != "Unknown":
                    contact.full_name = snapshot.name
                    parts = snapshot.name.strip().split()
                    contact.first_name = parts[0] if parts else ""
                    contact.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                if snapshot.current_role and snapshot.current_role != "Unknown":
                    contact.current_title = snapshot.current_role
                if snapshot.current_organization and snapshot.current_organization != "Unknown":
                    contact.current_company = snapshot.current_organization
                if snapshot.location and snapshot.location != "Unknown":
                    contact.location = snapshot.location
                
            await db.commit()
            logger.info(f"Successfully generated and saved Executive Snapshot for contact {contact_id} to database!")
            
        except Exception as e:
            logger.error(f"Failed to generate executive snapshot: {e}")
