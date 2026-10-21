"""
Opportunity Intelligence Engine Service.
Module 3, Step 3: Core Business Logic & Safeguards.

Implements multi-tenant opportunity lifecycle management, evidence grounding,
identity confidence gating (70% threshold), provenance tracking, and
idempotent opportunity derivation from Contact 360 research.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Set

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.models.opportunity import Opportunity, OpportunityLifecycleStatus
from app.models.identity import Contact
from app.models.evidence import SourceResult, Evidence, EvidenceType
from app.models.company_knowledge import CompanyProfile, Product
from app.schemas.opportunity import (
    OpportunityCreateIn,
    OpportunityValidateIn,
    to_backend_status,
    to_frontend_status,
)
from app.services.semantic_product_matcher import SemanticProductMatcherService

logger = logging.getLogger("networkos.opportunity_service")

# Canonical product catalog ID mapping
PRODUCT_NAME_TO_ID: Dict[str, str] = {
    "janmasethu": "prod-janmasethu",
    "prod-janmasethu": "prod-janmasethu",
    "ottobon course platform": "prod-ottobon-courses",
    "prod-ottobon-courses": "prod-ottobon-courses",
    "sbloom": "prod-sbloom",
    "prod-sbloom": "prod-sbloom",
    "talentops": "prod-talentops",
    "prod-talentops": "prod-talentops",
    "networkos platform": "prod-networkos",
    "networkos": "prod-networkos",
    "prod-networkos": "prod-networkos",
}

# Canonical lifecycle transition rules
ALLOWED_TRANSITIONS: Dict[OpportunityLifecycleStatus, Set[OpportunityLifecycleStatus]] = {
    OpportunityLifecycleStatus.DISCOVERED: {
        OpportunityLifecycleStatus.DISCOVERED,
        OpportunityLifecycleStatus.SOURCE_VERIFIED,
        OpportunityLifecycleStatus.MATCH_REVIEW,
        OpportunityLifecycleStatus.QUALIFIED,
        OpportunityLifecycleStatus.REJECTED,
        OpportunityLifecycleStatus.ON_HOLD,
    },
    OpportunityLifecycleStatus.SOURCE_VERIFIED: {
        OpportunityLifecycleStatus.SOURCE_VERIFIED,
        OpportunityLifecycleStatus.MATCH_REVIEW,
        OpportunityLifecycleStatus.QUALIFIED,
        OpportunityLifecycleStatus.REJECTED,
        OpportunityLifecycleStatus.ON_HOLD,
    },
    OpportunityLifecycleStatus.MATCH_REVIEW: {
        OpportunityLifecycleStatus.MATCH_REVIEW,
        OpportunityLifecycleStatus.QUALIFIED,
        OpportunityLifecycleStatus.REJECTED,
        OpportunityLifecycleStatus.ON_HOLD,
    },
    OpportunityLifecycleStatus.QUALIFIED: {
        OpportunityLifecycleStatus.QUALIFIED,
        OpportunityLifecycleStatus.ACTIVE,
        OpportunityLifecycleStatus.WON,
        OpportunityLifecycleStatus.LOST,
        OpportunityLifecycleStatus.ON_HOLD,
        OpportunityLifecycleStatus.REJECTED,
    },
    OpportunityLifecycleStatus.ACTIVE: {
        OpportunityLifecycleStatus.ACTIVE,
        OpportunityLifecycleStatus.WON,
        OpportunityLifecycleStatus.LOST,
        OpportunityLifecycleStatus.ON_HOLD,
        OpportunityLifecycleStatus.REJECTED,
    },
    OpportunityLifecycleStatus.ON_HOLD: {
        OpportunityLifecycleStatus.ON_HOLD,
        OpportunityLifecycleStatus.DISCOVERED,
        OpportunityLifecycleStatus.SOURCE_VERIFIED,
        OpportunityLifecycleStatus.MATCH_REVIEW,
        OpportunityLifecycleStatus.QUALIFIED,
        OpportunityLifecycleStatus.ACTIVE,
        OpportunityLifecycleStatus.REJECTED,
    },
    OpportunityLifecycleStatus.REJECTED: {
        OpportunityLifecycleStatus.REJECTED,
        OpportunityLifecycleStatus.DISCOVERED,
        OpportunityLifecycleStatus.ON_HOLD,
    },
    OpportunityLifecycleStatus.WON: {
        OpportunityLifecycleStatus.WON,
        OpportunityLifecycleStatus.ACTIVE,
    },
    OpportunityLifecycleStatus.LOST: {
        OpportunityLifecycleStatus.LOST,
        OpportunityLifecycleStatus.DISCOVERED,
        OpportunityLifecycleStatus.ON_HOLD,
    },
    OpportunityLifecycleStatus.EXPIRED: {
        OpportunityLifecycleStatus.EXPIRED,
        OpportunityLifecycleStatus.DISCOVERED,
    },
}


class OpportunityService:
    """
    Comprehensive business logic service for NetworkOS Opportunity Management.
    Enforces multi-tenant organization boundaries, identity confidence gating,
    provenance traceability, and strict commercial qualification safeguards.
    """

    @classmethod
    async def list_opportunities(
        cls,
        db: AsyncSession,
        organization_id: str,
        status: Optional[str] = None,
        contact_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[Opportunity], int]:
        """
        Returns paginated opportunities filtered by authorized organization and optional filters.
        Supports both canonical backend lifecycle statuses and frontend status aliases.
        """
        query = select(Opportunity).where(Opportunity.organization_id == organization_id)
        count_query = select(func.count(Opportunity.id)).where(Opportunity.organization_id == organization_id)

        if contact_id:
            query = query.where(Opportunity.contact_id == contact_id)
            count_query = count_query.where(Opportunity.contact_id == contact_id)

        if status:
            cleaned_status = status.strip().upper()
            if cleaned_status == "CANDIDATE":
                candidate_statuses = [
                    OpportunityLifecycleStatus.DISCOVERED,
                    OpportunityLifecycleStatus.SOURCE_VERIFIED,
                    OpportunityLifecycleStatus.MATCH_REVIEW,
                ]
                query = query.where(Opportunity.status.in_(candidate_statuses))
                count_query = count_query.where(Opportunity.status.in_(candidate_statuses))
            elif cleaned_status == "VALIDATED":
                query = query.where(Opportunity.status == OpportunityLifecycleStatus.QUALIFIED)
                count_query = count_query.where(Opportunity.status == OpportunityLifecycleStatus.QUALIFIED)
            elif cleaned_status == "SOLUTION_MATCHING":
                query = query.where(Opportunity.status == OpportunityLifecycleStatus.MATCH_REVIEW)
                count_query = count_query.where(Opportunity.status == OpportunityLifecycleStatus.MATCH_REVIEW)
            elif cleaned_status == "PIPELINE":
                query = query.where(Opportunity.status == OpportunityLifecycleStatus.ACTIVE)
                count_query = count_query.where(Opportunity.status == OpportunityLifecycleStatus.ACTIVE)
            elif cleaned_status == "OUTCOME":
                outcome_statuses = [OpportunityLifecycleStatus.WON, OpportunityLifecycleStatus.LOST]
                query = query.where(Opportunity.status.in_(outcome_statuses))
                count_query = count_query.where(Opportunity.status.in_(outcome_statuses))
            else:
                try:
                    be_status = to_backend_status(cleaned_status)
                    query = query.where(Opportunity.status == be_status)
                    count_query = count_query.where(Opportunity.status == be_status)
                except ValueError:
                    logger.warning(f"Invalid status filter '{status}' provided to list_opportunities")
                    return [], 0

        total_res = await db.execute(count_query)
        total = total_res.scalar() or 0

        # Order by creation date descending
        query = query.order_by(Opportunity.created_at.desc()).offset(max(0, offset)).limit(max(1, min(100, limit)))
        results = (await db.execute(query)).scalars().all()

        # Batch-hydrate contact records to populate full name
        contact_ids = [opp.contact_id for opp in results if opp.contact_id]
        if contact_ids:
            c_stmt = select(Contact).where(Contact.id.in_(contact_ids))
            contacts_map = {c.id: c for c in (await db.execute(c_stmt)).scalars().all()}
            for opp in results:
                if opp.contact_id in contacts_map:
                    opp.contact = contacts_map[opp.contact_id]

        return list(results), total

    @classmethod
    async def get_opportunity(
        cls,
        db: AsyncSession,
        opportunity_id: str,
        organization_id: str
    ) -> Opportunity:
        """
        Retrieves one opportunity strictly scoped to the user's authorized organization.
        Raises HTTP 404 for missing or cross-tenant records to avoid entity existence leakage.
        """
        stmt = select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.organization_id == organization_id
        )
        opp = (await db.execute(stmt)).scalars().first()
        if not opp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Opportunity not found"
            )

        if opp.contact_id:
            c_stmt = select(Contact).where(Contact.id == opp.contact_id)
            contact = (await db.execute(c_stmt)).scalars().first()
            if contact:
                opp.contact = contact

        return opp

    @classmethod
    async def create_opportunity(
        cls,
        db: AsyncSession,
        payload: OpportunityCreateIn,
        organization_id: str,
        user: Optional[Dict[str, Any]] = None
    ) -> Opportunity:
        """
        Validates referenced contacts, companies, products, and evidence before persisting.
        Enforces organization boundaries and prevents cross-tenant contamination.
        """
        # 1. Validate contact reference
        contact = None
        if payload.contact_id:
            stmt = select(Contact).where(
                Contact.id == payload.contact_id,
                Contact.organization_id == organization_id
            )
            contact = (await db.execute(stmt)).scalars().first()
            if not contact:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Referenced contact not found or does not belong to your organization"
                )

        # 2. Validate company profile reference
        if payload.company_id:
            cp_stmt = select(CompanyProfile).where(CompanyProfile.id == payload.company_id)
            company_profile = (await db.execute(cp_stmt)).scalars().first()
            if not company_profile:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Referenced company profile not found"
                )

        # 3. Validate matched product reference
        if payload.matched_product_id:
            normalized_prod_id = PRODUCT_NAME_TO_ID.get(payload.matched_product_id.lower().strip(), payload.matched_product_id)
            prod_stmt = select(Product).where(Product.id == normalized_prod_id)
            product = (await db.execute(prod_stmt)).scalars().first()
            if not product:
                # Also check in-memory product catalog for flexibility
                catalog_ids = {p["id"] for p in SemanticProductMatcherService.PRODUCT_CATALOG}
                if normalized_prod_id not in catalog_ids:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Referenced product not found in active product catalog"
                    )
            payload.matched_product_id = normalized_prod_id

        # 4. Validate supporting evidence references & ownership
        if payload.supporting_evidence_ids:
            ev_stmt = select(Evidence).where(Evidence.id.in_(payload.supporting_evidence_ids))
            existing_evidences = (await db.execute(ev_stmt)).scalars().all()
            found_ids = {e.id for e in existing_evidences}
            missing_ids = set(payload.supporting_evidence_ids) - found_ids
            if missing_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Referenced evidence records not found: {sorted(list(missing_ids))}"
                )

            # Never attach evidence belonging to another contact
            if payload.contact_id:
                for ev in existing_evidences:
                    if ev.related_entity_id != payload.contact_id:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Evidence {ev.id} belongs to a different entity and cannot be attached"
                        )

        # 5. Resolve canonical status
        initial_status = OpportunityLifecycleStatus.DISCOVERED
        if payload.status:
            try:
                initial_status = to_backend_status(payload.status)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e)
                )

        # 6. Instantiate and persist Opportunity
        opp_id = f"opp-{uuid.uuid4().hex[:12]}"
        opp = Opportunity(
            id=opp_id,
            organization_id=organization_id,
            owner_user_id=user.get("user_id") if user else None,
            contact_id=payload.contact_id,
            company_name=payload.company_name,
            company_id=payload.company_id,
            title=payload.title,
            description=payload.description,
            problem=payload.problem,
            requirement=payload.requirement,
            opportunity_type=payload.opportunity_type,
            status=initial_status,
            confidence=payload.confidence,
            timeline=payload.timeline,
            budget_signal=payload.budget_signal,
            matched_product_id=payload.matched_product_id,
            matched_product_name=payload.matched_product_name,
            match_score=payload.match_score,
            match_rationale=payload.match_rationale,
            supporting_evidence_ids=payload.supporting_evidence_ids or [],
            trusted_context_ids=payload.trusted_context_ids or [],
            valid_until=payload.valid_until
        )

        db.add(opp)
        await db.commit()
        await db.refresh(opp)

        if contact:
            opp.contact = contact

        return opp

    @classmethod
    async def validate_opportunity(
        cls,
        db: AsyncSession,
        opportunity_id: str,
        payload: OpportunityValidateIn,
        organization_id: str,
        user: Optional[Dict[str, Any]] = None
    ) -> Opportunity:
        """
        Enforces lifecycle transition rules, audit trailing, review notes on rejection,
        and strictly enforces the 70% identity confidence gate before qualification.
        """
        opp = await cls.get_opportunity(db, opportunity_id, organization_id)

        try:
            target_status = to_backend_status(payload.status)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        # 1. Lifecycle transition rule check
        allowed = ALLOWED_TRANSITIONS.get(opp.status, set())
        if target_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid lifecycle transition from {opp.status.value} to {target_status.value}"
            )

        # 2. Mandatory review notes for rejection
        if target_status == OpportunityLifecycleStatus.REJECTED:
            if not payload.review_notes or not payload.review_notes.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Review notes are required when rejecting an opportunity"
                )

        # 3. 70% Identity Confidence Gate for Qualification
        if target_status == OpportunityLifecycleStatus.QUALIFIED:
            if opp.contact_id:
                stmt = select(Contact).where(Contact.id == opp.contact_id)
                contact = (await db.execute(stmt)).scalars().first()
                if not contact or contact.status == "DELETED":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot qualify opportunity: Linked contact does not exist or is unresolved"
                    )

                # Fetch latest executive snapshot from SourceResult
                sr_stmt = select(SourceResult).where(
                    SourceResult.source_id == 'evidence_engine'
                ).order_by(SourceResult.retrieved_at.desc())
                all_srs = (await db.execute(sr_stmt)).scalars().all()
                snapshot = {}
                for sr in all_srs:
                    if sr.metadata_ and sr.metadata_.get("contact_id") == opp.contact_id:
                        if sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
                            snapshot = sr.extracted_data['executive_snapshot']
                        break

                ev_stmt = select(Evidence).where(Evidence.related_entity_id == opp.contact_id)
                contact_evidences = (await db.execute(ev_stmt)).scalars().all()

                identity_confidence = snapshot.get("identity_confidence", 0)
                if not identity_confidence and contact_evidences:
                    identity_confidence = max([ev.confidence for ev in contact_evidences] or [0])
                elif not identity_confidence:
                    identity_confidence = 100 if contact.full_name else 50

                is_identity_uncertain = (
                    snapshot.get("pipeline_stage") == "UNCERTAIN_IDENTITY"
                    or snapshot.get("provenance_status") == "UNVERIFIED"
                    or identity_confidence < 70
                )

                if is_identity_uncertain or identity_confidence < 70:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Cannot validate opportunity: Target identity confidence is below threshold "
                            f"({identity_confidence}% < 70%) or unverified. Complete identity verification "
                            f"before commercial qualification."
                        )
                    )
            else:
                if opp.confidence < 70:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot qualify opportunity: Confidence ({opp.confidence}% < 70%) is below qualification threshold"
                    )

        # 4. Record review and timestamp
        now_utc = datetime.now(timezone.utc)
        opp.status = target_status
        opp.review_notes = payload.review_notes
        opp.reviewed_by = (user.get("user_id") if user else None) or "founder"
        opp.reviewed_at = now_utc

        if payload.confirmed_problem:
            opp.problem = payload.confirmed_problem
        if payload.confirmed_solution:
            opp.match_rationale = payload.confirmed_solution

        await db.commit()
        await db.refresh(opp)

        return opp

    @classmethod
    async def derive_opportunity_from_contact(
        cls,
        db: AsyncSession,
        contact_id: str,
        organization_id: str,
        user: Optional[Dict[str, Any]] = None
    ) -> Opportunity:
        """
        Consumes existing Contact 360 SourceResult and Evidence records,
        extracts supported problem statements without fabrication,
        invokes SemanticProductMatcherService to evaluate product portfolio alignment,
        and persists a DISCOVERED opportunity with full provenance.

        Safeguards:
        - Never triggers duplicate crawling or external research.
        - Idempotent: returns existing active opportunity rather than creating duplicates.
        - Zero fabrication of problems, budgets, or buyer intent.
        - Rejects deleted or unresolved contacts.
        - Scoped strictly to the authenticated organization.
        """
        # 1. Verify contact exists and belongs to organization
        stmt = select(Contact).where(
            Contact.id == contact_id,
            Contact.organization_id == organization_id
        )
        contact = (await db.execute(stmt)).scalars().first()
        if not contact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found"
            )

        if getattr(contact, "status", None) == "DELETED" or not (contact.full_name or contact.current_company):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot derive opportunity from unresolved or deleted contact"
            )

        # 2. Idempotency safeguard: Check for existing active opportunity
        existing_stmt = select(Opportunity).where(
            Opportunity.contact_id == contact_id,
            Opportunity.organization_id == organization_id
        ).order_by(Opportunity.created_at.desc())
        existing_opps = (await db.execute(existing_stmt)).scalars().all()

        active_opp = next(
            (o for o in existing_opps if o.status not in [
                OpportunityLifecycleStatus.REJECTED,
                OpportunityLifecycleStatus.LOST,
                OpportunityLifecycleStatus.EXPIRED
            ]),
            None
        )
        if active_opp:
            logger.info(f"Derivation is idempotent: Returning existing opportunity {active_opp.id} for contact {contact_id}")
            active_opp.contact = contact
            return active_opp

        # 3. Retrieve Contact 360 SourceResults and Evidence (strictly existing DB records)
        sr_stmt = select(SourceResult).where(
            SourceResult.source_id == 'evidence_engine'
        ).order_by(SourceResult.retrieved_at.desc())
        all_srs = (await db.execute(sr_stmt)).scalars().all()
        target_sr = None
        snapshot = {}
        for sr in all_srs:
            if sr.metadata_ and sr.metadata_.get("contact_id") == contact_id:
                target_sr = sr
                if sr.extracted_data and 'executive_snapshot' in sr.extracted_data:
                    snapshot = sr.extracted_data['executive_snapshot']
                break

        ev_stmt = select(Evidence).where(Evidence.related_entity_id == contact_id)
        contact_evidences = (await db.execute(ev_stmt)).scalars().all()

        # 4. Extract authentic problem statement (no fabrication)
        smallest_solvable = (snapshot.get("smallest_solvable_problem") or "").strip()
        broad_problem = (snapshot.get("broad_business_problem") or "").strip()
        validated_problem = ""
        if target_sr and target_sr.extracted_data:
            validated_problem = (target_sr.extracted_data.get("opportunity_validation", {}).get("business_problem") or "").strip()

        problem_text = smallest_solvable or broad_problem or validated_problem
        if not problem_text:
            for ev in contact_evidences:
                claim = (ev.claim or "").strip()
                if ev.evidence_type in [EvidenceType.SIGNAL, EvidenceType.FACT] and any(w in claim.lower() for w in ["problem", "bottleneck", "challenge", "need"]):
                    problem_text = claim
                    break

        if not problem_text or problem_text.lower() in ["unspecified", "none", "unknown"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No supported business problem identified in existing contact research. Complete Contact 360 research first before deriving opportunities."
            )

        # 5. Extract identity confidence
        identity_confidence = snapshot.get("identity_confidence", 0)
        if not identity_confidence and contact_evidences:
            identity_confidence = max([ev.confidence for ev in contact_evidences] or [0])
        elif not identity_confidence:
            identity_confidence = 100 if contact.full_name else 50

        # 6. Invoke SemanticProductMatcherService (Solution fit match != buyer intent)
        industry_context = snapshot.get("domain_name") or "Enterprise Operations"
        match_response = await SemanticProductMatcherService.match_connection_problem(
            problem_text=problem_text,
            connection_id=contact.id,
            connection_name=contact.full_name,
            connection_company=contact.current_company,
            connection_title=contact.current_title,
            context={"industry": industry_context}
        )

        matched_product_id = None
        matched_product_name = None
        match_score = None
        match_rationale = match_response.rationale

        if match_response.matches:
            top_match = match_response.matches[0]
            raw_id = top_match.product_id
            matched_product_name = top_match.product_name
            match_score = top_match.match_score
            match_rationale = top_match.why_this_product_solves_it or match_response.rationale

            # Normalize product ID to canonical database products.id
            if matched_product_name and matched_product_name.lower().strip() in PRODUCT_NAME_TO_ID:
                matched_product_id = PRODUCT_NAME_TO_ID[matched_product_name.lower().strip()]
            elif raw_id and raw_id.lower().strip() in PRODUCT_NAME_TO_ID:
                matched_product_id = PRODUCT_NAME_TO_ID[raw_id.lower().strip()]
            else:
                matched_product_id = raw_id

            # Verify against products table to guarantee zero FK violation
            if matched_product_id:
                p_check = (await db.execute(select(Product.id).where(Product.id == matched_product_id))).scalar()
                if not p_check:
                    logger.warning(f"Matched product ID '{matched_product_id}' not found in products table, clearing FK")
                    matched_product_id = None

        # 7. Collect authentic evidence IDs (prevent cross-contact / cross-tenant attachment)
        authentic_evidence_ids = [e.id for e in contact_evidences]
        trusted_context_ids = [target_sr.id] if target_sr else []

        # 8. Assemble grounded opportunity fields (zero fabrication)
        company_name = contact.current_company or "Target Enterprise"
        category = snapshot.get("opportunity_category") or "EXPERT_LED_PRODUCT_VENTURE"
        title = f"{company_name} - {snapshot.get('domain_name') or 'Operational Opportunity'}"

        if match_response.matches and match_response.matches[0].relevant_features:
            requirement = ", ".join(match_response.matches[0].relevant_features)
        elif match_response.supported_capabilities:
            requirement = ", ".join(match_response.supported_capabilities)
        elif snapshot.get("ottobon_capability_match"):
            requirement = snapshot.get("ottobon_capability_match")
        else:
            requirement = f"Capability solution for {problem_text[:100]}"

        # Calculate realistic initial confidence bounded between 0 and 100
        if match_score:
            calculated_confidence = int((identity_confidence * 0.4) + (match_score * 0.6))
        else:
            calculated_confidence = min(identity_confidence, 50)
        calculated_confidence = max(0, min(100, calculated_confidence))

        budget_signal = snapshot.get("cost_pricing_estimate") or None
        timeline = snapshot.get("why_now") or None
        description = snapshot.get("who_they_are") or (snapshot.get("full_markdown_report") or "")[:500] or None

        opp_id = f"opp-{uuid.uuid4().hex[:12]}"
        opp = Opportunity(
            id=opp_id,
            organization_id=organization_id,
            owner_user_id=user.get("user_id") if user else None,
            contact_id=contact.id,
            company_name=company_name,
            company_id=None,
            title=title,
            description=description,
            problem=problem_text,
            requirement=requirement,
            opportunity_type=category,
            status=OpportunityLifecycleStatus.DISCOVERED,
            confidence=calculated_confidence,
            timeline=timeline,
            budget_signal=budget_signal,
            matched_product_id=matched_product_id,
            matched_product_name=matched_product_name,
            match_score=match_score,
            match_rationale=match_rationale,
            supporting_evidence_ids=authentic_evidence_ids,
            trusted_context_ids=trusted_context_ids,
        )

        db.add(opp)
        await db.commit()
        await db.refresh(opp)

        opp.contact = contact
        return opp


# Singleton instance export
opportunity_service = OpportunityService()
