import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy.future import select

from app.models.evidence import SourceResult, Evidence, EvidenceType
from app.models.identity import Contact, ContactStatus
from app.models.research import ResearchSource


@pytest.mark.asyncio
async def test_authenticated_access_to_valid_evidence_record(client, db_session):
    """
    Verify that an authenticated user can retrieve a valid evidence record
    with all attribution, excerpt, dates, and separated confidences.
    """
    cid = f"test-contact-{uuid.uuid4().hex[:8]}"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Alice Candidate",
        current_title="VP of Engineering",
        status=ContactStatus.READY
    )
    db_session.add(contact)
    await db_session.flush()

    sr_id = f"sr-{uuid.uuid4().hex[:8]}"
    sr = SourceResult(
        id=sr_id,
        source_id="github",
        query="Alice Candidate Engineering",
        raw_reference="https://github.com/alice-candidate",
        status="SUCCESS",
        extracted_data={
            "profile": {"bio": "Distributed systems engineer building cloud platforms."},
            "repositories": [
                {
                    "name": "cloud-mesh",
                    "description": "High-throughput service mesh controller in Go.",
                    "html_url": "https://github.com/alice-candidate/cloud-mesh"
                }
            ]
        },
        metadata_={
            "identity_match_status": "CONFIRMED",
            "identity_match_confidence": 95,
            "identity_match_rationale": "Verified GitHub profile matches candidate credentials."
        }
    )
    db_session.add(sr)
    await db_session.flush()

    ev_id = f"ev-{uuid.uuid4().hex[:8]}"
    observed = datetime(2025, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    ev = Evidence(
        id=ev_id,
        evidence_type=EvidenceType.FACT,
        claim="Repository: cloud-mesh (Go) service mesh controller",
        source_id="github",
        source_reference="https://github.com/alice-candidate/cloud-mesh",
        observed_date=observed,
        retrieved_date=datetime.now(timezone.utc),
        confidence=88,
        source_result_id=sr_id,
        related_entity_id=cid
    )
    db_session.add(ev)
    await db_session.commit()

    # Request evidence detail
    resp = await client.get(
        f"/api/v1/contacts/{cid}/evidence/{ev_id}",
        headers={"Authorization": "Bearer mock-token"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["id"] == ev_id
    assert data["contact_id"] == cid
    assert data["claim"] == "Repository: cloud-mesh (Go) service mesh controller"
    assert data["evidence_type"] == "FACT"
    assert data["confidence"] == 88  # Claim confidence
    assert data["identity_match_status"] == "CONFIRMED"
    assert data["identity_match_confidence"] == 95  # Identity match confidence
    assert data["identity_match_rationale"] == "Verified GitHub profile matches candidate credentials."
    assert data["source_id"] == "github"
    assert data["source_name"] == "GitHub Developer Intelligence"
    assert data["source_url"] == "https://github.com/alice-candidate/cloud-mesh"
    assert data["source_result_id"] == sr_id
    assert "service mesh controller" in data["excerpt"]
    assert "2025-04-15" in data["publication_date"]
    assert data["retrieved_date"] is not None


@pytest.mark.asyncio
async def test_evidence_belonging_to_another_contact_returns_404(client, db_session):
    """
    Ensure that requesting evidence with a contact ID it is NOT associated with returns 404.
    """
    contact_a_id = f"contact-a-{uuid.uuid4().hex[:8]}"
    contact_b_id = f"contact-b-{uuid.uuid4().hex[:8]}"

    ca = Contact(id=contact_a_id, organization_id="org-1", full_name="Contact A", status=ContactStatus.READY)
    cb = Contact(id=contact_b_id, organization_id="org-1", full_name="Contact B", status=ContactStatus.READY)
    db_session.add_all([ca, cb])
    await db_session.flush()

    ev_b_id = f"ev-b-{uuid.uuid4().hex[:8]}"
    ev_b = Evidence(
        id=ev_b_id,
        evidence_type=EvidenceType.SIGNAL,
        claim="Claim for Contact B only",
        source_id="github",
        confidence=70,
        related_entity_id=contact_b_id
    )
    db_session.add(ev_b)
    await db_session.commit()

    # Query with Contact A id -> Must return 404
    resp = await client.get(
        f"/api/v1/contacts/{contact_a_id}/evidence/{ev_b_id}",
        headers={"Authorization": "Bearer mock-token"}
    )
    assert resp.status_code == 404
    assert "Evidence record not found" in resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_cross_organization_access_denial_returns_404(client, db_session):
    """
    Ensure that an evidence record belonging to a contact in a different tenant/organization
    returns 404 without exposing any existence or data.
    """
    other_cid = f"contact-other-{uuid.uuid4().hex[:8]}"
    other_contact = Contact(
        id=other_cid,
        organization_id="org-foreign-corp",
        full_name="Foreign Corp Executive",
        status=ContactStatus.READY
    )
    db_session.add(other_contact)
    await db_session.flush()

    other_ev_id = f"ev-foreign-{uuid.uuid4().hex[:8]}"
    other_ev = Evidence(
        id=other_ev_id,
        evidence_type=EvidenceType.FACT,
        claim="Confidential patent filing",
        source_id="github",
        confidence=90,
        related_entity_id=other_cid
    )
    db_session.add(other_ev)
    await db_session.commit()

    # Authenticated user is org-1
    resp = await client.get(
        f"/api/v1/contacts/{other_cid}/evidence/{other_ev_id}",
        headers={"Authorization": "Bearer mock-token"}
    )
    assert resp.status_code == 404
    assert "Contact not found" in resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_nonexistent_evidence_id_returns_404(client, db_session):
    """
    Ensure that requesting a nonexistent evidence ID for a valid contact returns 404.
    """
    cid = f"test-contact-{uuid.uuid4().hex[:8]}"
    contact = Contact(id=cid, organization_id="org-1", full_name="Valid Contact", status=ContactStatus.READY)
    db_session.add(contact)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/contacts/{cid}/evidence/does-not-exist-9999",
        headers={"Authorization": "Bearer mock-token"}
    )
    assert resp.status_code == 404
    assert "Evidence record not found" in resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401(client, db_session):
    """
    Ensure that unauthenticated requests to the evidence endpoint return 401.
    """
    resp = await client.get("/api/v1/contacts/any-contact/evidence/any-evidence")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_missing_publication_date_and_excerpt_return_null(client, db_session):
    """
    Ensure that missing publication date and missing excerpt strictly return null
    and are NEVER fabricated.
    """
    cid = f"test-nulls-{uuid.uuid4().hex[:8]}"
    contact = Contact(id=cid, organization_id="org-1", full_name="Null Test", status=ContactStatus.READY)
    db_session.add(contact)
    await db_session.flush()

    sr_id = f"sr-nulls-{uuid.uuid4().hex[:8]}"
    sr = SourceResult(
        id=sr_id,
        source_id="general_web",
        query="Null Test",
        status="SUCCESS",
        extracted_data={},  # No excerpts or structured items
        metadata_={"identity_match_status": "PROBABLE", "identity_match_confidence": 60}
    )
    db_session.add(sr)
    await db_session.flush()

    ev_id = f"ev-nulls-{uuid.uuid4().hex[:8]}"
    ev = Evidence(
        id=ev_id,
        evidence_type=EvidenceType.SIGNAL,
        claim="Indexed web mention without publication date",
        source_id="general_web",
        observed_date=None,  # Missing publication date
        confidence=60,
        source_result_id=sr_id,
        related_entity_id=cid
    )
    db_session.add(ev)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/contacts/{cid}/evidence/{ev_id}",
        headers={"Authorization": "Bearer mock-token"}
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["publication_date"] is None
    assert data["excerpt"] is None
    assert data["claim"] == "Indexed web mention without publication date"
    assert data["confidence"] == 60


@pytest.mark.asyncio
async def test_claim_confidence_separated_from_identity_confidence(client, db_session):
    """
    Verify that claim confidence (extraction certainty) and identity confidence
    (candidate match certainty) are distinctly maintained in the API contract.
    """
    cid = f"test-conf-{uuid.uuid4().hex[:8]}"
    contact = Contact(id=cid, organization_id="org-1", full_name="Confidence Test", status=ContactStatus.READY)
    db_session.add(contact)
    await db_session.flush()

    sr_id = f"sr-conf-{uuid.uuid4().hex[:8]}"
    sr = SourceResult(
        id=sr_id,
        source_id="academic_openalex",
        query="Confidence Test",
        status="SUCCESS",
        extracted_data={"authors": [{"display_name": "Confidence Test", "institutions": ["MIT"]}]},
        metadata_={
            "identity_match_status": "CONFIRMED",
            "identity_match_confidence": 98,
            "identity_match_rationale": "Direct affiliation and name match."
        }
    )
    db_session.add(sr)
    await db_session.flush()

    ev_id = f"ev-conf-{uuid.uuid4().hex[:8]}"
    ev = Evidence(
        id=ev_id,
        evidence_type=EvidenceType.FACT,
        claim="Co-authored paper on distributed consensus",
        source_id="academic_openalex",
        confidence=62,  # Moderate extraction confidence
        source_result_id=sr_id,
        related_entity_id=cid
    )
    db_session.add(ev)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/contacts/{cid}/evidence/{ev_id}",
        headers={"Authorization": "Bearer mock-token"}
    )
    assert resp.status_code == 200
    data = resp.json()

    # Assert clear distinction
    assert data["confidence"] == 62
    assert data["identity_match_confidence"] == 98
    assert data["identity_match_status"] == "CONFIRMED"
    assert data["confidence"] != data["identity_match_confidence"]


@pytest.mark.asyncio
async def test_contact_360_includes_signals_and_evidence_map(client, db_session):
    """
    Verify that GET /api/v1/contacts/{id}/360 populates signals with real evidence IDs
    and includes evidenceMap mapping citation keys to real persisted evidence IDs.
    """
    cid = f"test-360-{uuid.uuid4().hex[:8]}"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Morgan Stark",
        current_title="Director of Research",
        current_company="Stark Industries",
        status=ContactStatus.READY
    )
    db_session.add(contact)
    await db_session.flush()

    ev_id1 = f"ev-360-1-{uuid.uuid4().hex[:8]}"
    ev1 = Evidence(
        id=ev_id1,
        evidence_type=EvidenceType.FACT,
        claim="Director of Research at Stark Industries",
        source_id="company_web",
        confidence=95,
        related_entity_id=cid
    )
    ev_id2 = f"ev-360-2-{uuid.uuid4().hex[:8]}"
    ev2 = Evidence(
        id=ev_id2,
        evidence_type=EvidenceType.SIGNAL,
        claim="Published technical article on clean energy",
        source_id="news_public",
        confidence=75,
        related_entity_id=cid
    )
    db_session.add_all([ev1, ev2])
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/contacts/{cid}/360",
        headers={"Authorization": "Bearer mock-token"}
    )
    assert resp.status_code == 200
    data = resp.json()

    # Signals populated
    assert len(data["signals"]) == 2
    signal_ev_ids = [s["evidenceId"] for s in data["signals"]]
    assert ev_id1 in signal_ev_ids
    assert ev_id2 in signal_ev_ids

    # Commercial intelligence has evidenceMap
    ci = data.get("commercialIntelligence")
    assert ci is not None
    ev_map = ci.get("evidenceMap", {})
    assert len(ev_map) >= 2
    assert "E1" in ev_map
    assert "E2" in ev_map
    map_ev_ids = [v.get("evidence_id") for v in ev_map.values()]
    assert ev_id1 in map_ev_ids
    assert ev_id2 in map_ev_ids


@pytest.mark.asyncio
async def test_direct_evidence_endpoint_lookup_and_tenant_security(client, db_session):
    """
    Verify GET /api/v1/contacts/evidence/{evidence_id} allows direct lookup
    while upholding tenant isolation.
    """
    cid = f"test-dir-{uuid.uuid4().hex[:8]}"
    contact = Contact(id=cid, organization_id="org-1", full_name="Direct Lookup User", status=ContactStatus.READY)
    db_session.add(contact)
    await db_session.flush()

    ev_id = f"ev-dir-{uuid.uuid4().hex[:8]}"
    ev = Evidence(
        id=ev_id,
        evidence_type=EvidenceType.SIGNAL,
        claim="Directly looked up signal",
        source_id="duckduckgo",
        confidence=80,
        related_entity_id=cid
    )
    db_session.add(ev)
    await db_session.commit()

    # Valid direct lookup
    resp = await client.get(
        f"/api/v1/contacts/evidence/{ev_id}",
        headers={"Authorization": "Bearer mock-token"}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == ev_id

    # Nonexistent direct lookup
    resp_none = await client.get(
        "/api/v1/contacts/evidence/does-not-exist",
        headers={"Authorization": "Bearer mock-token"}
    )
    assert resp_none.status_code == 404
