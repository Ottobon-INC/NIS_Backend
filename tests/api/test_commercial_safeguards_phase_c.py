import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.future import select

from app.models.evidence import SourceResult, Evidence, EvidenceType
from app.models.identity import Contact, ContactStatus
from app.models.orchestration import ResearchRun, ResearchTask, TaskStatus
from app.services.evidence import EvidenceEngine, ExecutiveSnapshot
from app.schemas.research import OpportunityStatus


@pytest.mark.asyncio
async def test_ai_generated_opportunity_defaults_to_proposed_never_validated(client, db_session):
    """
    Test 1: Verify that an AI-generated opportunity defaults to PROPOSED
    and can NEVER automatically become VALIDATED or QUALIFIED upon report synthesis.
    Even if the LLM output suggests QUALIFIED/VALIDATED, the engine forces PROPOSED.
    """
    cid = f"test-c-{uuid.uuid4().hex[:8]}"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Dr. Elena Rostova",
        current_title="Principal Researcher",
        current_company="QuantumAI Labs",
        status=ContactStatus.RESEARCHING
    )
    db_session.add(contact)

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    run = ResearchRun(
        id=run_id,
        contact_id=cid,
        status="COMPLETED"
    )
    db_session.add(run)

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    task = ResearchTask(
        id=task_id,
        research_run_id=run_id,
        source_id="github",
        status=TaskStatus.COMPLETED
    )
    db_session.add(task)
    await db_session.flush()

    sr_id = f"sr-{uuid.uuid4().hex[:8]}"
    sr = SourceResult(
        id=sr_id,
        research_task_id=task_id,
        source_id="github",
        query="Elena Rostova QuantumAI",
        status="SUCCESS",
        extracted_data={"profile": {"bio": "Quantum Researcher"}, "text": "Principal Researcher at QuantumAI Labs leading quantum ML algorithms"},
        metadata_={"contact_id": cid, "identity_match_status": "CONFIRMED", "identity_match_confidence": 92}
    )
    db_session.add(sr)
    await db_session.flush()

    # Confirmed evidence
    ev = Evidence(
        id=f"ev-{uuid.uuid4().hex[:8]}",
        evidence_type=EvidenceType.FACT,
        claim="Bio: Principal Researcher at QuantumAI Labs leading quantum ML algorithms",
        source_id="github",
        source_result_id=sr_id,
        confidence=90,
        related_entity_id=cid
    )
    db_session.add(ev)

    await db_session.commit()


    # Mock LLM attempting to qualify/validate automatically
    mock_snapshot = ExecutiveSnapshot(
        name="Dr. Elena Rostova",
        current_role="Principal Researcher",
        current_organization="QuantumAI Labs",
        location="Zurich",
        domain_name="Quantum Computing",
        proven_domain_expertise="Quantum Machine Learning",
        customer_knowledge_level="High",
        is_domain_sme="SME",
        operating_in_own_domain=True,
        opportunity_category="Expert-Led Product Venture",
        opportunity_nature="Direct",
        broad_business_problem="Quantum circuit noise optimization",
        smallest_solvable_problem="Circuit simulation module",
        why_now="Recent breakthrough paper",
        ottobon_capability_match="AI Applications",
        delivery_risk_level="MEDIUM",
        estimated_effort_hours="140 hours",

        cost_pricing_estimate="$15,000 sprint at 70% gross margin (Assumption)",
        proposed_first_engagement="Simulation module pilot",
        relationship_path="Cold outreach",
        pipeline_stage="QUALIFIED",  # Speculative qualification attempted by LLM
        next_action_step="Founder discovery",
        full_markdown_report="""# Commercial Opportunity Intelligence Report
## 1. Executive & Domain Intelligence
- **Current Role & Org**: Principal Researcher at QuantumAI Labs [E1] `[VERIFIED CURRENT]`
## 2. Opportunity Discovery & Classification
- **AI Opportunity Hypotheses**: `[AI HYPOTHESIS]` Quantum simulation sprint
## 4. Feasibility, Capability Matching & Commercial Scenarios
- Indicative pricing $15,000 (Hypothesis)
## 5. Tentative Proposal & Action Plan
- **Governance & Approval Gate**: `STATUS: PROPOSED_OPPORTUNITY (Awaiting Founder Validation)`
"""
    )

    with patch("app.services.evidence.ChatOpenAI") as mock_openai:
        mock_llm_instance = MagicMock()
        mock_openai.return_value = mock_llm_instance
        mock_structured_chain = MagicMock()
        mock_llm_instance.with_structured_output.return_value = mock_structured_chain
        with patch("langchain_core.runnables.base.RunnableSequence.ainvoke", new=AsyncMock(return_value=mock_snapshot)):
            await EvidenceEngine.process_run_and_extract_snapshot(db_session, run_id, cid)

    # Check generated SourceResult
    sr_stmt = select(SourceResult).where(SourceResult.source_id == "evidence_engine").order_by(SourceResult.retrieved_at.desc())
    all_srs = (await db_session.execute(sr_stmt)).scalars().all()
    saved_sr = next((s for s in all_srs if s.metadata_ and s.metadata_.get("contact_id") == cid), None)
    assert saved_sr is not None
    snap = saved_sr.extracted_data["executive_snapshot"]

    # Commercial Safeguard: MUST be normalized to PROPOSED, NEVER QUALIFIED or VALIDATED
    assert snap["pipeline_stage"] == "PROPOSED"
    assert snap["pipeline_stage"] != "QUALIFIED"
    assert snap["pipeline_stage"] != "VALIDATED"


@pytest.mark.asyncio
async def test_uncertain_identity_strictly_blocks_opportunity_validation(client, db_session):
    """
    Test 2: Uncertain identity (<70% confidence or UNCERTAIN match status)
    must strictly block human qualification/validation with HTTP 400.
    """
    cid = f"test-uncert-{uuid.uuid4().hex[:8]}"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Uncertain Lead",
        status=ContactStatus.READY
    )
    db_session.add(contact)

    # Low-confidence evidence (50%)
    ev = Evidence(
        id=f"ev-{uuid.uuid4().hex[:8]}",
        evidence_type=EvidenceType.SIGNAL,
        claim="Unverified web mention of Lead",
        source_id="news_public",
        confidence=50,
        related_entity_id=cid
    )
    db_session.add(ev)

    # SourceResult with low identity confidence (55% < 70%)
    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:8]}",
        source_id="evidence_engine",
        query=cid,
        status="SUCCESS",
        extracted_data={
            "executive_snapshot": {
                "name": "Uncertain Lead",
                "identity_confidence": 55,
                "provenance_status": "UNVERIFIED",
                "pipeline_stage": "UNCERTAIN_IDENTITY",
                "broad_business_problem": "Unknown challenges"
            }
        },
        metadata_={"contact_id": cid}
    )
    db_session.add(sr)
    await db_session.commit()

    # Attempt to validate via API as an authenticated founder
    headers = {"Authorization": "Bearer mock-token"}
    resp = await client.post(
        f"/api/v1/contacts/{cid}/opportunity/validate",
        json={
            "status": "VALIDATED",
            "review_notes": "Attempting to qualify lead prematurely"
        },
        headers=headers
    )

    # Must be blocked by identity gate with HTTP 400
    assert resp.status_code == 400
    detail = resp.json().get("detail", "")
    assert "below threshold" in detail or "unverified" in detail
    assert "70%" in detail


@pytest.mark.asyncio
async def test_authorized_founder_can_validate_opportunity_with_sufficient_identity(client, db_session):
    """
    Test 3: An authorized user with sufficient identity confidence (>=70%)
    can explicitly validate the opportunity. Reviewer and timestamp are recorded.
    """
    cid = f"test-val-{uuid.uuid4().hex[:8]}"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Marcus Vance",
        current_title="VP Architecture",
        current_company="CoreMesh",
        status=ContactStatus.READY
    )
    db_session.add(contact)

    ev_id = f"ev-{uuid.uuid4().hex[:8]}"
    ev = Evidence(
        id=ev_id,
        evidence_type=EvidenceType.FACT,
        claim="Corporate Page: VP Architecture at CoreMesh",
        source_id="company_web",
        confidence=85,
        related_entity_id=cid
    )
    db_session.add(ev)

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:8]}",
        source_id="evidence_engine",
        query=cid,
        status="SUCCESS",
        extracted_data={
            "executive_snapshot": {
                "name": "Marcus Vance",
                "identity_confidence": 85,
                "provenance_status": "VERIFIED CURRENT",
                "pipeline_stage": "PROPOSED",
                "smallest_solvable_problem": "Distributed mesh routing optimization",
                "ottobon_capability_match": "AI Applications",
                "cost_pricing_estimate": "$15,000 sprint (Assumption)",
                "estimated_effort_hours": "120 hours"
            }
        },
        metadata_={"contact_id": cid}
    )
    db_session.add(sr)
    await db_session.commit()

    # Founder validates the opportunity
    headers = {"Authorization": "Bearer mock-token"}
    resp = await client.post(
        f"/api/v1/contacts/{cid}/opportunity/validate",
        json={
            "status": "VALIDATED",
            "review_notes": "Validated delivery capability and verified domain need with architectural advisory team."
        },
        headers=headers
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["contact_id"] == cid
    assert data["status"] == "VALIDATED"
    assert data["reviewed_by"] == "1"  # User ID from auth token
    assert data["reviewed_at"] is not None
    assert "Validated delivery capability" in data["review_notes"]
    assert data["identity_gate_passed"] is True
    assert ev_id in data["supporting_evidence_ids"]

    # Subsequent Contact 360 lookup reflects validated state
    resp_360 = await client.get(f"/api/v1/contacts/{cid}/360", headers=headers)
    assert resp_360.status_code == 200
    data_360 = resp_360.json()
    assert data_360["commercialIntelligence"]["pipelineStage"] == "VALIDATED"
    assert data_360["commercialIntelligence"]["opportunityValidation"]["status"] == "VALIDATED"
    assert data_360["commercialIntelligence"]["opportunityValidation"]["reviewedBy"] == "1"


@pytest.mark.asyncio
async def test_cross_organization_validation_attempt_rejected(client, db_session):
    """
    Test 4: Validation requests across organizations are strictly rejected (HTTP 404).
    """
    other_cid = f"test-other-org-{uuid.uuid4().hex[:8]}"
    contact = Contact(
        id=other_cid,
        organization_id="org-foreign",  # Different organization
        full_name="Competitor Contact",
        status=ContactStatus.READY
    )
    db_session.add(contact)
    await db_session.commit()

    # User belongs to org-1
    headers = {"Authorization": "Bearer mock-token"}
    resp = await client.post(
        f"/api/v1/contacts/{other_cid}/opportunity/validate",
        json={
            "status": "VALIDATED",
            "review_notes": "Unauthorized validation attempt"
        },
        headers=headers
    )
    assert resp.status_code == 404
    assert "Contact not found" in resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_unauthenticated_validation_attempt_returns_401(client, db_session):
    """
    Test 5: Unauthenticated validation request returns 401.
    """
    resp = await client.post(
        "/api/v1/contacts/any-id/opportunity/validate",
        json={"status": "VALIDATED"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_founder_can_put_opportunity_on_hold_or_reject(client, db_session):
    """
    Test 6: Founders can review and decline (REJECTED) or defer (ON_HOLD) opportunities.
    """
    cid = f"test-hold-{uuid.uuid4().hex[:8]}"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Sarah Connor",
        status=ContactStatus.READY
    )
    db_session.add(contact)
    await db_session.commit()

    headers = {"Authorization": "Bearer mock-token"}

    # 1. Put ON_HOLD
    resp_hold = await client.post(
        f"/api/v1/contacts/{cid}/opportunity/validate",
        json={
            "status": "ON_HOLD",
            "review_notes": "Interesting domain, but client is undergoing leadership transition. Revisit next quarter."
        },
        headers=headers
    )
    assert resp_hold.status_code == 200
    assert resp_hold.json()["status"] == "ON_HOLD"

    # Verify Contact 360
    resp_360 = await client.get(f"/api/v1/contacts/{cid}/360", headers=headers)
    assert resp_360.json()["commercialIntelligence"]["pipelineStage"] == "ON_HOLD"

    # 2. Reject
    resp_rej = await client.post(
        f"/api/v1/contacts/{cid}/opportunity/validate",
        json={
            "status": "REJECTED",
            "review_notes": "Misaligned with current Ottobon product strategy."
        },
        headers=headers
    )
    assert resp_rej.status_code == 200
    assert resp_rej.json()["status"] == "REJECTED"

    resp_360_rej = await client.get(f"/api/v1/contacts/{cid}/360", headers=headers)
    assert resp_360_rej.json()["commercialIntelligence"]["pipelineStage"] == "REJECTED"


@pytest.mark.asyncio
async def test_unsupported_pricing_and_effort_framed_as_assumptions_not_facts(client, db_session):
    """
    Test 7: Commercial effort and pricing numbers are treated as hypotheses/assumptions,
    and missing information (rate card catalog, client budget authority) is explicitly preserved.
    """
    cid = f"test-assump-{uuid.uuid4().hex[:8]}"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Assumptions Lead",
        status=ContactStatus.READY
    )
    db_session.add(contact)
    await db_session.commit()

    headers = {"Authorization": "Bearer mock-token"}
    resp = await client.post(
        f"/api/v1/contacts/{cid}/opportunity/validate",
        json={
            "status": "PROPOSED",
            "review_notes": "Catalog review check"
        },
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()

    # Verify assumptions and missing info are populated
    assert len(data["assumptions"]) > 0
    assert any("rate card" in a.lower() or "hypotheses" in a.lower() or "pricing" in a.lower() for a in data["assumptions"])
    assert len(data["missing_information"]) > 0
    assert any("budget" in m.lower() or "authority" in m.lower() or "registry" in m.lower() for m in data["missing_information"])


@pytest.mark.asyncio
async def test_conflicting_evidence_remains_visible_alongside_opportunity(client, db_session):
    """
    Test 8: Conflicting claims (e.g. differing employers) remain visible to the reviewer
    and are not suppressed or flattened when opportunity intelligence is reviewed.
    """
    cid = f"test-conflict-{uuid.uuid4().hex[:8]}"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Conflict Lead",
        status=ContactStatus.READY
    )
    db_session.add(contact)

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:8]}",
        source_id="evidence_engine",
        query=cid,
        status="SUCCESS",
        extracted_data={
            "executive_snapshot": {
                "name": "Conflict Lead",
                "identity_confidence": 80,
                "pipeline_stage": "PROPOSED",
                "detected_conflicts": [
                    "Conflicting employer claims detected: 'Corp A' vs 'Corp B'"
                ]
            }
        },
        metadata_={"contact_id": cid}
    )
    db_session.add(sr)
    await db_session.commit()

    headers = {"Authorization": "Bearer mock-token"}
    resp = await client.get(f"/api/v1/contacts/{cid}/360", headers=headers)
    assert resp.status_code == 200
    ci = resp.json()["commercialIntelligence"]
    # Evidence engine snapshot must retain conflicts
    assert ci["pipelineStage"] == "PROPOSED"
