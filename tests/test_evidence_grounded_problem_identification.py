import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
from langchain_core.runnables import RunnableLambda

from app.models.evidence import SourceResult, Evidence, EvidenceType, ProblemEpistemicStatus
from app.models.identity import Contact, ContactStatus
from app.models.orchestration import ResearchRun
from app.services.evidence import (
    EvidenceEngine,
    ExecutiveSnapshot,
    ProblemEvidenceReference
)
from app.services.semantic_product_matcher import (
    SemanticProductMatcherService,
    MatchingOutcome
)
from app.api.v1.endpoints.matching import semantic_match_connection


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    result_mock.scalars.return_value.first.return_value = None
    session.execute.return_value = result_mock
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


def make_mock_structured_llm(snapshot_instance):
    mock_runnable = RunnableLambda(lambda x: snapshot_instance)
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_runnable
    return mock_llm


def make_test_snapshot(**kwargs):
    defaults = {
        "name": "Test Person",
        "current_role": "Executive",
        "current_organization": "Test Corp",
        "location": "New York, NY",
        "provenance_status": "VERIFIED CURRENT",
        "domain_name": "Enterprise Operations",
        "proven_domain_expertise": "Extensive enterprise leadership track record",
        "customer_knowledge_level": "High domain knowledge",
        "is_domain_sme": "Direct Practitioner",
        "operating_in_own_domain": True,
        "opportunity_category": "Small Service Engagement",
        "opportunity_nature": "Direct",
        "problem_epistemic_status": ProblemEpistemicStatus.NO_OBSERVED_PROBLEM,
        "broad_business_problem": None,
        "smallest_solvable_problem": None,
        "problem_evidence_references": [],
        "structured_problem_references": [],
        "why_now": None,
        "ottobon_capability_match": None,
        "delivery_risk_level": "LOW",
        "estimated_effort_hours": None,
        "cost_pricing_estimate": None,
        "proposed_first_engagement": "Advisory discovery discussion",
        "relationship_path": "Direct contact",
        "pipeline_stage": "PROPOSED",
        "next_action_step": "Founder review",
        "full_markdown_report": "# Test Intelligence Report\n\n- Role: Executive [E1]\n"
    }
    defaults.update(kwargs)
    return ExecutiveSnapshot(**defaults)


@pytest.mark.asyncio
async def test_1_biographical_profile_only_returns_no_observed_problem(mock_db_session):
    """
    Test 1: A profile containing only a job title, company and location returns
    NO_OBSERVED_PROBLEM or INSUFFICIENT_EVIDENCE, with null problem fields.
    """
    cid = f"test-c-{uuid.uuid4().hex[:6]}"
    contact = Contact(
        id=cid,
        full_name="Sarah Jenkins",
        current_title="Director of Operations",
        current_company="Acme Logistics",
        location="Austin, Texas"
    )

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="web_research",
        query="Sarah Jenkins Acme Logistics",
        entity_searched="Sarah Jenkins",
        raw_reference="https://acmelogistics.com/team/sarah",
        status="SUCCESS",
        extracted_data={
            "title": "Sarah Jenkins - Acme Logistics",
            "text": "Sarah Jenkins is the Director of Operations at Acme Logistics in Austin, Texas."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="Sarah Jenkins",
        current_role="Director of Operations",
        current_organization="Acme Logistics",
        location="Austin, Texas",
        broad_business_problem=None,
        smallest_solvable_problem=None,
        problem_epistemic_status=ProblemEpistemicStatus.NO_OBSERVED_PROBLEM,
        structured_problem_references=[]
    )

    mock_llm = make_mock_structured_llm(mock_snapshot)

    with patch("app.services.evidence.ChatOpenAI", return_value=mock_llm):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            target_person="Sarah Jenkins",
            target_company="Acme Logistics"
        )

    assert result["broad_business_problem"] is None
    assert result["smallest_solvable_problem"] is None
    assert result["problem_epistemic_status"] in [
        ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value,
        ProblemEpistemicStatus.INSUFFICIENT_EVIDENCE.value
    ]
    assert len(result.get("structured_problem_references", [])) == 0


@pytest.mark.asyncio
async def test_2_technical_skills_do_not_generate_deficiency_claim(mock_db_session):
    """
    Test 2: A profile containing only technical skills does not generate an infrastructure-deficiency claim.
    If the LLM tries to invent one without evidence passage, the epistemic verifier nullifies it.
    """
    cid = f"test-c-{uuid.uuid4().hex[:6]}"
    contact = Contact(
        id=cid,
        full_name="Alex Rivera",
        current_title="Principal Engineer",
        current_company="CloudScale Systems"
    )

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="linkedin_profile",
        query="Alex Rivera CloudScale",
        entity_searched="Alex Rivera",
        raw_reference="https://linkedin.com/in/alexrivera-test",
        status="SUCCESS",
        extracted_data={
            "title": "Alex Rivera - LinkedIn",
            "text": "Alex Rivera is a Principal Engineer proficient in Kubernetes, Go, Kafka, PostgreSQL, and distributed architecture."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    # LLM hallucinates an operational problem based purely on listed skills
    mock_snapshot = make_test_snapshot(
        name="Alex Rivera",
        current_role="Principal Engineer",
        current_organization="CloudScale Systems",
        broad_business_problem="Struggling with Kubernetes cluster scalability and Kafka throughput bottlenecks.",
        smallest_solvable_problem="Kubernetes cluster optimization.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=["E1"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E1]",
                evidence_id="E1",
                source_url="https://linkedin.com/in/alexrivera-test",
                supporting_passage="Alex Rivera is a Principal Engineer proficient in Kubernetes, Go, Kafka, PostgreSQL, and distributed architecture.",
                is_direct_problem_statement=False
            )
        ]
    )

    mock_llm = make_mock_structured_llm(mock_snapshot)

    with patch("app.services.evidence.ChatOpenAI", return_value=mock_llm):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            target_person="Alex Rivera",
            target_company="CloudScale Systems"
        )

    # Epistemic verifier must demote or nullify because passage states skills, not an operational deficit
    assert result["problem_epistemic_status"] != ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert result["broad_business_problem"] is None or result["problem_epistemic_status"] == ProblemEpistemicStatus.SUPPORTED_INFERENCE.value


@pytest.mark.asyncio
async def test_3_neutral_company_expansion_is_not_operational_problem(mock_db_session):
    """
    Test 3: A neutral company expansion announcement does not automatically become an operational problem.
    """
    cid = f"test-c-{uuid.uuid4().hex[:6]}"
    contact = Contact(
        id=cid,
        full_name="Elena Rostova",
        current_title="VP of Expansion",
        current_company="FinTech Global"
    )

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="press_release",
        query="FinTech Global Singapore expansion",
        entity_searched="FinTech Global",
        raw_reference="https://fintechglobal.com/news/expansion-singapore",
        status="SUCCESS",
        extracted_data={
            "title": "FinTech Global Expands to Singapore",
            "text": "FinTech Global announced today that it has opened a brand new regional headquarters in Singapore and hired 50 engineers."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="Elena Rostova",
        current_role="VP of Expansion",
        current_organization="FinTech Global",
        broad_business_problem=None,
        smallest_solvable_problem=None,
        problem_epistemic_status=ProblemEpistemicStatus.NO_OBSERVED_PROBLEM,
        why_now="Opening Singapore regional headquarters."
    )

    mock_llm = make_mock_structured_llm(mock_snapshot)

    with patch("app.services.evidence.ChatOpenAI", return_value=mock_llm):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            target_person="Elena Rostova",
            target_company="FinTech Global"
        )

    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value
    assert result["broad_business_problem"] is None
    assert result["smallest_solvable_problem"] is None


@pytest.mark.asyncio
async def test_4_explicit_source_backed_problem_extracted_with_references(mock_db_session):
    """
    Test 4: An explicit, source-backed operational problem can be extracted with correct evidence references.
    """
    cid = f"test-c-{uuid.uuid4().hex[:6]}"
    contact = Contact(
        id=cid,
        full_name="Marcus Vance",
        current_title="VP Engineering",
        current_company="HealthData Inc"
    )

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="engineering_blog",
        query="Marcus Vance database bottlenecks",
        entity_searched="Marcus Vance",
        raw_reference="https://healthdata.io/blog/scaling-struggles",
        status="SUCCESS",
        extracted_data={
            "title": "Our Migration Bottlenecks",
            "text": "We are facing severe database latency bottlenecks during peak ingestion hours, causing query timeouts and slowing down patient record retrieval."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="Marcus Vance",
        current_role="VP Engineering",
        current_organization="HealthData Inc",
        broad_business_problem="Severe database latency bottlenecks during peak ingestion hours causing query timeouts.",
        smallest_solvable_problem="Resolve peak-hour database ingestion timeouts.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=["E1"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E1]",
                evidence_id="E1",
                source_url="https://healthdata.io/blog/scaling-struggles",
                supporting_passage="We are facing severe database latency bottlenecks during peak ingestion hours, causing query timeouts and slowing down patient record retrieval.",
                is_direct_problem_statement=True
            )
        ]
    )

    mock_llm = make_mock_structured_llm(mock_snapshot)

    with patch("app.services.evidence.ChatOpenAI", return_value=mock_llm):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            target_person="Marcus Vance",
            target_company="HealthData Inc"
        )

    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert result["broad_business_problem"] is not None
    assert "database latency" in result["broad_business_problem"].lower()
    assert len(result.get("structured_problem_references", [])) >= 1
    assert result["structured_problem_references"][0]["supports_directly"] is True


@pytest.mark.asyncio
async def test_5_indirect_signal_classified_as_supported_inference(mock_db_session):
    """
    Test 5: An indirect but relevant signal is classified as an inference, not a direct fact.
    """
    cid = f"test-c-{uuid.uuid4().hex[:6]}"
    contact = Contact(
        id=cid,
        full_name="Rachel Green",
        current_title="Head of People",
        current_company="HyperGrowth AI"
    )

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="job_board",
        query="HyperGrowth AI hiring HR",
        entity_searched="HyperGrowth AI",
        raw_reference="https://hypergrowth.ai/careers",
        status="SUCCESS",
        extracted_data={
            "title": "Careers at HyperGrowth AI",
            "text": "HyperGrowth AI has opened 15 urgent vacancies for HR Operations Coordinators and Payroll Specialists across 4 continents."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="Rachel Green",
        current_role="Head of People",
        current_organization="HyperGrowth AI",
        broad_business_problem="Multinational onboarding overhead and distributed payroll coordination friction.",
        smallest_solvable_problem="Automated onboarding workflow coordination.",
        problem_epistemic_status=ProblemEpistemicStatus.SUPPORTED_INFERENCE,
        problem_evidence_references=["E1"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E1]",
                evidence_id="E1",
                source_url="https://hypergrowth.ai/careers",
                supporting_passage="HyperGrowth AI has opened 15 urgent vacancies for HR Operations Coordinators and Payroll Specialists across 4 continents.",
                is_direct_problem_statement=False
            )
        ]
    )

    mock_llm = make_mock_structured_llm(mock_snapshot)

    with patch("app.services.evidence.ChatOpenAI", return_value=mock_llm):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            target_person="Rachel Green",
            target_company="HyperGrowth AI"
        )

    # Indirect signal should remain SUPPORTED_INFERENCE, not EVIDENCE_GROUNDED
    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.SUPPORTED_INFERENCE.value
    assert result["structured_problem_references"][0]["supports_directly"] is False


@pytest.mark.asyncio
async def test_6_invented_evidence_id_is_rejected(mock_db_session):
    """
    Test 6: An invented evidence ID is rejected and prevents EVIDENCE_GROUNDED assignment.
    """
    cid = f"test-c-{uuid.uuid4().hex[:6]}"
    contact = Contact(
        id=cid,
        full_name="Thomas Wright",
        current_title="CTO",
        current_company="Nexus Financial"
    )

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="nexus_about",
        query="Thomas Wright Nexus",
        entity_searched="Thomas Wright",
        raw_reference="https://nexusfin.com/about",
        status="SUCCESS",
        extracted_data={
            "title": "About Nexus Financial",
            "text": "Nexus Financial provides institutional portfolio analytics."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    # LLM hallucinates an evidence ID E99 that does not exist in the structured evidence context (only E1 exists)
    mock_snapshot = make_test_snapshot(
        name="Thomas Wright",
        current_role="CTO",
        current_organization="Nexus Financial",
        broad_business_problem="Severe payment gateway downtime causing customer churn.",
        smallest_solvable_problem="Payment gateway high availability.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=["E99"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E99]",
                evidence_id="E99",
                source_url="https://fabricated-source.com/outage",
                supporting_passage="Fabricated passage regarding payment gateway downtime.",
                is_direct_problem_statement=True
            )
        ]
    )

    mock_llm = make_mock_structured_llm(mock_snapshot)

    with patch("app.services.evidence.ChatOpenAI", return_value=mock_llm):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            target_person="Thomas Wright",
            target_company="Nexus Financial"
        )

    # The epistemic validation filter must reject the fabricated ID E99 and downgrade to NO_OBSERVED_PROBLEM
    assert result["problem_epistemic_status"] != ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert result["broad_business_problem"] is None


@pytest.mark.asyncio
async def test_7_contradictory_relevant_evidence_produces_conflict_status(mock_db_session):
    """
    Test 7: Contradictory relevant evidence produces an appropriate conflict status.
    """
    cid = f"test-c-{uuid.uuid4().hex[:6]}"
    contact = Contact(
        id=cid,
        full_name="David Sterling",
        current_title="VP Operations",
        current_company="RetailLogix"
    )

    sr1 = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="news_article",
        query="RetailLogix warehouse sync failure",
        entity_searched="RetailLogix",
        raw_reference="https://techinsider.com/retaillogix-outage",
        status="SUCCESS",
        extracted_data={
            "title": "RetailLogix Warehouse Bottlenecks",
            "text": "RetailLogix confirmed severe warehouse inventory sync failure leading to order backlogs."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )
    sr2 = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="company_statement",
        query="RetailLogix official statement",
        entity_searched="RetailLogix",
        raw_reference="https://retaillogix.com/statement",
        status="SUCCESS",
        extracted_data={
            "title": "Official Statement",
            "text": "RetailLogix denies all claims of warehouse sync issues; systems are operating at 99.99% uptime with zero backlogs."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="David Sterling",
        current_role="VP Operations",
        current_organization="RetailLogix",
        broad_business_problem="Disputed inventory sync failure vs 99.99% operational uptime claims.",
        smallest_solvable_problem=None,
        problem_epistemic_status=ProblemEpistemicStatus.CONFLICTING_EVIDENCE,
        problem_evidence_references=["E1", "E2"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E1]",
                evidence_id="E1",
                source_url="https://techinsider.com/retaillogix-outage",
                supporting_passage="RetailLogix confirmed severe warehouse inventory sync failure.",
                is_direct_problem_statement=True
            ),
            ProblemEvidenceReference(
                citation_key="[E2]",
                evidence_id="E2",
                source_url="https://retaillogix.com/statement",
                supporting_passage="RetailLogix denies all claims of warehouse sync issues.",
                is_direct_problem_statement=False
            )
        ]
    )

    mock_llm = make_mock_structured_llm(mock_snapshot)

    with patch("app.services.evidence.ChatOpenAI", return_value=mock_llm):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr1, sr2],
            contact=contact,
            target_person="David Sterling",
            target_company="RetailLogix"
        )

    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.CONFLICTING_EVIDENCE.value


@pytest.mark.asyncio
async def test_8_identity_verified_with_no_problem_gets_no_product_match(mock_db_session):
    """
    Test 8: An identity-verified profile with no problem evidence does not receive a definitive product match.
    """
    cid = f"test-c-{uuid.uuid4().hex[:6]}"
    contact = Contact(
        id=cid,
        full_name="Samantha Cole",
        current_title="Partner",
        current_company="Apex Advisory Partners"
    )

    snapshot_data = {
        "name": "Samantha Cole",
        "current_role": "Partner",
        "current_organization": "Apex Advisory Partners",
        "identity_confidence": 100,
        "provenance_status": "VERIFIED",
        "problem_epistemic_status": "NO_OBSERVED_PROBLEM",
        "broad_business_problem": None,
        "smallest_solvable_problem": None
    }

    sr = SourceResult(
        id=f"sr-ee-{uuid.uuid4().hex[:6]}",
        source_id="evidence_engine",
        entity_searched="Samantha Cole",
        extracted_data={"executive_snapshot": snapshot_data},
        metadata_={"contact_id": cid},
        retrieved_at=datetime.now(timezone.utc)
    )

    scalars_mock = MagicMock()
    scalars_mock.first.side_effect = [None, contact]  # run is None, contact is contact
    scalars_mock.all.side_effect = [[sr]]  # srs list
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_db_session.execute.return_value = result_mock

    resp = await semantic_match_connection(
        contact_id=cid,
        db=mock_db_session
    )

    # Must NOT produce a definitive product match (MATCH_FOUND)
    assert resp.matching_outcome in [
        MatchingOutcome.INSUFFICIENT_INFORMATION,
        MatchingOutcome.NO_MATCH_FOUND
    ]
    assert len(resp.matches) == 0
    assert resp.suggested_status == "Problem Unverified"


@pytest.mark.asyncio
async def test_9_legacy_snapshot_without_epistemic_status_is_not_verified(mock_db_session):
    """
    Test 9: A legacy snapshot without problem epistemic status is not automatically considered verified.
    """
    cid = f"test-c-{uuid.uuid4().hex[:6]}"
    contact = Contact(
        id=cid,
        full_name="Robert Lang",
        current_title="Director of Engineering",
        current_company="Legacy Corp"
    )

    # Legacy snapshot has problem text but NO problem_epistemic_status field
    legacy_snapshot = {
        "name": "Robert Lang",
        "current_role": "Director of Engineering",
        "current_organization": "Legacy Corp",
        "broad_business_problem": "Legacy software scaling challenges.",
        "smallest_solvable_problem": "Legacy refactor."
        # Missing problem_epistemic_status!
    }

    sr = SourceResult(
        id=f"sr-ee-{uuid.uuid4().hex[:6]}",
        source_id="evidence_engine",
        entity_searched="Robert Lang",
        extracted_data={"executive_snapshot": legacy_snapshot},
        metadata_={"contact_id": cid},
        retrieved_at=datetime.now(timezone.utc)
    )

    scalars_mock = MagicMock()
    scalars_mock.first.side_effect = [None, contact]
    scalars_mock.all.side_effect = [[sr]]
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_db_session.execute.return_value = result_mock

    resp = await semantic_match_connection(
        contact_id=cid,
        db=mock_db_session
    )

    # Must NOT be treated as verified, therefore matching_outcome must not be MATCH_FOUND
    assert resp.matching_outcome != MatchingOutcome.MATCH_FOUND
    assert len(resp.matches) == 0
    assert resp.suggested_status == "Problem Unverified"


@pytest.mark.asyncio
async def test_10_null_problem_fields_serialize_without_breaking_api():
    """
    Test 10: Null problem fields serialize and render without breaking the API contract.
    """
    snapshot = make_test_snapshot(
        name="Clara Oswald",
        current_role="Research Fellow",
        current_organization="St John's College",
        broad_business_problem=None,
        smallest_solvable_problem=None,
        why_now=None,
        ottobon_capability_match=None,
        cost_pricing_estimate=None,
        estimated_effort_hours=None,
        problem_epistemic_status=ProblemEpistemicStatus.NO_OBSERVED_PROBLEM,
        structured_problem_references=[]
    )

    # Pydantic serialization test
    dumped = snapshot.model_dump()
    assert dumped["broad_business_problem"] is None
    assert dumped["smallest_solvable_problem"] is None
    assert dumped["problem_epistemic_status"] == "NO_OBSERVED_PROBLEM"
    assert dumped["structured_problem_references"] == []

    # SemanticProductMatcherService should cleanly handle null problem_text
    response = await SemanticProductMatcherService.match_connection_problem(
        problem_text=dumped["broad_business_problem"] or "",
        connection_name=snapshot.name,
        connection_company=snapshot.current_organization,
        connection_title=snapshot.current_role
    )

    assert response.matching_outcome == MatchingOutcome.INSUFFICIENT_INFORMATION
    assert response.matches == []
    assert response.suggested_status == "Problem Unverified"


@pytest.mark.asyncio
async def test_11_manually_entered_custom_problem_works():
    """
    Test 11: Manually entered custom problems still work through the existing workflow.
    """
    # A user explicitly enters a concrete problem statement in the UI edit box
    custom_problem = "Our HR team is overwhelmed with manual employee onboarding, delayed leave approvals, and payroll processing errors."
    
    response = await SemanticProductMatcherService.match_connection_problem(
        problem_text=custom_problem,
        connection_name="Manual Reviewer",
        connection_company="FastScale Tech",
        connection_title="COO"
    )

    # Matches TalentOps from our authentic catalog
    assert response.matching_outcome == MatchingOutcome.MATCH_FOUND
    assert len(response.matches) >= 1
    assert any(m.product_id == "prod-talentops" or "talentops" in m.product_name.lower() for m in response.matches)
