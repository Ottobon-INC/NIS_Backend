import logging
import re
from typing import List, Dict, Any, Optional, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.identity import Contact
from app.models.evidence import SourceResult
from app.services.semantic_product_matcher import SemanticProductMatcherService

logger = logging.getLogger(__name__)

STOPWORDS = {
    "and", "the", "for", "with", "from", "that", "this", "these", "those",
    "have", "has", "had", "will", "would", "can", "could", "should", "our",
    "their", "his", "her", "its", "into", "over", "after", "before", "while",
    "scaling", "growing", "managing", "improving", "conduct", "conducted",
    "sprint", "4-week", "diagnostic", "conduct", "active", "potential",
    "diverse", "global", "across", "while", "training", "expanding"
}


def _extract_keywords(text: str) -> Set[str]:
    if not text:
        return set()
    tokens = re.findall(r'[a-zA-Z0-9_\-\+]{3,}', text.lower())
    return {t for t in tokens if t not in STOPWORDS}


class ProblemSolverAggregatorService:
    """
    Aggregates all researched people problems and computes two solvable channels:
    1. Ottobon Internal Capabilities (Products & Pilot Sprint offerings)
    2. Network Connections Solvers (Existing connections whose role, craft masteries,
       or 'what_they_can_solve' profile can solve the target's problem).
    """

    @classmethod
    async def get_problems_and_solvers_board(cls, db: AsyncSession) -> List[Dict[str, Any]]:
        # 1. Fetch all contacts
        contacts_query = await db.execute(select(Contact))
        contacts_map: Dict[str, Contact] = {c.id: c for c in contacts_query.scalars().all()}

        # 2. Fetch all evidence engine snapshots (deduplicating to the latest snapshot per contact)
        sr_query = await db.execute(
            select(SourceResult)
            .where(SourceResult.source_id == "evidence_engine")
            .order_by(SourceResult.retrieved_at.desc())
        )
        srs = sr_query.scalars().all()

        latest_snapshots_by_contact: Dict[str, Dict[str, Any]] = {}
        for sr in srs:
            contact_id = (sr.metadata_ or {}).get("contact_id")
            if not contact_id and sr.entity_searched:
                # Match by entity name if contact_id metadata missing
                for cid, c in contacts_map.items():
                    if c.full_name and c.full_name.strip().lower() == sr.entity_searched.strip().lower():
                        contact_id = cid
                        break

            if contact_id and contact_id not in latest_snapshots_by_contact:
                if sr.extracted_data and "executive_snapshot" in sr.extracted_data:
                    latest_snapshots_by_contact[contact_id] = sr.extracted_data["executive_snapshot"]

        # 3. Categorize people into Solvers Pool
        solvers_pool: List[Dict[str, Any]] = []
        for cid, snap in latest_snapshots_by_contact.items():
            contact = contacts_map.get(cid)
            name = snap.get("name") or (contact.full_name if contact else "Unknown")
            role = snap.get("current_role") or (contact.current_title if contact else "Unknown")
            company = snap.get("current_organization") or (contact.current_company if contact else "Unknown")
            what_they_can_solve = snap.get("what_they_can_solve") or []
            core_strengths = snap.get("core_strengths") or []
            domain_knowledge = snap.get("domain_knowledge") or snap.get("proven_domain_expertise") or ""
            domain_name = snap.get("domain_name") or ""
            tier = snap.get("networkos_tier") or getattr(contact, "tier", "Tier 3")

            # Collect keywords for this solver
            solver_text = f"{role} {domain_name} {domain_knowledge} {' '.join(what_they_can_solve)} {' '.join(core_strengths)}"
            keywords = _extract_keywords(solver_text)

            solvers_pool.append({
                "contact_id": cid,
                "name": name,
                "role": role,
                "company": company,
                "tier": tier,
                "what_they_can_solve": what_they_can_solve,
                "core_strengths": core_strengths,
                "domain_knowledge": domain_knowledge,
                "domain_name": domain_name,
                "keywords": keywords,
                "raw_text": solver_text.lower()
            })

        # 4. Extract verified problems and match them
        board_items: List[Dict[str, Any]] = []
        for cid, snap in latest_snapshots_by_contact.items():
            contact = contacts_map.get(cid)
            name = snap.get("name") or (contact.full_name if contact else "Unknown")
            role = snap.get("current_role") or (contact.current_title if contact else "Unknown")
            company = snap.get("current_organization") or (contact.current_company if contact else "Unknown")
            location = snap.get("location") or (contact.location if contact else None)
            tier = snap.get("networkos_tier") or getattr(contact, "tier", "Tier 3")
            linkedin_url = contact.profile_url if contact else snap.get("profile_url")

            broad_problem = snap.get("broad_business_problem")
            smallest_problem = snap.get("smallest_solvable_problem")
            epistemic_status = snap.get("problem_epistemic_status")
            if hasattr(epistemic_status, "value"):
                epistemic_status = epistemic_status.value
            epistemic_status = str(epistemic_status or "INSUFFICIENT_EVIDENCE")

            # Filter out non-problems or unverified placeholder text
            if not broad_problem and not smallest_problem:
                continue

            prob_text = f"{broad_problem or ''} {smallest_problem or ''}".strip()
            if SemanticProductMatcherService._is_unverified_problem(prob_text):
                continue
            if epistemic_status in ["NO_OBSERVED_PROBLEM", "INSUFFICIENT_EVIDENCE"]:
                continue

            # A. Ottobon Internal Capability Solvable Way
            ottobon_capability = snap.get("ottobon_capability_match") or "Engineering & Technical Consulting"
            pilot_sprint = smallest_problem or broad_problem or "Scoping Sprint"
            delivery_risk = snap.get("delivery_risk_level", "LOW")
            pricing = snap.get("cost_pricing_estimate") or "Milestone Sprint ($10k - $15k internal assumption)"

            ottobon_way = {
                "capability": ottobon_capability,
                "proposed_sprint": pilot_sprint,
                "delivery_risk": delivery_risk,
                "cost_pricing_estimate": pricing,
                "why_now": snap.get("why_now") or "Active enterprise growth / system scaling signals."
            }

            # B. Network Connections Solvers (X -> Y)
            problem_keywords = _extract_keywords(prob_text + " " + (snap.get("domain_name") or ""))
            matched_solvers: List[Dict[str, Any]] = []

            for solver in solvers_pool:
                if solver["contact_id"] == cid:
                    continue  # Can't match person to themselves

                overlap = problem_keywords.intersection(solver["keywords"])
                matched_items = []

                # 1. Check explicit what_they_can_solve matches
                for cap in solver["what_they_can_solve"]:
                    cap_kw = _extract_keywords(cap)
                    if cap_kw.intersection(problem_keywords):
                        matched_items.append(cap)

                # 2. Check core strengths matches
                for strength in solver["core_strengths"]:
                    st_kw = _extract_keywords(strength)
                    if st_kw.intersection(problem_keywords) and strength not in matched_items:
                        matched_items.append(f"Strength: {strength}")

                # 3. Determine match strength
                match_strength = None
                reason = ""
                if matched_items:
                    match_strength = "STRONG"
                    reason = f"Explicit solver capability overlap: {', '.join(matched_items[:2])}"
                elif len(overlap) >= 2:
                    match_strength = "MODERATE"
                    overlap_sample = ", ".join(list(overlap)[:3])
                    reason = f"Domain alignment on: {overlap_sample} ({solver['role']} at {solver['company']})"

                if match_strength:
                    matched_solvers.append({
                        "solver_contact_id": solver["contact_id"],
                        "solver_name": solver["name"],
                        "solver_title": solver["role"],
                        "solver_company": solver["company"],
                        "solver_tier": solver["tier"],
                        "match_strength": match_strength,
                        "matched_capabilities": matched_items if matched_items else [solver["role"]],
                        "core_strengths": solver["core_strengths"],
                        "solver_reason": reason
                    })

            # Sort network solvers: STRONG first, then by tier/name
            matched_solvers.sort(key=lambda s: (0 if s["match_strength"] == "STRONG" else 1, s["solver_name"]))

            board_items.append({
                "contact_id": cid,
                "contact_name": name,
                "contact_title": role,
                "contact_company": company,
                "contact_location": location,
                "contact_tier": tier,
                "linkedin_url": linkedin_url,
                "epistemic_status": epistemic_status,
                "broad_business_problem": broad_problem,
                "smallest_solvable_problem": smallest_problem,
                "why_now": snap.get("why_now"),
                "ottobon_solvable_way": ottobon_way,
                "network_solvers": matched_solvers
            })

        # Sort items: EVIDENCE_GROUNDED first, then SUPPORTED_INFERENCE
        board_items.sort(
            key=lambda item: (
                0 if item["epistemic_status"] == "EVIDENCE_GROUNDED" else (
                    1 if item["epistemic_status"] == "SUPPORTED_INFERENCE" else 2
                ),
                item["contact_name"]
            )
        )

        return board_items
