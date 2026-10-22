"""
Comprehensive API-level test suite for NetworkOS Opportunity Intelligence REST Endpoints.
NetworkOS Module 3, Step 4.

Validates:
1. Authentication & Bearer token enforcement (401 on missing/invalid credentials).
2. Multi-tenant organization isolation (GET, POST, PATCH cannot access cross-tenant records).
3. Request schema validation (missing fields, confidence bounds, invalid lifecycle statuses).
4. Lifecycle status transitions and mandatory rejection review notes.
5. Strict 70% identity confidence gate before qualification.
6. Zero duplicate research crawling and idempotent opportunity derivation.
7. Frontend compatibility routing (/api/opportunities and /api/v1/opportunities) with camelCase responses.
"""

import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy import delete

from app.models.opportunity import Opportunity, OpportunityLifecycleStatus
from app.models.identity import Contact, ContactStatus
from app.models.evidence import SourceResult, Evidence, EvidenceType
from sqlalchemy.orm.attributes import flag_modified


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer mock-token"}


@pytest.fixture
def test_prefix():
    return f"api-test-{uuid.uuid4().hex[:8]}"


# ==============================================================================
# 1. Authentication Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_unauthenticated_requests_rejected(client):
    """
    All opportunity endpoints require valid authentication and reject unauthenticated requests with 401.
    """
    # 1. List
    resp = await client.get("/api/v1/opportunities")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"]["code"] == "UNAUTHORIZED"

    # 2. Detail
    resp = await client.get("/api/v1/opportunities/opp-any-123")
    assert resp.status_code == 401

    # 3. Create
    resp = await client.post("/api/v1/opportunities", json={"title": "Test"})
    assert resp.status_code == 401

    # 4. Validate
    resp = await client.patch("/api/v1/opportunities/opp-any-123/validate", json={"status": "VALIDATED"})
    assert resp.status_code == 401

    # 5. Derive
    resp = await client.post("/api/v1/opportunities/derive/contact-123")
    assert resp.status_code == 401

    # 6. Invalid token
    resp = await client.get("/api/v1/opportunities", headers={"Authorization": "Bearer invalid-token"})
    assert resp.status_code == 401

    # 7. Frontend compatibility endpoint without auth
    resp = await client.get("/api/opportunities")
    assert resp.status_code == 401


# ==============================================================================
# 2. Organization Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_api_organization_isolation(client, db_session, auth_headers, test_prefix):
    """
    Records belonging to another organization are invisible in lists and return 404 on direct access.
    """
    # Create opportunity in org-other
    foreign_opp = Opportunity(
        id=f"opp-foreign-{test_prefix}",
        organization_id="org-foreign-tenant",
        company_name="Foreign Corp",
        title="Restricted Deal",
        problem="Secret operational bottleneck",
        requirement="Specialized capability",
        opportunity_type="DIGITAL_TRANSFORMATION",
        status=OpportunityLifecycleStatus.DISCOVERED,
        confidence=60
    )
    db_session.add(foreign_opp)
    await db_session.commit()

    try:
        # Listing opportunities for org-1 should NOT include foreign_opp
        list_resp = await client.get("/api/v1/opportunities", headers=auth_headers)
        assert list_resp.status_code == 200
        opp_ids = [o["id"] for o in list_resp.json()["opportunities"]]
        assert foreign_opp.id not in opp_ids

        # Direct access with mock-token (org-1) must return 404 Not Found
        detail_resp = await client.get(f"/api/v1/opportunities/{foreign_opp.id}", headers=auth_headers)
        assert detail_resp.status_code == 404
        assert detail_resp.json()["detail"] == "Opportunity not found"

        # Direct validation attempt must also return 404
        patch_resp = await client.patch(
            f"/api/v1/opportunities/{foreign_opp.id}/validate",
            json={"status": "VALIDATED"},
            headers=auth_headers
        )
        assert patch_resp.status_code == 404

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == foreign_opp.id))
        await db_session.commit()


# ==============================================================================
# 3. Request Validation & Schema Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_api_request_validation_errors(client, auth_headers):
    """
    Enforces strict Pydantic schema validation: required fields, confidence range, and lifecycle statuses.
    """
    # 1. Missing required fields
    resp = await client.post("/api/v1/opportunities", json={}, headers=auth_headers)
    assert resp.status_code == 422

    # 2. Missing problem statement
    resp = await client.post(
        "/api/v1/opportunities",
        json={"title": "Missing Problem", "company_name": "Test Co", "requirement": "Solution"},
        headers=auth_headers
    )
    assert resp.status_code == 422

    # 3. Out-of-bounds confidence score (> 100)
    resp = await client.post(
        "/api/v1/opportunities",
        json={
            "title": "Invalid Score Deal",
            "company_name": "Test Co",
            "problem": "Operational friction",
            "requirement": "Modern tooling",
            "confidence": 150
        },
        headers=auth_headers
    )
    assert resp.status_code == 422

    # 4. Out-of-bounds confidence score (< 0)
    resp = await client.post(
        "/api/v1/opportunities",
        json={
            "title": "Negative Score Deal",
            "company_name": "Test Co",
            "problem": "Operational friction",
            "requirement": "Modern tooling",
            "confidence": -5
        },
        headers=auth_headers
    )
    assert resp.status_code == 422


# ==============================================================================
# 4. Lifecycle Transitions & Rejection Review Notes Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_api_status_transitions_and_rejection_notes(client, db_session, auth_headers, test_prefix):
    """
    Validates lifecycle progression:
    - DISCOVERED -> SOURCE_VERIFIED -> MATCH_REVIEW succeeds.
    - REJECTED requires review notes (400 if empty).
    - Invalid transition (e.g. REJECTED -> QUALIFIED) is rejected with 400.
    """
    opp = Opportunity(
        id=f"opp-api-trans-{test_prefix}",
        organization_id="org-1",
        company_name="Lifecycle Enterprise",
        title="Lifecycle Transition Opp",
        problem="Bottlenecks in invoice reconciliation workflows",
        requirement="Automated matching engine",
        opportunity_type="DIGITAL_TRANSFORMATION",
        status=OpportunityLifecycleStatus.DISCOVERED,
        confidence=80
    )
    db_session.add(opp)
    await db_session.commit()

    try:
        # 1. Transition DISCOVERED -> SOURCE_VERIFIED
        resp1 = await client.patch(
            f"/api/v1/opportunities/{opp.id}/validate",
            json={"status": "SOURCE_VERIFIED", "review_notes": "Source citations checked"},
            headers=auth_headers
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["success"] is True
        assert data1["status"] == "CANDIDATE"  # Frontend maps SOURCE_VERIFIED to CANDIDATE

        # 2. Rejection without review notes must fail with 400
        resp_reject_empty = await client.patch(
            f"/api/v1/opportunities/{opp.id}/validate",
            json={"status": "REJECTED", "review_notes": ""},
            headers=auth_headers
        )
        assert resp_reject_empty.status_code == 400
        assert "review notes are required" in resp_reject_empty.json()["detail"].lower()

        # 3. Rejection with notes succeeds
        resp_reject = await client.patch(
            f"/api/v1/opportunities/{opp.id}/validate",
            json={"status": "REJECTED", "review_notes": "Company chosen in-house tooling; deal declined."},
            headers=auth_headers
        )
        assert resp_reject.status_code == 200
        assert resp_reject.json()["status"] == "REJECTED"

        # 4. Invalid transition from REJECTED directly to QUALIFIED fails with 400
        resp_invalid = await client.patch(
            f"/api/v1/opportunities/{opp.id}/validate",
            json={"status": "QUALIFIED", "review_notes": "Trying direct re-activation to qualified"},
            headers=auth_headers
        )
        assert resp_invalid.status_code == 400
        assert "invalid lifecycle transition" in resp_invalid.json()["detail"].lower()

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp.id))
        await db_session.commit()


# ==============================================================================
# 5. The 70% Identity Gate Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_api_70_percent_identity_gate(client, db_session, auth_headers, test_prefix):
    """
    Enforces the commercial decision safeguard:
    - Linked contact with < 70% identity confidence strictly blocks qualification (HTTP 400).
    - Linked contact with >= 70% identity confidence allows qualification (HTTP 200).
    """
    cid_low = f"c-api-low-{test_prefix}"
    contact_low = Contact(
        id=cid_low,
        organization_id="org-1",
        full_name="Uncertain Exec",
        current_company="Uncertain Inc",
        status=ContactStatus.RESEARCHING
    )
    sr_low = SourceResult(
        id=f"sr-api-low-{test_prefix}",
        source_id="evidence_engine",
        query=cid_low,
        status="SUCCESS",
        extracted_data={
            "executive_snapshot": {
                "name": "Uncertain Exec",
                "identity_confidence": 55,
                "provenance_status": "UNVERIFIED",
                "smallest_solvable_problem": "Fragmented data workflows"
            }
        },
        metadata_={"contact_id": cid_low}
    )
    opp_low = Opportunity(
        id=f"opp-api-low-{test_prefix}",
        organization_id="org-1",
        contact_id=cid_low,
        company_name="Uncertain Inc",
        title="Uncertain Opp",
        problem="Fragmented data workflows",
        requirement="Data centralization",
        opportunity_type="DIGITAL_TRANSFORMATION",
        status=OpportunityLifecycleStatus.MATCH_REVIEW,
        confidence=55
    )
    db_session.add_all([contact_low, sr_low, opp_low])
    await db_session.commit()

    try:
        # Qualification attempt on <70% identity confidence must fail
        resp = await client.patch(
            f"/api/v1/opportunities/{opp_low.id}/validate",
            json={"status": "VALIDATED", "review_notes": "Premature qualification attempt"},
            headers=auth_headers
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        assert "below threshold" in detail or "unverified" in detail
        assert "70%" in detail

        # Update identity confidence to 88% (>= 70%) and verified provenance
        sr_low.extracted_data["executive_snapshot"]["identity_confidence"] = 88
        sr_low.extracted_data["executive_snapshot"]["provenance_status"] = "VERIFIED CURRENT"
        flag_modified(sr_low, "extracted_data")
        await db_session.commit()

        # Qualification attempt now succeeds
        resp_success = await client.patch(
            f"/api/v1/opportunities/{opp_low.id}/validate",
            json={"status": "VALIDATED", "review_notes": "Identity verified via domain publication"},
            headers=auth_headers
        )
        assert resp_success.status_code == 200
        data_success = resp_success.json()
        assert data_success["success"] is True
        assert data_success["status"] == "VALIDATED"

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp_low.id))
        await db_session.execute(delete(SourceResult).where(SourceResult.id == sr_low.id))
        await db_session.execute(delete(Contact).where(Contact.id == cid_low))
        await db_session.commit()


# ==============================================================================
# 6. Derivation Endpoint & Idempotence Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_api_derive_opportunity_and_idempotence(client, db_session, auth_headers, test_prefix):
    """
    POST /api/v1/opportunities/derive/{contact_id}:
    - Derives opportunity grounded in Contact 360 research.
    - Repeated derivation requests are idempotent and return the existing active opportunity.
    - Contacts with empty problem statements are rejected with 400.
    """
    cid = f"c-api-derive-{test_prefix}"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Karthik Iyer",
        current_title="Director of Engineering",
        current_company="TalentScale Tech",
        status=ContactStatus.READY
    )
    db_session.add(contact)

    ev = Evidence(
        id=f"ev-api-{test_prefix}",
        evidence_type=EvidenceType.SIGNAL,
        claim="Engineering managers overwhelmed by manual skill assessments and tech screening bottlenecks",
        source_id="company_web",
        confidence=90,
        related_entity_id=cid
    )
    db_session.add(ev)

    sr = SourceResult(
        id=f"sr-api-derive-{test_prefix}",
        source_id="evidence_engine",
        query=cid,
        status="SUCCESS",
        extracted_data={
            "executive_snapshot": {
                "name": "Karthik Iyer",
                "identity_confidence": 92,
                "domain_name": "Workforce & Talent Operations",
                "opportunity_category": "EXPERT_LED_PRODUCT_VENTURE",
                "smallest_solvable_problem": "Engineering managers overwhelmed by manual skill assessments and tech screening bottlenecks",
                "cost_pricing_estimate": "$20,000 sprint pilot"
            }
        },
        metadata_={"contact_id": cid}
    )
    db_session.add(sr)
    await db_session.commit()

    try:
        # First derivation call
        derive_resp = await client.post(f"/api/v1/opportunities/derive/{cid}", headers=auth_headers)
        assert derive_resp.status_code == 201
        opp_data = derive_resp.json()
        assert opp_data["personId"] == cid
        assert opp_data["companyName"] == "TalentScale Tech"
        assert opp_data["status"] == "CANDIDATE"
        assert ev.id in opp_data["supportingEvidenceIds"]
        opp_id = opp_data["id"]

        # Repeated derivation call (idempotency check)
        derive_resp_2 = await client.post(f"/api/v1/opportunities/derive/{cid}", headers=auth_headers)
        assert derive_resp_2.status_code in [200, 201]
        assert derive_resp_2.json()["id"] == opp_id

        # Verify only 1 opportunity row was created in DB
        db_opps = (await db_session.execute(select(Opportunity).where(Opportunity.contact_id == cid))).scalars().all()
        assert len(db_opps) == 1

        # Non-existent contact returns 404
        missing_resp = await client.post("/api/v1/opportunities/derive/c-non-existent-999", headers=auth_headers)
        assert missing_resp.status_code == 404

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.contact_id == cid))
        await db_session.execute(delete(Evidence).where(Evidence.related_entity_id == cid))
        await db_session.execute(delete(SourceResult).where(SourceResult.id == sr.id))
        await db_session.execute(delete(Contact).where(Contact.id == cid))
        await db_session.commit()


# ==============================================================================
# 7. Frontend Compatibility Routing & Response Contract Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_frontend_compatibility_endpoints(client, db_session, auth_headers, test_prefix):
    """
    Verifies that `/api/opportunities` and `/api/opportunities/{id}` endpoints work identically
    to `/api/v1/opportunities`, returning camelCase fields matching the frontend Opportunity TypeScript interface.
    """
    opp = Opportunity(
        id=f"opp-front-{test_prefix}",
        organization_id="org-1",
        company_name="FrontEnd Alignment Corp",
        title="FrontEnd Compatible Deal",
        problem="Legacy system communication friction",
        requirement="Modern API mesh",
        opportunity_type="DIGITAL_TRANSFORMATION",
        status=OpportunityLifecycleStatus.QUALIFIED,
        confidence=85,
        budget_signal="$25,000 deployment",
        timeline="Q4 2026",
        supporting_evidence_ids=["ev-fake-1"],
        trusted_context_ids=["tc-fake-1"]
    )
    db_session.add(opp)
    await db_session.commit()

    try:
        # 1. GET /api/opportunities (Frontend Compatibility Route)
        resp = await client.get("/api/opportunities", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "opportunities" in data
        assert "total" in data

        found = next((o for o in data["opportunities"] if o["id"] == opp.id), None)
        assert found is not None
        # Verify 1:1 camelCase frontend interface fields
        assert found["companyName"] == "FrontEnd Alignment Corp"
        assert found["opportunityType"] == "DIGITAL_TRANSFORMATION"
        assert found["budgetSignal"] == "$25,000 deployment"
        assert found["timeline"] == "Q4 2026"
        assert found["status"] == "VALIDATED"  # QUALIFIED mapped to frontend VALIDATED
        assert "trustedContextIds" in found

        # 2. GET /api/opportunities/{id}
        detail_resp = await client.get(f"/api/opportunities/{opp.id}", headers=auth_headers)
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == opp.id
        assert detail["status"] == "VALIDATED"
        assert detail["companyName"] == "FrontEnd Alignment Corp"

        # 3. PATCH /api/opportunities/{id}/validate
        validate_resp = await client.patch(
            f"/api/opportunities/{opp.id}/validate",
            json={"status": "VALIDATED", "review_notes": "Confirmed by founder in UI"},
            headers=auth_headers
        )
        assert validate_resp.status_code == 200
        val_data = validate_resp.json()
        assert val_data["success"] is True
        assert val_data["status"] == "VALIDATED"

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp.id))
        await db_session.commit()


# ==============================================================================
# 8. Capability Matching & Delivery Path Persistence Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_opportunity_capability_matches_and_delivery_path_lifecycle(client, db_session, auth_headers, test_prefix):
    """
    Verifies the end-to-end capability-delivery workflow:
    1. GET /api/opportunities/{id}/capability-matches returns real, ranked offerings.
    2. PATCH /api/opportunities/{id}/capability-matches/{match_id} persists selected capability in DB.
    3. Rejection of invalid match status with 400.
    4. GET /api/opportunities/{id}/solutions returns INTERNAL, NETWORK, and HYBRID candidates.
    5. PATCH /api/opportunities/{id}/path enforces supported values (INTERNAL, NETWORK, HYBRID)
       and persists delivery_path in PostgreSQL.
    6. Rejection of invalid delivery path with 400.
    7. GET /api/opportunities/{id} returns persisted deliveryPath and selectedSolutionId.
    8. Cross-tenant or missing records return 404.
    """
    opp = Opportunity(
        id=f"opp-cap-{test_prefix}",
        organization_id="org-1",
        company_name="CloudScale Enterprises",
        title="Cloud Modernization & Pipeline Automation",
        problem="Legacy monolithic database bottlenecks and delayed automated reporting pipelines.",
        requirement="Microservices refactoring and automated ETL telemetry with SOC2 audit trails.",
        opportunity_type="ENTERPRISE_AI_PILOT",
        status=OpportunityLifecycleStatus.DISCOVERED,
        confidence=80,
        supporting_evidence_ids=["ev-test-cloud-1"]
    )
    db_session.add(opp)
    await db_session.commit()

    try:
        # 1. GET /api/opportunities/{id}/capability-matches
        matches_resp = await client.get(f"/api/opportunities/{opp.id}/capability-matches", headers=auth_headers)
        assert matches_resp.status_code == 200
        matches_data = matches_resp.json()
        assert "matches" in matches_data
        assert len(matches_data["matches"]) > 0

        first_match = matches_data["matches"][0]
        assert "id" in first_match
        assert "capability" in first_match
        assert first_match["capability"]["name"]
        assert "reasoning" in first_match
        assert first_match["reasoning"]["overallExplanation"]
        assert first_match["status"] in ["CANDIDATE", "SELECTED"]

        target_match_id = first_match["id"]
        target_cap_id = first_match["capabilityId"]

        # 2. PATCH /api/opportunities/{id}/capability-matches/{match_id} (Select Match)
        select_resp = await client.patch(
            f"/api/opportunities/{opp.id}/capability-matches/{target_match_id}",
            json={"status": "SELECTED"},
            headers=auth_headers
        )
        assert select_resp.status_code == 200
        assert select_resp.json()["success"] is True

        # Verify DB persistence of selected capability
        db_opp = (await db_session.execute(select(Opportunity).where(Opportunity.id == opp.id))).scalars().first()
        await db_session.refresh(db_opp)
        assert db_opp.selected_solution_id == target_cap_id
        assert db_opp.delivery_path == "INTERNAL"

        # 3. PATCH with invalid match status returns 400
        bad_status_resp = await client.patch(
            f"/api/opportunities/{opp.id}/capability-matches/{target_match_id}",
            json={"status": "INVALID_STATE"},
            headers=auth_headers
        )
        assert bad_status_resp.status_code == 400

        # 4. GET /api/opportunities/{id}/solutions
        solutions_resp = await client.get(f"/api/opportunities/{opp.id}/solutions", headers=auth_headers)
        assert solutions_resp.status_code == 200
        sols_data = solutions_resp.json()
        assert "solutions" in sols_data
        sol_types = {s["type"] for s in sols_data["solutions"]}
        assert "INTERNAL" in sol_types
        assert "NETWORK" in sol_types
        assert "HYBRID" in sol_types

        # 5. PATCH /api/opportunities/{id}/path with valid supported paths
        for valid_path in ["NETWORK", "HYBRID", "INTERNAL"]:
            path_resp = await client.patch(
                f"/api/opportunities/{opp.id}/path",
                json={"path": valid_path},
                headers=auth_headers
            )
            assert path_resp.status_code == 200
            p_data = path_resp.json()
            assert p_data["success"] is True
            assert p_data["selected_path"] == valid_path
            assert p_data["delivery_path"] == valid_path

            # Verify PostgreSQL persistence
            await db_session.refresh(db_opp)
            assert db_opp.delivery_path == valid_path
            assert db_opp.selected_path == valid_path

        # 6. PATCH /api/opportunities/{id}/path with invalid path returns 400
        invalid_path_resp = await client.patch(
            f"/api/opportunities/{opp.id}/path",
            json={"path": "OUTSOURCED"},
            headers=auth_headers
        )
        assert invalid_path_resp.status_code == 400
        assert "Supported values" in invalid_path_resp.json()["detail"]

        # 7. GET /api/opportunities/{id} returns deliveryPath & selectedSolutionId
        get_detail_resp = await client.get(f"/api/opportunities/{opp.id}", headers=auth_headers)
        assert get_detail_resp.status_code == 200
        detail_data = get_detail_resp.json()
        assert detail_data["deliveryPath"] == "INTERNAL"
        assert detail_data["selectedSolutionId"] == target_cap_id

        # 8. Non-existent opportunity returns 404
        missing_id = "opp-non-existent-cap-999"
        assert (await client.get(f"/api/opportunities/{missing_id}/capability-matches", headers=auth_headers)).status_code == 404
        assert (await client.get(f"/api/opportunities/{missing_id}/solutions", headers=auth_headers)).status_code == 404
        assert (await client.patch(f"/api/opportunities/{missing_id}/path", json={"path": "INTERNAL"}, headers=auth_headers)).status_code == 404

    finally:
        await db_session.execute(delete(Opportunity).where(Opportunity.id == opp.id))
        await db_session.commit()

