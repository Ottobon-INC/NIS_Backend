import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta
from langchain_core.runnables import RunnableLambda

from app.models.evidence import SourceResult, Evidence, EvidenceType, ProblemEpistemicStatus
from app.models.identity import Contact, ContactStatus
from app.schemas.business_signal import (
    SignalType,
    SignalClassification,
    SignalFreshness,
    BusinessSignal,
    SignalDiscoveryQuery,
)
from app.services.business_signal_discovery import (
    BusinessSignalDiscoveryService,
    BusinessSignalConfig,
)
from app.services.evidence import (
    EvidenceEngine,
    ExecutiveSnapshot,
    ProblemEvidenceReference,
)
from app.api.v1.endpoints.matching import semantic_match_connection
from app.schemas.matching import MatchingOutcome, SemanticProblemMatchRequest


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
    session.flush = AsyncMock()
    return session


def make_mock_structured_llm(snapshot_instance):
    mock_runnable = RunnableLambda(lambda x: snapshot_instance)
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_runnable
    return mock_llm


def make_test_snapshot(**kwargs):
    defaults = {
        "name": "Jane Doe",
        "current_role": "VP Engineering",
        "current_organization": "CloudScale Systems",
        "location": "San Francisco, CA",
        "provenance_status": "VERIFIED CURRENT",
        "domain_name": "Cloud Infrastructure",
        "proven_domain_expertise": "Expertise in distributed architecture",
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
        "proposed_first_engagement": "Exploratory technical consultation.",
        "relationship_path": "Direct outreach to VP",
        "pipeline_stage": "PROPOSED",
        "next_action_step": "Technical discovery interview",
        "full_markdown_report": "# Commercial Opportunity Intelligence Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: VP Engineering at CloudScale Systems [E1] [VERIFIED CURRENT]\n- **Location**: San Francisco, CA [E1]\n- **Proven Domain Expertise**: Cloud Infrastructure [E1]\n",
        "sources_used": []
    }
    defaults.update(kwargs)
    return ExecutiveSnapshot(**defaults)


# ==============================================================================
# TEST 1: An official source explicitly describes a target-specific operational problem.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_1_official_source_explicit_operational_problem(mock_db_session):
    raw_ref = "https://cloudscale.io/engineering/database-latency-incident"
    text = "CloudScale Systems post-mortem: We are struggling with severe database query latency and connection pool bottleneck across our payment clusters."

    signal = BusinessSignalDiscoveryService.evaluate_candidate_signal(
        raw_reference=raw_ref,
        raw_text=text,
        target_company="CloudScale Systems",
        target_domain="cloudscale.io",
        source_title="CloudScale Systems Incident Report: Query Latency"
    )

    assert signal.signal_type in [SignalType.OPERATIONAL_CHALLENGE, SignalType.SERVICE_DISRUPTION]
    assert signal.classification == SignalClassification.DIRECT_PROBLEM_EVIDENCE
    assert signal.explicitly_states_problem is True
    assert signal.entity_association_status == "MATCH_CONFIRMED"

    # Verify pipeline integration with EvidenceEngine
    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="business_signal_cloudscale.io",
        query="CloudScale Systems engineering bottleneck",
        entity_searched="CloudScale Systems",
        raw_reference=raw_ref,
        status="SUCCESS",
        extracted_data={"text": text},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95}
    )

    contact = Contact(id="c-1", full_name="Jane Doe", current_title="VP Engineering", current_company="CloudScale Systems")
    mock_snapshot = make_test_snapshot(
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        broad_business_problem="Severe database query latency and connection pool bottleneck",
        smallest_solvable_problem="Optimize connection pool configuration and query cache indexing",
        problem_evidence_references=["[E1]"],
        full_markdown_report="# Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: VP at CloudScale Systems [E1]\n- **Location**: San Francisco, CA [E1]\n- **Proven Domain Expertise**: Cloud [E1]\n"
    )

    with patch("app.services.evidence.ChatOpenAI") as mock_chat:
        mock_chat.return_value = make_mock_structured_llm(mock_snapshot)
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            enable_epistemic_verification=True
        )

    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert len(result["structured_problem_references"]) == 1
    assert result["structured_problem_references"][0]["supports_directly"] is True


# ==============================================================================
# TEST 2: A neutral expansion announcement is stored as context, not a confirmed problem.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_2_neutral_expansion_stored_as_context(mock_db_session):
    raw_ref = "https://cloudscale.io/press/london-expansion-2026"
    text = "CloudScale Systems announced today that it has opened a brand new regional headquarters in London, celebrating expansion into European markets."

    signal = BusinessSignalDiscoveryService.evaluate_candidate_signal(
        raw_reference=raw_ref,
        raw_text=text,
        target_company="CloudScale Systems",
        target_domain="cloudscale.io",
        source_title="CloudScale Systems Expands into Europe"
    )

    assert signal.signal_type == SignalType.CORPORATE_EXPANSION
    assert signal.classification == SignalClassification.CONTEXTUAL_SIGNAL
    assert signal.explicitly_states_problem is False

    # Pipeline integration: neutral expansion cannot produce EVIDENCE_GROUNDED
    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="press_wire",
        query="CloudScale Systems expansion",
        entity_searched="CloudScale Systems",
        raw_reference=raw_ref,
        status="SUCCESS",
        extracted_data={"text": text},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95}
    )

    contact = Contact(id="c-2", full_name="Jane Doe", current_title="VP Engineering", current_company="CloudScale Systems")
    mock_snapshot = make_test_snapshot(
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,  # Model attempts to hallucinate grounded status
        broad_business_problem="Scaling difficulties from geographic expansion",
        smallest_solvable_problem="Regional latency optimization",
        problem_evidence_references=["[E1]"],
        full_markdown_report="# Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: VP at CloudScale Systems [E1]\n- **Location**: San Francisco, CA [E1]\n- **Proven Domain Expertise**: Cloud [E1]\n"
    )

    with patch("app.services.evidence.ChatOpenAI") as mock_chat:
        mock_chat.return_value = make_mock_structured_llm(mock_snapshot)
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            enable_epistemic_verification=True
        )

    # Must be demoted because citation only provides neutral context
    assert result["problem_epistemic_status"] != ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.SUPPORTED_INFERENCE.value
    assert result["structured_problem_references"][0]["supports_directly"] is False


# ==============================================================================
# TEST 3: A public job posting is not inverted into an unsupported deficiency.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_3_job_posting_not_inverted_into_deficiency():
    raw_ref = "https://cloudscale.io/careers/senior-kubernetes-architect"
    text = "We are hiring senior infrastructure engineers. Open positions: Senior Architect. Seeking experienced talent proficient in Kubernetes clusters and Kafka."

    signal = BusinessSignalDiscoveryService.evaluate_candidate_signal(
        raw_reference=raw_ref,
        raw_text=text,
        target_company="CloudScale Systems",
        target_domain="cloudscale.io",
        source_title="Careers at CloudScale Systems: Senior Kubernetes Architect"
    )

    assert signal.signal_type == SignalType.HIRING_INITIATIVE
    assert signal.classification == SignalClassification.CONTEXTUAL_SIGNAL
    assert signal.explicitly_states_problem is False
    assert "job posting / hiring need" in signal.relevance_rationale.lower()
    assert "does NOT prove operational deficiency" in signal.relevance_rationale


# ==============================================================================
# TEST 4: A same-name company result is rejected when identity association fails.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_4_same_name_company_rejected_when_identity_fails():
    # Target is "CloudScale Systems" (cloudscale.io)
    # Result is an unrelated plumbing firm "Cloudscale Plumbing & Heating LLC"
    raw_ref = "https://cloudscaleplumbing.com/outage-report"
    text = "CloudScale Plumbing services experienced an outage in pump pressure for city district."

    signal = BusinessSignalDiscoveryService.evaluate_candidate_signal(
        raw_reference=raw_ref,
        raw_text=text,
        target_company="CloudScale Systems",
        target_domain="cloudscale.io",
        source_title="Cloudscale Plumbing Pressure Outage"
    )

    assert signal.entity_association_status in ["UNMATCHED", "AMBIGUOUS"]
    assert signal.classification == SignalClassification.UNRELIABLE_OR_MISATTRIBUTED
    assert signal.explicitly_states_problem is False


# ==============================================================================
# TEST 5: A stale signal is flagged appropriately.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_5_stale_signal_flagged_appropriately(mock_db_session):
    pub_date = datetime.now(timezone.utc) - timedelta(days=500)  # > 365 days
    raw_ref = "https://cloudscale.io/blog/archive-2024-outage"
    text = "CloudScale Systems incident report: Database query latency bottleneck caused outage."

    signal = BusinessSignalDiscoveryService.evaluate_candidate_signal(
        raw_reference=raw_ref,
        raw_text=text,
        target_company="CloudScale Systems",
        target_domain="cloudscale.io",
        publication_date=pub_date
    )

    assert signal.freshness_status == SignalFreshness.STALE
    assert signal.is_stale is True
    # Stale problem cannot be asserted as an active current problem
    assert signal.explicitly_states_problem is False
    assert "[STALE:" in signal.relevance_rationale

    # In EvidenceEngine, stale evidence cannot produce EVIDENCE_GROUNDED
    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="archive_blog",
        query="CloudScale historical incident",
        entity_searched="CloudScale Systems",
        raw_reference=raw_ref,
        status="SUCCESS",
        extracted_data={"text": text},
        metadata_={
            "identity_match_status": "CONFIRMED",
            "identity_match_confidence": 95,
            "is_stale": True,
            "observed_date": pub_date.strftime("%Y-%m-%d")
        }
    )

    contact = Contact(id="c-5", full_name="Jane Doe", current_title="VP Engineering", current_company="CloudScale Systems")
    mock_snapshot = make_test_snapshot(
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        broad_business_problem="Database query latency bottleneck",
        smallest_solvable_problem="Cache layer optimization",
        problem_evidence_references=["[E1]"],
        full_markdown_report="# Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: VP at CloudScale Systems [E1]\n- **Location**: San Francisco, CA [E1]\n- **Proven Domain Expertise**: Cloud [E1]\n"
    )

    with patch("app.services.evidence.ChatOpenAI") as mock_chat:
        mock_chat.return_value = make_mock_structured_llm(mock_snapshot)
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            enable_epistemic_verification=True
        )

    assert result["problem_epistemic_status"] != ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert result["structured_problem_references"][0]["is_stale"] is True
    assert result["structured_problem_references"][0]["supports_directly"] is False


# ==============================================================================
# TEST 6: Duplicate reports do not inflate the evidence count.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_6_duplicate_reports_do_not_inflate_evidence():
    text = "CloudScale Systems experienced an infrastructure outage due to network partition in US-East."
    sig1 = BusinessSignal(
        signal_id="sig-1",
        signal_type=SignalType.SERVICE_DISRUPTION,
        classification=SignalClassification.DIRECT_PROBLEM_EVIDENCE,
        factual_description="Outage in US-East",
        source_url="https://techcrunch.com/2026/03/cloudscale-outage?utm_source=rss",
        publisher_domain="techcrunch.com",
        quoted_passage=text,
        target_company="CloudScale Systems",
        relevance_rationale="Direct outage report"
    )
    sig2 = BusinessSignal(
        signal_id="sig-2",
        signal_type=SignalType.SERVICE_DISRUPTION,
        classification=SignalClassification.DIRECT_PROBLEM_EVIDENCE,
        factual_description="Outage in US-East",
        source_url="https://techcrunch.com/2026/03/cloudscale-outage?utm_source=twitter",  # Same canonical URL
        publisher_domain="techcrunch.com",
        quoted_passage=text,
        target_company="CloudScale Systems",
        relevance_rationale="Duplicate article via social link"
    )

    unique, duplicates = BusinessSignalDiscoveryService.deduplicate_signals([sig1, sig2])
    assert len(unique) == 1
    assert len(duplicates) == 1
    assert duplicates[0].signal_id == "sig-2"


# ==============================================================================
# TEST 7: Two independent sources remain distinguishable.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_7_independent_sources_remain_distinguishable():
    sig_official = BusinessSignal(
        signal_id="sig-1",
        signal_type=SignalType.SERVICE_DISRUPTION,
        classification=SignalClassification.DIRECT_PROBLEM_EVIDENCE,
        factual_description="Official post-mortem",
        source_url="https://status.cloudscale.io/incidents/march-1",
        publisher_domain="status.cloudscale.io",
        quoted_passage="Official incident log: Redis cache eviction caused service disruption on March 1.",
        target_company="CloudScale Systems",
        relevance_rationale="Official status log"
    )
    sig_media = BusinessSignal(
        signal_id="sig-2",
        signal_type=SignalType.SERVICE_DISRUPTION,
        classification=SignalClassification.DIRECT_PROBLEM_EVIDENCE,
        factual_description="Media investigative report",
        source_url="https://theregister.com/2026/03/cloudscale-architecture-breakdown",
        publisher_domain="theregister.com",
        quoted_passage="Journalistic investigation details architectural fragility and customer impact during recent downtime.",
        target_company="CloudScale Systems",
        relevance_rationale="Independent journalistic report"
    )

    unique, duplicates = BusinessSignalDiscoveryService.deduplicate_signals([sig_official, sig_media])
    assert len(unique) == 2
    assert len(duplicates) == 0


# ==============================================================================
# TEST 8: A missing publication date is not fabricated.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_8_missing_publication_date_not_fabricated():
    signal = BusinessSignalDiscoveryService.evaluate_candidate_signal(
        raw_reference="https://cloudscale.io/architecture/overview",
        raw_text="CloudScale Systems operates microservices across cloud regions.",
        target_company="CloudScale Systems",
        target_domain="cloudscale.io",
        publication_date=None  # Explicitly undated
    )

    assert signal.publication_date is None
    assert signal.freshness_status == SignalFreshness.UNDATED
    assert signal.is_stale is False


# ==============================================================================
# TEST 9: A source without sufficient problem evidence cannot produce EVIDENCE_GROUNDED.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_9_source_without_problem_evidence_cannot_produce_evidence_grounded(mock_db_session):
    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="general_web",
        query="CloudScale Systems company info",
        entity_searched="CloudScale Systems",
        raw_reference="https://cloudscale.io/about",
        status="SUCCESS",
        extracted_data={"text": "CloudScale Systems provides cloud orchestration software for enterprise IT teams."},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 90}
    )

    contact = Contact(id="c-9", full_name="Jane Doe", current_title="VP Engineering", current_company="CloudScale Systems")
    mock_snapshot = make_test_snapshot(
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,  # Model attempts ungrounded claim
        broad_business_problem="Enterprise software delivery latency",
        smallest_solvable_problem="CI/CD delivery acceleration",
        problem_evidence_references=["[E1]"],
        full_markdown_report="# Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: VP at CloudScale Systems [E1]\n- **Location**: San Francisco, CA [E1]\n- **Proven Domain Expertise**: Cloud [E1]\n"
    )

    with patch("app.services.evidence.ChatOpenAI") as mock_chat:
        mock_chat.return_value = make_mock_structured_llm(mock_snapshot)
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            enable_epistemic_verification=True
        )

    # Must be demoted to SUPPORTED_INFERENCE because text contains no problem keywords
    assert result["problem_epistemic_status"] != ProblemEpistemicStatus.EVIDENCE_GROUNDED.value
    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.SUPPORTED_INFERENCE.value


# ==============================================================================
# TEST 10: An unreliable or unverified source cannot bypass Phase 3 validation.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_10_unreliable_source_cannot_bypass_validation(mock_db_session):
    sr = SourceResult(
        id=f"sr-{uuid.uuid4().hex[:6]}",
        source_id="unverified_blog",
        query="CloudScale rumor",
        entity_searched="CloudScale Systems",
        raw_reference="https://random-forum.com/thread/123",
        status="SUCCESS",
        extracted_data={"text": "User posted: CloudScale Systems has a big latency problem and system outage."},
        metadata_={"identity_match_status": "UNCERTAIN", "identity_match_confidence": 30}  # Fails identity
    )

    contact = Contact(id="c-10", full_name="Jane Doe", current_title="VP Engineering", current_company="CloudScale Systems")
    mock_snapshot = make_test_snapshot(
        problem_epistemic_status=ProblemEpistemicStatus.EVIDENCE_GROUNDED,
        broad_business_problem="Latency problem and system outage",
        smallest_solvable_problem="Outage remediation",
        problem_evidence_references=["[E1]"],
        full_markdown_report="# Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: VP at CloudScale Systems [UNVERIFIED]\n- **Location**: San Francisco, CA [UNVERIFIED]\n- **Proven Domain Expertise**: Cloud [UNVERIFIED]\n"
    )

    with patch("app.services.evidence.ChatOpenAI") as mock_chat:
        mock_chat.return_value = make_mock_structured_llm(mock_snapshot)
        result = await EvidenceEngine.extract_evidence(
            db=mock_db_session,
            source_results=[sr],
            contact=contact,
            enable_epistemic_verification=True
        )

    # Citation rejected due to UNCERTAIN identity match -> 0 valid citations -> NO_OBSERVED_PROBLEM
    assert result["problem_epistemic_status"] == ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value
    assert result["problem_evidence_references"] == []


# ==============================================================================
# TEST 11: A direct evidence-backed problem can proceed to the existing matching pipeline.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_11_direct_evidence_proceeds_to_matching(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Jane Doe", current_title="VP Engineering", current_company="CloudScale Systems")

    grounded_snapshot = {
        "problem_epistemic_status": ProblemEpistemicStatus.EVIDENCE_GROUNDED.value,
        "broad_business_problem": "Severe timesheet collection delays, manual payroll calculations, and contractor onboarding bottlenecks.",
        "smallest_solvable_problem": "Automated payroll preparation and onboarding workflow sprint",
        "problem_evidence_references": ["[E1]"],
        "structured_problem_references": [{
            "citation_key": "[E1]",
            "source_url": "https://cloudscale.io/postmortem",
            "supporting_passage": "Audit: severe timesheet collection delays, manual payroll calculations, and contractor onboarding bottlenecks.",
            "publication_date": "2026-02-15",
            "supports_directly": True
        }]
    }

    sr = SourceResult(
        id="sr-1",
        source_id="evidence_engine",
        status="SUCCESS",
        extracted_data={"executive_snapshot": grounded_snapshot},
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

    match_response = await semantic_match_connection(contact_id=cid, db=mock_db_session)
    assert match_response.matching_outcome == MatchingOutcome.MATCH_FOUND
    assert len(match_response.matches) > 0


# ==============================================================================
# TEST 12: No-observed-problem and legacy-snapshot safeguards remain intact.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_12_no_problem_and_legacy_safeguards_intact(mock_db_session):
    cid = f"c-{uuid.uuid4().hex[:6]}"
    contact = Contact(id=cid, full_name="Jane Doe", current_title="VP Engineering", current_company="CloudScale Systems")

    # 1. NO_OBSERVED_PROBLEM snapshot
    no_prob_snapshot = {
        "problem_epistemic_status": ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value,
        "broad_business_problem": None,
        "smallest_solvable_problem": None,
        "problem_evidence_references": []
    }

    sr_no_prob = SourceResult(
        id="sr-no-prob",
        source_id="evidence_engine",
        status="SUCCESS",
        extracted_data={"executive_snapshot": no_prob_snapshot},
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

    async def _mock_execute_no_prob(stmt, *args, **kwargs):
        stmt_str = str(stmt)
        if "FROM contacts" in stmt_str:
            return _MockResult(contact, [contact])
        elif "FROM source_results" in stmt_str:
            return _MockResult(sr_no_prob, [sr_no_prob])
        return _MockResult(None, [])

    mock_db_session.execute = _mock_execute_no_prob

    res_no_prob = await semantic_match_connection(contact_id=cid, db=mock_db_session)
    assert res_no_prob.matching_outcome == MatchingOutcome.INSUFFICIENT_INFORMATION
    assert len(res_no_prob.matches) == 0

    # 2. Legacy unverified snapshot without epistemic status
    legacy_snapshot = {
        "broad_business_problem": "Legacy ungrounded problem hypothesis",
        "smallest_solvable_problem": "Legacy solution"
    }

    sr_legacy = SourceResult(
        id="sr-legacy",
        source_id="evidence_engine",
        status="SUCCESS",
        extracted_data={"executive_snapshot": legacy_snapshot},
        metadata_={"contact_id": cid}
    )

    async def _mock_execute_legacy(stmt, *args, **kwargs):
        stmt_str = str(stmt)
        if "FROM contacts" in stmt_str:
            return _MockResult(contact, [contact])
        elif "FROM source_results" in stmt_str:
            return _MockResult(sr_legacy, [sr_legacy])
        return _MockResult(None, [])

    mock_db_session.execute = _mock_execute_legacy

    res_legacy = await semantic_match_connection(contact_id=cid, db=mock_db_session)
    assert res_legacy.matching_outcome == MatchingOutcome.INSUFFICIENT_INFORMATION
    assert len(res_legacy.matches) == 0


# ==============================================================================
# TEST 13: Provider failures or empty search results do not create placeholder problems.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_13_empty_search_does_not_create_placeholder_problems(mock_db_session):
    contact = Contact(id="c-13", full_name="Jane Doe", current_title="VP Engineering", current_company="CloudScale Systems")

    # Empty source results list
    result = await EvidenceEngine.extract_evidence(
        db=mock_db_session,
        source_results=[],
        contact=contact,
        enable_epistemic_verification=True
    )

    assert result["problem_epistemic_status"] in [
        ProblemEpistemicStatus.NO_OBSERVED_PROBLEM.value,
        ProblemEpistemicStatus.INSUFFICIENT_EVIDENCE.value
    ]
    assert result["broad_business_problem"] is None
    assert result["smallest_solvable_problem"] is None
    assert result["problem_evidence_references"] == []


# ==============================================================================
# TEST 14: Repeated research runs do not generate duplicate records unnecessarily.
# ==============================================================================
@pytest.mark.asyncio
async def test_case_14_repeated_research_runs_do_not_duplicate_records(mock_db_session):
    contact_id = "c-14"
    signal = BusinessSignal(
        signal_id="sig-repeat",
        signal_type=SignalType.OPERATIONAL_CHALLENGE,
        classification=SignalClassification.DIRECT_PROBLEM_EVIDENCE,
        factual_description="Database latency bottleneck",
        source_url="https://cloudscale.io/engineering/db-latency",
        publisher_domain="cloudscale.io",
        quoted_passage="CloudScale Systems experiencing database latency bottleneck.",
        target_company="CloudScale Systems",
        relevance_rationale="Direct incident log",
        explicitly_states_problem=True
    )

    # First run: empty existing refs in DB
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = []
    persisted_first = await BusinessSignalDiscoveryService.persist_signals_to_pipeline(
        db=mock_db_session,
        signals=[signal],
        contact_id=contact_id
    )
    assert len(persisted_first) == 1

    # Second run: DB already contains the normalized reference
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = [
        "https://cloudscale.io/engineering/db-latency"
    ]
    persisted_second = await BusinessSignalDiscoveryService.persist_signals_to_pipeline(
        db=mock_db_session,
        signals=[signal],
        contact_id=contact_id
    )
    # Deduplicated, no new evidence records created
    assert len(persisted_second) == 0
