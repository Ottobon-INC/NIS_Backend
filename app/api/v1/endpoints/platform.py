from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Any, List, Optional
import uuid
import json

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.models.identity import Contact
from app.models.evidence import SourceResult
from app.models.company_knowledge import Product
from app.schemas.company_knowledge import ProductCreate, ProductUpdate, ProductInDB
from app.services.semantic_product_matcher import SemanticProductMatcherService

router = APIRouter()

# --- Dashboard & Founder Decisions ---

@router.get("/dashboard")
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    valid_contacts = (await db.execute(
        select(Contact.id).where(
            Contact.organization_id == user["organization_id"],
            Contact.full_name.isnot(None),
            Contact.full_name != "Unknown"
        )
    )).scalars().all()
    contacts_count = len(valid_contacts)
    return {
        "stats": {
            "actionRequired": 3,
            "researched": contacts_count or 2,
            "conversations": 4,
            "openOpportunities": 2,
            "outcomes": 1
        }
    }

@router.get("/founder/decisions")
async def get_founder_decisions(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    contacts = (await db.execute(select(Contact).where(Contact.organization_id == user["organization_id"]))).scalars().all()
    satya = next((c for c in contacts if "Satya" in (c.full_name or "")), None)
    
    return [
        {
            "id": "task-1",
            "type": "VALIDATION_REQUIRED",
            "title": "Review Opportunity Brief & Commercial Terms",
            "personId": satya.id if satya else "2b892b5c-d98f-4953-b4b1-3bed4afab79d",
            "opportunityId": "opp-satya-ai",
            "personName": satya.full_name if satya else "Satya Nadella",
            "companyName": satya.current_company if satya else "Microsoft",
            "relatedEntityName": "Enterprise Agent Governance Pilot",
            "description": "Evidence engine identified a bounded 2-week pilot sprint ($12,000–$15,000) for Azure enterprise agent compliance.",
            "whyItMatters": "Founder sign-off required on commercial assumptions before initiating outreach or discovery.",
            "evidenceSummary": "5 verified sources (LinkedIn, Wikipedia, Official Exec Bio, CNBC)",
            "confidence": 95,
            "status": "PENDING",
            "primaryActionLabel": "Review Commercial Brief"
        },
        {
            "id": "task-2",
            "type": "MATCH_REVIEW_REQUIRED",
            "title": "Review Ecosystem Match",
            "personId": satya.id if satya else "2b892b5c-d98f-4953-b4b1-3bed4afab79d",
            "opportunityId": "opp-copilot-integration",
            "personName": satya.full_name if satya else "Satya Nadella",
            "companyName": satya.current_company if satya else "Microsoft",
            "relatedEntityName": "Capability Match: AI Applications & Backend Systems",
            "description": "Ottobon AI Applications capability matched at 95% confidence with Azure Copilot extensibility.",
            "whyItMatters": "Internal capacity validation required before introduction path confirmation.",
            "evidenceSummary": "Cross-verified domain alignment",
            "confidence": 95,
            "status": "PENDING",
            "primaryActionLabel": "Review Match"
        }
    ]

# --- Trusted Context ---

@router.get("/contacts/{contact_id}/trusted-context")
async def get_contact_trusted_context(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    stmt = select(Contact).where(Contact.id == contact_id, Contact.organization_id == user["organization_id"])
    contact = (await db.execute(stmt)).scalars().first()

    name = contact.full_name if contact else "Executive Contact"
    company = contact.current_company if contact else "Target Enterprise"

    return {
        "items": [
            {
                "id": "tc-1",
                "contactId": contact_id,
                "type": "PROBLEM",
                "currentVersion": 1,
                "content": f"Enterprise AI agent compliance and validation bottleneck at scale.",
                "evidence": f"Cross-verified across {company} leadership communications and public domain reporting.",
                "sourceMeetingId": f"meet-{contact_id[:8]}",
                "history": [
                    {
                        "version": 1,
                        "content": f"Enterprise AI agent compliance and validation bottleneck at scale.",
                        "timestamp": "2026-10-13T10:00:00Z"
                    }
                ]
            },
            {
                "id": "tc-2",
                "contactId": contact_id,
                "type": "REQUIREMENT",
                "currentVersion": 1,
                "content": "Turnkey verification bridge requiring zero core platform disruption.",
                "evidence": f"Bounded 2-week deliverable scoped for {name} ({company}).",
                "sourceMeetingId": f"meet-{contact_id[:8]}",
                "history": [
                    {
                        "version": 1,
                        "content": "Turnkey verification bridge requiring zero core platform disruption.",
                        "timestamp": "2026-10-13T10:00:00Z"
                    }
                ]
            }
        ]
    }

@router.patch("/trusted-context/{item_id}")
async def update_trusted_context(
    item_id: str,
    payload: Dict[str, Any] = Body(...),
    user: dict = Depends(get_current_user)
):
    return {"success": True}

# --- Opportunities ---

@router.get("/opportunities")
async def list_opportunities(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    contacts = (await db.execute(select(Contact).where(Contact.organization_id == user["organization_id"]))).scalars().all()
    satya = next((c for c in contacts if "Satya" in (c.full_name or "")), None)

    return {
        "opportunities": [
            {
                "id": "opp-satya-ai",
                "title": "Azure AI Agent Governance & Verification Pilot",
                "personId": satya.id if satya else "2b892b5c-d98f-4953-b4b1-3bed4afab79d",
                "personName": satya.full_name if satya else "Satya Nadella",
                "companyId": "comp-msft",
                "companyName": satya.current_company if satya else "Microsoft",
                "problem": "Enterprise clients deploying custom autonomous agents face audit and governance bottlenecks.",
                "requirement": "Bounded plug-and-play governance validation module with turnkey Azure integration.",
                "opportunityType": "Enterprise AI Solutions",
                "confidence": 95,
                "status": "QUALIFIED",
                "createdAt": "2026-10-13T10:30:00Z",
                "updatedAt": "2026-10-13T10:30:00Z",
                "trustedContextIds": ["tc-1", "tc-2"]
            }
        ]
    }

@router.get("/opportunities/pipeline")
async def get_opportunities_pipeline(user: dict = Depends(get_current_user)):
    return {
        "pipeline": [
            {
                "stage": "IDENTIFIED",
                "count": 2,
                "opportunities": [
                    {"id": "opp-satya-ai", "title": "Azure AI Governance Pilot", "company": "Microsoft", "value": "$15,000"}
                ]
            },
            {
                "stage": "QUALIFIED",
                "count": 1,
                "opportunities": [
                    {"id": "opp-satya-ai", "title": "Azure AI Governance Pilot", "company": "Microsoft", "value": "$15,000"}
                ]
            },
            {
                "stage": "OUTREACH_PENDING",
                "count": 1,
                "opportunities": []
            }
        ]
    }

@router.get("/opportunities/{id}")
async def get_opportunity_by_id(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    contacts = (await db.execute(select(Contact).where(Contact.organization_id == user["organization_id"]))).scalars().all()
    satya = next((c for c in contacts if "Satya" in (c.full_name or "")), None)

    return {
        "id": id,
        "title": "Azure AI Agent Governance & Verification Pilot",
        "personId": satya.id if satya else "2b892b5c-d98f-4953-b4b1-3bed4afab79d",
        "personName": satya.full_name if satya else "Satya Nadella",
        "companyId": "comp-msft",
        "companyName": satya.current_company if satya else "Microsoft",
        "relationshipId": "rel-1",
        "sourceMeetingId": f"meet-{satya.id[:8]}" if satya else "meet-1",
        "trustedContextIds": ["tc-1", "tc-2"],
        "problem": "Enterprise clients deploying custom autonomous agents face audit and governance bottlenecks.",
        "requirement": "Bounded plug-and-play governance validation module with turnkey Azure integration.",
        "timeline": "Q4 2026",
        "budgetSignal": "$12,000 – $15,000 Milestone Sprint",
        "opportunityType": "Enterprise AI Solutions",
        "confidence": 95,
        "status": "QUALIFIED",
        "createdAt": "2026-10-13T10:30:00Z",
        "updatedAt": "2026-10-13T10:30:00Z"
    }

@router.patch("/opportunities/{id}/validate")
async def validate_opportunity(id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    return {"success": True}

@router.get("/opportunities/{id}/solutions")
async def get_opportunity_solutions(id: str, user: dict = Depends(get_current_user)):
    return {
        "solutions": [
            {
                "id": "sol-1",
                "name": "Enterprise Agent Verification Bridge",
                "description": "Ottobon internal delivery capability for autonomous agent compliance and audit telemetry.",
                "type": "INTERNAL",
                "matchScore": 95,
                "trustLevel": "CONFIRMED",
                "evidenceId": "ev-1"
            },
            {
                "id": "sol-2",
                "name": "Azure Partner Ecosystem Squad",
                "description": "Ecosystem network match with verified Microsoft cloud architecture credentials.",
                "type": "NETWORK",
                "matchScore": 90,
                "trustLevel": "HYPOTHESIS"
            }
        ]
    }

@router.patch("/opportunities/{id}/path")
async def set_opportunity_path(id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    return {"success": True}

@router.post("/opportunities/{id}/outcome")
async def post_opportunity_outcome(id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    return {"success": True}

@router.get("/opportunities/{id}/capability-matches")
async def get_opportunity_capability_matches(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    opp = await get_opportunity_by_id(id, db=db, user=user)
    problem_text = opp.get("problem", "Enterprise AI agent compliance and validation bottleneck at scale.")

    match_res = await SemanticProductMatcherService.match_connection_problem(
        problem_text=problem_text,
        connection_name=opp.get("personName"),
        connection_company=opp.get("companyName")
    )

    if match_res.matching_outcome == "NO_MATCH_FOUND" or not match_res.matches:
        return {"matches": []}

    out_matches = []
    for idx, m in enumerate(match_res.matches):
        out_matches.append({
            "id": f"cmatch-{idx+1}",
            "opportunityId": id,
            "capabilityId": m.product_id,
            "capabilityName": m.product_name,
            "capabilityCategory": "PRODUCT",
            "status": "CANDIDATE",
            "confidence": m.match_score,
            "capability": {
                "id": m.product_id,
                "name": m.product_name,
                "category": "PRODUCT",
                "description": m.why_this_product_solves_it,
                "relevantExpertise": m.relevant_features,
                "evidenceSource": m.category
            },
            "reasoning": {
                "problemAlignment": m.alignment_level,
                "requirementAlignment": m.alignment_level,
                "technologyAlignment": m.alignment_level,
                "industryAlignment": "STRONG",
                "overallExplanation": m.why_this_product_solves_it
            },
            "evidenceIds": ["tc-1"]
        })
    return {"matches": out_matches}

@router.patch("/opportunities/{id}/capability-matches/{match_id}")
async def update_capability_match(id: str, match_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    return {"success": True}

@router.get("/opportunities/{id}/network-matches")
async def get_opportunity_network_matches(id: str, user: dict = Depends(get_current_user)):
    return {
        "selectedCapability": {
            "id": "cap-1",
            "name": "AI Applications & Backend Systems",
            "category": "SERVICE",
            "description": "Delivery of custom enterprise agent systems and verification bridges.",
            "relevantExpertise": ["Generative AI", "Azure Architecture", "Governance", "API Integration"],
            "evidenceSource": "Ottobon Capabilities Catalog 2026"
        },
        "matches": [
            {
                "id": "nmatch-1",
                "opportunityId": id,
                "capabilityId": "cap-1",
                "candidateId": "u-1",
                "candidateName": "Internal Engineering Lead",
                "candidateTitle": "AI Architecture Lead",
                "candidateCompany": "Ottobon",
                "matchType": "INTERNAL",
                "status": "QUALIFIED",
                "dimensions": {
                    "relevance": "STRONG",
                    "expertise": "STRONG",
                    "relationshipStrength": "STRONG",
                    "industryFit": "STRONG",
                    "geography": "STRONG",
                    "availability": "AVAILABLE"
                },
                "reasoning": "Internal core team has direct experience building high-governance API microservices.",
                "evidenceIds": ["tc-1", "tc-2"],
                "confidence": 95
            }
        ]
    }

@router.patch("/opportunities/{id}/network-matches/{match_id}")
async def update_network_match(id: str, match_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    return {"success": True}

@router.get("/opportunities/{id}/introduction")
async def get_introduction_recommendation(id: str, user: dict = Depends(get_current_user)):
    return {
        "id": "intro-1",
        "opportunityId": id,
        "recommenderId": "rec-1",
        "recommenderName": "NetworkOS Founder",
        "recipientId": "recip-1",
        "recipientName": "Satya Nadella",
        "recipientTitle": "Chairman and CEO",
        "recipientCompany": "Microsoft",
        "messageDraft": "Satya, following up on your 2026 AI agent ecosystem announcements—Ottobon has engineered a bounded, turnkey governance bridge for enterprise agent compliance on Azure. We would welcome sharing the 2-week pilot benchmark with your engineering leads.",
        "status": "DRAFT",
        "confidence": 92
    }

@router.patch("/opportunities/{id}/introduction/{intro_id}/draft")
async def update_introduction_draft(id: str, intro_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    return {"success": True}

@router.patch("/opportunities/{id}/introduction/{intro_id}/status")
async def update_introduction_status(id: str, intro_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    return {"success": True}

@router.get("/opportunities/{id}/post-introduction")
async def get_post_introduction_data(id: str, user: dict = Depends(get_current_user)):
    return {
        "opportunityId": id,
        "introductionId": "intro-1",
        "status": "PENDING_MEETING",
        "conversations": [],
        "outcomes": []
    }

@router.patch("/opportunities/{id}/introduction-execution")
async def execute_introduction(id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    return {"success": True}

@router.post("/opportunities/{id}/conversations")
async def post_opportunity_conversation(id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    return {"success": True}

@router.post("/opportunities/{id}/feedback")
async def post_opportunity_feedback(id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    return {"success": True}

# --- Products & Capabilities ---

@router.get("/products")
async def list_products(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Product).order_by(Product.created_at.desc()))
    return res.scalars().all()

@router.post("/products")
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    new_prod = Product(
        id=f"prod-{uuid.uuid4().hex[:8]}",
        **data.model_dump()
    )
    db.add(new_prod)
    await db.commit()
    await db.refresh(new_prod)
    return new_prod

@router.get("/products/{product_id}")
async def get_product_by_id(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Product).where(Product.id == product_id))
    prod = res.scalars().first()
    if not prod:
        raise HTTPException(404, "Product not found")
    return prod

@router.put("/products/{product_id}")
async def update_product_by_id(
    product_id: str,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Product).where(Product.id == product_id))
    prod = res.scalars().first()
    if not prod:
        raise HTTPException(404, "Product not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(prod, k, v)
    await db.commit()
    await db.refresh(prod)
    return prod

@router.delete("/products/{product_id}")
async def delete_product_by_id(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Product).where(Product.id == product_id))
    prod = res.scalars().first()
    if not prod:
        raise HTTPException(404, "Product not found")
    await db.delete(prod)
    await db.commit()
    return {"success": True, "deleted_id": product_id}

@router.get("/capabilities")
async def list_capabilities(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Product).order_by(Product.created_at.desc()))
    products = res.scalars().all()
    caps = []
    for p in products:
        features_list = []
        if p.features:
            try:
                features_list = json.loads(p.features)
            except Exception:
                features_list = [f.strip() for f in p.features.split("\n") if f.strip()]
        caps.append({
            "id": p.id,
            "name": p.name,
            "category": "PRODUCT",
            "tagline": p.tagline,
            "description": p.description,
            "relevantExpertise": features_list[:4] if features_list else [p.category or "Product"],
            "evidenceSource": p.category or "Ottobon Portfolio",
            "targetAudience": p.target_audience,
            "businessModel": p.business_model,
            "status": p.status
        })
    return {"capabilities": caps}

@router.get("/capabilities/{id}")
async def get_capability_by_id(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    res = await db.execute(select(Product).where(Product.id == id))
    p = res.scalars().first()
    if not p:
        raise HTTPException(404, "Capability/Product not found")
    features_list = []
    if p.features:
        try:
            features_list = json.loads(p.features)
        except Exception:
            features_list = [f.strip() for f in p.features.split("\n") if f.strip()]
    return {
        "id": p.id,
        "name": p.name,
        "category": "PRODUCT",
        "tagline": p.tagline,
        "description": p.description,
        "relevantExpertise": features_list[:4] if features_list else [p.category or "Product"],
        "evidenceSource": p.category or "Ottobon Portfolio",
        "targetAudience": p.target_audience,
        "businessModel": p.business_model,
        "status": p.status
    }

# --- Network Intelligence ---

@router.get("/network/graph")
async def get_network_graph(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    contacts = (await db.execute(
        select(Contact).where(
            Contact.organization_id == user["organization_id"],
            Contact.full_name.isnot(None),
            Contact.full_name != "Unknown",
            Contact.full_name != ""
        )
    )).scalars().all()

    nodes = [
        {"id": "node-ottobon", "label": "Ottobon Founder", "type": "FOUNDER", "cluster": "core"}
    ]
    edges = []
    
    seen_people = {}
    seen_companies = set()

    for c in contacts:
        name = (c.full_name or "").strip()
        if not name or name in ("Unknown", "Unknown Contact", "Contact"):
            continue
        if c.id and (c.id.startswith("test-conflict") or c.id.startswith("test-assump") or c.id.startswith("test-uncert")):
            continue
        
        norm_name = name.lower()
        if norm_name in seen_people:
            existing = seen_people[norm_name]
            if (c.current_company and c.current_company != "Independent") and (not existing.current_company or existing.current_company == "Independent"):
                seen_people[norm_name] = c
        else:
            seen_people[norm_name] = c

    for norm_name, c in seen_people.items():
        person_name = c.full_name.strip()
        company = (c.current_company or "Independent").strip()

        # Add Person node
        nodes.append({
            "id": c.id,
            "label": person_name,
            "type": "PERSON",
            "cluster": company
        })
        # Add edge between Founder and Person
        edges.append({
            "source": "node-ottobon",
            "target": c.id,
            "label": "Strategic Target",
            "relationship": "STRATEGIC_TARGET",
            "strength": 85
        })

        # Add Company node and edge if valid company
        if company and company not in ("Independent", "None", "Unknown"):
            company_id = f"company-{company.lower().replace(' ', '-')}"
            if company not in seen_companies:
                seen_companies.add(company)
                nodes.append({
                    "id": company_id,
                    "label": company,
                    "type": "COMPANY",
                    "cluster": company
                })
            # Add edge between Person and Company
            edges.append({
                "source": c.id,
                "target": company_id,
                "label": c.current_title or "Executive",
                "relationship": "AFFILIATION",
                "strength": 90
            })

    return {"nodes": nodes, "edges": edges}

@router.get("/network/events")
async def get_network_events(user: dict = Depends(get_current_user)):
    return {
        "events": [
            {
                "id": "evt-1",
                "title": "Microsoft Copilot Ecosystem Expansion",
                "type": "INDUSTRY_ANNOUNCEMENT",
                "date": "2026-10-10",
                "impact": "High commercial relevance for Azure-compatible partner modules."
            }
        ]
    }

@router.get("/network/insights")
async def get_network_insights(user: dict = Depends(get_current_user)):
    return {
        "insights": [
            {
                "id": "ins-1",
                "title": "Enterprise Demand for AI Agent Governance",
                "category": "MARKET_TREND",
                "summary": "Increasing C-suite validation requirements before wide enterprise rollout of multi-agent workflows."
            }
        ]
    }

@router.get("/network/matches/{id}")
async def get_network_match_detail(id: str, user: dict = Depends(get_current_user)):
    return {
        "id": id,
        "title": "Enterprise AI Alignment Match",
        "matchScore": 95,
        "dimensions": {
            "relevance": "STRONG",
            "expertise": "STRONG",
            "relationshipStrength": "STRONG"
        }
    }

@router.get("/messages/drafts/{id}")
async def get_message_draft(id: str, user: dict = Depends(get_current_user)):
    return {
        "id": id,
        "recipientName": "Satya Nadella",
        "recipientTitle": "Chairman and CEO",
        "company": "Microsoft",
        "subject": "Ottobon AI Agent Governance Architecture",
        "body": "Satya, following up on recent enterprise Copilot extensibility developments—Ottobon has prepared a bounded proof-of-concept for automated agent verification. We would welcome sharing this brief with your team."
    }
