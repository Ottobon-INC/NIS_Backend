from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import distinct, or_
from typing import List, Dict, Any, Optional

from app.db.session import get_db
from app.models.identity import Contact, ContactType
from app.models.orchestration import ResearchRun
from app.api.dependencies import get_current_user

router = APIRouter()


@router.get("/graph")
async def get_network_graph(
    q: Optional[str] = Query(default=None, description="Optional search term to filter nodes"),
    limit: int = Query(default=1000, description="Max connections to return"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Returns live graph nodes and edges representing the network:
    - Root Node: Bhanu (Founder)
    - Target prospects (e.g. Rahul Dhamdhere, David Chen)
    - Bhanu's imported connections (all unique deduplicated records from CSV)
    - Company nodes connecting people
    """
    clean_q = q.strip() if isinstance(q, str) and q.strip() else None
    limit_val = limit if isinstance(limit, int) else 1000

    # 1. Fetch researched contact IDs so nodes know their deep research status
    run_cids_res = await db.execute(select(ResearchRun.contact_id).distinct().where(ResearchRun.contact_id.isnot(None)))
    researched_set = set(run_cids_res.scalars().all())

    # 2. Fetch Target contacts with stable alphabetical sort
    targets_stmt = (
        select(Contact)
        .where(Contact.contact_type.in_([ContactType.TARGET, "TARGET_PROSPECT"]))
        .order_by(Contact.full_name.asc())
    )
    if clean_q:
        search_term = f"%{clean_q}%"
        targets_stmt = targets_stmt.where(
            or_(
                Contact.full_name.ilike(search_term),
                Contact.current_company.ilike(search_term),
                Contact.current_title.ilike(search_term)
            )
        )
    targets = (await db.execute(targets_stmt)).scalars().all()

    # 3. Fetch Bhanu's imported connections with deterministic alphabetical order
    bhanu_stmt = (
        select(Contact)
        .where(Contact.contact_type == ContactType.BHANU_CONNECTION)
        .order_by(Contact.full_name.asc())
        .limit(limit_val)
    )
    if clean_q:
        search_term = f"%{clean_q}%"
        bhanu_stmt = (
            select(Contact)
            .where(Contact.contact_type == ContactType.BHANU_CONNECTION)
            .where(
                or_(
                    Contact.full_name.ilike(search_term),
                    Contact.current_company.ilike(search_term),
                    Contact.current_title.ilike(search_term)
                )
            )
            .order_by(Contact.full_name.asc())
            .limit(limit)
        )

    bhanu_conns = (await db.execute(bhanu_stmt)).scalars().all()

    nodes: List[Dict[str, Any]] = [
        {
            "id": "bhanu-root",
            "label": "Bhanu (Founder)",
            "type": "PERSON",
            "role": "Founder & Managing Director",
            "company": "Ottobon",
            "origin": "FOUNDER"
        }
    ]
    edges: List[Dict[str, Any]] = []

    seen_nodes = {"bhanu-root"}

    # Add Target Prospects
    for t in targets:
        tid = f"target-{t.id}"
        has_research = (t.id in researched_set)
        if tid not in seen_nodes:
            seen_nodes.add(tid)
            nodes.append({
                "id": tid,
                "contactId": t.id,
                "label": t.full_name or "Target Prospect",
                "type": "PERSON",
                "role": t.current_title or "Target Executive",
                "company": t.current_company or "Enterprise Target",
                "hasResearch": has_research,
                "researchStatus": t.status.value if hasattr(t.status, 'value') else str(t.status),
                "origin": "TARGET"
            })

        # Company node
        if t.current_company and t.current_company not in ["Pending research", "Unknown", "[UNVERIFIED]", "None"]:
            cid = f"comp-{t.current_company.strip().lower().replace(' ', '-')}"
            if cid not in seen_nodes:
                seen_nodes.add(cid)
                nodes.append({
                    "id": cid,
                    "label": t.current_company.strip(),
                    "type": "COMPANY"
                })
            edges.append({
                "source": tid,
                "target": cid,
                "label": t.current_title or "Employed At"
            })

    # Add Bhanu's Connections
    for bc in bhanu_conns:
        bc_id = f"conn-{bc.id}"
        has_research = (bc.id in researched_set)
        if bc_id not in seen_nodes:
            seen_nodes.add(bc_id)
            nodes.append({
                "id": bc_id,
                "contactId": bc.id,
                "label": bc.full_name or "Connection",
                "type": "PERSON",
                "role": bc.current_title or "LinkedIn Connection",
                "company": bc.current_company or "Independent",
                "hasResearch": has_research,
                "researchStatus": bc.status.value if hasattr(bc.status, 'value') else str(bc.status),
                "relationshipStrength": bc.relationship_strength or 3,
                "reachability": bc.reachability or "UNKNOWN",
                "connectedSince": bc.connected_since.isoformat() if bc.connected_since else None,
                "isScored": bc.is_scored,
                "origin": "BHANU_CONNECTION"
            })

        # Connect Bhanu to his connection
        edges.append({
            "source": "bhanu-root",
            "target": bc_id,
            "label": f"Strength: {bc.relationship_strength or 3}/5"
        })

        # Connect to their company
        if bc.current_company and bc.current_company not in ["Pending research", "Unknown", "[UNVERIFIED]", "None"]:
            cid = f"comp-{bc.current_company.strip().lower().replace(' ', '-')}"
            if cid not in seen_nodes:
                seen_nodes.add(cid)
                nodes.append({
                    "id": cid,
                    "label": bc.current_company.strip(),
                    "type": "COMPANY"
                })
            edges.append({
                "source": bc_id,
                "target": cid,
                "label": bc.current_title or "Works At"
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "total_people": len([n for n in nodes if n["type"] == "PERSON"]),
        "total_companies": len([n for n in nodes if n["type"] == "COMPANY"]),
        "total_connections": len(edges)
    }


@router.get("/events")
async def get_network_events(
    user: dict = Depends(get_current_user),
):
    return {
        "events": [
            {
                "id": "ev-1",
                "title": "Network Ingestion Complete",
                "description": "Bhanu's connections imported successfully to populate route intelligence.",
                "contactId": "bhanu-root",
                "contactName": "Bhanu",
                "date": "Today",
                "signalStrength": "HIGH"
            }
        ]
    }


@router.get("/insights")
async def get_network_insights(
    user: dict = Depends(get_current_user),
):
    return {
        "insights": [
            {
                "id": "ins-1",
                "title": "Bhanu Network Bridge Capacity",
                "description": "Imported connections enable single-hop warm intros to enterprise targets.",
                "patternStrength": "STRONG",
                "isConfirmed": True,
                "relatedNodesCount": 5
            }
        ]
    }
