"""
Opportunity Live Search Service.
Module 3: PostgreSQL-backed faceted search with relevance scoring and match reasoning.
Enforces multi-tenant isolation (organization_id), zero in-memory full-table scans,
and indexed SQL queries joining Opportunity and Contact.
"""

import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import func, or_, case

from app.models.opportunity import Opportunity, OpportunityLifecycleStatus
from app.models.identity import Contact
from app.schemas.opportunity import (
    to_backend_status,
    OpportunityOut,
    OpportunitySearchResult,
    OpportunitySearchResponse,
)

logger = logging.getLogger("networkos.opportunity_search")


class OpportunitySearchService:
    """
    High-performance live opportunity search engine backed by PostgreSQL.
    Searches title, problem, requirement, company name, and champion contact name.
    Calculates relevance scores (0-100+) and generates human-readable match reasons.
    """

    @classmethod
    async def search_opportunities(
        cls,
        db: AsyncSession,
        organization_id: str,
        q: str = "",
        status: Optional[str] = None,
        min_confidence: int = 0,
        opportunity_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> OpportunitySearchResponse:
        """
        Executes a real-time database query across opportunities and champion contacts
        scoped strictly to the tenant organization.
        """
        query_str = (q or "").strip()
        q_lower = query_str.lower()

        # Base tenant condition
        conditions = [Opportunity.organization_id == organization_id]

        # 1. Status Filter (Frontend aliases & backend canonical enums)
        if status and status.strip().upper() != "ALL":
            cleaned_status = status.strip().upper()
            if cleaned_status == "CANDIDATE":
                candidate_statuses = [
                    OpportunityLifecycleStatus.DISCOVERED,
                    OpportunityLifecycleStatus.SOURCE_VERIFIED,
                    OpportunityLifecycleStatus.MATCH_REVIEW,
                ]
                conditions.append(Opportunity.status.in_(candidate_statuses))
            elif cleaned_status in ("VALIDATED", "PATH_DEFINED"):
                conditions.append(Opportunity.status == OpportunityLifecycleStatus.QUALIFIED)
            elif cleaned_status == "SOLUTION_MATCHING":
                conditions.append(Opportunity.status == OpportunityLifecycleStatus.MATCH_REVIEW)
            elif cleaned_status == "PIPELINE":
                conditions.append(Opportunity.status == OpportunityLifecycleStatus.ACTIVE)
            elif cleaned_status == "OUTCOME":
                outcome_statuses = [
                    OpportunityLifecycleStatus.WON,
                    OpportunityLifecycleStatus.LOST,
                ]
                conditions.append(Opportunity.status.in_(outcome_statuses))
            else:
                try:
                    be_status = to_backend_status(cleaned_status)
                    conditions.append(Opportunity.status == be_status)
                except ValueError:
                    logger.warning(f"Invalid status filter '{status}' provided to search_opportunities")
                    return OpportunitySearchResponse(query=q, total=0, results=[])

        # 2. Confidence Threshold Filter
        if min_confidence and min_confidence > 0:
            conditions.append(Opportunity.confidence >= min_confidence)

        # 3. Opportunity Type / Category Filter
        if opportunity_type and opportunity_type.strip().upper() != "ALL":
            conditions.append(func.lower(Opportunity.opportunity_type) == opportunity_type.strip().lower())

        # Champion contact name column expression (handling nullable contacts)
        contact_name_col = func.coalesce(Contact.full_name, "")

        # 4. Search Keyword Filter & Scoring Expression
        words = [w.strip() for w in query_str.split() if len(w.strip()) > 1]

        if query_str:
            escaped = query_str.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"

            search_terms = [
                Opportunity.title.ilike(pattern),
                Opportunity.company_name.ilike(pattern),
                Opportunity.problem.ilike(pattern),
                Opportunity.requirement.ilike(pattern),
                contact_name_col.ilike(pattern),
            ]

            # If multi-word, also match individual terms for recall
            if len(words) > 1:
                for w in words:
                    w_esc = w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    w_pattern = f"%{w_esc}%"
                    search_terms.extend([
                        Opportunity.title.ilike(w_pattern),
                        Opportunity.company_name.ilike(w_pattern),
                        Opportunity.problem.ilike(w_pattern),
                        Opportunity.requirement.ilike(w_pattern),
                        contact_name_col.ilike(w_pattern),
                    ])

            conditions.append(or_(*search_terms))

            # Database-level relevance calculation
            score_expr = (
                case((Opportunity.title.ilike(pattern), 50), else_=0) +
                case((Opportunity.company_name.ilike(pattern), 40), else_=0) +
                case((contact_name_col.ilike(pattern), 35), else_=0) +
                case((Opportunity.problem.ilike(pattern), 30), else_=0) +
                case((Opportunity.requirement.ilike(pattern), 25), else_=0)
            )
        else:
            score_expr = case((True, 100), else_=100)

        # 5. Count Total Matching Records
        count_stmt = (
            select(func.count(Opportunity.id))
            .outerjoin(Contact, Opportunity.contact_id == Contact.id)
            .where(*conditions)
        )
        total_res = await db.execute(count_stmt)
        total = total_res.scalar() or 0

        if total == 0:
            return OpportunitySearchResponse(query=q, total=0, results=[])

        # 6. Fetch Page of Records
        stmt = (
            select(Opportunity, score_expr.label("score"))
            .outerjoin(Contact, Opportunity.contact_id == Contact.id)
            .options(joinedload(Opportunity.contact))
            .where(*conditions)
        )

        if query_str:
            stmt = stmt.order_by(score_expr.desc(), Opportunity.created_at.desc())
        else:
            stmt = stmt.order_by(Opportunity.created_at.desc())

        stmt = stmt.offset(offset).limit(limit)
        results_rows = (await db.execute(stmt)).all()

        # 7. Build Search Results with Human-Readable Match Reasons
        search_results: List[OpportunitySearchResult] = []
        for row in results_rows:
            opp = row[0]
            sql_score = int(row[1]) if len(row) > 1 and row[1] is not None else 100

            reasons: List[str] = []
            if not query_str:
                score = 100
                reasons = ["General inquiry match"]
            else:
                champion_name = (opp.contact.full_name if opp.contact else opp.person_name) or ""
                if q_lower in (opp.title or "").lower():
                    reasons.append("Title match")
                if q_lower in (opp.company_name or "").lower():
                    reasons.append(f"Company: {opp.company_name}")
                if champion_name and q_lower in champion_name.lower():
                    reasons.append(f"Champion: {champion_name}")
                if q_lower in (opp.problem or "").lower():
                    reasons.append("Problem description match")
                if q_lower in (opp.requirement or "").lower():
                    reasons.append("Requirement match")

                # If word-level matches occurred when full phrase wasn't all-in-one
                if not reasons and len(words) > 1:
                    for w in words:
                        wl = w.lower()
                        if wl in (opp.title or "").lower():
                            reasons.append(f"Title keyword: {w}")
                        if wl in (opp.company_name or "").lower():
                            reasons.append(f"Company: {opp.company_name}")
                        if champion_name and wl in champion_name.lower():
                            reasons.append(f"Champion: {champion_name}")
                        if wl in (opp.problem or "").lower():
                            reasons.append("Problem description match")
                        if wl in (opp.requirement or "").lower():
                            reasons.append("Requirement match")

                if not reasons:
                    reasons = ["Partial keyword match"]

                # Ensure score reflects matches even if word-level
                score = max(sql_score, 20 if reasons and reasons != ["Partial keyword match"] else 10)

            opp_out = OpportunityOut.model_validate(opp)
            opp_dict = opp_out.model_dump()
            opp_dict["relevanceScore"] = score
            opp_dict["matchReasons"] = reasons

            search_results.append(OpportunitySearchResult.model_validate(opp_dict))

        return OpportunitySearchResponse(
            query=q,
            total=total,
            results=search_results,
        )
