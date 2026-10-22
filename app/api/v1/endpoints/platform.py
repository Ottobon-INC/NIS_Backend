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

# Opportunities routes are canonically owned and served by app.api.v1.endpoints.opportunities

@router.get("/opportunities/{id}/network-matches")
async def get_opportunity_network_matches(
    id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    from app.models.opportunity import Opportunity
    from app.models.company_knowledge import Product, Capability
    opp = (await db.execute(select(Opportunity).where(Opportunity.id == id))).scalars().first()
    selected_cap = {
        "id": "cap-1",
        "name": "AI Applications & Backend Systems",
        "category": "SERVICE",
        "description": "Delivery of custom enterprise agent systems and verification bridges.",
        "relevantExpertise": ["Generative AI", "Azure Architecture", "Governance", "API Integration"],
        "evidenceSource": "Ottobon Capabilities Catalog 2026"
    }
    if opp and opp.selected_solution_id:
        prod = (await db.execute(select(Product).where(Product.id == opp.selected_solution_id))).scalars().first()
        if prod:
            selected_cap = {
                "id": prod.id,
                "name": prod.name,
                "category": "PRODUCT",
                "description": prod.description or prod.tagline or "",
                "relevantExpertise": [prod.name, "Enterprise Offering"],
                "evidenceSource": "Internal Products Catalog"
            }
        else:
            cap = (await db.execute(select(Capability).where(Capability.id == opp.selected_solution_id))).scalars().first()
            if cap:
                selected_cap = {
                    "id": cap.id,
                    "name": cap.name,
                    "category": "CAPABILITY",
                    "description": cap.description or "",
                    "relevantExpertise": [cap.name, "Verified Capability"],
                    "evidenceSource": "Internal Capabilities Catalog"
                }
    elif opp and opp.matched_product_name:
        selected_cap["name"] = opp.matched_product_name

    return {
        "selectedCapability": selected_cap,
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
