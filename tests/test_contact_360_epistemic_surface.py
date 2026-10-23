import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from app.models.identity import Contact, ContactStatus
from app.models.evidence import SourceResult, Evidence, EvidenceType
from app.models.orchestration import ResearchRun
from app.api.v1.endpoints.contacts import get_contact_360_data


@pytest.fixture
def mock_db():
    session = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_contact_360_epistemic_surface_full(mock_db):
    """
    Test 1: Contact 360 returns all epistemic verification fields:
    - verifiedFacts
    - signalsContext
    - commercialHypotheses
    - conflictsAndQuarantined
    - identityResolutionStatus
    - epistemicVerification summary
    """
    cid = "c-test-epistemic-1"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Elena Rostova",
        current_title="VP Engineering",
        current_company="Acme Corp",
        status=ContactStatus.RESEARCHING
    )

    snapshot_data = {
        "name": "Elena Rostova",
        "current_role": "VP Engineering",
        "current_organization": "Acme Corp",
        "provenance_status": "VERIFIED CURRENT",
        "identity_confidence": 95,
        "identity_resolution_status": "CONFIRMED",
        "pipeline_stage": "PROPOSED",
        "verified_facts": [
            {
                "claim_id": "c-1",
                "predicate": "CURRENT_ROLE",
                "value": "VP Engineering at Acme Corp",
                "epistemic_status": "VERIFIED",
                "evidence": [{
                    "source_id": "linkedin_profile",
                    "source_url": "https://linkedin.com/in/elena-rostova",
                    "source_authority": "PRIMARY_OFFICIAL",
                    "verbatim_quote": "Elena Rostova is VP Engineering at Acme Corp",
                    "identity_status": "MATCH_CONFIRMED"
                }]
            },
            {
                "claim_id": "c-2",
                "predicate": "OBSERVED_SIGNAL",
                "value": "Speaker at Cloud Architecture Summit 2025",
                "epistemic_status": "PARTIALLY_SUPPORTED",
                "evidence": [{
                    "source_id": "web_article",
                    "source_url": "https://techconference.io/speakers",
                    "source_authority": "UNVERIFIED_WEB",
                    "verbatim_quote": "Elena Rostova spoke on distributed caching",
                    "identity_status": "PROBABLE"
                }]
            }
        ],
        "commercial_hypotheses": [
            {
                "hypothesis_id": "hyp-1",
                "trigger_claim_ids": ["E1"],
                "inferred_pain_point": "Scaling microservice latency across regions",
                "ottobon_capability_offering": "AI Applications & Infrastructure",
                "delivery_risk_assessment": "LOW",
                "estimated_effort_hours": "120 hours",
                "pricing_scenario": "$18,000",
                "epistemic_status": "HYPOTHESIS"
            }
        ],
        "audit_issues": [
            {
                "claim_id": "c-fake",
                "issue_type": "QUOTE_NOT_FOUND",
                "message": "Quote not found in stored content for source blog_post",
                "severity": "FATAL"
            }
        ],
        "detected_conflicts": [
            "Differing role titles reported: 'VP Engineering' vs 'Lead Architect'"
        ],
        "evidence_map": {
            "E1": {"claim": "VP Engineering at Acme Corp", "confidence": 95, "evidence_type": "FACT"}
        }
    }

    sr = SourceResult(
        id="sr-engine-1",
        source_id="evidence_engine",
        status="SUCCESS",
        extracted_data={"executive_snapshot": snapshot_data},
        metadata_={"contact_id": cid}
    )

    ev_quarantined = Evidence(
        id="ev-quarantine-1",
        related_entity_id=cid,
        source_id="web",
        claim="[❌ UNVERIFIED] Elena Rostova filed 10 quantum patents",
        confidence=0,
        evidence_type=EvidenceType.INFERENCE
    )

    def mock_exec(stmt):
        stmt_str = str(stmt).lower()
        mock_res = MagicMock()
        if "from contacts" in stmt_str:
            mock_res.scalars.return_value.first.return_value = contact
        elif "from research_runs" in stmt_str:
            mock_res.scalars.return_value.first.return_value = None
            mock_res.scalars.return_value.all.return_value = []
        elif "from source_results" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [sr]
        elif "from evidence" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [ev_quarantined]
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.scalars.return_value.first.return_value = None
        return mock_res

    mock_db.execute.side_effect = mock_exec

    resp = await get_contact_360_data(
        id=cid,
        db=mock_db,
        user={"user_id": "u-1", "organization_id": "org-1"}
    )

    assert resp["id"] == cid
    assert resp["name"] == "Elena Rostova"

    # Epistemic top-level verification metadata
    epistemic = resp.get("epistemicVerification")
    assert epistemic is not None
    assert epistemic["identityStatus"] == "CONFIRMED"
    assert epistemic["identityConfidence"] == 95
    assert epistemic["verifiedFactsCount"] == 1
    assert epistemic["signalsCount"] == 1
    assert epistemic["hypothesesCount"] == 1
    assert epistemic["quarantinedCount"] >= 2  # 1 audit issue + 1 detected conflict + 1 quarantined evidence

    # Commercial intelligence section verification
    ci = resp.get("commercialIntelligence")
    assert ci is not None
    assert ci["identityResolutionStatus"] == "CONFIRMED"

    # 1. Verified facts
    assert len(ci["verifiedFacts"]) == 1
    vf = ci["verifiedFacts"][0]
    assert vf["claim"] == "VP Engineering at Acme Corp"
    assert vf["status"] == "VERIFIED"
    assert vf["authorityTier"] == "PRIMARY_OFFICIAL"

    # 2. Signals & observed context
    assert len(ci["signalsContext"]) == 1
    sig = ci["signalsContext"][0]
    assert sig["claim"] == "Speaker at Cloud Architecture Summit 2025"
    assert sig["status"] == "PARTIALLY_SUPPORTED"

    # 3. Commercial hypotheses
    assert len(ci["commercialHypotheses"]) == 1
    hyp = ci["commercialHypotheses"][0]
    assert hyp["inferred_pain_point"] == "Scaling microservice latency across regions"
    assert hyp["trigger_claim_ids"] == ["E1"]
    assert hyp["epistemic_status"] == "HYPOTHESIS"

    # 4. Conflicts & quarantined claims
    quarantined = ci["conflictsAndQuarantined"]
    assert len(quarantined) >= 2
    assert any(q["issueType"] == "QUOTE_NOT_FOUND" for q in quarantined)
    assert any(q["issueType"] == "CROSS_SOURCE_CONFLICT" for q in quarantined)
    assert any("[❌ UNVERIFIED]" not in q["reason"] and "Elena Rostova filed 10 quantum patents" in q["reason"] for q in quarantined)

    # Unsupported claim NEVER appears in verifiedFacts
    assert not any("quantum patents" in fact["claim"].lower() for fact in ci["verifiedFacts"])


@pytest.mark.asyncio
async def test_contact_360_backward_compatibility(mock_db):
    """
    Test 2: Verifies that existing response fields (pipelineStage, domainName,
    sourcesUsed, evidenceMap, opportunityValidation) remain intact and fully functional.
    """
    cid = "c-compat-lead"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Legacy Lead",
        current_title="Director",
        current_company="Legacy Inc",
        status=ContactStatus.READY
    )

    snapshot_data = {
        "name": "Legacy Lead",
        "current_role": "Director",
        "current_organization": "Legacy Inc",
        "provenance_status": "VERIFIED CURRENT",
        "domain_name": "Logistics Systems",
        "broad_business_problem": "Route optimization bottleneck",
        "smallest_solvable_problem": "Fleet telemetry dashboard",
        "ottobon_capability_match": "AI Applications",
        "delivery_risk_level": "LOW",
        "estimated_effort_hours": "80 hours",
        "cost_pricing_estimate": "$12,000",
        "pipeline_stage": "PROPOSED",
        "sources_used": [{"source_id": "web", "reference": "https://legacy.com", "status": "SUCCESS"}],
        "evidence_map": {"E1": {"claim": "Director at Legacy Inc", "confidence": 90, "evidence_type": "FACT"}}
    }

    sr = SourceResult(
        id="sr-compat",
        source_id="evidence_engine",
        status="SUCCESS",
        extracted_data={"executive_snapshot": snapshot_data},
        metadata_={"contact_id": cid}
    )

    def mock_exec(stmt):
        stmt_str = str(stmt).lower()
        mock_res = MagicMock()
        if "from contacts" in stmt_str:
            mock_res.scalars.return_value.first.return_value = contact
        elif "from source_results" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [sr]
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.scalars.return_value.first.return_value = None
        return mock_res

    mock_db.execute.side_effect = mock_exec

    resp = await get_contact_360_data(
        id=cid,
        db=mock_db,
        user={"user_id": "u-1", "organization_id": "org-1"}
    )

    ci = resp["commercialIntelligence"]
    assert ci["provenanceStatus"] == "VERIFIED CURRENT"
    assert ci["domainName"] == "Logistics Systems"
    assert ci["broadBusinessProblem"] == "Route optimization bottleneck"
    assert ci["smallestSolvableProblem"] == "Fleet telemetry dashboard"
    assert ci["ottobonCapabilityMatch"] == "AI Applications"
    assert ci["estimatedEffortHours"] == "80 hours"
    assert ci["costPricingEstimate"] == "$12,000"
    assert ci["pipelineStage"] == "PROPOSED"
    assert len(ci["sourcesUsed"]) == 1
    assert "E1" in ci["evidenceMap"]
    assert ci["opportunityValidation"]["identityGatePassed"] is True


@pytest.mark.asyncio
async def test_contact_360_ambiguous_identity_quarantines_commercials(mock_db):
    """
    Test 3: When identity resolution status is AMBIGUOUS (confidence < 70%),
    the endpoint marks identityResolutionStatus as AMBIGUOUS,
    suppresses commercial estimates, and sets identityGatePassed to False.
    """
    cid = "c-ambig-lead"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="Common Name Lead",
        status=ContactStatus.RESEARCHING
    )

    snapshot_data = {
        "name": "Common Name Lead",
        "provenance_status": "UNVERIFIED",
        "identity_confidence": 35,
        "identity_resolution_status": "AMBIGUOUS",
        "pipeline_stage": "UNCERTAIN_IDENTITY",
        "cost_pricing_estimate": "SUPPRESSED: Identity unverified",
        "estimated_effort_hours": "SUPPRESSED",
        "verified_facts": []
    }

    sr = SourceResult(
        id="sr-ambig",
        source_id="evidence_engine",
        status="SUCCESS",
        extracted_data={"executive_snapshot": snapshot_data},
        metadata_={"contact_id": cid}
    )

    def mock_exec(stmt):
        stmt_str = str(stmt).lower()
        mock_res = MagicMock()
        if "from contacts" in stmt_str:
            mock_res.scalars.return_value.first.return_value = contact
        elif "from source_results" in stmt_str:
            mock_res.scalars.return_value.all.return_value = [sr]
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.scalars.return_value.first.return_value = None
        return mock_res

    mock_db.execute.side_effect = mock_exec

    resp = await get_contact_360_data(
        id=cid,
        db=mock_db,
        user={"user_id": "u-1", "organization_id": "org-1"}
    )

    ci = resp["commercialIntelligence"]
    assert ci["identityResolutionStatus"] == "AMBIGUOUS"
    assert ci["provenanceStatus"] == "UNVERIFIED"
    assert ci["pipelineStage"] == "UNCERTAIN_IDENTITY"
    assert ci["opportunityValidation"]["identityGatePassed"] is False
    assert "SUPPRESSED" in ci["costPricingEstimate"]
    assert len(ci["verifiedFacts"]) == 0
    assert resp["epistemicVerification"]["identityStatus"] == "AMBIGUOUS"


@pytest.mark.asyncio
async def test_contact_360_empty_snapshot_safe_fallbacks(mock_db):
    """
    Test 4: Missing or empty executive snapshot does not crash the endpoint.
    It returns safe default fallbacks with zero verified facts.
    """
    cid = "c-empty-lead"
    contact = Contact(
        id=cid,
        organization_id="org-1",
        full_name="New Prospect",
        current_title="Founder",
        current_company="Stealth Startup",
        status=ContactStatus.RESEARCHING
    )

    def mock_exec(stmt):
        stmt_str = str(stmt).lower()
        mock_res = MagicMock()
        if "from contacts" in stmt_str:
            mock_res.scalars.return_value.first.return_value = contact
        else:
            mock_res.scalars.return_value.all.return_value = []
            mock_res.scalars.return_value.first.return_value = None
        return mock_res

    mock_db.execute.side_effect = mock_exec

    resp = await get_contact_360_data(
        id=cid,
        db=mock_db,
        user={"user_id": "u-1", "organization_id": "org-1"}
    )

    assert resp["id"] == cid
    assert resp["name"] == "New Prospect"
    assert resp["epistemicVerification"]["verifiedFactsCount"] == 0
    assert resp["epistemicVerification"]["quarantinedCount"] == 0
    if resp.get("commercialIntelligence"):
        assert resp["commercialIntelligence"]["verifiedFacts"] == []
