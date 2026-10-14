import pytest
import os
from unittest.mock import AsyncMock, patch

from app.schemas.matching import (
    CompanyProfileAnalysis,
    CompanyMatchingResult,
    ProblemItem,
    ProblemType,
    EvidenceStatus,
    MatchingOutcome
)
from app.services.problem_matcher import ProblemMatcherService
from app.services.conversation_intelligence import ConversationIntelligenceService

@pytest.fixture
def mock_catalog():
    return {
        "services": {
            "svc-reporting": "Automated Reporting & Data Pipelines",
            "svc-cloud": "Cloud Modernization & Architecture Refactoring",
            "svc-integration": "API & Multi-System Integration",
            "svc-soc2": "SOC2 Compliance & Security Governance"
        },
        "products": {
            "prod-networkos": "NetworkOS Platform"
        },
        "capabilities": {
            "cap-reporting": "Automated Reporting & Data Pipelines",
            "cap-cloud": "Cloud Modernization & Architecture Refactoring",
            "cap-integration": "Enterprise API & Multi-System Integration",
            "cap-soc2": "SOC2 Compliance & Security Governance",
            "cap-ai-rag": "Enterprise AI Orchestration & RAG Systems"
        }
    }

@pytest.mark.asyncio
async def test_talentops_match_found(mock_catalog):
    """
    Test Case 1: TalentOps profile with explicit verified problems in HR/payroll/audit
    must yield MATCH_FOUND with approved offerings and full mandatory capability coverage.
    """
    profile = CompanyProfileAnalysis(
        company_name="TalentOps",
        industry="Human Resources Technology",
        business_model="B2B SaaS Managed Workforce Platform",
        operating_context="AI-powered HR and workforce management system.",
        source_filename="TalentOps Business Overview.pdf",
        technology_stack=["FastAPI", "React", "PostgreSQL"],
        business_objectives=["Reduce HR operational overhead by 80%"],
        explicit_problems=[
            ProblemItem(
                id="p-1",
                title="HR Operations & Payroll Reporting Delays",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Manual timesheet consolidation and delayed payroll export reporting.",
                supporting_evidence=["Payroll processing complexity and attendance inconsistencies cause 3-day delays."],
                likely_business_impact="Excess administrative overhead and employee dissatisfaction.",
                validation_questions=["What is the current payroll aggregation cycle time?"]
            ),
            ProblemItem(
                id="p-2",
                title="Lack of SOC2 Audit Trail and Security Governance",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Enterprise clients require verified SOC2 Type II audit logging and RBAC.",
                supporting_evidence=["Missing automated audit trails block enterprise customer onboarding."],
                likely_business_impact="Revenue stall in enterprise segment.",
                validation_questions=["When is the upcoming SOC2 audit window?"]
            )
        ]
    )

    with patch.object(ProblemMatcherService, "_load_approved_catalog", return_value=mock_catalog):
        result = await ProblemMatcherService.match_profile(profile)

    assert result.matching_outcome == MatchingOutcome.MATCH_FOUND
    assert len(result.candidate_solutions) >= 1
    # Check that solutions are approved
    offering_ids = [c.offering_id for c in result.candidate_solutions]
    assert any(oid in mock_catalog["services"] for oid in offering_ids)
    assert "Schedule founder discovery" in result.recommended_next_step

@pytest.mark.asyncio
async def test_internal_offering_no_match(mock_catalog):
    """
    Test Case 2: Internal Ottobon Course Platform document must yield NO_MATCH_FOUND.
    NetworkOS must not hallucinate client sales opportunities for internal assets.
    """
    profile = CompanyProfileAnalysis(
        company_name="Ottobon Course Platform",
        industry="EdTech / Internal Academy",
        business_model="Internal Training & Curriculum Delivery",
        operating_context="Internal educational platform for student onboarding.",
        source_filename="ottobon_course_platform_business_overview.docx",
        explicit_problems=[],
        inferred_hypotheses=[]
    )

    with patch.object(ProblemMatcherService, "_load_approved_catalog", return_value=mock_catalog):
        result = await ProblemMatcherService.match_profile(profile)

    assert result.matching_outcome == MatchingOutcome.NO_MATCH_FOUND
    assert "internal educational product" in result.matching_rationale.lower()
    assert len(result.candidate_solutions) == 0

@pytest.mark.asyncio
async def test_sbloom_needs_validation(mock_catalog):
    """
    Test Case 3: sBLOOM document with unconfirmed Section 28 commercial revenue-share
    and physical studio hardware gaps must yield NEEDS_VALIDATION.
    """
    profile = CompanyProfileAnalysis(
        company_name="sBLOOM",
        industry="Creator & Media Production",
        business_model="Creator content and digital growth ecosystem",
        operating_context="Creator marketing vertical under Autobahn Professional Services.",
        source_filename="sBLOOM_Detailed_Business_Proposal_Overview.docx",
        explicit_problems=[
            ProblemItem(
                id="sb-1",
                title="Creator Production Workflow Bottleneck",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Creators handle filming and distribution manually.",
                supporting_evidence=["A creator who handles scripting, filming, and publishing alone has a hard ceiling."],
                validation_questions=["How many creators are actively onboarded?"]
            )
        ],
        unknowns_and_missing=[
            "Section 28 flags creator 25% revenue-share model as unconfirmed.",
            "Physical video cameras and acoustic isolation require external vendor."
        ]
    )

    with patch.object(ProblemMatcherService, "_load_approved_catalog", return_value=mock_catalog):
        result = await ProblemMatcherService.match_profile(profile)

    assert result.matching_outcome == MatchingOutcome.NEEDS_VALIDATION
    assert "Founder validation required" in result.recommended_next_step
    assert "Section 28" in result.matching_rationale

@pytest.mark.asyncio
async def test_insufficient_information(mock_catalog):
    """
    Test Case 4: Profile with minimal or missing information must return INSUFFICIENT_INFORMATION.
    """
    profile = CompanyProfileAnalysis(
        company_name="Unknown Company",
        industry="",
        business_model="",
        operating_context="",
        source_filename="empty_doc.txt",
        explicit_problems=[],
        inferred_hypotheses=[]
    )

    with patch.object(ProblemMatcherService, "_load_approved_catalog", return_value=mock_catalog):
        result = await ProblemMatcherService.match_profile(profile)

    assert result.matching_outcome == MatchingOutcome.INSUFFICIENT_INFORMATION
    assert "lacks enough verifiable business context" in result.matching_rationale

@pytest.mark.asyncio
async def test_unapproved_offerings_rejected():
    """
    Test Case 5: Ensure unapproved offerings cannot become recommendations.
    If an offering is not in the approved database catalog, it must NOT be matched.
    """
    # Empty approved catalog
    empty_catalog = {
        "services": {},
        "products": {},
        "capabilities": {}
    }

    profile = CompanyProfileAnalysis(
        company_name="AuditTech",
        industry="Cybersecurity",
        business_model="B2B",
        operating_context="Needs SOC2 audit compliance",
        source_filename="audittech.txt",
        explicit_problems=[
            ProblemItem(
                id="at-1",
                title="SOC2 Audit Logging Gap",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Missing SOC2 audit logging.",
                supporting_evidence=["Client requires SOC2."]
            )
        ]
    )

    with patch.object(ProblemMatcherService, "_load_approved_catalog", return_value=empty_catalog):
        result = await ProblemMatcherService.match_profile(profile)

    # Catalog is empty, so no offerings qualify
    assert len(result.candidate_solutions) == 0
    assert result.matching_outcome in [MatchingOutcome.INSUFFICIENT_INFORMATION, MatchingOutcome.NO_MATCH_FOUND]

@pytest.mark.asyncio
async def test_unsupported_domain_flagged_as_gap(mock_catalog):
    """
    Test Case 6: Problems outside Ottobon's software capabilities (e.g. physical camera studio)
    must produce explicit capability gaps and not hallucinate a solution.
    """
    profile = CompanyProfileAnalysis(
        company_name="CinemaStudio",
        industry="Film Production",
        business_model="B2B Studio Rental",
        operating_context="Renting physical soundstages.",
        source_filename="cinemastudio.txt",
        explicit_problems=[
            ProblemItem(
                id="cs-1",
                title="Studio rental and camera hardware maintenance",
                problem_type=ProblemType.EXPLICIT_PROBLEM,
                evidence_status=EvidenceStatus.VERIFIED_FACT,
                business_summary="Physical studio rental and lighting equipment failure.",
                supporting_evidence=["Physical acoustic isolation and camera repair."]
            )
        ]
    )

    with patch.object(ProblemMatcherService, "_load_approved_catalog", return_value=mock_catalog):
        result = await ProblemMatcherService.match_profile(profile)

    # Must flag capability gap
    assert any("Out of catalog" in gap for gap in result.capability_gaps)


# --- Tests for SemanticProductMatcherService ---
from app.services.semantic_product_matcher import SemanticProductMatcherService

@pytest.mark.asyncio
async def test_semantic_match_talentops_hr():
    """
    Evaluates an HR and payroll challenge. Must semantically match TalentOps,
    include 'TalentOps' in suggested_status, and have score >= 75.
    """
    res = await SemanticProductMatcherService.match_connection_problem(
        problem_text="Our HR team is overwhelmed with manual employee onboarding, delayed leave approvals, and payroll processing errors.",
        connection_name="Ananya Sharma",
        connection_company="ScaleTech Labs",
        connection_title="Head of People"
    )
    assert res.matching_outcome == "MATCH_FOUND"
    assert "TalentOps" in res.suggested_status
    assert len(res.matches) >= 1
    assert res.matches[0].product_name == "TalentOps"
    assert res.matches[0].match_score >= 75
    assert len(res.matches[0].relevant_features) > 0


@pytest.mark.asyncio
async def test_semantic_match_janmasethu_fertility():
    """
    Evaluates a fertility clinic workflow problem. Must semantically match JanmaSethu,
    include 'JanmaSethu' in suggested_status.
    """
    res = await SemanticProductMatcherService.match_connection_problem(
        problem_text="Fertility clinics wasting clinical hours dealing with unqualified or unprepared patient inquiries and lacking bilingual regional support.",
        connection_name="Dr. Suresh Rao",
        connection_company="Nova Fertility Clinic",
        connection_title="Clinical Director"
    )
    assert res.matching_outcome == "MATCH_FOUND"
    assert "JanmaSethu" in res.suggested_status
    assert len(res.matches) >= 1
    assert res.matches[0].product_name == "JanmaSethu"
    assert res.matches[0].match_score >= 70


@pytest.mark.asyncio
async def test_semantic_match_sbloom_creator():
    """
    Evaluates a creator production burnout problem. Must semantically match sBLOOM,
    include 'sBLOOM' in suggested_status.
    """
    res = await SemanticProductMatcherService.match_connection_problem(
        problem_text="Creators overwhelmed by shooting, editing reels, and scripting alone with hard output ceilings and inconsistent thought leadership.",
        connection_name="Rohit Verma",
        connection_company="Creator Ventures",
        connection_title="Lead Creator"
    )
    assert res.matching_outcome == "MATCH_FOUND"
    assert "sBLOOM" in res.suggested_status
    assert len(res.matches) >= 1
    assert res.matches[0].product_name == "sBLOOM"


@pytest.mark.asyncio
async def test_semantic_match_ottobon_courses_edtech():
    """
    Evaluates software developer tutorial fatigue. Must semantically match Ottobon Course Platform.
    """
    res = await SemanticProductMatcherService.match_connection_problem(
        problem_text="Software developers experience tutorial fatigue, watching endless courses without practical project building or code sandboxes.",
        connection_name="Vikram Mehta",
        connection_company="Tech University",
        connection_title="Dean of Computing"
    )
    assert res.matching_outcome == "MATCH_FOUND"
    assert "Ottobon Course Platform" in res.suggested_status
    assert len(res.matches) >= 1
    assert res.matches[0].product_name == "Ottobon Course Platform"


@pytest.mark.asyncio
async def test_semantic_match_unsupported_suggests_no_matches_found():
    """
    Evaluates a problem completely outside our catalog (heavy civil construction excavators).
    Must explicitly return NO_MATCH_FOUND and suggest 'No matches found'.
    """
    res = await SemanticProductMatcherService.match_connection_problem(
        problem_text="We need heavy hydraulic excavators, bulldozer leasing, and civil engineering earthmoving concrete machinery.",
        connection_name="Rajesh Patil",
        connection_company="Patil Earthmovers & Infra",
        connection_title="Managing Director"
    )
    assert res.matching_outcome == "NO_MATCH_FOUND"
    assert res.suggested_status == "No matches found"
    assert len(res.matches) == 0
    assert "None of our current products" in res.rationale or "No matches found" in res.rationale
    assert res.capability_gap is not None


@pytest.mark.asyncio
async def test_screenshot_example_returns_insufficient_information():
    """
    Evaluates the exact problem statement from the screenshot:
    'Expansion and growth in the retail and real estate market, particularly in India.'
    Must return INSUFFICIENT_INFORMATION, classify domain accurately (NOT 'Non-matching Domain'),
    populate missing information, validation questions, and unverified hypotheses.
    """
    res = await SemanticProductMatcherService.match_connection_problem(
        problem_text="Expansion and growth in the retail and real estate market, particularly in India.",
        connection_name="Rahul Dhamdhere",
        connection_company="Nexus Select Trust",
        connection_title="Marketing Leader",
        context={"industry": "Retail and Real Estate"}
    )
    assert res.matching_outcome == "INSUFFICIENT_INFORMATION"
    assert res.suggested_status == "Insufficient Information"
    assert res.problem_domain == "Retail & Commercial Real Estate Expansion"
    assert "non-matching" not in res.problem_domain.lower()
    assert len(res.matches) == 0
    assert len(res.missing_information) >= 2
    assert len(res.validation_questions) >= 2
    assert len(res.unverified_hypotheses) >= 1
    assert len(res.relevant_evidence) >= 1
    assert "operational" in res.rationale.lower()
    assert res.recommended_next_step is not None


@pytest.mark.asyncio
async def test_semantic_match_needs_validation():
    """
    Evaluates a candidate capability fit where technical prerequisites or organizational
    assumptions require validation before recommending.
    """
    res = await SemanticProductMatcherService.match_connection_problem(
        problem_text="Founder seeking executive thought leadership on LinkedIn but unconfirmed content production workflow.",
        connection_name="Vikram Seth",
        connection_company="Growth Ventures",
        connection_title="Founder"
    )
    # Either MATCH_FOUND or NEEDS_VALIDATION depending on confidence threshold,
    # but must have rich validation questions and clear next steps
    assert res.matching_outcome in ["NEEDS_VALIDATION", "MATCH_FOUND"]
    assert len(res.validation_questions) > 0
    assert res.recommended_next_step is not None


def test_domain_classification_never_returns_non_matching():
    """
    Verifies that domain classification accurately classifies industries and business domains,
    and NEVER returns 'Non-matching Domain'.
    """
    test_cases = [
        ("Expansion and growth in the retail and real estate market, particularly in India.", "Retail & Commercial Real Estate Expansion"),
        ("Patient appointments and clinical gastroenterology practice management.", "Healthtech & Clinical Practice Management"),
        ("Overwhelmed by video editing, reels, and personal branding on LinkedIn.", "Creator Media & Executive Personal Branding"),
        ("Manual employee onboarding, timesheet reconciliation, and payroll delays.", "Workforce Operations & HR Management"),
        ("Software developers stuck in tutorial fatigue watching programming videos.", "AI-Native Developer Education & Upskilling"),
        ("Excavator leasing and heavy bulldozer earthmoving civil engineering.", "Heavy Civil Engineering & Machinery"),
        ("Enterprise ERP billing software and SAP ledger reconciliation.", "Enterprise Systems & ERP Billing"),
    ]
    for problem, expected_domain in test_cases:
        domain = SemanticProductMatcherService._classify_domain(problem)
        assert domain == expected_domain
        assert "non-matching" not in domain.lower()


