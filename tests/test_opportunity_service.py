"""
Focused service-level tests for OpportunityService (NetworkOS Module 3, Step 3).

Validates:
1. Multi-tenant organization isolation (listing, getting, creating).
2. Evidence ownership and entity attribution safeguards.
3. Allowed lifecycle status transitions and audit logging.
4. Mandatory review notes on opportunity rejection.
5. Strict 70% identity confidence gate before qualification.
6. Zero duplicate research or crawling during derivation.
7. Idempotent derivation preventing duplicate opportunities.
8. Zero problem or evidence fabrication for empty research dossiers.
"""

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException
from sqlalchemy.future import select
from sqlalchemy import delete

from app.models.opportunity import Opportunity, OpportunityLifecycleStatus
from app.models.identity import Contact, ContactStatus
from app.models.evidence import SourceResult, Evidence, EvidenceType
from app.models.company_knowledge import Product, CompanyProfile
from app.schemas.opportunity import (
    OpportunityCreateIn,
    OpportunityValidateIn,
)
from app.services.opportunity_service import OpportunityService, ALLOWED_TRANSITIONS
from app.schemas.matching import (
    SemanticProductMatchResponse,
    ProductMatchItem,
    MatchingOutcome
)


# ==============================================================================
# Helper fixtures / cleanup
# ==============================================================================

@pytest.fixture
def test_prefix():
    return f"test-{uuid.uuid4().hex[:8]}"


# ==============================================================================
# 1. Organization Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_list_opportunities_organization_isolation(db_session, test_prefix):
    """
    Ensure list_opportunities strictly returns records belonging to the authenticated organization.
    """
    org_a = f"org-a-{test_prefix}"
    org_b = f"org-b-{test_prefix}"

    opp_a = Opportunity(
        id=f"opp-a-{test_prefix}",
        organization_id=org_a,
        company_name="Enterprise A",
        title="Opportunity A",
        problem="Problem A with operational workflow",
        requirement="Requirement A",
        opportunity_type="DIGITAL_TRANSFORMATION",
        status=OpportunityLifecycleStatus.DISCOVERED,
        confidence=60
    )
    opp_b = Opportunity(
        id=f"opp-b-{test_prefix}",
        organization_id=org_b,
        company_name="Enterprise B",
        title="Opportunity B",
        problem="Problem B with operational workflow",
        requirement="Requirement B",
        opportunity_type="DIGITAL_TRANSFORMATION",
        status=OpportunityLifecycleStatus.DISCOVERED,
        confidence=70
    )
    db_session.add_all([opp_a, opp_b])
    await db_session.commit()

    try:
        # Query for Org A
        opps_a, total_a = await OpportunityService.list_opportunities(db_session, organization_id=org_a)
        assert total_a == 1
        assert opps_a[0].id == opp_a.id
        assert opps_a[0].organization_id == org_a

        # Query for Org B
        opps_b, total_b = await OpportunityService.list_opportunities(db_session, organization_id=org_b)
        assert total_b == 1
        assert opps_b[0].id == opp_b.id
        assert opps_b[0].organization_id == org_b

        # Filter by status
        opps_filtered, total_filtered = await OpportunityService.list_opportunities(
            db_session, organization_id=org_a, status="CANDIDATE"
        )
        assert total_filtered == 1
        assert opps_filtered[0].id == opp_a.id

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id.in_([opp_a.id, opp_b.id])))
        await db_session.commit()


@pytest.mark.asyncio
async def test_get_opportunity_organization_isolation(db_session, test_prefix):
    """
    Accessing an opportunity belonging to another organization raises standard HTTP 404.
    """
    org_a = f"org-a-{test_prefix}"
    org_b = f"org-b-{test_prefix}"

    opp = Opportunity(
        id=f"opp-sec-{test_prefix}",
        organization_id=org_a,
        company_name="Secure Org Enterprise",
        title="Restricted Deal",
        problem="Internal operations friction",
        requirement="Process modernization",
        opportunity_type="DIGITAL_TRANSFORMATION",
        status=OpportunityLifecycleStatus.DISCOVERED,
        confidence=65
    )
    db_session.add(opp)
    await db_session.commit()

    try:
        # Access from authorized organization succeeds
        retrieved = await OpportunityService.get_opportunity(db_session, opp.id, organization_id=org_a)
        assert retrieved.id == opp.id

        # Access from cross-tenant organization fails with 404 (prevents entity existence leakage)
        with pytest.raises(HTTPException) as exc_info:
            await OpportunityService.get_opportunity(db_session, opp.id, organization_id=org_b)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Opportunity not found"

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp.id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_create_opportunity_rejects_cross_tenant_contact(db_session, test_prefix):
    """
    Creating an opportunity referencing a contact from another organization raises HTTP 400.
    """
    org_a = f"org-a-{test_prefix}"
    org_b = f"org-b-{test_prefix}"

    contact_b = Contact(
        id=f"contact-b-{test_prefix}",
        organization_id=org_b,
        full_name="Bob Foreign",
        current_company="Foreign Corp",
        status=ContactStatus.READY
    )
    db_session.add(contact_b)
    await db_session.commit()

    try:
        payload = OpportunityCreateIn(
            title="Cross-tenant Attempt",
            company_name="Foreign Corp",
            problem="Cross-tenant workflow problem",
            requirement="Automation capability",
            contact_id=contact_b.id,
            confidence=60
        )
        with pytest.raises(HTTPException) as exc_info:
            await OpportunityService.create_opportunity(db_session, payload, organization_id=org_a)
        assert exc_info.value.status_code == 400
        assert "organization" in exc_info.value.detail.lower()

    finally:
        await db_session.execute(delete(Contact).where(Contact.id == contact_b.id))
        await db_session.commit()


# ==============================================================================
# 2. Evidence Ownership & Attribution Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_create_opportunity_rejects_unowned_evidence(db_session, test_prefix):
    """
    Never attach evidence belonging to another contact or non-existent records.
    """
    org_id = f"org-{test_prefix}"

    contact_1 = Contact(
        id=f"c1-{test_prefix}",
        organization_id=org_id,
        full_name="Alice Owner",
        current_company="Alpha Inc",
        status=ContactStatus.READY
    )
    contact_2 = Contact(
        id=f"c2-{test_prefix}",
        organization_id=org_id,
        full_name="Charlie Other",
        current_company="Beta Inc",
        status=ContactStatus.READY
    )
    db_session.add_all([contact_1, contact_2])
    await db_session.commit()

    ev_2 = Evidence(
        id=f"ev-beta-{test_prefix}",
        evidence_type=EvidenceType.FACT,
        claim="Charlie's Verified Fact",
        confidence=90,
        related_entity_id=contact_2.id
    )
    db_session.add(ev_2)
    await db_session.commit()

    try:
        # Attempt to link Charlie's evidence to Alice's opportunity
        payload = OpportunityCreateIn(
            title="Alice's Deal with Stolen Evidence",
            company_name="Alpha Inc",
            problem="Operational dispatch bottlenecks",
            requirement="Smart dispatch solution",
            contact_id=contact_1.id,
            supporting_evidence_ids=[ev_2.id],
            confidence=70
        )

        with pytest.raises(HTTPException) as exc_info:
            await OpportunityService.create_opportunity(db_session, payload, organization_id=org_id)
        assert exc_info.value.status_code == 400
        assert "belongs to a different entity" in exc_info.value.detail

        # Attempt to link non-existent evidence
        payload_missing = OpportunityCreateIn(
            title="Alice's Deal with Ghost Evidence",
            company_name="Alpha Inc",
            problem="Operational dispatch bottlenecks",
            requirement="Smart dispatch solution",
            contact_id=contact_1.id,
            supporting_evidence_ids=["ev-non-existent-1234"],
            confidence=70
        )
        with pytest.raises(HTTPException) as exc_missing:
            await OpportunityService.create_opportunity(db_session, payload_missing, organization_id=org_id)
        assert exc_missing.value.status_code == 400
        assert "not found" in exc_missing.value.detail

    finally:
        await db_session.execute(delete(Evidence).where(Evidence.id == ev_2.id))
        await db_session.execute(delete(Contact).where(Contact.id.in_([contact_1.id, contact_2.id])))
        await db_session.commit()


# ==============================================================================
# 3. Lifecycle Status Transition & Rejection Rules Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_opportunity_lifecycle_transitions_and_review_notes(db_session, test_prefix):
    """
    Test valid and invalid state transitions, reviewer attribution, and rejection notes requirement.
    """
    org_id = f"org-{test_prefix}"
    user = {"user_id": "reviewer-user-99", "role": "MEMBER"}

    opp = Opportunity(
        id=f"opp-trans-{test_prefix}",
        organization_id=org_id,
        company_name="State Transition Tech",
        title="Workflow Pipeline Opp",
        problem="Manual timesheet approvals slowing billing cycle",
        requirement="Automated approval workflows",
        opportunity_type="DIGITAL_TRANSFORMATION",
        status=OpportunityLifecycleStatus.DISCOVERED,
        confidence=75
    )
    db_session.add(opp)
    await db_session.commit()

    try:
        # 1. DISCOVERED -> SOURCE_VERIFIED (Valid)
        val_payload = OpportunityValidateIn(status="SOURCE_VERIFIED", review_notes="Evidence checked")
        updated = await OpportunityService.validate_opportunity(db_session, opp.id, val_payload, org_id, user)
        assert updated.status == OpportunityLifecycleStatus.SOURCE_VERIFIED
        assert updated.reviewed_by == "reviewer-user-99"
        assert updated.reviewed_at is not None

        # 2. SOURCE_VERIFIED -> MATCH_REVIEW (Valid)
        val_payload2 = OpportunityValidateIn(status="MATCH_REVIEW")
        updated2 = await OpportunityService.validate_opportunity(db_session, opp.id, val_payload2, org_id, user)
        assert updated2.status == OpportunityLifecycleStatus.MATCH_REVIEW

        # 3. REJECTED requires review notes
        val_reject_empty = OpportunityValidateIn(status="REJECTED", review_notes="")
        with pytest.raises(HTTPException) as exc_reject:
            await OpportunityService.validate_opportunity(db_session, opp.id, val_reject_empty, org_id, user)
        assert exc_reject.value.status_code == 400
        assert "review notes are required" in exc_reject.value.detail.lower()

        # 4. Rejecting with proper notes succeeds
        val_reject = OpportunityValidateIn(
            status="REJECTED",
            review_notes="Client confirmed they just purchased Workday; opportunity closed."
        )
        updated_rejected = await OpportunityService.validate_opportunity(db_session, opp.id, val_reject, org_id, user)
        assert updated_rejected.status == OpportunityLifecycleStatus.REJECTED
        assert "purchased Workday" in updated_rejected.review_notes

        # 5. Invalid transition: REJECTED directly to QUALIFIED is blocked
        val_invalid = OpportunityValidateIn(status="QUALIFIED", review_notes="Try direct skip")
        with pytest.raises(HTTPException) as exc_invalid:
            await OpportunityService.validate_opportunity(db_session, opp.id, val_invalid, org_id, user)
        assert exc_invalid.value.status_code == 400
        assert "invalid lifecycle transition" in exc_invalid.value.detail.lower()

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp.id))
        await db_session.commit()


# ==============================================================================
# 4. The 70% Identity Gate Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_70_percent_identity_gate_strictly_blocks_qualification(db_session, test_prefix):
    """
    Qualification to QUALIFIED (or frontend VALIDATED) is strictly blocked
    when linked contact identity confidence is < 70% or unverified.
    """
    org_id = f"org-{test_prefix}"
    user = {"user_id": "founder-1", "role": "ADMIN"}

    # Contact with low identity confidence (55% < 70%)
    cid = f"c-gate-{test_prefix}"
    contact = Contact(
        id=cid,
        organization_id=org_id,
        full_name="Uncertain Executive",
        current_company="Shadowy Corp",
        status=ContactStatus.RESEARCHING
    )
    db_session.add(contact)

    sr = SourceResult(
        id=f"sr-low-{test_prefix}",
        source_id="evidence_engine",
        query=cid,
        status="SUCCESS",
        extracted_data={
            "executive_snapshot": {
                "name": "Uncertain Executive",
                "identity_confidence": 55,
                "provenance_status": "UNVERIFIED",
                "pipeline_stage": "UNCERTAIN_IDENTITY",
                "smallest_solvable_problem": "Fragmented data silos"
            }
        },
        metadata_={"contact_id": cid}
    )
    db_session.add(sr)

    opp = Opportunity(
        id=f"opp-gate-{test_prefix}",
        organization_id=org_id,
        contact_id=cid,
        company_name="Shadowy Corp",
        title="Shadowy Deal",
        problem="Fragmented data silos",
        requirement="Data integration",
        opportunity_type="DIGITAL_TRANSFORMATION",
        status=OpportunityLifecycleStatus.MATCH_REVIEW,
        confidence=55
    )
    db_session.add(opp)
    await db_session.commit()

    try:
        # Attempt to qualify using frontend status alias "VALIDATED"
        payload_val = OpportunityValidateIn(
            status="VALIDATED",
            review_notes="Trying to qualify despite 55% identity confidence"
        )

        with pytest.raises(HTTPException) as exc_info:
            await OpportunityService.validate_opportunity(db_session, opp.id, payload_val, org_id, user)

        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail.lower()
        assert "below threshold" in detail or "unverified" in detail
        assert "70%" in detail

        # Attempt to qualify using canonical backend status "QUALIFIED"
        payload_qual = OpportunityValidateIn(
            status="QUALIFIED",
            review_notes="Direct backend qualification attempt"
        )
        with pytest.raises(HTTPException) as exc_info2:
            await OpportunityService.validate_opportunity(db_session, opp.id, payload_qual, org_id, user)
        assert exc_info2.value.status_code == 400

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp.id))
        await db_session.execute(delete(SourceResult).where(SourceResult.id == sr.id))
        await db_session.execute(delete(Contact).where(Contact.id == contact.id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_70_percent_identity_gate_permits_qualification_when_verified(db_session, test_prefix):
    """
    When contact identity confidence is >= 70% and verified, qualification succeeds.
    """
    org_id = f"org-{test_prefix}"
    user = {"user_id": "founder-1", "role": "ADMIN"}

    cid = f"c-high-{test_prefix}"
    contact = Contact(
        id=cid,
        organization_id=org_id,
        full_name="Verified Dr. Sarah Lin",
        current_company="Clinica Health",
        status=ContactStatus.READY
    )
    db_session.add(contact)

    sr = SourceResult(
        id=f"sr-high-{test_prefix}",
        source_id="evidence_engine",
        query=cid,
        status="SUCCESS",
        extracted_data={
            "executive_snapshot": {
                "name": "Dr. Sarah Lin",
                "identity_confidence": 92,
                "provenance_status": "VERIFIED CURRENT",
                "pipeline_stage": "PROPOSED",
                "smallest_solvable_problem": "Doctor-patient communication gaps and specialty intake delays"
            }
        },
        metadata_={"contact_id": cid}
    )
    db_session.add(sr)

    opp = Opportunity(
        id=f"opp-high-{test_prefix}",
        organization_id=org_id,
        contact_id=cid,
        company_name="Clinica Health",
        title="Clinica Intake Modernization",
        problem="Doctor-patient communication gaps and specialty intake delays",
        requirement="Specialty clinical intake pipeline",
        opportunity_type="DIGITAL_TRANSFORMATION",
        status=OpportunityLifecycleStatus.MATCH_REVIEW,
        confidence=85
    )
    db_session.add(opp)
    await db_session.commit()

    try:
        payload = OpportunityValidateIn(
            status="VALIDATED",
            review_notes="Identity confirmed via corporate publications; clinical friction validated."
        )

        updated = await OpportunityService.validate_opportunity(db_session, opp.id, payload, org_id, user)
        assert updated.status == OpportunityLifecycleStatus.QUALIFIED
        assert updated.reviewed_by == "founder-1"
        assert updated.reviewed_at is not None

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp.id))
        await db_session.execute(delete(SourceResult).where(SourceResult.id == sr.id))
        await db_session.execute(delete(Contact).where(Contact.id == contact.id))
        await db_session.commit()


# ==============================================================================
# 5. Derivation Safeguards, No Duplicate Research & Idempotency Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_derive_opportunity_no_duplicate_research_and_provenance(db_session, test_prefix):
    """
    derive_opportunity_from_contact:
    - Consumes existing Contact 360 SourceResult and Evidence records only.
    - NEVER triggers duplicate crawling, scraping, or web research.
    - Connects to SemanticProductMatcherService interface.
    - Persists in canonical DISCOVERED lifecycle status with authentic evidence IDs.
    """
    org_id = f"org-{test_prefix}"
    user = {"user_id": "analyst-1", "role": "MEMBER"}

    cid = f"c-derive-{test_prefix}"
    contact = Contact(
        id=cid,
        organization_id=org_id,
        full_name="Vikram Mehta",
        current_title="VP Clinical Operations",
        current_company="Apollo Gastro Clinics",
        status=ContactStatus.READY
    )
    db_session.add(contact)

    ev1 = Evidence(
        id=f"ev1-{test_prefix}",
        evidence_type=EvidenceType.FACT,
        claim="Practicing gastroenterologist and clinic director at Apollo Gastro",
        source_id="company_web",
        confidence=95,
        related_entity_id=cid
    )
    ev2 = Evidence(
        id=f"ev2-{test_prefix}",
        evidence_type=EvidenceType.SIGNAL,
        claim="Clinic consultation hours wasted dealing with unqualified or unprepared patient inquiries",
        source_id="news_public",
        confidence=85,
        related_entity_id=cid
    )
    db_session.add_all([ev1, ev2])

    sr = SourceResult(
        id=f"sr-derive-{test_prefix}",
        source_id="evidence_engine",
        query=cid,
        status="SUCCESS",
        extracted_data={
            "executive_snapshot": {
                "name": "Vikram Mehta",
                "identity_confidence": 90,
                "provenance_status": "VERIFIED CURRENT",
                "domain_name": "Healthtech & Digital Health Solutions",
                "opportunity_category": "EXPERT_LED_PRODUCT_VENTURE",
                "smallest_solvable_problem": "Specialty clinics and doctors wasting clinical consultation hours dealing with unqualified or unprepared patient inquiries.",
                "ottobon_capability_match": "JanmaSethu clinic portal with patient preparedness scoring",
                "cost_pricing_estimate": "$15,000 clinic deployment sprint",
                "why_now": "Clinic expansion across 3 metro centers"
            }
        },
        metadata_={"contact_id": cid}
    )
    db_session.add(sr)
    await db_session.commit()

    try:
        # Patch web crawler and external search providers to guarantee ZERO calls are made
        with patch("app.services.web.crawler.CrawlerService.scrape_page", new_callable=AsyncMock) as mock_crawl, \
             patch("app.services.providers.search.DuckDuckGoProvider.search_person", new_callable=AsyncMock) as mock_search:

            derived = await OpportunityService.derive_opportunity_from_contact(
                db=db_session,
                contact_id=cid,
                organization_id=org_id,
                user=user
            )

            # Safeguard Check 1: Zero duplicate research calls
            assert mock_crawl.call_count == 0
            assert mock_search.call_count == 0

            # Safeguard Check 2: Canonical initial status is DISCOVERED
            assert derived.status == OpportunityLifecycleStatus.DISCOVERED

            # Safeguard Check 3: Grounded in genuine evidence & contact info
            assert derived.contact_id == cid
            assert derived.company_name == "Apollo Gastro Clinics"
            assert "Specialty clinics" in derived.problem
            assert ev1.id in derived.supporting_evidence_ids
            assert ev2.id in derived.supporting_evidence_ids

            # Safeguard Check 4: Solution match from SemanticProductMatcher (JanmaSethu)
            assert derived.matched_product_name == "JanmaSethu"
            assert derived.matched_product_id == "prod-janmasethu"
            assert derived.match_score is not None and derived.match_score >= 50
            assert derived.budget_signal == "$15,000 clinic deployment sprint"
            assert derived.timeline == "Clinic expansion across 3 metro centers"

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.contact_id == cid))
        await db_session.execute(delete(Evidence).where(Evidence.related_entity_id == cid))
        await db_session.execute(delete(SourceResult).where(SourceResult.id == sr.id))
        await db_session.execute(delete(Contact).where(Contact.id == cid))
        await db_session.commit()


@pytest.mark.asyncio
async def test_derive_opportunity_idempotence(db_session, test_prefix):
    """
    Calling derive_opportunity_from_contact repeatedly for the same contact
    returns the existing active opportunity without creating duplicate records.
    """
    org_id = f"org-{test_prefix}"

    cid = f"c-idem-{test_prefix}"
    contact = Contact(
        id=cid,
        organization_id=org_id,
        full_name="Idempotent Contact",
        current_company="Idem Corp",
        status=ContactStatus.READY
    )
    db_session.add(contact)

    sr = SourceResult(
        id=f"sr-idem-{test_prefix}",
        source_id="evidence_engine",
        query=cid,
        status="SUCCESS",
        extracted_data={
            "executive_snapshot": {
                "name": "Idempotent Contact",
                "identity_confidence": 85,
                "smallest_solvable_problem": "Talent acquisition screening and candidate skill validation bottleneck"
            }
        },
        metadata_={"contact_id": cid}
    )
    db_session.add(sr)
    await db_session.commit()

    try:
        # First derivation
        opp1 = await OpportunityService.derive_opportunity_from_contact(db_session, cid, org_id)
        assert opp1.id is not None

        # Second derivation (Repeated request)
        opp2 = await OpportunityService.derive_opportunity_from_contact(db_session, cid, org_id)

        # Must return the identical opportunity instance / ID
        assert opp1.id == opp2.id

        # Verify database has exactly 1 opportunity row for this contact
        count_stmt = select(Opportunity).where(Opportunity.contact_id == cid)
        db_opps = (await db_session.execute(count_stmt)).scalars().all()
        assert len(db_opps) == 1

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.contact_id == cid))
        await db_session.execute(delete(SourceResult).where(SourceResult.id == sr.id))
        await db_session.execute(delete(Contact).where(Contact.id == cid))
        await db_session.commit()


@pytest.mark.asyncio
async def test_derive_opportunity_rejects_empty_problem_dossier(db_session, test_prefix):
    """
    Zero fabrication safeguard: If contact research results do not identify
    a business problem, derivation raises HTTP 400 rather than hallucinating one.
    """
    org_id = f"org-{test_prefix}"

    cid = f"c-empty-{test_prefix}"
    contact = Contact(
        id=cid,
        organization_id=org_id,
        full_name="Vacuous Executive",
        current_company="Empty Corp",
        status=ContactStatus.READY
    )
    db_session.add(contact)

    sr = SourceResult(
        id=f"sr-empty-{test_prefix}",
        source_id="evidence_engine",
        query=cid,
        status="SUCCESS",
        extracted_data={
            "executive_snapshot": {
                "name": "Vacuous Executive",
                "identity_confidence": 70,
                "smallest_solvable_problem": "",
                "broad_business_problem": "Unknown"
            }
        },
        metadata_={"contact_id": cid}
    )
    db_session.add(sr)
    await db_session.commit()

    try:
        with pytest.raises(HTTPException) as exc_info:
            await OpportunityService.derive_opportunity_from_contact(db_session, cid, org_id)

        assert exc_info.value.status_code == 400
        assert "no supported business problem" in exc_info.value.detail.lower()

    finally:
        await db_session.execute(delete(SourceResult).where(SourceResult.id == sr.id))
        await db_session.execute(delete(Contact).where(Contact.id == cid))
        await db_session.commit()


# ==============================================================================
# 9. Capability Matching & Delivery Path Service Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_set_delivery_path_service(db_session, test_prefix):
    """
    Validates set_delivery_path enforces supported values (INTERNAL, NETWORK, HYBRID)
    and rejects invalid delivery path values with 400.
    """
    org_id = f"org-path-{test_prefix}"
    opp = Opportunity(
        id=f"opp-path-{test_prefix}",
        organization_id=org_id,
        company_name="Path Enterprises",
        title="Infrastructure Modernization",
        problem="High latency monolithic microservices bottlenecks",
        requirement="Cloud native refactoring",
        status=OpportunityLifecycleStatus.DISCOVERED,
        confidence=75
    )
    db_session.add(opp)
    await db_session.commit()

    try:
        # Valid paths
        for p in ["INTERNAL", "NETWORK", "HYBRID"]:
            updated = await OpportunityService.set_delivery_path(
                db=db_session,
                opportunity_id=opp.id,
                path=p,
                organization_id=org_id
            )
            assert updated.delivery_path == p
            assert updated.selected_path == p

        # Invalid path rejected with 400
        with pytest.raises(HTTPException) as exc_info:
            await OpportunityService.set_delivery_path(
                db=db_session,
                opportunity_id=opp.id,
                path="OFFSHORE_OUTSOURCE",
                organization_id=org_id
            )
        assert exc_info.value.status_code == 400
        assert "Supported values" in exc_info.value.detail

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp.id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_capability_matching_and_update_service(db_session, test_prefix):
    """
    Validates get_capability_matches evaluates database offerings and
    update_capability_match persists selection and defaults delivery_path to INTERNAL.
    """
    org_id = f"org-cap-srv-{test_prefix}"
    opp = Opportunity(
        id=f"opp-cap-srv-{test_prefix}",
        organization_id=org_id,
        company_name="Pipeline Scale Corp",
        title="Reporting Pipeline Modernization",
        problem="Automated reporting data pipeline latency and manual CSV export delays",
        requirement="Scheduled ETL aggregation with automated validation",
        status=OpportunityLifecycleStatus.DISCOVERED,
        confidence=80,
        supporting_evidence_ids=["ev-srv-1"]
    )
    db_session.add(opp)
    await db_session.commit()

    try:
        # 1. Evaluate matches
        matches = await OpportunityService.get_capability_matches(
            db=db_session,
            opportunity_id=opp.id,
            organization_id=org_id
        )
        assert len(matches) > 0
        first_match = matches[0]
        assert first_match.capability.name
        assert first_match.reasoning.overallExplanation

        # 2. Select match
        ok = await OpportunityService.update_capability_match(
            db=db_session,
            opportunity_id=opp.id,
            match_id=first_match.id,
            status_val="SELECTED",
            organization_id=org_id
        )
        assert ok is True

        # Refresh opportunity and verify DB persistence
        await db_session.refresh(opp)
        assert opp.selected_solution_id == first_match.capabilityId
        assert opp.delivery_path == "INTERNAL"

        # 3. Reject match
        ok_rej = await OpportunityService.update_capability_match(
            db=db_session,
            opportunity_id=opp.id,
            match_id=first_match.id,
            status_val="REJECTED",
            organization_id=org_id
        )
        assert ok_rej is True
        await db_session.refresh(opp)
        assert opp.selected_solution_id is None

        # 4. Invalid match status rejected
        with pytest.raises(HTTPException) as exc_info:
            await OpportunityService.update_capability_match(
                db=db_session,
                opportunity_id=opp.id,
                match_id=first_match.id,
                status_val="INVALID_STATUS",
                organization_id=org_id
            )
        assert exc_info.value.status_code == 400

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp.id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_solution_candidates_service(db_session, test_prefix):
    """
    Validates get_solution_candidates returns INTERNAL, NETWORK, and HYBRID paths.
    """
    org_id = f"org-sol-{test_prefix}"
    opp = Opportunity(
        id=f"opp-sol-{test_prefix}",
        organization_id=org_id,
        company_name="Solutions Corp",
        title="Enterprise AI Deployment",
        problem="AI governance and regulatory compliance automation",
        requirement="Real-time compliance monitoring",
        status=OpportunityLifecycleStatus.QUALIFIED,
        confidence=90
    )
    db_session.add(opp)
    await db_session.commit()

    try:
        solutions = await OpportunityService.get_solution_candidates(
            db=db_session,
            opportunity_id=opp.id,
            organization_id=org_id
        )
        assert len(solutions) == 3
        types = {s.type for s in solutions}
        assert types == {"INTERNAL", "NETWORK", "HYBRID"}

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp.id))
        await db_session.commit()

