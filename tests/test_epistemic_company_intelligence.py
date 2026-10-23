import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from app.schemas.company_intelligence import CompanyIntelligenceOut
from app.schemas.epistemic_evidence import (
    AtomicClaim,
    EvidenceRef,
    CommercialHypothesis
)
from app.models.company_intelligence import CompanyIntelligence
from app.services.company_intelligence import (
    CompanyIntelligenceService,
    CompanyExtractionSchema,
    extract_deterministic_epistemic_claims
)
from app.services.research.entity_resolver import (
    EntityResolver,
    TargetCompanyAnchor,
    EntityResolutionResult
)
from app.services.research.research_verifier import (
    ResearchVerifier,
    StoredSourceRecord
)


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    # Mock scalars().first() to return None by default (no existing record)
    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = None
    result_mock.fetchall.return_value = []
    session.execute.return_value = result_mock
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_authoritative_company_extraction(mock_db_session):
    """
    Test 1: Company with authoritative supporting evidence (canonical website & Greenhouse job board).
    Must extract verified technologies, active hiring state, and segregated commercial hypotheses.
    """
    company_name = "CloudFlow Dynamics"

    ddg_mock_results = {
        "status": "SUCCESS",
        "text_content": "CloudFlow Dynamics enterprise cloud workflow engine.",
        "extracted_data": {
            "results": [
                {
                    "title": "CloudFlow Dynamics - Official Site",
                    "href": "https://cloudflowdynamics.com",
                    "body": "CloudFlow Dynamics builds distributed workflow automation using Python, FastAPI, and PostgreSQL on AWS."
                },
                {
                    "title": "Careers at CloudFlow Dynamics",
                    "href": "https://boards.greenhouse.io/cloudflowdynamics/jobs/101",
                    "body": "We are actively hiring a Backend Engineer to scale our distributed cloud queues."
                }
            ]
        }
    }

    with patch("app.services.company_intelligence.DuckDuckGoProvider.search_person", new_callable=AsyncMock) as mock_ddg, \
         patch("app.services.providers.web.GeneralWebProvider.fetch_public_webpage", new_callable=AsyncMock) as mock_web:

        mock_ddg.return_value = ddg_mock_results
        mock_web.return_value = {
            "status": "SUCCESS",
            "text_content": "CloudFlow Dynamics provides high-performance workflow automation using Python, FastAPI, and PostgreSQL."
        }

        result = await CompanyIntelligenceService.extract_and_persist(
            db=mock_db_session,
            company_name=company_name,
            enable_epistemic_verification=True
        )

        assert result.company_name == company_name
        assert result.website == "https://cloudflowdynamics.com"
        assert "Python" in result.technologies_used
        assert "FastAPI" in result.technologies_used
        assert "PostgreSQL" in result.technologies_used
        assert result.is_hiring is True
        assert result.hiring_status in ["ACTIVELY_HIRING", "MODERATE"]
        assert "Backend Engineer" in result.hiring_roles

        # Ensure Section 5 explicitly contains commercial hypothesis label
        assert "## 5. Commercial Opportunity Hypotheses (Ottobon Internal - Unverified Projections)" in result.summary_markdown
        assert "[HYPOTHESIS - SALES INFERENCE]" in result.summary_markdown

        # Verify API response compatibility
        api_out = CompanyIntelligenceOut.model_validate(result)
        assert api_out.company_name == company_name
        assert api_out.is_hiring is True


@pytest.mark.asyncio
async def test_company_with_no_supporting_evidence(mock_db_session):
    """
    Test 2: Company with no supporting evidence discovered across search indexes.
    Must return UNKNOWN without filling gaps with fabricated default technologies.
    """
    company_name = "Phantom Cryptic Zero"

    with patch("app.services.company_intelligence.DuckDuckGoProvider.search_person", new_callable=AsyncMock) as mock_ddg, \
         patch("app.services.providers.web.GeneralWebProvider.fetch_public_webpage", new_callable=AsyncMock) as mock_web:

        mock_ddg.return_value = {
            "status": "SUCCESS",
            "text_content": "No search results returned for query.",
            "extracted_data": {"results": []}
        }
        mock_web.return_value = None

        result = await CompanyIntelligenceService.extract_and_persist(
            db=mock_db_session,
            company_name=company_name,
            enable_epistemic_verification=True
        )

        assert result.company_name == company_name
        assert result.technologies_used == []  # MUST NOT be hardcoded default ["Cloud Architecture", ...]
        assert result.hiring_roles == []
        assert result.is_hiring is False
        assert result.hiring_status == "UNKNOWN"
        assert "No verified public intelligence records" in result.overview
        assert "No verified technical architectures" in result.what_they_implemented

        # API Out compatibility
        api_out = CompanyIntelligenceOut.model_validate(result)
        assert api_out.technologies_used == []
        assert api_out.hiring_status == "UNKNOWN"


def test_fabricated_technology_attribution_rejected():
    """
    Test 3: LLM hallucinates a technology (e.g. Kubernetes) that is not in the source text.
    ResearchVerifier must reject it as UNSUPPORTED and omit it from verified technologies.
    """
    stored_text = "Acme develops logistics software in Python and React."
    sources_registry = {
        "src-1": StoredSourceRecord(
            source_id="src-1",
            url="https://acme.com",
            domain="acme.com",
            raw_text=stored_text,
            content_sha256="hash-1",
            authority_tier="PRIMARY_OFFICIAL",
            identity_resolution=EntityResolutionResult(
                status="MATCH_CONFIRMED",
                is_eligible_for_factual_claims=True,
                resolution_notes="Official site"
            )
        )
    }

    # Legitimate claim
    c1 = AtomicClaim(
        claim_id="c-legit",
        subject_entity_id="Acme",
        subject_type="COMPANY",
        predicate="USES_TECH",
        value="Python",
        evidence=[EvidenceRef(
            source_id="src-1",
            source_url="https://acme.com",
            source_domain="acme.com",
            verbatim_quote="software in Python and React"
        )]
    )

    # Fabricated claim
    c2_fake = AtomicClaim(
        claim_id="c-fake",
        subject_entity_id="Acme",
        subject_type="COMPANY",
        predicate="USES_TECH",
        value="Kubernetes",
        evidence=[EvidenceRef(
            source_id="src-1",
            source_url="https://acme.com",
            source_domain="acme.com",
            verbatim_quote="Acme orchestrates 200 Kubernetes microservices"  # Fabricated!
        )]
    )

    dossier = ResearchVerifier.verify_dossier(
        subject_entity_id="Acme",
        subject_type="COMPANY",
        raw_claims=[c1, c2_fake],
        sources_registry=sources_registry
    )

    verified_techs = [c.value for c in dossier.verified_claims if c.predicate == "USES_TECH"]
    unsupported_ids = [c.claim_id for c in dossier.unsupported_claims]

    assert "Python" in verified_techs
    assert "Kubernetes" not in verified_techs
    assert "c-fake" in unsupported_ids


@pytest.mark.asyncio
async def test_ambiguous_company_identity_withheld(mock_db_session):
    """
    Test 4: Candidate sources match a generic name without domain proof (e.g. Apex plumbing for Apex).
    Must mark source as AMBIGUOUS and withhold factual claims.
    """
    company_name = "Apex"

    with patch("app.services.company_intelligence.DuckDuckGoProvider.search_person", new_callable=AsyncMock) as mock_ddg, \
         patch("app.services.providers.web.GeneralWebProvider.fetch_public_webpage", new_callable=AsyncMock) as mock_web:

        mock_ddg.return_value = {
            "status": "SUCCESS",
            "text_content": "Apex search results",
            "extracted_data": {
                "results": [
                    {
                        "title": "Apex Residential Plumbing Services",
                        "href": "https://apex-local-drain.com",
                        "body": "Apex provides emergency drain unclogging and boiler repair."
                    }
                ]
            }
        }
        mock_web.return_value = None

        result = await CompanyIntelligenceService.extract_and_persist(
            db=mock_db_session,
            company_name=company_name,
            enable_epistemic_verification=True
        )

        assert result.company_name == company_name
        assert result.technologies_used == []
        assert result.is_hiring is False
        assert result.hiring_status == "UNKNOWN"
        # Disqualified status in audit trail
        assert "Disqualified" in result.summary_markdown


def test_conflicting_sources_handling():
    """
    Test 5: Conflicting hiring reports (one says actively hiring, another says hiring freeze).
    Must derive CONFLICTING status.
    """
    sources_registry = {
        "src-jobs": StoredSourceRecord(
            source_id="src-jobs",
            url="https://boards.greenhouse.io/acme",
            domain="greenhouse.io",
            raw_text="Acme is actively hiring 10 engineers right now.",
            content_sha256="h1",
            authority_tier="REPUTABLE_AGGREGATOR",
            identity_resolution=EntityResolutionResult(status="MATCH_CONFIRMED", is_eligible_for_factual_claims=True, resolution_notes="")
        ),
        "src-news": StoredSourceRecord(
            source_id="src-news",
            url="https://technews.com/acme-freeze",
            domain="technews.com",
            raw_text="Acme announced an immediate hiring freeze across all departments.",
            content_sha256="h2",
            authority_tier="REPUTABLE_AGGREGATOR",
            identity_resolution=EntityResolutionResult(status="MATCH_CONFIRMED", is_eligible_for_factual_claims=True, resolution_notes="")
        )
    }

    c1 = AtomicClaim(
        claim_id="c1",
        subject_entity_id="Acme",
        subject_type="COMPANY",
        predicate="HIRING_STATUS",
        value="ACTIVELY_HIRING",
        evidence=[EvidenceRef(source_id="src-jobs", source_url="https://boards.greenhouse.io/acme", source_domain="greenhouse.io", verbatim_quote="actively hiring 10 engineers")]
    )

    c2 = AtomicClaim(
        claim_id="c2",
        subject_entity_id="Acme",
        subject_type="COMPANY",
        predicate="HIRING_STATUS",
        value="HIRING_FREEZE",
        evidence=[EvidenceRef(source_id="src-news", source_url="https://technews.com/acme-freeze", source_domain="technews.com", verbatim_quote="immediate hiring freeze across all departments")]
    )

    dossier = ResearchVerifier.verify_dossier(
        subject_entity_id="Acme",
        subject_type="COMPANY",
        raw_claims=[c1, c2],
        sources_registry=sources_registry
    )

    assert dossier.hiring_state == "CONFLICTING"
    assert len(dossier.conflicting_claims) == 2


def test_stale_hiring_or_role_information():
    """
    Test 6: Past tense indicators ('formerly', 'stepped down', 'frozen') in current claim.
    Must flag CONFLICTING or WARNING.
    """
    sources_registry = {
        "src-archive": StoredSourceRecord(
            source_id="src-archive",
            url="https://acme.com/archive",
            domain="acme.com",
            raw_text="Acme was previously hiring frontend developers prior to 2022 restructuring.",
            content_sha256="h-arch",
            authority_tier="PRIMARY_OFFICIAL",
            identity_resolution=EntityResolutionResult(status="MATCH_CONFIRMED", is_eligible_for_factual_claims=True, resolution_notes="")
        )
    }

    claim = AtomicClaim(
        claim_id="c-stale",
        subject_entity_id="Acme",
        subject_type="COMPANY",
        predicate="HIRING_STATUS",
        value="ACTIVELY_HIRING",
        evidence=[EvidenceRef(
            source_id="src-archive",
            source_url="https://acme.com/archive",
            source_domain="acme.com",
            verbatim_quote="previously hiring frontend developers prior to 2022"
        )]
    )

    v_claim, issues = ResearchVerifier.verify_single_claim(claim, sources_registry)
    assert v_claim.epistemic_status == "CONFLICTING"
    assert any(i.issue_type == "STALE_PAST_TENSE" for i in issues)


def test_missing_or_invalid_citations():
    """
    Test 7: Claim references a nonexistent source ID.
    Must be rejected as UNSUPPORTED.
    """
    sources_registry = {}

    claim = AtomicClaim(
        claim_id="c-invalid",
        subject_entity_id="Acme",
        subject_type="COMPANY",
        predicate="USES_TECH",
        value="Docker",
        evidence=[EvidenceRef(
            source_id="src-nonexistent-999",
            source_url="https://unknown.com",
            source_domain="unknown.com",
            verbatim_quote="Docker containers deployed"
        )]
    )

    v_claim, issues = ResearchVerifier.verify_single_claim(claim, sources_registry)
    assert v_claim.epistemic_status == "UNSUPPORTED"
    assert any(i.issue_type == "SOURCE_ID_MISSING" for i in issues)


@pytest.mark.asyncio
async def test_persistence_safely_preserves_existing_data(mock_db_session):
    """
    Test 8: Re-extracting a company with zero new findings must NOT overwrite existing verified technologies.
    """
    existing = CompanyIntelligence(
        id="existing-1",
        company_name="Acme Corp",
        website="https://acme.com",
        industry="Enterprise SaaS",
        overview="Acme Corp builds cloud billing tools.",
        what_they_implemented="Custom event billing architecture",
        is_hiring=True,
        hiring_status="ACTIVELY_HIRING",
        hiring_roles=["Billing Architect"],
        technologies_used=["Python", "PostgreSQL", "Redis"],
        key_initiatives=["SOC2 Type II"],
        sources=[]
    )

    # Return existing record from db query
    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = existing
    mock_db_session.execute.return_value = result_mock

    # Mock search returning no results on refresh
    with patch("app.services.company_intelligence.DuckDuckGoProvider.search_person", new_callable=AsyncMock) as mock_ddg, \
         patch("app.services.providers.web.GeneralWebProvider.fetch_public_webpage", new_callable=AsyncMock) as mock_web:

        mock_ddg.return_value = {"status": "SUCCESS", "text_content": "", "extracted_data": {"results": []}}
        mock_web.return_value = None

        updated = await CompanyIntelligenceService.extract_and_persist(
            db=mock_db_session,
            company_name="Acme Corp",
            enable_epistemic_verification=True
        )

        # Existing verified technologies and overview must be preserved
        assert updated.technologies_used == ["Python", "PostgreSQL", "Redis"]
        assert updated.overview == "Acme Corp builds cloud billing tools."
        assert updated.what_they_implemented == "Custom event billing architecture"


@pytest.mark.asyncio
async def test_feature_flag_toggle(mock_db_session):
    """
    Test 9: Feature flag toggle test.
    When enable_epistemic_verification=False, runs legacy path.
    When enable_epistemic_verification=True, runs epistemic verification path.
    """
    company_name = "Ottobon"

    with patch("app.services.company_intelligence.DuckDuckGoProvider.search_person", new_callable=AsyncMock) as mock_ddg, \
         patch("app.services.providers.web.GeneralWebProvider.fetch_public_webpage", new_callable=AsyncMock) as mock_web:

        mock_ddg.return_value = {"status": "SUCCESS", "text_content": "", "extracted_data": {"results": []}}
        mock_web.return_value = None

        # 1. Epistemic Verification Enabled
        res_epistemic = await CompanyIntelligenceService.extract_and_persist(
            db=mock_db_session,
            company_name=company_name,
            enable_epistemic_verification=True
        )
        assert "[HYPOTHESIS - SALES INFERENCE]" in res_epistemic.summary_markdown

        # 2. Epistemic Verification Disabled (Legacy fallback)
        res_legacy = await CompanyIntelligenceService.extract_and_persist(
            db=mock_db_session,
            company_name=company_name,
            enable_epistemic_verification=False
        )
        assert "## 5. Potential Collaboration Angles for Ottobon" in res_legacy.summary_markdown
