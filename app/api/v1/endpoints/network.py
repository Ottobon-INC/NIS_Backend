from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Dict, Any

from app.db.session import get_db
from app.models.identity import Contact, ContactType
from app.api.dependencies import get_current_user

router = APIRouter()


@router.get("/graph")
async def get_network_graph(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Returns live graph nodes and edges representing the network:
    - Root Node: Bhanu (Founder)
    - Target prospects (e.g. Rahul Dhamdhere, David Chen)
    - Bhanu's imported connections
    - Company nodes connecting people
    """
    # 1. Fetch Target contacts
    targets_stmt = (
        select(Contact)
        .where(Contact.contact_type == ContactType.TARGET)
        .limit(20)
    )
    targets_res = await db.execute(targets_stmt)
    targets = targets_res.scalars().all()

    # 2. Fetch sample of Bhanu's connections
    bhanu_stmt = (
        select(Contact)
        .where(Contact.contact_type == ContactType.BHANU_CONNECTION)
        .limit(30)
    )
    bhanu_res = await db.execute(bhanu_stmt)
    bhanu_conns = bhanu_res.scalars().all()

    nodes: List[Dict[str, Any]] = [
        {"id": "bhanu-root", "label": "Bhanu (Founder)", "type": "PERSON"}
    ]
    edges: List[Dict[str, Any]] = []

    seen_nodes = {"bhanu-root"}
    company_nodes = set()

    # Add Target Prospects
    for t in targets:
        tid = f"target-{t.id}"
        if tid not in seen_nodes:
            seen_nodes.add(tid)
            nodes.append({
                "id": tid,
                "label": t.full_name or "Target Prospect",
                "type": "PERSON"
            })

        # Company node
        if t.current_company and t.current_company != "Pending research":
            cid = f"comp-{t.current_company.lower().replace(' ', '-')}"
            if cid not in seen_nodes:
                seen_nodes.add(cid)
                company_nodes.add(cid)
                nodes.append({
                    "id": cid,
                    "label": t.current_company,
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
        if bc_id not in seen_nodes:
            seen_nodes.add(bc_id)
            nodes.append({
                "id": bc_id,
                "label": bc.full_name or "Connection",
                "type": "PERSON"
            })

        # Connect Bhanu to his connection
        edges.append({
            "source": "bhanu-root",
            "target": bc_id,
            "label": f"Strength: {bc.relationship_strength or 3}/5"
        })

        # Connect to their company
        if bc.current_company:
            cid = f"comp-{bc.current_company.lower().replace(' ', '-')}"
            if cid not in seen_nodes:
                seen_nodes.add(cid)
                nodes.append({
                    "id": cid,
                    "label": bc.current_company,
                    "type": "COMPANY"
                })
            edges.append({
                "source": bc_id,
                "target": cid,
                "label": bc.current_title or "Works At"
            })

    return {
        "nodes": nodes,
        "edges": edges
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
