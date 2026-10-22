"""
Comprehensive API-level test suite for NetworkOS Meeting Intelligence REST Endpoints.
NetworkOS Module: Meeting Preparation, Capture, Structured Intelligence Extraction & Validation.

Validates:
1. Authentication & Bearer token enforcement (401 on missing/invalid credentials).
2. Multi-tenant organization isolation (cross-tenant access prohibited for Brief, Capture, Intelligence, Validation).
3. Meeting creation & Executive Brief retrieval with Contact 360 intelligence.
4. Meeting capture, transcript parsing, and structured candidate finding extraction (status=AWAITING_VALIDATION, verbatim quote).
5. Founder validation workflow (CONFIRMED, EDITED, REJECTED).
6. Downstream propagation of confirmed findings to Trusted Context and the Opportunity Engine.
7. Error handling & validation (404 on missing records, 422 on empty transcript/invalid status).
"""

import uuid
import pytest
from sqlalchemy import delete
from sqlalchemy.future import select

from app.models.identity import Contact, ContactStatus
from app.models.meeting import Meeting, MeetingFinding, MeetingStatus, FindingType, FindingStatus
from app.models.trusted_context import TrustedContext
from app.models.opportunity import Opportunity


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer mock-token"}


@pytest.fixture
def test_prefix():
    return f"meet-test-{uuid.uuid4().hex[:8]}"


# ==============================================================================
# 1. Authentication Enforcement Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_unauthenticated_meeting_requests_rejected(client):
    """All meeting intelligence endpoints must reject unauthenticated requests with 401."""
    # 1. GET brief
    resp = await client.get("/api/v1/meetings/meet-any-123/brief")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"]["code"] == "UNAUTHORIZED"

    # 2. POST capture
    resp = await client.post("/api/v1/meetings/meet-any-123/capture", json={"transcript": "Test transcript"})
    assert resp.status_code == 401

    # 3. GET intelligence
    resp = await client.get("/api/v1/meetings/meet-any-123/intelligence")
    assert resp.status_code == 401

    # 4. PATCH intelligence validation
    resp = await client.patch(
        "/api/v1/meetings/meet-any-123/intelligence/f-any-123",
        json={"status": "CONFIRMED"}
    )
    assert resp.status_code == 401

    # 5. GET meetings list
    resp = await client.get("/api/v1/meetings")
    assert resp.status_code == 401

    # 6. POST create meeting
    resp = await client.post("/api/v1/meetings", json={"title": "Test Meeting"})
    assert resp.status_code == 401

    # 7. Invalid token
    resp = await client.get(
        "/api/v1/meetings/meet-any-123/brief",
        headers={"Authorization": "Bearer invalid-token"}
    )
    assert resp.status_code == 401


# ==============================================================================
# 2. Multi-Tenant Organization Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_meeting_organization_isolation(client, db_session, auth_headers, test_prefix):
    """Meetings and findings belonging to foreign tenant cannot be accessed or modified by org-1."""
    foreign_contact_id = f"c-foreign-{test_prefix}"
    foreign_meeting_id = f"m-foreign-{test_prefix}"
    foreign_finding_id = f"f-foreign-{test_prefix}"

    foreign_contact = Contact(
        id=foreign_contact_id,
        organization_id="org-foreign-tenant",
        full_name=f"Foreign Exec {test_prefix}",
        current_company="Foreign Enterprise",
        status=ContactStatus.READY,
    )
    foreign_meeting = Meeting(
        id=foreign_meeting_id,
        organization_id="org-foreign-tenant",
        contact_id=foreign_contact_id,
        title="Confidential Foreign Board Meeting",
        status=MeetingStatus.SCHEDULED,
        raw_transcript="Confidential discussions on cross-border operations.",
    )
    foreign_finding = MeetingFinding(
        id=foreign_finding_id,
        organization_id="org-foreign-tenant",
        meeting_id=foreign_meeting_id,
        contact_id=foreign_contact_id,
        finding_type="PROBLEM",
        claim="Confidential foreign operational bottleneck",
        evidence_quote="'Strictly private tenant memo'",
        status="AWAITING_VALIDATION",
    )

    db_session.add(foreign_contact)
    db_session.add(foreign_meeting)
    db_session.add(foreign_finding)
    await db_session.commit()

    try:
        # 1. Direct GET of foreign meeting metadata must return 404
        get_resp = await client.get(
            f"/api/v1/meetings/{foreign_meeting_id}",
            headers=auth_headers
        )
        assert get_resp.status_code == 404

        # 2. GET brief of foreign meeting must return 404
        brief_resp = await client.get(
            f"/api/v1/meetings/{foreign_meeting_id}/brief",
            headers=auth_headers
        )
        assert brief_resp.status_code == 404

        # 3. GET intelligence of foreign meeting must return 404
        intel_resp = await client.get(
            f"/api/v1/meetings/{foreign_meeting_id}/intelligence",
            headers=auth_headers
        )
        assert intel_resp.status_code == 404

        # 4. POST capture on foreign meeting must return 404
        capture_resp = await client.post(
            f"/api/v1/meetings/{foreign_meeting_id}/capture",
            json={"transcript": "Unauthorized transcript injection"},
            headers=auth_headers
        )
        assert capture_resp.status_code == 404

        # 5. PATCH validation on foreign finding must return 404
        patch_resp = await client.patch(
            f"/api/v1/meetings/{foreign_meeting_id}/intelligence/{foreign_finding_id}",
            json={"status": "CONFIRMED"},
            headers=auth_headers
        )
        assert patch_resp.status_code == 404

    finally:
        await db_session.execute(delete(MeetingFinding).where(MeetingFinding.id == foreign_finding_id))
        await db_session.execute(delete(Meeting).where(Meeting.id == foreign_meeting_id))
        await db_session.execute(delete(Contact).where(Contact.id == foreign_contact_id))
        await db_session.commit()


# ==============================================================================
# 3. Meeting Creation & Brief Retrieval Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_meeting_creation_and_brief_retrieval(client, db_session, auth_headers, test_prefix):
    """Creates a meeting with associated contact and verifies pre-meeting executive brief."""
    contact_id = f"c-brief-{test_prefix}"
    contact = Contact(
        id=contact_id,
        organization_id="org-1",
        full_name=f"Rahul Dhamdhere {test_prefix}",
        current_company="Global Logistics Corp",
        current_title="VP Engineering & Architecture",
        status=ContactStatus.READY,
    )
    db_session.add(contact)
    await db_session.commit()

    created_meeting_id = None
    try:
        # 1. Create meeting
        create_payload = {
            "title": f"Enterprise Modernization Alignment {test_prefix}",
            "contact_id": contact_id,
            "objectives": [
                "Explore autonomous ABAP migration pilot.",
                "Review enterprise SLA and cloud boundaries."
            ],
            "suggested_topics": [
                "Acknowledge recent public modernization milestone at Global Logistics.",
                "Address specific technical bottleneck around custom SAP ECC table dependencies."
            ]
        }
        create_resp = await client.post(
            "/api/v1/meetings",
            json=create_payload,
            headers=auth_headers
        )
        assert create_resp.status_code == 201
        meeting_data = create_resp.json()
        created_meeting_id = meeting_data["id"]

        assert meeting_data["title"] == create_payload["title"]
        assert meeting_data["contactId"] == contact_id
        assert meeting_data["contactName"] == contact.full_name
        assert meeting_data["company"] == contact.current_company
        assert meeting_data["status"] == "SCHEDULED"

        # 2. Retrieve executive brief
        brief_resp = await client.get(
            f"/api/v1/meetings/{created_meeting_id}/brief",
            headers=auth_headers
        )
        assert brief_resp.status_code == 200
        brief = brief_resp.json()

        assert brief["meetingId"] == created_meeting_id
        assert brief["contactId"] == contact_id
        assert brief["contactName"] == contact.full_name
        assert brief["company"] == contact.current_company
        assert len(brief["objectives"]) >= 2
        assert len(brief["suggestedTopics"]) >= 2
        assert len(brief["talkingPoints"]) >= 2
        assert brief["relationshipContext"] is not None

    finally:
        if created_meeting_id:
            await db_session.execute(delete(MeetingFinding).where(MeetingFinding.meeting_id == created_meeting_id))
            await db_session.execute(delete(Meeting).where(Meeting.id == created_meeting_id))
        await db_session.execute(delete(Contact).where(Contact.id == contact_id))
        await db_session.commit()


# ==============================================================================
# 4. Meeting Capture & Structured Candidate Extraction Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_meeting_capture_and_extraction(client, db_session, auth_headers, test_prefix):
    """
    Captures conversation notes, parses problems and requirements into candidate findings,
    strictly keeping them unconfirmed (status=AWAITING_VALIDATION) with verbatim evidence quotes.
    """
    contact_id = f"c-cap-{test_prefix}"
    contact = Contact(
        id=contact_id,
        organization_id="org-1",
        full_name=f"Elena Vasquez {test_prefix}",
        current_company="Apex FinTech",
        current_title="CTO",
        status=ContactStatus.READY,
    )
    meeting_id = f"m-cap-{test_prefix}"
    meeting = Meeting(
        id=meeting_id,
        organization_id="org-1",
        contact_id=contact_id,
        title="Apex Modernization Architecture Review",
        status=MeetingStatus.SCHEDULED,
    )
    db_session.add(contact)
    db_session.add(meeting)
    await db_session.commit()

    try:
        # Realistic conversation transcript with explicit problems and architectural requirements
        transcript = (
            "During the briefing, Elena explained that their core engineering team is struggling "
            "with massive legacy custom ABAP workflows with zero active documentation, causing "
            "costly migration delays. Furthermore, their company policy strictly requires that "
            "any pilot solution must run on-premise or within a sovereign VPC to adhere to EU "
            "data privacy standards. CTO Elena confirmed their Q3 roadmap initiative has "
            "allocated budget for validation."
        )

        # 1. Post capture
        capture_resp = await client.post(
            f"/api/v1/meetings/{meeting_id}/capture",
            json={"transcript": transcript},
            headers=auth_headers
        )
        assert capture_resp.status_code == 200
        cap_data = capture_resp.json()
        assert cap_data["meetingId"] == meeting_id
        assert cap_data["status"] == "EXTRACTED"
        assert cap_data["extractedNeedsCount"] >= 2

        # 2. Retrieve intelligence findings
        intel_resp = await client.get(
            f"/api/v1/meetings/{meeting_id}/intelligence",
            headers=auth_headers
        )
        assert intel_resp.status_code == 200
        intel = intel_resp.json()
        assert intel["meetingId"] == meeting_id
        assert intel["contactId"] == contact_id
        findings = intel["findings"]
        assert len(findings) >= 2

        # Ensure all extracted candidate findings are NOT confirmed initially
        for f in findings:
            assert f["status"] == "AWAITING_VALIDATION"
            assert f["sourceMeetingId"] == meeting_id
            assert f["evidenceQuote"] is not None
            assert len(f["evidenceQuote"]) > 5

        # Check that we extracted both a problem and a requirement
        problem_finding = next((f for f in findings if f["type"] == "PROBLEM"), None)
        assert problem_finding is not None
        assert "struggling" in problem_finding["evidenceQuote"].lower() or "legacy" in problem_finding["evidenceQuote"].lower()

        req_finding = next((f for f in findings if f["type"] == "REQUIREMENT"), None)
        assert req_finding is not None
        assert "require" in req_finding["evidenceQuote"].lower() or "sovereign" in req_finding["evidenceQuote"].lower()

    finally:
        await db_session.execute(delete(MeetingFinding).where(MeetingFinding.meeting_id == meeting_id))
        await db_session.execute(delete(Meeting).where(Meeting.id == meeting_id))
        await db_session.execute(delete(Contact).where(Contact.id == contact_id))
        await db_session.commit()


# ==============================================================================
# 5. Founder Validation & Downstream Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_meeting_finding_validation_and_downstream_integration(client, db_session, auth_headers, test_prefix):
    """
    Validating (confirming/editing) candidate findings:
    1. Updates finding status to CONFIRMED or EDITED.
    2. Propagates verified statement to Trusted Context.
    3. Promotes commercial problem finding to the Opportunity Engine as candidate opportunity.
    """
    contact_id = f"c-downstream-{test_prefix}"
    contact = Contact(
        id=contact_id,
        organization_id="org-1",
        full_name=f"Vikram Sen {test_prefix}",
        current_company="NexGen Rail Systems",
        current_title="Head of Platform Architecture",
        status=ContactStatus.READY,
    )
    meeting_id = f"m-downstream-{test_prefix}"
    meeting = Meeting(
        id=meeting_id,
        organization_id="org-1",
        contact_id=contact_id,
        title="NexGen Platform Deep Dive",
        status=MeetingStatus.SCHEDULED,
    )
    finding_problem_id = f"f-prob-{test_prefix}"
    finding_prob = MeetingFinding(
        id=finding_problem_id,
        organization_id="org-1",
        meeting_id=meeting_id,
        contact_id=contact_id,
        finding_type="PROBLEM",
        claim="Real-time signaling telemetry engine saturates CPU under peak rail traffic.",
        evidence_quote="'Under peak congestion our streaming decoder drops 15% of packets.'",
        confidence=90,
        status="AWAITING_VALIDATION",
    )

    finding_req_id = f"f-req-{test_prefix}"
    finding_req = MeetingFinding(
        id=finding_req_id,
        organization_id="org-1",
        meeting_id=meeting_id,
        contact_id=contact_id,
        finding_type="REQUIREMENT",
        claim="Initial inference on edge latency threshold",
        evidence_quote="'Sub-50ms latency is mandatory for wayside signaling safety'",
        confidence=85,
        status="AWAITING_VALIDATION",
    )

    db_session.add(contact)
    db_session.add(meeting)
    db_session.add(finding_prob)
    db_session.add(finding_req)
    await db_session.commit()

    created_tc_id = None
    created_opp_id = None

    try:
        # 1. CONFIRM problem finding -> should propagate to Trusted Context AND create Opportunity
        confirm_resp = await client.patch(
            f"/api/v1/meetings/{meeting_id}/intelligence/{finding_problem_id}",
            json={"status": "CONFIRMED"},
            headers=auth_headers
        )
        assert confirm_resp.status_code == 200
        res = confirm_resp.json()
        assert res["success"] is True
        assert res["finding"]["status"] == "CONFIRMED"
        assert res["finding"]["trustLevel"] == "CONFIRMED"
        
        created_tc_id = res["trustedContextId"]
        created_opp_id = res["opportunityId"]

        assert created_tc_id is not None
        assert created_opp_id is not None

        # Verify downstream Trusted Context persistence
        tc_resp = await client.get(
            f"/api/v1/trusted-context/{created_tc_id}",
            headers=auth_headers
        )
        assert tc_resp.status_code == 200
        tc_data = tc_resp.json()
        assert tc_data["id"] == created_tc_id
        assert tc_data["content"] == finding_prob.claim
        assert tc_data["isConfirmed"] is True

        # Verify downstream Opportunity Engine persistence
        opp_resp = await client.get(
            f"/api/v1/opportunities/{created_opp_id}",
            headers=auth_headers
        )
        assert opp_resp.status_code == 200
        opp_data = opp_resp.json()
        assert opp_data["id"] == created_opp_id
        assert opp_data["problem"] == finding_prob.claim
        assert (opp_data.get("personId") or opp_data.get("contactId") or opp_data.get("contact_id")) == contact_id
        assert opp_data["status"] in ("DISCOVERED", "CANDIDATE")

        # 2. EDIT & CONFIRM second finding -> updates content, sets status EDITED, propagates to Trusted Context
        edited_content = "Founder confirmed: strict sub-40ms wayside determinism constraint"
        edit_resp = await client.patch(
            f"/api/v1/meetings/{meeting_id}/intelligence/{finding_req_id}",
            json={
                "status": "EDITED",
                "content": edited_content,
                "correction_note": "Founder clarified precision safety threshold",
            },
            headers=auth_headers
        )
        assert edit_resp.status_code == 200
        edit_res = edit_resp.json()
        assert edit_res["success"] is True
        assert edit_res["finding"]["status"] == "EDITED"
        assert edit_res["finding"]["content"] == edited_content

        tc_req_id = edit_res["trustedContextId"]
        assert tc_req_id is not None
        tc_req_resp = await client.get(
            f"/api/v1/trusted-context/{tc_req_id}",
            headers=auth_headers
        )
        assert tc_req_resp.status_code == 200
        assert tc_req_resp.json()["content"] == edited_content

    finally:
        if created_opp_id:
            await db_session.execute(delete(Opportunity).where(Opportunity.id == created_opp_id))
        if created_tc_id:
            await db_session.execute(delete(TrustedContext).where(TrustedContext.id == created_tc_id))
        await db_session.execute(delete(MeetingFinding).where(MeetingFinding.meeting_id == meeting_id))
        await db_session.execute(delete(Meeting).where(Meeting.id == meeting_id))
        await db_session.execute(delete(Contact).where(Contact.id == contact_id))
        await db_session.commit()


# ==============================================================================
# 6. Error Handling & Input Validation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_meeting_error_handling_and_validation(client, db_session, auth_headers, test_prefix):
    """Empty inputs return 422, non-existent records return 404, and invalid statuses return 422."""
    contact_id = f"c-err-{test_prefix}"
    contact = Contact(
        id=contact_id,
        organization_id="org-1",
        full_name="Error Handling User",
        current_company="Acme Testing",
        status=ContactStatus.READY,
    )
    meeting_id = f"m-err-{test_prefix}"
    meeting = Meeting(
        id=meeting_id,
        organization_id="org-1",
        contact_id=contact_id,
        title="Error Test Meeting",
        status=MeetingStatus.SCHEDULED,
    )
    db_session.add(contact)
    db_session.add(meeting)
    await db_session.commit()

    try:
        # 1. Non-existent meeting ID returns 404
        bad_brief = await client.get(
            "/api/v1/meetings/m-nonexistent-99999/brief",
            headers=auth_headers
        )
        assert bad_brief.status_code == 404

        bad_intel = await client.get(
            "/api/v1/meetings/m-nonexistent-99999/intelligence",
            headers=auth_headers
        )
        assert bad_intel.status_code == 404

        # 2. Empty capture transcript returns 422
        empty_capture = await client.post(
            f"/api/v1/meetings/{meeting_id}/capture",
            json={"transcript": "   "},
            headers=auth_headers
        )
        assert empty_capture.status_code == 422

        # 3. Invalid validation status returns 422
        bad_status = await client.patch(
            f"/api/v1/meetings/{meeting_id}/intelligence/f-nonexistent-123",
            json={"status": "INVALID_STATUS"},
            headers=auth_headers
        )
        assert bad_status.status_code == 422

        # 4. Non-existent finding ID returns 404
        missing_finding = await client.patch(
            f"/api/v1/meetings/{meeting_id}/intelligence/f-nonexistent-123",
            json={"status": "CONFIRMED"},
            headers=auth_headers
        )
        assert missing_finding.status_code == 404

    finally:
        await db_session.execute(delete(MeetingFinding).where(MeetingFinding.meeting_id == meeting_id))
        await db_session.execute(delete(Meeting).where(Meeting.id == meeting_id))
        await db_session.execute(delete(Contact).where(Contact.id == contact_id))
        await db_session.commit()
