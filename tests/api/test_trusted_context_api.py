"""
Comprehensive API-level test suite for NetworkOS Trusted Context REST Endpoints.
NetworkOS Module: Founder-Confirmed Intelligence & Verified Ground Truth.

Validates:
1. Authentication & Bearer token enforcement (401 on missing/invalid credentials).
2. Multi-tenant organization isolation (cross-tenant access prohibited for GET, POST, PATCH, DELETE).
3. Contact validation (404 when target contact does not exist or belongs to another tenant).
4. Creation with initial version 1 and provenance metadata.
5. Updating and correcting context with immutable historical version tracking (incrementing version, preserving history).
6. Input schema validation (rejecting empty statements, invalid payloads).
7. Missing record handling (404 on unknown IDs).
8. Successful deletion and subsequent 404 verification.
"""

import uuid
import pytest
from sqlalchemy import delete
from sqlalchemy.future import select

from app.models.identity import Contact, ContactStatus
from app.models.trusted_context import TrustedContext, TrustedContextType


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer mock-token"}


@pytest.fixture
def test_prefix():
    return f"tc-test-{uuid.uuid4().hex[:8]}"


# ==============================================================================
# 1. Authentication Enforcement Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_unauthenticated_trusted_context_requests_rejected(client):
    """All trusted context endpoints must reject unauthenticated requests with 401."""
    # 1. GET contact context
    resp = await client.get("/api/v1/contacts/c-any-123/trusted-context")
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"]["code"] == "UNAUTHORIZED"

    # 2. POST contact context
    resp = await client.post("/api/v1/contacts/c-any-123/trusted-context", json={"content": "Test context"})
    assert resp.status_code == 401

    # 3. GET item
    resp = await client.get("/api/v1/trusted-context/tc-any-123")
    assert resp.status_code == 401

    # 4. PATCH item
    resp = await client.patch("/api/v1/trusted-context/tc-any-123", json={"content": "Updated"})
    assert resp.status_code == 401

    # 5. DELETE item
    resp = await client.delete("/api/v1/trusted-context/tc-any-123")
    assert resp.status_code == 401

    # 6. Invalid token
    resp = await client.get(
        "/api/v1/contacts/c-any-123/trusted-context",
        headers={"Authorization": "Bearer invalid-token"}
    )
    assert resp.status_code == 401


# ==============================================================================
# 2. Multi-Tenant Organization Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_trusted_context_organization_isolation(client, db_session, auth_headers, test_prefix):
    """Records belonging to another organization cannot be read, updated, or deleted by org-1."""
    foreign_contact_id = f"c-foreign-{test_prefix}"
    foreign_tc_id = f"tc-foreign-{test_prefix}"

    foreign_contact = Contact(
        id=foreign_contact_id,
        organization_id="org-foreign-tenant",
        full_name=f"Foreign Exec {test_prefix}",
        current_company="Foreign Enterprise",
        status=ContactStatus.READY,
    )
    foreign_tc = TrustedContext(
        id=foreign_tc_id,
        organization_id="org-foreign-tenant",
        contact_id=foreign_contact_id,
        type="PROBLEM",
        content="Confidential cross-tenant bottleneck",
        evidence="Internal board memo",
        current_version=1,
        history=[{"version": 1, "content": "Confidential cross-tenant bottleneck", "timestamp": "2026-10-10T10:00:00Z"}],
        is_confirmed=True,
    )

    db_session.add(foreign_contact)
    db_session.add(foreign_tc)
    await db_session.commit()

    try:
        # 1. Listing contact context for foreign contact must return 404
        list_resp = await client.get(
            f"/api/v1/contacts/{foreign_contact_id}/trusted-context",
            headers=auth_headers
        )
        assert list_resp.status_code == 404
        assert list_resp.json()["detail"] == "Contact not found"

        # 2. Direct GET of foreign item must return 404
        get_resp = await client.get(
            f"/api/v1/trusted-context/{foreign_tc_id}",
            headers=auth_headers
        )
        assert get_resp.status_code == 404
        assert get_resp.json()["detail"] == "Trusted context not found"

        # 3. Direct PATCH of foreign item must return 404
        patch_resp = await client.patch(
            f"/api/v1/trusted-context/{foreign_tc_id}",
            json={"content": "Attempted cross-tenant modification"},
            headers=auth_headers
        )
        assert patch_resp.status_code == 404

        # 4. Direct DELETE of foreign item must return 404
        del_resp = await client.delete(
            f"/api/v1/trusted-context/{foreign_tc_id}",
            headers=auth_headers
        )
        assert del_resp.status_code == 404

    finally:
        await db_session.execute(delete(TrustedContext).where(TrustedContext.id == foreign_tc_id))
        await db_session.execute(delete(Contact).where(Contact.id == foreign_contact_id))
        await db_session.commit()


# ==============================================================================
# 3. Creation, Retrieval, and Provenance Metadata
# ==============================================================================

@pytest.mark.asyncio
async def test_trusted_context_creation_and_retrieval(client, db_session, auth_headers, test_prefix):
    """Creating trusted context creates version 1, sets provenance, and persists in database."""
    contact_id = f"c-org1-{test_prefix}"
    contact = Contact(
        id=contact_id,
        organization_id="org-1",
        full_name=f"Rahul Dhamdhere {test_prefix}",
        current_company="Global Logistics Corp",
        status=ContactStatus.READY,
    )
    db_session.add(contact)
    await db_session.commit()

    created_tc_id = None
    try:
        # 1. Create a new trusted context item
        create_payload = {
            "type": "PROBLEM",
            "content": f"Legacy SAP ECC custom workflows stalling migration {test_prefix}",
            "evidence": "Direct statement during Q3 modernization briefing",
            "confidence": 95,
        }
        create_resp = await client.post(
            f"/api/v1/contacts/{contact_id}/trusted-context",
            json=create_payload,
            headers=auth_headers
        )
        assert create_resp.status_code == 201
        data = create_resp.json()
        created_tc_id = data["id"]

        assert data["contactId"] == contact_id
        assert data["type"] == "PROBLEM"
        assert data["currentVersion"] == 1
        assert data["content"] == create_payload["content"]
        assert data["evidence"] == create_payload["evidence"]
        assert data["isConfirmed"] is True
        assert data["confidence"] == 95
        assert len(data["history"]) == 1
        assert data["history"][0]["version"] == 1
        assert data["history"][0]["content"] == create_payload["content"]

        # 2. Retrieve via contact endpoint
        list_resp = await client.get(
            f"/api/v1/contacts/{contact_id}/trusted-context",
            headers=auth_headers
        )
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["total"] >= 1
        found = next((i for i in list_data["items"] if i["id"] == created_tc_id), None)
        assert found is not None
        assert found["content"] == create_payload["content"]

        # 3. Retrieve via direct item endpoint
        item_resp = await client.get(
            f"/api/v1/trusted-context/{created_tc_id}",
            headers=auth_headers
        )
        assert item_resp.status_code == 200
        item_data = item_resp.json()
        assert item_data["id"] == created_tc_id
        assert item_data["currentVersion"] == 1

    finally:
        if created_tc_id:
            await db_session.execute(delete(TrustedContext).where(TrustedContext.id == created_tc_id))
        await db_session.execute(delete(Contact).where(Contact.id == contact_id))
        await db_session.commit()


# ==============================================================================
# 4. Context Correction & Version History Tracking
# ==============================================================================

@pytest.mark.asyncio
async def test_trusted_context_update_version_history(client, db_session, auth_headers, test_prefix):
    """Updating trusted context increments currentVersion and appends previous version to history."""
    contact_id = f"c-vhist-{test_prefix}"
    tc_id = f"tc-vhist-{test_prefix}"

    contact = Contact(
        id=contact_id,
        organization_id="org-1",
        full_name="Elena Vasquez",
        current_company="Apex FinTech",
        status=ContactStatus.READY,
    )
    initial_content = "V1: Initial inference on cross-border payment latency."
    tc = TrustedContext(
        id=tc_id,
        organization_id="org-1",
        contact_id=contact_id,
        type="PROBLEM",
        content=initial_content,
        evidence="Preliminary meeting notes",
        current_version=1,
        history=[{"version": 1, "content": initial_content, "timestamp": "2026-10-15T12:00:00Z", "updated_by": "1"}],
        is_confirmed=True,
    )
    db_session.add(contact)
    db_session.add(tc)
    await db_session.commit()

    try:
        # First update: V1 -> V2
        updated_content_v2 = "V2: Founder clarified - sub-100ms streaming LLM decision bottleneck."
        patch_resp = await client.patch(
            f"/api/v1/trusted-context/{tc_id}",
            json={
                "content": updated_content_v2,
                "correction_note": "Founder clarified precision latency threshold",
            },
            headers=auth_headers
        )
        assert patch_resp.status_code == 200
        res = patch_resp.json()
        assert res["success"] is True
        item = res["item"]
        assert item["currentVersion"] == 2
        assert item["content"] == updated_content_v2
        assert len(item["history"]) == 2
        assert item["history"][0]["version"] == 1
        assert item["history"][0]["content"] == initial_content
        assert item["history"][1]["version"] == 2
        assert item["history"][1]["content"] == updated_content_v2
        assert item["history"][1]["correctionNote"] == "Founder clarified precision latency threshold"

        # Second update: V2 -> V3
        updated_content_v3 = "V3: Final verified ground truth approved by founder."
        patch_resp_3 = await client.patch(
            f"/api/v1/trusted-context/{tc_id}",
            json={"content": updated_content_v3},
            headers=auth_headers
        )
        assert patch_resp_3.status_code == 200
        item_3 = patch_resp_3.json()["item"]
        assert item_3["currentVersion"] == 3
        assert item_3["content"] == updated_content_v3
        assert len(item_3["history"]) == 3
        assert item_3["history"][0]["version"] == 1
        assert item_3["history"][1]["version"] == 2
        assert item_3["history"][2]["version"] == 3

        # Verify persistence via GET
        get_resp = await client.get(
            f"/api/v1/trusted-context/{tc_id}",
            headers=auth_headers
        )
        assert get_resp.status_code == 200
        persisted = get_resp.json()
        assert persisted["currentVersion"] == 3
        assert persisted["content"] == updated_content_v3
        assert len(persisted["history"]) == 3

    finally:
        await db_session.execute(delete(TrustedContext).where(TrustedContext.id == tc_id))
        await db_session.execute(delete(Contact).where(Contact.id == contact_id))
        await db_session.commit()


# ==============================================================================
# 5. Input Validation, Deletion & 404 Error Handling
# ==============================================================================

@pytest.mark.asyncio
async def test_trusted_context_validation_and_deletion(client, db_session, auth_headers, test_prefix):
    """Empty inputs return 422, non-existent records return 404, and deletion succeeds."""
    contact_id = f"c-val-{test_prefix}"
    contact = Contact(
        id=contact_id,
        organization_id="org-1",
        full_name="Validation User",
        current_company="Acme Corp",
        status=ContactStatus.READY,
    )
    db_session.add(contact)
    await db_session.commit()

    tc_id = f"tc-del-{test_prefix}"
    tc = TrustedContext(
        id=tc_id,
        organization_id="org-1",
        contact_id=contact_id,
        type="REQUIREMENT",
        content="Transient requirement for deletion test",
        current_version=1,
        history=[{"version": 1, "content": "Transient requirement", "timestamp": "2026-10-15T12:00:00Z"}],
    )
    db_session.add(tc)
    await db_session.commit()

    try:
        # 1. Non-existent contact ID returns 404
        resp_bad_contact = await client.post(
            "/api/v1/contacts/c-nonexistent-99999/trusted-context",
            json={"content": "Should fail"},
            headers=auth_headers
        )
        assert resp_bad_contact.status_code == 404

        # 2. Missing/empty content returns 422
        resp_empty_post = await client.post(
            f"/api/v1/contacts/{contact_id}/trusted-context",
            json={"content": ""},
            headers=auth_headers
        )
        assert resp_empty_post.status_code == 422

        resp_empty_patch = await client.patch(
            f"/api/v1/trusted-context/{tc_id}",
            json={"content": ""},
            headers=auth_headers
        )
        assert resp_empty_patch.status_code == 422

        # 3. Non-existent item ID returns 404
        resp_bad_item = await client.get(
            "/api/v1/trusted-context/tc-nonexistent-99999",
            headers=auth_headers
        )
        assert resp_bad_item.status_code == 404

        # 4. Successful deletion
        del_resp = await client.delete(
            f"/api/v1/trusted-context/{tc_id}",
            headers=auth_headers
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

        # 5. Subsequent GET returns 404
        get_deleted = await client.get(
            f"/api/v1/trusted-context/{tc_id}",
            headers=auth_headers
        )
        assert get_deleted.status_code == 404

    finally:
        await db_session.execute(delete(TrustedContext).where(TrustedContext.id == tc_id))
        await db_session.execute(delete(Contact).where(Contact.id == contact_id))
        await db_session.commit()
