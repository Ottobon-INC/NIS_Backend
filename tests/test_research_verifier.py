import pytest
from datetime import datetime, timezone

from app.schemas.epistemic_evidence import (
    AtomicClaim,
    EvidenceRef,
    CommercialHypothesis
)
from app.services.research.entity_resolver import EntityResolutionResult
from app.services.research.research_verifier import (
    ResearchVerifier,
    StoredSourceRecord
)


@pytest.fixture
def sample_sources_registry():
    primary_text = "Gaurav Khatana is the Founder and Chief Architect at Ottobon, based in San Francisco."
    greenhouse_text = "Ottobon is actively hiring a Senior Distributed Systems Engineer to scale our network graph."
    unverified_blog_text = "Rumor has it Ottobon is planning to launch a multi-agent CRM system in Q3."
    stale_bio_text = "Gaurav Khatana was formerly the Lead Data Engineer at Acronis until stepping down in 2021."

    return {
        "src-primary-01": StoredSourceRecord(
            source_id="src-primary-01",
            url="https://ottobon.com/leadership/gaurav",
            canonical_url="https://ottobon.com/leadership/gaurav",
            domain="ottobon.com",
            raw_text=primary_text,
            content_sha256="hash-primary-01",
            authority_tier="PRIMARY_OFFICIAL",
            identity_resolution=EntityResolutionResult(
                status="MATCH_CONFIRMED",
                is_eligible_for_factual_claims=True,
                resolution_notes="Official company leadership bio"
            )
        ),
        "src-jobs-01": StoredSourceRecord(
            source_id="src-jobs-01",
            url="https://boards.greenhouse.io/ottobon/jobs/101",
            canonical_url="https://boards.greenhouse.io/ottobon/jobs/101",
            domain="greenhouse.io",
            raw_text=greenhouse_text,
            content_sha256="hash-jobs-01",
            authority_tier="REPUTABLE_AGGREGATOR",
            identity_resolution=EntityResolutionResult(
                status="MATCH_CONFIRMED",
                is_eligible_for_factual_claims=True,
                resolution_notes="Verified Greenhouse job board"
            )
        ),
        "src-unverified-blog": StoredSourceRecord(
            source_id="src-unverified-blog",
            url="https://techrumors.io/post/ottobon-agents",
            domain="techrumors.io",
            raw_text=unverified_blog_text,
            content_sha256="hash-blog-01",
            authority_tier="UNVERIFIED_WEB",
            identity_resolution=EntityResolutionResult(
                status="PROBABLE",
                is_eligible_for_factual_claims=True,
                resolution_notes="Probable entity mention on unverified tech blog"
            )
        ),
        "src-stale-bio": StoredSourceRecord(
            source_id="src-stale-bio",
            url="https://acronis-archive.org/people/gaurav",
            domain="acronis-archive.org",
            raw_text=stale_bio_text,
            content_sha256="hash-stale-01",
            authority_tier="PRIMARY_OFFICIAL",
            identity_resolution=EntityResolutionResult(
                status="MATCH_CONFIRMED",
                is_eligible_for_factual_claims=True,
                resolution_notes="Verified historical archive"
            )
        ),
        "src-ambiguous-01": StoredSourceRecord(
            source_id="src-ambiguous-01",
            url="https://genericnews.com/tech-roundup",
            domain="genericnews.com",
            raw_text="Gaurav Khatana participated in the regional cricket tournament.",
            content_sha256="hash-ambiguous-01",
            authority_tier="UNVERIFIED_WEB",
            identity_resolution=EntityResolutionResult(
                status="AMBIGUOUS",
                is_eligible_for_factual_claims=False,
                resolution_notes="No company or title corroboration"
            )
        )
    }


def test_quote_exact_match_authoritative_source_verified(sample_sources_registry):
    """Test that a verbatim quote from a PRIMARY_OFFICIAL source with confirmed identity is VERIFIED."""
    claim = AtomicClaim(
        claim_id="claim-01",
        subject_entity_id="gaurav-khatana",
        subject_type="EXECUTIVE",
        predicate="CURRENT_ROLE",
        value="Founder and Chief Architect",
        evidence=[
            EvidenceRef(
                source_id="src-primary-01",
                source_url="https://ottobon.com/leadership/gaurav",
                source_domain="ottobon.com",
                verbatim_quote="Gaurav Khatana is the Founder and Chief Architect at Ottobon"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sample_sources_registry)
    assert verified_claim.epistemic_status == "VERIFIED"
    assert verified_claim.signals.has_primary_source is True
    assert verified_claim.signals.identity_match_confirmed is True
    assert len(issues) == 0
    assert verified_claim.evidence[0].char_offset_start is not None


def test_quote_match_unverified_web_downgraded_to_partially_supported(sample_sources_registry):
    """
    CRITICAL SAFETY REQUIREMENT:
    Quote matching establishes textual presence, NOT truth.
    When text appears on an UNVERIFIED_WEB source, status must be PARTIALLY_SUPPORTED, never VERIFIED.
    """
    claim = AtomicClaim(
        claim_id="claim-02",
        subject_entity_id="ottobon",
        subject_type="COMPANY",
        predicate="USES_TECH",
        value="multi-agent CRM system",
        evidence=[
            EvidenceRef(
                source_id="src-unverified-blog",
                source_url="https://techrumors.io/post/ottobon-agents",
                source_domain="techrumors.io",
                verbatim_quote="Rumor has it Ottobon is planning to launch a multi-agent CRM system"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sample_sources_registry)
    assert verified_claim.epistemic_status == "PARTIALLY_SUPPORTED"
    assert "PARTIALLY_SUPPORTED" in verified_claim.epistemic_rationale


def test_fabricated_quote_rejected_as_unsupported(sample_sources_registry):
    """Hallucinated quote by LLM must be rejected as UNSUPPORTED with a FATAL issue."""
    claim = AtomicClaim(
        claim_id="claim-03",
        subject_entity_id="ottobon",
        subject_type="COMPANY",
        predicate="USES_TECH",
        value="Apache Kafka & Cassandra",
        evidence=[
            EvidenceRef(
                source_id="src-primary-01",
                source_url="https://ottobon.com/leadership/gaurav",
                source_domain="ottobon.com",
                verbatim_quote="Ottobon runs 500 nodes of Apache Kafka in AWS us-east-1"  # Not in text!
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sample_sources_registry)
    assert verified_claim.epistemic_status == "UNSUPPORTED"
    assert len(verified_claim.evidence) == 0
    assert any(i.issue_type == "QUOTE_NOT_FOUND" for i in issues)


def test_missing_source_id_rejected(sample_sources_registry):
    """Hallucinated source ID (e.g. src-999) must be rejected."""
    claim = AtomicClaim(
        claim_id="claim-04",
        subject_entity_id="ottobon",
        subject_type="COMPANY",
        predicate="REVENUE",
        value="$10M ARR",
        evidence=[
            EvidenceRef(
                source_id="src-nonexistent-id",
                source_url="https://fake.com",
                source_domain="fake.com",
                verbatim_quote="Revenue is $10M ARR"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sample_sources_registry)
    assert verified_claim.epistemic_status == "UNSUPPORTED"
    assert any(i.issue_type == "SOURCE_ID_MISSING" for i in issues)


def test_ambiguous_identity_source_rejected(sample_sources_registry):
    """Sources where identity resolution flagged AMBIGUOUS must not yield factual claims."""
    claim = AtomicClaim(
        claim_id="claim-05",
        subject_entity_id="gaurav-khatana",
        subject_type="EXECUTIVE",
        predicate="HOBBY",
        value="Cricket",
        evidence=[
            EvidenceRef(
                source_id="src-ambiguous-01",
                source_url="https://genericnews.com/tech-roundup",
                source_domain="genericnews.com",
                verbatim_quote="Gaurav Khatana participated in the regional cricket tournament"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sample_sources_registry)
    assert verified_claim.epistemic_status == "UNSUPPORTED"
    assert any(i.issue_type == "IDENTITY_AMBIGUOUS" for i in issues)


def test_temporal_negation_stale_role_flagged_conflicting(sample_sources_registry):
    """Asserting a CURRENT_ROLE when the quote says 'formerly' or 'stepping down' must be flagged CONFLICTING."""
    claim = AtomicClaim(
        claim_id="claim-06",
        subject_entity_id="gaurav-khatana",
        subject_type="EXECUTIVE",
        predicate="CURRENT_ROLE",
        value="Lead Data Engineer at Acronis",
        evidence=[
            EvidenceRef(
                source_id="src-stale-bio",
                source_url="https://acronis-archive.org/people/gaurav",
                source_domain="acronis-archive.org",
                verbatim_quote="Gaurav Khatana was formerly the Lead Data Engineer at Acronis until stepping down in 2021."
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sample_sources_registry)
    assert verified_claim.epistemic_status == "CONFLICTING"
    assert any(i.issue_type == "STALE_PAST_TENSE" for i in issues)


def test_explicit_unknown_value_handled(sample_sources_registry):
    """Explicitly unmentioned attributes must stay UNKNOWN without hallucination."""
    claim = AtomicClaim(
        claim_id="claim-07",
        subject_entity_id="ottobon",
        subject_type="COMPANY",
        predicate="SERIES_B_INVESTORS",
        value="[UNVERIFIED]",
        evidence=[]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sample_sources_registry)
    assert verified_claim.epistemic_status == "UNKNOWN"
    assert verified_claim.value is None


def test_complete_dossier_verification_and_hypothesis_separation(sample_sources_registry):
    """
    Verifies that a complete research dossier:
    1. Partitions claims cleanly into verified, partially supported, conflicting, and unsupported.
    2. Derives overall hiring state (ACTIVE).
    3. Keeps commercial sales hypotheses strictly isolated with epistemic_status == 'HYPOTHESIS'.
    """
    c1 = AtomicClaim(
        claim_id="c1",
        subject_entity_id="gaurav-khatana",
        subject_type="EXECUTIVE",
        predicate="CURRENT_ROLE",
        value="Founder and Chief Architect",
        evidence=[
            EvidenceRef(
                source_id="src-primary-01",
                source_url="https://ottobon.com/leadership/gaurav",
                source_domain="ottobon.com",
                verbatim_quote="Gaurav Khatana is the Founder and Chief Architect at Ottobon"
            )
        ]
    )

    c2 = AtomicClaim(
        claim_id="c2",
        subject_entity_id="ottobon",
        subject_type="COMPANY",
        predicate="HIRING_STATUS",
        value="ACTIVELY_HIRING",
        evidence=[
            EvidenceRef(
                source_id="src-jobs-01",
                source_url="https://boards.greenhouse.io/ottobon/jobs/101",
                source_domain="greenhouse.io",
                verbatim_quote="Ottobon is actively hiring a Senior Distributed Systems Engineer to scale our network graph."
            )
        ]
    )

    c3_fake = AtomicClaim(
        claim_id="c3_fake",
        subject_entity_id="ottobon",
        subject_type="COMPANY",
        predicate="TECH_STACK",
        value="Kubernetes & Terraform",
        evidence=[
            EvidenceRef(
                source_id="src-primary-01",
                source_url="https://ottobon.com/leadership/gaurav",
                source_domain="ottobon.com",
                verbatim_quote="We use Kubernetes and Terraform daily"  # Fabricated!
            )
        ]
    )

    hypothesis = CommercialHypothesis(
        hypothesis_id="hyp-01",
        target_entity_id="ottobon",
        trigger_claim_ids=["c2"],
        inferred_pain_point="Scaling high-throughput network graph query latency",
        ottobon_capability_offering="Distributed Graph Indexing Sprint",
        delivery_risk_assessment="LOW: Standard distributed systems modernization",
        estimated_effort_hours="120-160 hours",
        pricing_scenario="$15,000 fixed price sprint"
    )

    dossier = ResearchVerifier.verify_dossier(
        subject_entity_id="gaurav-khatana",
        subject_type="EXECUTIVE",
        raw_claims=[c1, c2, c3_fake],
        sources_registry=sample_sources_registry,
        hypotheses=[hypothesis]
    )

    assert len(dossier.verified_claims) == 2
    assert len(dossier.unsupported_claims) == 1
    assert dossier.unsupported_claims[0].claim_id == "c3_fake"
    assert dossier.hiring_state == "ACTIVE"
    assert len(dossier.commercial_hypotheses) == 1
    assert dossier.commercial_hypotheses[0].epistemic_status == "HYPOTHESIS"
    assert dossier.commercial_hypotheses[0].inferred_pain_point == "Scaling high-throughput network graph query latency"
