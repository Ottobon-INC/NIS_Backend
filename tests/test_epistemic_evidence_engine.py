import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from app.models.evidence import SourceResult, Evidence, EvidenceType
from app.models.identity import Contact, ContactStatus
from app.models.orchestration import ResearchRun, ResearchTask, TaskStatus
from app.services.evidence import (
    EvidenceEngine,
    ExecutiveSnapshot,
    detect_conflicts,
    build_structured_evidence_context,
    validate_report_citations
)
from app.services.research.entity_resolver import (
    EntityResolver,
    TargetExecutiveAnchor,
    EntityResolutionResult
)
from app.services.research.research_verifier import (
    ResearchVerifier,
    StoredSourceRecord
)


from langchain_core.runnables import RunnableLambda


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
    """Creates a mock LLM that correctly implements with_structured_output -> ainvoke via RunnableLambda."""
    mock_runnable = RunnableLambda(lambda x: snapshot_instance)
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_runnable
    return mock_llm


@pytest.mark.asyncio
async def test_two_executives_same_name_disambiguation(mock_db_session):
    """
    Test 1: Two executives with the same name.
    Candidate source for Gaurav Khatana at Siemens must be marked UNCERTAIN/AMBIGUOUS
    when target is Gaurav Khatana at Ottobon, and excluded from confirmed factual claims.
    """
    cid = "c-target-gaurav"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Gaurav Khatana",
        current_title="Founder & CEO",
        current_company="Ottobon",
        status=ContactStatus.RESEARCHING
    )

    # Mock SourceResult 1: Authentic Ottobon LinkedIn/website
    sr1 = SourceResult(
        id="sr-1",
        research_task_id="task-1",
        source_id="company_web",
        query="Gaurav Khatana Ottobon",
        raw_reference="https://ottobon.com/team/gaurav",
        status="SUCCESS",
        extracted_data={"title": "Gaurav Khatana - Founder at Ottobon", "text": "Gaurav Khatana is the Founder at Ottobon building NetworkOS."},
        metadata_={}
    )

    # Mock SourceResult 2: Unrelated person with same name at Siemens
    sr2 = SourceResult(
        id="sr-2",
        research_task_id="task-1",
        source_id="general_web",
        query="Gaurav Khatana Siemens",
        raw_reference="https://siemens.com/team/gaurav",
        status="SUCCESS",
        extracted_data={"title": "Gaurav Khatana at Siemens Energy", "text": "Gaurav Khatana leads turbine operations at Siemens Energy."},
        metadata_={}
    )

    ev1 = Evidence(
        id="ev-1",
        source_result_id="sr-1",
        source_id="company_web",
        source_reference="https://ottobon.com/team/gaurav",
        claim="Gaurav Khatana is Founder at Ottobon",
        confidence=90,
        evidence_type=EvidenceType.SIGNAL,
        related_entity_id=cid
    )

    ev2 = Evidence(
        id="ev-2",
        source_result_id="sr-2",
        source_id="general_web",
        source_reference="https://siemens.com/team/gaurav",
        claim="Gaurav Khatana leads turbine operations at Siemens Energy",
        confidence=90,
        evidence_type=EvidenceType.SIGNAL,
        related_entity_id=cid
    )

    def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt).lower()
        if "from contacts" in stmt_str:
            mock_res.scalars.return_value.first.return_value = contact
        elif "from research_tasks" in stmt_str:
            task = ResearchTask(id="task-1", research_run_id="run-1", source_id="web", status=TaskStatus.COMPLETED)
            mock_res.scalars.return_value.all.return_value = [task]
        elif "from source_results" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [sr1, sr2]
        elif "from evidence" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [ev1, ev2]
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.scalars.return_value.first.return_value = None
        return mock_res

    mock_db_session.execute.side_effect = mock_execute

    snapshot_obj = ExecutiveSnapshot(
        name="Gaurav Khatana",
        current_role="Founder & CEO",
        current_organization="Ottobon",
        location="San Francisco",
        provenance_status="VERIFIED CURRENT",
        domain_name="Enterprise AI",
        proven_domain_expertise="Autonomous Relationship OS",
        customer_knowledge_level="High",
        is_domain_sme="Practitioner",
        operating_in_own_domain=True,
        opportunity_category="Expert-Led Product Venture",
        opportunity_nature="Direct",
        broad_business_problem="Manual enterprise BD outreach",
        smallest_solvable_problem="[AI HYPOTHESIS - SALES INFERENCE] Automated network routing",
        why_now="Launch of NetworkOS [E1]",
        ottobon_capability_match="Development",
        delivery_risk_level="LOW",
        estimated_effort_hours="100 hours",
        cost_pricing_estimate="$15,000",
        proposed_first_engagement="Integration sprint",
        relationship_path="Direct founder contact",
        pipeline_stage="PROPOSED",
        next_action_step="Founder sign-off",
        full_markdown_report=(
            "# Commercial Opportunity Intelligence Report\n\n"
            "## 1. Executive & Domain Intelligence\n"
            "- **Current Role & Org**: Founder at Ottobon [E1] [VERIFIED CURRENT]\n"
            "- **Location**: San Francisco [E1]\n"
            "- **Proven Domain Expertise**: Enterprise AI [E1]\n\n"
            "## 2. Opportunity Discovery & Classification\n"
            "Identified Context [E1]\n\n"
            "## 3. The Smallest Worthwhile Solvable Problem\n"
            "- **Bounded Ottobon Solution**: [AI HYPOTHESIS - SALES INFERENCE] Workflow engine\n\n"
            "## 4. Feasibility, Capability Matching\n"
            "- **Indicative Commercial Calculation**: $15k\n"
        )
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(snapshot_obj)):
        await EvidenceEngine.process_run_and_extract_snapshot(
            db=mock_db_session,
            run_id="run-1",
            contact_id=cid,
            enable_epistemic_verification=True
        )

        # Assert sr2 (Siemens) was marked UNCERTAIN / AMBIGUOUS
        assert sr2.metadata_["identity_match_status"] == "UNCERTAIN"
        assert sr2.metadata_["epistemic_resolution_status"] == "AMBIGUOUS"
        assert sr2.metadata_["is_eligible_for_factual_claims"] is False

        # Assert sr1 (Ottobon) was marked CONFIRMED
        assert sr1.metadata_["identity_match_status"] == "CONFIRMED"
        assert sr1.metadata_["is_eligible_for_factual_claims"] is True

        # Assert ev2 (Siemens turbine claim) was quarantined with 0 confidence
        assert ev2.confidence == 0
        assert ev2.evidence_type == EvidenceType.INFERENCE


@pytest.mark.asyncio
async def test_fabricated_quote_in_evidence_quarantined(mock_db_session):
    """
    Test 2: Evidence item with fabricated quote that does not exist in source text.
    ResearchVerifier must quarantine it as UNSUPPORTED with confidence 0.
    """
    cid = "c-target-alice"
    contact = Contact(id=cid, full_name="Alice Smith", current_company="Alpha Corp")

    sr = SourceResult(
        id="sr-alice",
        research_task_id="task-1",
        source_id="web",
        raw_reference="https://alphacorp.com/alice",
        status="SUCCESS",
        extracted_data={"text": "Alice Smith is VP Product at Alpha Corp overseeing cloud billing."},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 95}
    )

    ev_fake = Evidence(
        id="ev-fake",
        source_result_id="sr-alice",
        source_id="web",
        source_reference="https://alphacorp.com/alice",
        claim="Alice Smith personally patented 5 quantum encryption chips",  # Not in text!
        confidence=90,
        evidence_type=EvidenceType.SIGNAL,
        related_entity_id=cid
    )

    def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt).lower()
        if "from contacts" in stmt_str:
            mock_res.scalars.return_value.first.return_value = contact
        elif "from research_tasks" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [ResearchTask(id="task-1", research_run_id="run-1", source_id="web")]
        elif "from source_results" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [sr]
        elif "from evidence" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [ev_fake]
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.scalars.return_value.first.return_value = None
        return mock_res

    mock_db_session.execute.side_effect = mock_execute

    snapshot_obj = ExecutiveSnapshot(
        name="Alice Smith",
        current_role="VP Product",
        current_organization="Alpha Corp",
        location="Remote",
        provenance_status="VERIFIED CURRENT",
        domain_name="Cloud Billing",
        proven_domain_expertise="Billing",
        customer_knowledge_level="High",
        is_domain_sme="Practitioner",
        operating_in_own_domain=True,
        opportunity_category="Small Service Engagement",
        opportunity_nature="Direct",
        broad_business_problem="Billing scaling",
        smallest_solvable_problem="[AI HYPOTHESIS - SALES INFERENCE] Audit",
        why_now="Growth [E1]",
        ottobon_capability_match="Development",
        delivery_risk_level="LOW",
        estimated_effort_hours="50 hours",
        cost_pricing_estimate="$8,000",
        proposed_first_engagement="Audit",
        relationship_path="Direct",
        pipeline_stage="PROPOSED",
        next_action_step="Review",
        full_markdown_report="# Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: VP Product at Alpha Corp [E1] [VERIFIED CURRENT]\n\n## 4. Feasibility\n- **Commercial**: $8k"
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(snapshot_obj)):
        await EvidenceEngine.process_run_and_extract_snapshot(
            db=mock_db_session,
            run_id="run-1",
            contact_id=cid,
            enable_epistemic_verification=True
        )

        # Assert fake evidence row was downgraded to INFERENCE with 0 confidence
        assert ev_fake.evidence_type == EvidenceType.INFERENCE
        assert ev_fake.confidence == 0
        assert "[❌ UNVERIFIED]" in ev_fake.claim


@pytest.mark.asyncio
async def test_conflicting_executive_employers_detected(mock_db_session):
    """
    Test 3: Two sources state conflicting current employers (e.g. Acme Corp vs Beta Systems).
    Must detect conflict, flag conflict warning in report, and prevent arbitrary single-employer assumption.
    """
    cid = "c-target-bob"
    contact = Contact(id=cid, full_name="Bob Jones", current_company="Acme Corp")

    sr1 = SourceResult(
        id="sr-1",
        research_task_id="t1",
        source_id="company_web",
        raw_reference="https://acmecorp.com/bob",
        status="SUCCESS",
        extracted_data={"text": "Bob Jones is currently CTO at Acme Corp"},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 90}
    )
    sr2 = SourceResult(
        id="sr-2",
        research_task_id="t1",
        source_id="general_web",
        raw_reference="https://betasystems.com/bob",
        status="SUCCESS",
        extracted_data={"text": "Bob Jones is currently CTO at Beta Systems"},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 90}
    )

    ev1 = Evidence(
        id="ev-1",
        source_result_id="sr-1",
        source_id="company_web",
        claim="Employer: Acme Corp | Role: CTO",
        confidence=90,
        evidence_type=EvidenceType.FACT,
        related_entity_id=cid
    )
    ev2 = Evidence(
        id="ev-2",
        source_result_id="sr-2",
        source_id="general_web",
        claim="Employer: Beta Systems | Role: CTO",
        confidence=90,
        evidence_type=EvidenceType.FACT,
        related_entity_id=cid
    )

    def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt).lower()
        if "from contacts" in stmt_str:
            mock_res.scalars.return_value.first.return_value = contact
        elif "from research_tasks" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [ResearchTask(id="t1", research_run_id="run-1", source_id="web")]
        elif "from source_results" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [sr1, sr2]
        elif "from evidence" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [ev1, ev2]
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.scalars.return_value.first.return_value = None
        return mock_res

    mock_db_session.execute.side_effect = mock_execute

    snapshot_obj = ExecutiveSnapshot(
        name="Bob Jones",
        current_role="CTO",
        current_organization="Acme Corp / Beta Systems (Conflicting)",
        location="Remote",
        provenance_status="VERIFIED CURRENT",
        domain_name="Tech",
        proven_domain_expertise="Software",
        customer_knowledge_level="Med",
        is_domain_sme="Practitioner",
        operating_in_own_domain=True,
        opportunity_category="Small Service Engagement",
        opportunity_nature="Direct",
        broad_business_problem="Scaling",
        smallest_solvable_problem="[AI HYPOTHESIS - SALES INFERENCE] Consult",
        why_now="Dispute [E1]",
        ottobon_capability_match="Development",
        delivery_risk_level="HIGH",
        estimated_effort_hours="80 hours",
        cost_pricing_estimate="$10,000",
        proposed_first_engagement="Consult",
        relationship_path="Direct",
        pipeline_stage="PROPOSED",
        next_action_step="Clarify employer",
        full_markdown_report="# Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: CTO at Acme Corp [E1] [VERIFIED CURRENT]\n- **Source Conflicts & History**: Conflicting employer claims detected between Acme Corp and Beta Systems.\n\n## 4. Feasibility\n- **Commercial**: $10k"
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(snapshot_obj)):
        await EvidenceEngine.process_run_and_extract_snapshot(
            db=mock_db_session,
            run_id="run-1",
            contact_id=cid,
            enable_epistemic_verification=True
        )

        conflicts = detect_conflicts([
            {"source_id": "company_web", "claim": "Employer: Acme Corp", "excerpt": "", "key": "E1"},
            {"source_id": "general_web", "claim": "Employer: Beta Systems", "excerpt": "", "key": "E2"}
        ], [sr1, sr2], contact)

        assert len(conflicts) > 0
        assert any("Acme Corp" in c and "Beta Systems" in c for c in conflicts)


@pytest.mark.asyncio
async def test_low_identity_confidence_suppresses_commercial_scenarios(mock_db_session):
    """
    Test 4: When all sources have UNCERTAIN identity (max identity confidence < 70%),
    the engine MUST enforce UNVERIFIED provenance status, UNCERTAIN_IDENTITY pipeline stage,
    and suppress commercial pricing and effort calculations.
    """
    cid = "c-target-uncertain"
    contact = Contact(id=cid, full_name="John Doe", current_company="Unknown Corp")

    sr = SourceResult(
        id="sr-unc",
        research_task_id="t1",
        source_id="web",
        raw_reference="https://blog.com/john-doe",
        status="SUCCESS",
        extracted_data={"text": "John Doe attended a technology conference"},
        metadata_={"identity_match_status": "UNCERTAIN", "identity_match_confidence": 30}
    )

    ev = Evidence(
        id="ev-unc",
        source_result_id="sr-unc",
        source_id="web",
        claim="Conference attendee",
        confidence=30,
        evidence_type=EvidenceType.SIGNAL,
        related_entity_id=cid
    )

    def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt).lower()
        if "from contacts" in stmt_str:
            mock_res.scalars.return_value.first.return_value = contact
        elif "from research_tasks" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [ResearchTask(id="t1", research_run_id="run-1", source_id="web")]
        elif "from source_results" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [sr]
        elif "from evidence" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [ev]
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.scalars.return_value.first.return_value = None
        return mock_res

    mock_db_session.execute.side_effect = mock_execute

    snapshot_obj = ExecutiveSnapshot(
        name="John Doe",
        current_role="Unknown",
        current_organization="Unknown Corp",
        location="Unknown",
        provenance_status="VERIFIED CURRENT",  # Model attempted to claim verified
        domain_name="Tech",
        proven_domain_expertise="Unverified",
        customer_knowledge_level="Unverified",
        is_domain_sme="Practitioner",
        operating_in_own_domain=False,
        opportunity_category="Expert-Led Product Venture",
        opportunity_nature="Direct",
        broad_business_problem="Unknown",
        smallest_solvable_problem="None",
        why_now="None",
        ottobon_capability_match="Development",
        delivery_risk_level="HIGH",
        estimated_effort_hours="150 hours",  # Model tried to output estimates
        cost_pricing_estimate="$20,000",
        proposed_first_engagement="Sprint",
        relationship_path="None",
        pipeline_stage="PROPOSED",
        next_action_step="Research",
        full_markdown_report=(
            "# Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: Unverified\n\n"
            "## 4. Feasibility, Capability Matching\n"
            "- **Indicative Commercial Calculation**: Pricing: $20,000"
        )
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(snapshot_obj)):
        await EvidenceEngine.process_run_and_extract_snapshot(
            db=mock_db_session,
            run_id="run-1",
            contact_id=cid,
            enable_epistemic_verification=True
        )

        added_objs = [call[0][0] for call in mock_db_session.add.call_args_list]
        engine_res = next((o for o in added_objs if isinstance(o, SourceResult) and o.source_id == "evidence_engine"), None)
        assert engine_res is not None

        snapshot = engine_res.extracted_data["executive_snapshot"]
        assert snapshot["provenance_status"] == "UNVERIFIED"
        assert snapshot["pipeline_stage"] == "UNCERTAIN_IDENTITY"
        assert "SUPPRESSED" in snapshot["cost_pricing_estimate"]
        assert "SUPPRESSED" in snapshot["estimated_effort_hours"]
        assert "COMMERCIAL SCENARIO SUPPRESSED" in snapshot["full_markdown_report"]


@pytest.mark.asyncio
async def test_feature_flag_toggle_evidence_engine(mock_db_session):
    """
    Test 5: Verify feature flag toggle in EvidenceEngine.
    When enable_epistemic_verification=False, runs legacy flow without epistemic metadata.
    """
    cid = "c-target-flag"
    contact = Contact(id=cid, full_name="Flag Test", current_company="Flag Corp")

    sr = SourceResult(
        id="sr-flag",
        research_task_id="t1",
        source_id="web",
        raw_reference="https://flag.com",
        status="SUCCESS",
        extracted_data={"text": "Flag Test profile"},
        metadata_={"identity_match_status": "CONFIRMED", "identity_match_confidence": 85}
    )

    def mock_execute(stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt).lower()
        if "from contacts" in stmt_str:
            mock_res.scalars.return_value.first.return_value = contact
        elif "from research_tasks" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [ResearchTask(id="t1", research_run_id="run-1", source_id="web")]
        elif "from source_results" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [sr]
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.scalars.return_value.first.return_value = None
        return mock_res

    mock_db_session.execute.side_effect = mock_execute

    snapshot_obj = ExecutiveSnapshot(
        name="Flag Test",
        current_role="CEO",
        current_organization="Flag Corp",
        location="Austin",
        provenance_status="VERIFIED CURRENT",
        domain_name="Tech",
        proven_domain_expertise="SaaS",
        customer_knowledge_level="High",
        is_domain_sme="Practitioner",
        operating_in_own_domain=True,
        opportunity_category="Small Service Engagement",
        opportunity_nature="Direct",
        broad_business_problem="Growth",
        smallest_solvable_problem="Sprint",
        why_now="Now",
        ottobon_capability_match="Development",
        delivery_risk_level="LOW",
        estimated_effort_hours="40 hours",
        cost_pricing_estimate="$5,000",
        proposed_first_engagement="Sprint",
        relationship_path="Direct",
        pipeline_stage="PROPOSED",
        next_action_step="Review",
        full_markdown_report="# Report\n\n## 1. Executive & Domain Intelligence\n- **Current Role & Org**: CEO at Flag Corp [E1] [VERIFIED CURRENT]\n\n## 4. Feasibility\n- **Cost**: $5k"
    )

    with patch("app.services.evidence.ChatOpenAI", return_value=make_mock_structured_llm(snapshot_obj)):
        await EvidenceEngine.process_run_and_extract_snapshot(
            db=mock_db_session,
            run_id="run-1",
            contact_id=cid,
            enable_epistemic_verification=False
        )

        added_objs = [call[0][0] for call in mock_db_session.add.call_args_list]
        engine_res = next((o for o in added_objs if isinstance(o, SourceResult) and o.source_id == "evidence_engine"), None)
        assert engine_res is not None
        assert engine_res.metadata_["epistemic_verification_enabled"] is False
