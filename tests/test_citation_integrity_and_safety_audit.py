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
from app.schemas.matching import SemanticProblemMatchRequest
from app.api.v1.endpoints.matching import semantic_match_connection, semantic_match_problem


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
        "proposed_first_engagement": "Exploratory alignment conversation.",
        "relationship_path": "Direct outreach to executive",
        "pipeline_stage": "PROPOSED",
        "next_action_step": "Founder discovery interview",
        "full_markdown_report": "# Commercial Opportunity Intelligence Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: Executive at Test Corp [E1] [VERIFIED CURRENT]\n- **Location**: New York, NY [E1]\n- **Proven Domain Expertise**: Enterprise leadership [E1]\n",
        "sources_used": []
    }
    defaults.update(kwargs)
    return ExecutiveSnapshot(**defaults)


# ==============================================================================
# 1. A valid citation supports an explicitly stated operational problem.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_1_valid_citation_explicit_operational_problem(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Sarah Chen", current_title="CTO", current_company="DataFlow Inc")

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="tech_blog",
        query="DataFlow Inc engineering challenges",
        entity_searched="DataFlow Inc",
        raw_reference="https://dataflow.io/blog/scaling-challenges-2026",
        status="SUCCESS",
        extracted_data={
            "text": "DataFlow Inc is experiencing severe database query latency and connection pool bottleneck in distributed architecture."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="Sarah Chen",
        current_role="CTO",
        current_organization="DataFlow Inc",
        broad_business_problem="Severe database query latency and connection pool bottleneck.",
        smallest_solvable_problem="PostgreSQL query latency and connection pool tuning.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=["E1"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E1]",
                evidence_id="E1",
                source_url="https://dataflow.io/blog/scaling-challenges-2026",
                supporting_passage="DataFlow Inc is experiencing severe database query latency and connection pool bottleneck in distributed architecture.",
                is_direct_problem_statement=True
            )
        ]
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(mock_snapshot)):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact
        )

    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert result["broad_business_problem"] == "Severe database query latency and connection pool bottleneck."
    assert "[E1]" in result["problem_evidence_references"]
    assert len(result["structured_problem_references"]) == 1
    assert result["structured_problem_references"][0]["supports_directly"] is True


# ==============================================================================
# 2. A fabricated citation key is rejected.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_2_fabricated_citation_key_rejected(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Marcus Vance", current_title="VP Engineering", current_company="Nexus Systems")

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="news",
        query="Nexus Systems Marcus Vance",
        entity_searched="Nexus Systems",
        raw_reference="https://nexus.com/about",
        status="SUCCESS",
        extracted_data={"text": "Marcus Vance joined Nexus Systems as VP Engineering."},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 90, "contact_id": cid}
    )

    # LLM hallucinates citation key [E999]
    mock_snapshot = make_test_snapshot(
        name="Marcus Vance",
        current_role="VP Engineering",
        current_organization="Nexus Systems",
        broad_business_problem="Critical production microservice outage.",
        smallest_solvable_problem="Microservice circuit breakers.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=["E999"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E999]",
                evidence_id="E999",
                source_url="https://fakenews.com/outage",
                supporting_passage="Production microservice outage.",
                is_direct_problem_statement=True
            )
        ]
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(mock_snapshot)):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact
        )

    # Fabricated key [E999] must be discarded, demoting status to NO_OBSERVED_PROBLEM
    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value
    assert result["broad_business_problem"] is None
    assert result["problem_evidence_references"] == []


# ==============================================================================
# 3. A valid citation key points to an unrelated passage.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_3_citation_points_to_unrelated_passage(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="David Miller", current_title="Chief Architect", current_company="Alpha Corp")

    # Source passage discusses office opening, completely unrelated to operational problem
    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="press_release",
        query="Alpha Corp office opening",
        entity_searched="Alpha Corp",
        raw_reference="https://alphacorp.com/news",
        status="SUCCESS",
        extracted_data={
            "text": "Alpha Corp opened a brand new office in Austin and welcomed local community members."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 90, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="David Miller",
        current_role="Chief Architect",
        current_organization="Alpha Corp",
        broad_business_problem="Severe backend latency and memory leaks.",
        smallest_solvable_problem="Memory profiling.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=["E1"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E1]",
                evidence_id="E1",
                source_url="https://alphacorp.com/news",
                supporting_passage="Alpha Corp opened a brand new office in Austin and welcomed local community members.",
                is_direct_problem_statement=False
            )
        ]
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(mock_snapshot)):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact
        )

    # Cannot retain EVIDENCE_GROUNDED because Austin office opening has no operational deficiency
    assert result["problem_epistemic_status"] != ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert result["problem_epistemic_status"] in [
        ProblemEpistemicStatus.SUPPORTED_INFERENCE.value,
        ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value
    ]


# ==============================================================================
# 4. A source belongs to a different contact or research run (uncertain identity).
# ==============================================================================
@pytest.mark.asyncio
async def test_case_4_cross_contact_or_uncertain_source_rejected(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Robert Taylor", current_title="VP Sales", current_company="Acme Corp")

    # Source result matched an ambiguous person or wrong organization
    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="external_leak",
        query="Robert Taylor Acme",
        entity_searched="Acme Corp",
        raw_reference="https://leak.com/acme-issues",
        status="SUCCESS",
        extracted_data={"text": "Acme Corp is experiencing massive delivery delays and billing errors."},
        metadata_={"identity_match_status": "UNCERTAIN", "identity_match_confidence": 30, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="Robert Taylor",
        current_role="VP Sales",
        current_organization="Acme Corp",
        broad_business_problem="Massive delivery delays and billing errors.",
        smallest_solvable_problem="Billing error audit.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=["E1"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E1]",
                evidence_id="E1",
                source_url="https://leak.com/acme-issues",
                supporting_passage="Acme Corp is experiencing massive delivery delays and billing errors.",
                is_direct_problem_statement=True
            )
        ]
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(mock_snapshot)):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact
        )

    # Uncertain identity citation is rejected; cannot retain EVIDENCE_GROUNDED
    assert result["problem_epistemic_status"] != ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value
    assert result["broad_business_problem"] is None


# ==============================================================================
# 5. A profile contains only a job title and company (biographical profile only).
# ==============================================================================
@pytest.mark.asyncio
async def test_case_5_profile_contains_only_job_title_and_company(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Jessica Wu", current_title="Director of Engineering", current_company="OmniTech")

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="linkedin_profile",
        query="Jessica Wu OmniTech",
        entity_searched="Jessica Wu",
        raw_reference="https://linkedin.com/in/jessicawu-omnitech",
        status="SUCCESS",
        extracted_data={
            "title": "Jessica Wu - Director of Engineering - OmniTech | LinkedIn",
            "text": "Jessica Wu is Director of Engineering at OmniTech in San Francisco, CA. Past roles include Senior Engineering Manager at Stripe."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="Jessica Wu",
        current_role="Director of Engineering",
        current_organization="OmniTech",
        broad_business_problem=None,
        smallest_solvable_problem=None,
        problem_epistemic_status=ProblemEpistemicStatus.NO_OBSERVED_PROBLEM
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(mock_snapshot)):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact
        )

    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value
    assert result["broad_business_problem"] is None
    assert result["smallest_solvable_problem"] is None


# ==============================================================================
# 6. A source lists technical skills but no operational deficiency.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_6_skills_list_not_inverted_into_operational_problem(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Kevin Patel", current_title="Staff SRE", current_company="CloudNine")

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="linkedin",
        query="Kevin Patel CloudNine",
        entity_searched="Kevin Patel",
        raw_reference="https://linkedin.com/in/kevinpatel-sre",
        status="SUCCESS",
        extracted_data={
            "text": "Kevin Patel is Staff SRE at CloudNine. Core competencies: Kubernetes, Terraform, Prometheus, Golang, AWS CDK."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    # Prompt tries to claim EVIDENCE_GROUNDED based on skills list
    mock_snapshot = make_test_snapshot(
        name="Kevin Patel",
        current_role="Staff SRE",
        current_organization="CloudNine",
        broad_business_problem="Kubernetes cluster configuration overhead.",
        smallest_solvable_problem="Terraform automation.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=["E1"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E1]",
                evidence_id="E1",
                source_url="https://linkedin.com/in/kevinpatel-sre",
                supporting_passage="Core competencies: Kubernetes, Terraform, Prometheus, Golang, AWS CDK.",
                is_direct_problem_statement=False
            )
        ]
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(mock_snapshot)):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact
        )

    # Must be demoted: Skills list is not an operational deficiency
    assert result["problem_epistemic_status"] != ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.SUPPORTED_INFERENCE.value


# ==============================================================================
# 7. A neutral expansion or hiring announcement is not treated as a problem.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_7_neutral_expansion_not_treated_as_problem(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Samantha Reed", current_title="VP Growth", current_company="ScalePay")

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="press",
        query="ScalePay Singapore expansion",
        entity_searched="ScalePay",
        raw_reference="https://scalepay.com/news/expansion",
        status="SUCCESS",
        extracted_data={
            "text": "ScalePay announced today that it has opened a brand new regional headquarters in Tokyo and hired 50 engineers."
        },
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="Samantha Reed",
        current_role="VP Growth",
        current_organization="ScalePay",
        broad_business_problem="Hiring 50 engineers causes communication friction.",
        smallest_solvable_problem="Engineering onboarding.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=["E1"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E1]",
                evidence_id="E1",
                source_url="https://scalepay.com/news/expansion",
                supporting_passage="ScalePay announced today that it has opened a brand new regional headquarters in Tokyo and hired 50 engineers.",
                is_direct_problem_statement=False
            )
        ]
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(mock_snapshot)):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact
        )

    # Neutral expansion cannot retain EVIDENCE_GROUNDED
    assert result["problem_epistemic_status"] != ProblemEpistemicStatus.EVIDENCE_GROUNDED.value


# ==============================================================================
# 8. An LLM-generated URL or evidence reference does not correspond to a persisted source.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_8_llm_hallucinated_reference_rejected(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Liam Fox", current_title="Lead Architect", current_company="ZetaTech")

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="company_website",
        query="ZetaTech Liam Fox",
        entity_searched="ZetaTech",
        raw_reference="https://zetatech.com/team",
        status="SUCCESS",
        extracted_data={"text": "Liam Fox is Lead Architect at ZetaTech."},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 90, "contact_id": cid}
    )

    # LLM references non-existent key "E42"
    mock_snapshot = make_test_snapshot(
        name="Liam Fox",
        current_role="Lead Architect",
        current_organization="ZetaTech",
        broad_business_problem="Database deadlocks under peak traffic.",
        smallest_solvable_problem="Deadlock mitigation.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=["E42"],
        structured_problem_references=[
            ProblemEvidenceReference(
                citation_key="[E42]",
                evidence_id="E42",
                source_url="https://hallucinated-source.com/leak",
                supporting_passage="Database deadlocks under peak traffic.",
                is_direct_problem_statement=True
            )
        ]
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(mock_snapshot)):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact
        )

    # Hallucinated reference E42 must not be retained; demoted to NO_OBSERVED_PROBLEM
    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value
    assert result["problem_evidence_references"] == []


# ==============================================================================
# 9. Conflicting relevant sources produce an appropriate status (CONFLICTING_EVIDENCE).
# ==============================================================================
@pytest.mark.asyncio
async def test_case_9_conflicting_sources_produce_conflicting_status(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Anita Roy", current_title="VP Engineering", current_company="HealthCorp")

    sr1 = SourceResult(
        id=f"sr-1-{uuid.uuid4().hex[:6]}",
        source_id="news_source",
        query="HealthCorp technology stack",
        entity_searched="HealthCorp",
        raw_reference="https://news.com/healthcorp-stack",
        status="SUCCESS",
        extracted_data={"text": "HealthCorp states all microservices have been modernized and running on AWS EKS."},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    sr2 = SourceResult(
        id=f"sr-2-{uuid.uuid4().hex[:6]}",
        source_id="internal_leak",
        query="HealthCorp technology stack outage",
        entity_searched="HealthCorp",
        raw_reference="https://leak.com/healthcorp-outage",
        status="SUCCESS",
        extracted_data={"text": "HealthCorp is stuck on a legacy on-premise monolith causing frequent system failures."},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    mock_snapshot = make_test_snapshot(
        name="Anita Roy",
        current_role="VP Engineering",
        current_organization="HealthCorp",
        broad_business_problem="Discrepancy in technology stack claims across reports.",
        smallest_solvable_problem=None,
        problem_epistemic_status=ProblemEpistemicStatus.CONFLICTING_EVIDENCE,
        problem_evidence_references=["E1", "E2"]
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(mock_snapshot)):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr1, sr2],
            contact=contact
        )

    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.CONFLICTING_EVIDENCE.value


# ==============================================================================
# 10. An unsupported problem cannot enter automated matching through a direct API request.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_10_unsupported_problem_cannot_match_via_direct_api():
    # Direct API request with unverified placeholder
    req = SemanticProblemMatchRequest(
        problem_text="No observed problem in available evidence.",
        connection_id="test-conn-1",
        connection_name="Test Executive"
    )

    res = await semantic_match_problem(req)

    assert res.matching_outcome == MatchingOutcome.INSUFFICIENT_INFORMATION
    assert res.suggested_status == "Problem Unverified"
    assert len(res.matches) == 0
    assert res.proposed_solution is None


# ==============================================================================
# 11. A legacy snapshot without epistemic status remains unverified.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_11_legacy_snapshot_without_epistemic_status_is_unverified(mock_db_session):
    cid = f"test-c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Legacy User", current_title="Manager", current_company="OldCo")

    # Legacy snapshot with NO problem_epistemic_status
    legacy_snapshot = {
        "name": "Legacy User",
        "current_role": "Manager",
        "current_organization": "OldCo",
        "broad_business_problem": "Needs automated payroll and timesheet management.",
        "smallest_solvable_problem": "Timesheet collection."
        # problem_epistemic_status is deliberately omitted
    }

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="evidence_engine",
        query="Legacy Extraction",
        status="SUCCESS",
        extracted_data={"executive_snapshot": legacy_snapshot},
        metadata_={"contact_id": cid}
    )

    class _MockScalars:
        def __init__(self, first_val, all_val):
            self._first = first_val
            self._all = all_val
        def first(self):
            return self._first
        def all(self):
            return self._all

    class _MockResult:
        def __init__(self, first_val, all_val):
            self._scalars = _MockScalars(first_val, all_val)
        def scalars(self):
            return self._scalars

    async def _mock_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt)
        if "FROM contacts" in stmt_str:
            return _MockResult(contact, [contact])
        elif "FROM source_results" in stmt_str:
            return _MockResult(sr, [sr])
        return _MockResult(None, [])

    mock_db_session.execute = _mock_execute

    match_res = await semantic_match_connection(contact_id=cid, db=mock_db_session)

    # Legacy record must NOT enter automated matching; must return Problem Unverified
    assert match_res.matching_outcome == MatchingOutcome.INSUFFICIENT_INFORMATION
    assert match_res.suggested_status == "Problem Unverified"
    assert len(match_res.matches) == 0


# ==============================================================================
# 12. Manual custom-problem matching still works.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_12_manual_custom_problem_matching_works():
    # Explicit custom problem for HR Tech (TalentOps)
    req = SemanticProblemMatchRequest(
        problem_text="Severe timesheet collection delays, manual payroll calculations, and contractor onboarding bottlenecks.",
        connection_name="HR Director",
        connection_company="TechStartup",
        connection_title="Head of People"
    )

    res = await semantic_match_problem(req)

    assert res.matching_outcome == MatchingOutcome.MATCH_FOUND
    assert any(m.product_id == "prod-talentops" for m in res.matches)
    assert "TalentOps" in res.suggested_status


# ==============================================================================
# 13. Null problem fields and missing evidence serialize without breaking the API.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_13_null_problem_fields_serialize_without_breaking():
    snapshot = make_test_snapshot(
        broad_business_problem=None,
        smallest_solvable_problem=None,
        problem_evidence_references=[],
        structured_problem_references=[]
    )

    dumped = snapshot.model_dump()
    assert dumped["broad_business_problem"] is None
    assert dumped["smallest_solvable_problem"] is None
    assert dumped["problem_evidence_references"] == []
    assert dumped["problem_epistemic_status"] == ProblemEpistemicStatus.NO_OBSERVED_PROBLEM


# ==============================================================================
# 14. A model-generated EVIDENCE_GROUNDED status is downgraded when programmatic validation fails.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_14_downgrade_when_citations_fail_programmatic_validation(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Rachel Green", current_title="Lead Architect", current_company="CloudCo")

    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="linkedin",
        query="Rachel Green CloudCo",
        entity_searched="Rachel Green",
        raw_reference="https://linkedin.com/in/rachelgreen",
        status="SUCCESS",
        extracted_data={"text": "Rachel Green is a software architect with expertise in microservices."},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95, "contact_id": cid}
    )

    # Model claims EVIDENCE_GROUNDED with an empty citation list
    mock_snapshot = make_test_snapshot(
        name="Rachel Green",
        current_role="Lead Architect",
        current_organization="CloudCo",
        broad_business_problem="Microservice communication latency.",
        smallest_solvable_problem="gRPC migration.",
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        problem_evidence_references=[]  # No valid references!
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(mock_snapshot)):
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact
        )

    # Programmatic verification must downgrade status from EVIDENCE_GROUNDED to NO_OBSERVED_PROBLEM
    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value
    assert result["broad_business_problem"] is None
    assert result["smallest_solvable_problem"] is None
