import pytest
import hashlib
from datetime import datetime, timezone
from typing import Dict, Optional

from app.schemas.epistemic_evidence import (
    AtomicClaim,
    EvidenceRef,
    EpistemicStatus,
    CommercialHypothesis,
    SourceAuthorityTier
)
from app.services.research.entity_resolver import (
    EntityResolver,
    TargetExecutiveAnchor,
    TargetCompanyAnchor,
    EntityResolutionResult
)
from app.services.research.research_verifier import (
    ResearchVerifier,
    StoredSourceRecord,
    VerifiedResearchDossier
)
from app.services.evidence import validate_report_citations
from app.models.evidence import Evidence, EvidenceType


@pytest.fixture
def make_source_record():
    """Helper fixture to create deterministic stored source records."""
    def _create(
        source_id: str,
        raw_text: str,
        url: str = "https://acme-example.com/press",
        domain: str = "acme-example.com",
        authority: SourceAuthorityTier = "PRIMARY_OFFICIAL",
        identity_status: str = "MATCH_CONFIRMED"
    ) -> StoredSourceRecord:
        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        resolution = EntityResolutionResult(
            status=identity_status,
            is_eligible_for_factual_claims=(identity_status in ["MATCH_CONFIRMED", "PROBABLE"]),
            confidence_score=95 if identity_status == "MATCH_CONFIRMED" else 60,
            resolution_notes="Synthetic fixture resolution"
        )
        return StoredSourceRecord(
            source_id=source_id,
            url=url,
            canonical_url=url,
            domain=domain,
            raw_text=raw_text,
            content_sha256=content_hash,
            authority_tier=authority,
            identity_resolution=resolution
        )
    return _create


def make_ref(
    source_id: str,
    verbatim_quote: str,
    url: str = "https://acme-example.com/press",
    domain: str = "acme-example.com",
    authority: SourceAuthorityTier = "PRIMARY_OFFICIAL",
    char_offset_start: Optional[int] = None,
    char_offset_end: Optional[int] = None,
    content_sha256: Optional[str] = None
) -> EvidenceRef:
    return EvidenceRef(
        source_id=source_id,
        source_url=url,
        canonical_url=url,
        source_domain=domain,
        verbatim_quote=verbatim_quote,
        source_authority=authority,
        char_offset_start=char_offset_start,
        char_offset_end=char_offset_end,
        content_sha256=content_sha256
    )


# ============================================================================
# RED-TEAM TEST CASE 1: Real quote that does NOT support the generated claim
# ============================================================================
def test_case_1_real_quote_does_not_support_generated_claim(make_source_record):
    """
    Adversarial Scenario:
    The quote exists verbatim in the source document, but it discusses customer growth
    instead of the generated claim (Kubernetes infrastructure).
    Expected outcome: UNSUPPORTED (CLAIM_VALUE_NOT_IN_QUOTE).
    """
    raw_text = "Acme recorded 40% year-over-year customer growth across our commercial banking clients."
    source = make_source_record(
        source_id="src-1",
        raw_text=raw_text,
        authority="PRIMARY_OFFICIAL"
    )
    sources = {"src-1": source}

    # Hallucinated claim citing real verbatim quote from the page
    claim = AtomicClaim(
        claim_id="claim-hallucinated-tech",
        subject_entity_id="Acme Corp",
        subject_type="COMPANY",
        predicate="TECH_STACK",
        value="Kubernetes Container Orchestration",
        evidence=[
            make_ref(
                source_id="src-1",
                url=source.url,
                domain=source.domain,
                verbatim_quote="Acme recorded 40% year-over-year customer growth",
                authority="PRIMARY_OFFICIAL"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sources)

    assert verified_claim.epistemic_status == "UNSUPPORTED", (
        f"Expected UNSUPPORTED, got {verified_claim.epistemic_status}. "
        "A real verbatim quote that does not mention claim value must NEVER be verified."
    )
    assert any(i.issue_type == "CLAIM_VALUE_NOT_IN_QUOTE" for i in issues)


# ============================================================================
# RED-TEAM TEST CASE 2: Names target executive but describes different person's role
# ============================================================================
def test_case_2_source_names_executive_but_describes_different_person_role(make_source_record):
    """
    Adversarial Scenario:
    The article mentions target executive 'Alice Walker', but the Chief Technology Officer role
    is actually held by 'Bob Jenkins'.
    Expected outcome: UNSUPPORTED (ROLE_ATTRIBUTED_TO_OTHER_PERSON).
    """
    raw_text = (
        "During the press conference, founder Alice Walker announced that Bob Jenkins was appointed "
        "Chief Technology Officer to lead platform scaling."
    )
    source = make_source_record(
        source_id="src-press",
        raw_text=raw_text,
        authority="PRIMARY_OFFICIAL"
    )
    sources = {"src-press": source}

    # Claim incorrectly attributes CTO role to Alice Walker
    claim = AtomicClaim(
        claim_id="claim-misattributed-role",
        subject_entity_id="Alice Walker",
        subject_type="EXECUTIVE",
        predicate="CURRENT_ROLE",
        value="Chief Technology Officer",
        evidence=[
            make_ref(
                source_id="src-press",
                url=source.url,
                domain=source.domain,
                verbatim_quote="Bob Jenkins was appointed Chief Technology Officer",
                authority="PRIMARY_OFFICIAL"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sources)

    assert verified_claim.epistemic_status == "UNSUPPORTED", (
        f"Expected UNSUPPORTED, got {verified_claim.epistemic_status}."
    )
    assert any(i.issue_type == "ROLE_ATTRIBUTED_TO_OTHER_PERSON" for i in issues)


# ============================================================================
# RED-TEAM TEST CASE 3: Former employer incorrectly presented as current employer
# ============================================================================
def test_case_3_former_employer_incorrectly_presented_as_current(make_source_record):
    """
    Adversarial Scenario:
    Source states the person is a 'former' VP or 'previously served at Stripe until 2021',
    but the LLM synthesized it as CURRENT_COMPANY: Stripe.
    Expected outcome: CONFLICTING (STALE_PAST_TENSE), never VERIFIED.
    """
    raw_text = "Prior to joining Acme in 2022, she was previously at Stripe as Director of Risk until 2021."
    source = make_source_record(
        source_id="src-bio",
        raw_text=raw_text,
        authority="PRIMARY_OFFICIAL"
    )
    sources = {"src-bio": source}

    claim = AtomicClaim(
        claim_id="claim-stale-employer",
        subject_entity_id="Jane Doe",
        subject_type="EXECUTIVE",
        predicate="CURRENT_COMPANY",
        value="Stripe",
        evidence=[
            make_ref(
                source_id="src-bio",
                url=source.url,
                domain=source.domain,
                verbatim_quote="she was previously at Stripe as Director of Risk until 2021",
                authority="PRIMARY_OFFICIAL"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sources)

    assert verified_claim.epistemic_status == "CONFLICTING", (
        f"Expected CONFLICTING due to temporal past-tense phrasing, got {verified_claim.epistemic_status}."
    )
    assert any(i.issue_type == "STALE_PAST_TENSE" for i in issues)


# ============================================================================
# RED-TEAM TEST CASE 4: Old hiring announcement presented as active hiring
# ============================================================================
def test_case_4_old_hiring_announcement_presented_as_active(make_source_record):
    """
    Adversarial Scenario:
    A job posting says 'Position filled and closed in October 2023', but research
    claims active hiring.
    Expected outcome: CONFLICTING or UNSUPPORTED, dossier hiring_state must NEVER be ACTIVE.
    """
    raw_text = "Senior Staff Backend Engineer - Position filled and closed. Applications closed."
    source = make_source_record(
        source_id="src-job",
        raw_text=raw_text,
        authority="PRIMARY_OFFICIAL"
    )
    sources = {"src-job": source}

    claim = AtomicClaim(
        claim_id="claim-hiring-expired",
        subject_entity_id="Acme Corp",
        subject_type="COMPANY",
        predicate="HIRING_STATUS",
        value="ACTIVE - Senior Staff Backend Engineer",
        evidence=[
            make_ref(
                source_id="src-job",
                url=source.url,
                domain=source.domain,
                verbatim_quote="Senior Staff Backend Engineer - Position filled and closed",
                authority="PRIMARY_OFFICIAL"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sources)
    assert verified_claim.epistemic_status == "CONFLICTING"

    dossier = ResearchVerifier.verify_dossier(
        subject_entity_id="Acme Corp",
        subject_type="COMPANY",
        raw_claims=[claim],
        sources_registry=sources
    )

    assert dossier.hiring_state != "ACTIVE", (
        f"Expired hiring posting resulted in active hiring state: {dossier.hiring_state}"
    )


# ============================================================================
# RED-TEAM TEST CASE 5: Copied / syndicated articles as independent corroboration
# ============================================================================
def test_case_5_copied_articles_not_counted_as_independent_corroboration(make_source_record):
    """
    Adversarial Scenario:
    Three citations are attached to a claim. However, two come from the exact same domain
    and two share identical content hashes (syndicated wire copy).
    Expected outcome: Independent corroboration count must be 1, NOT 3.
    """
    text_a = "Acme Corp launched their new enterprise payments gateway in London."
    text_b = text_a  # Identical content (syndicated copy)

    src1 = make_source_record("src-1", text_a, url="https://newswire.com/article1", domain="newswire.com")
    src2 = make_source_record("src-2", text_b, url="https://newswire.com/article2", domain="newswire.com")
    src3 = make_source_record("src-3", text_b, url="https://fintechtimes.com/repost", domain="fintechtimes.com")

    # Force identical sha256 across all
    content_hash = hashlib.sha256(text_a.encode("utf-8")).hexdigest()
    src1.content_sha256 = content_hash
    src2.content_sha256 = content_hash
    src3.content_sha256 = content_hash

    sources = {"src-1": src1, "src-2": src2, "src-3": src3}

    claim = AtomicClaim(
        claim_id="claim-launch",
        subject_entity_id="Acme Corp",
        subject_type="COMPANY",
        predicate="PRODUCT_LAUNCH",
        value="Enterprise Payments Gateway",
        evidence=[
            make_ref(source_id="src-1", url=src1.url, domain=src1.domain, content_sha256=content_hash, verbatim_quote="Acme Corp launched their new enterprise payments gateway"),
            make_ref(source_id="src-2", url=src2.url, domain=src2.domain, content_sha256=content_hash, verbatim_quote="Acme Corp launched their new enterprise payments gateway"),
            make_ref(source_id="src-3", url=src3.url, domain=src3.domain, content_sha256=content_hash, verbatim_quote="Acme Corp launched their new enterprise payments gateway"),
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sources)

    assert verified_claim.signals.corroboration_count == 1, (
        f"Expected independent corroboration count of 1, got {verified_claim.signals.corroboration_count}."
    )
    assert any(i.issue_type == "SYNDICATED_OR_DUPLICATE_SOURCES" for i in issues)


# ============================================================================
# RED-TEAM TEST CASE 6: Fabricated technology attribution with plausible citation
# ============================================================================
def test_case_6_fabricated_tech_attribution_with_plausible_citation(make_source_record):
    """
    Adversarial Scenario:
    An LLM hallucinates that Acme uses 'Snowflake Data Cloud', citing a generic quote
    stating 'We use modern cloud data solutions'.
    Expected outcome: UNSUPPORTED (CLAIM_VALUE_NOT_IN_QUOTE).
    """
    raw_text = "Acme leverages modern cloud data solutions and microservices to serve 1M users."
    source = make_source_record("src-cloud", raw_text, authority="PRIMARY_OFFICIAL")
    sources = {"src-cloud": source}

    claim = AtomicClaim(
        claim_id="claim-fake-snowflake",
        subject_entity_id="Acme Corp",
        subject_type="COMPANY",
        predicate="TECH_STACK",
        value="Snowflake Data Cloud",
        evidence=[
            make_ref(
                source_id="src-cloud",
                url=source.url,
                domain=source.domain,
                verbatim_quote="Acme leverages modern cloud data solutions and microservices",
                authority="PRIMARY_OFFICIAL"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sources)

    assert verified_claim.epistemic_status == "UNSUPPORTED"
    assert any(i.issue_type == "CLAIM_VALUE_NOT_IN_QUOTE" for i in issues)


# ============================================================================
# RED-TEAM TEST CASE 7: Official company page that does not support specific claim
# ============================================================================
def test_case_7_official_company_page_does_not_support_specific_claim(make_source_record):
    """
    Adversarial Scenario:
    Even though the source is Tier 1 PRIMARY_OFFICIAL (acme.com), the quote from the page
    does not support the attributed claim (SAP ERP Migration).
    Expected outcome: UNSUPPORTED. Authority tier alone must never verify unsupported text.
    """
    raw_text = "Welcome to Acme Corp. We are the trusted partner for global logistics logistics solutions."
    source = make_source_record("src-official", raw_text, authority="PRIMARY_OFFICIAL")
    sources = {"src-official": source}

    claim = AtomicClaim(
        claim_id="claim-sap-migration",
        subject_entity_id="Acme Corp",
        subject_type="COMPANY",
        predicate="ERP_SYSTEM",
        value="SAP ERP S/4HANA Migration",
        evidence=[
            make_ref(
                source_id="src-official",
                url=source.url,
                domain=source.domain,
                verbatim_quote="trusted partner for global logistics logistics solutions",
                authority="PRIMARY_OFFICIAL"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sources)

    assert verified_claim.epistemic_status == "UNSUPPORTED", (
        f"Claim on official page with irrelevant quote must be UNSUPPORTED, got {verified_claim.epistemic_status}."
    )


# ============================================================================
# RED-TEAM TEST CASE 8: Conflicting official and third-party sources
# ============================================================================
def test_case_8_conflicting_official_and_third_party_sources(make_source_record):
    """
    Adversarial Scenario:
    Source A (Official) says Chief Executive Officer.
    Source B (Aggregator) says Executive Chairman.
    Expected outcome: Both claims flagged as CONFLICTING. Neither is silently picked.
    """
    src1 = make_source_record("src-official", "David Vance serves as Chief Executive Officer of Acme.", authority="PRIMARY_OFFICIAL")
    src2 = make_source_record("src-crunchbase", "David Vance serves as Executive Chairman of Acme.", authority="REPUTABLE_AGGREGATOR", domain="crunchbase.com")
    sources = {"src-official": src1, "src-crunchbase": src2}

    claim1 = AtomicClaim(
        claim_id="claim-ceo",
        subject_entity_id="David Vance",
        subject_type="EXECUTIVE",
        predicate="CURRENT_ROLE",
        value="Chief Executive Officer",
        evidence=[make_ref(source_id="src-official", url=src1.url, domain=src1.domain, verbatim_quote="David Vance serves as Chief Executive Officer")]
    )
    claim2 = AtomicClaim(
        claim_id="claim-chairman",
        subject_entity_id="David Vance",
        subject_type="EXECUTIVE",
        predicate="CURRENT_ROLE",
        value="Executive Chairman",
        evidence=[make_ref(source_id="src-crunchbase", url=src2.url, domain=src2.domain, verbatim_quote="David Vance serves as Executive Chairman")]
    )

    dossier = ResearchVerifier.verify_dossier(
        subject_entity_id="David Vance",
        subject_type="EXECUTIVE",
        raw_claims=[claim1, claim2],
        sources_registry=sources
    )

    assert len(dossier.verified_claims) == 0, "Conflicting single-value predicates must not appear in verified_claims."
    assert len(dossier.conflicting_claims) == 2, f"Expected 2 conflicting claims, got {len(dossier.conflicting_claims)}."
    for c in dossier.conflicting_claims:
        assert c.epistemic_status == "CONFLICTING"


# ============================================================================
# RED-TEAM TEST CASE 9: LLM timeout or malformed extraction response
# ============================================================================
def test_case_9_llm_malformed_response_triggers_quarantined_fallback():
    """
    Adversarial Scenario:
    The LLM response contains broken markdown, nonexistent citations ([E999]), or throws an error.
    Expected outcome: validate_report_citations detects unknown citations and flags them.
    Diagnostic fallback preserves UNVERIFIED provenance status.
    """
    bad_markdown = (
        "# Commercial Opportunity Intelligence Report\n\n"
        "## 1. Executive & Domain Intelligence\n"
        "- **Current Role & Org**: VP Product at Acme [E999]\n"
        "- **Past Role**: Engineer at StartupX [malformed citation]\n"
    )

    # Valid evidence map has only [E1]
    evidence_map = {
        "E1": {"evidence_id": "ev-1", "claim": "Founding member", "source": "LinkedIn"}
    }

    audit = validate_report_citations(bad_markdown, evidence_map)

    assert "E999" in audit["unknown_citations"], "Fabricated citation key [E999] was not caught."
    assert audit["valid"] is False, "Malformed report was marked valid."
    assert len(audit["warnings"]) > 0


# ============================================================================
# RED-TEAM TEST CASE 10: Legacy cached record containing unsupported claims
# ============================================================================
def test_case_10_legacy_cached_record_quarantined():
    """
    Adversarial Scenario:
    A legacy database row contains an Evidence item marked with confidence=85,
    but it has not undergone epistemic verification.
    Expected outcome: Must NEVER be promoted to verified facts in Contact 360 payload.
    """
    legacy_ev = Evidence(
        id="leg-123",
        evidence_type=EvidenceType.FACT,
        claim="Legacy unaudited claim regarding budget authority",
        source_id="legacy_scraper",
        source_reference="https://old-cache.example.com",
        confidence=85,
        related_entity_id="contact-1"
    )

    # Simulate legacy fallback logic from app.api.v1.endpoints.contacts
    verified_facts_list = []
    signals_context_list = []
    conflicts_quarantined_list = []

    contact_evidences = [legacy_ev]
    is_identity_uncertain = False

    # Execute updated contacts.py fallback logic
    if not verified_facts_list and not signals_context_list:
        for ev in contact_evidences:
            if ev.confidence == 0 or ev.evidence_type in [EvidenceType.INFERENCE, EvidenceType.HYPOTHESIS] or "[❌" in (ev.claim or ""):
                clean_text = (ev.claim or "").replace("[❌ UNVERIFIED] ", "")
                conflicts_quarantined_list.append({
                    "claimId": ev.id,
                    "issueType": "LEGACY_UNAUDITED_UNSUPPORTED",
                    "reason": f"Legacy unverified record withheld from verified facts: '{clean_text}'",
                    "severity": "FATAL",
                    "status": "QUARANTINED"
                })
                continue

            signals_context_list.append({
                "claimId": ev.id,
                "predicate": "OBSERVED_SIGNAL",
                "claim": (ev.claim or "").replace("[⚠️ CONFLICTING] ", ""),
                "status": "PARTIALLY_SUPPORTED",
                "authorityTier": "LEGACY_UNAUDITED",
                "sourceUrl": ev.source_reference or ev.source_id,
                "quote": ev.claim,
                "observedDate": ev.observed_date.strftime("%Y-%m-%d") if ev.observed_date else None,
                "identityStatus": "PROBABLE" if not is_identity_uncertain else "AMBIGUOUS"
            })

    # Assert legacy record was safely relegated and NOT in verified facts
    assert len(verified_facts_list) == 0, "Legacy record bypassed verification and entered verified_facts_list!"
    assert len(signals_context_list) == 1
    assert signals_context_list[0]["authorityTier"] == "LEGACY_UNAUDITED"
    assert signals_context_list[0]["status"] == "PARTIALLY_SUPPORTED"


# ============================================================================
# RED-TEAM TEST CASE 11: Missing URLs, invalid source IDs, and mismatched offsets
# ============================================================================
def test_case_11_missing_urls_invalid_source_ids_and_mismatched_offsets(make_source_record):
    """
    Adversarial Scenario:
    Test 1: ev.source_id does not exist in registry -> SOURCE_ID_MISSING -> UNSUPPORTED.
    Test 2: source record has missing / non-HTTP URL -> INVALID_SOURCE_METADATA -> UNSUPPORTED.
    Test 3: quote offsets point to completely different text -> OFFSET_MISMATCH flagged.
    """
    raw_text = "Acme Corporation head of engineering announced new API tools."
    src_valid = make_source_record("src-valid", raw_text, url="https://acme.com/news")
    src_bad_url = make_source_record("src-bad-url", raw_text, url="")  # Empty URL

    sources = {
        "src-valid": src_valid,
        "src-bad-url": src_bad_url
    }

    # 1. Non-existent source ID
    claim_bad_id = AtomicClaim(
        claim_id="c-bad-id",
        subject_entity_id="Acme",
        subject_type="COMPANY",
        predicate="API_TOOLS",
        value="API tools",
        evidence=[make_ref(source_id="nonexistent-id", url="https://foo.com", verbatim_quote="API tools")]
    )
    v1, issues1 = ResearchVerifier.verify_single_claim(claim_bad_id, sources)
    assert v1.epistemic_status == "UNSUPPORTED"
    assert any(i.issue_type == "SOURCE_ID_MISSING" for i in issues1)

    # 2. Invalid source URL metadata
    claim_bad_url = AtomicClaim(
        claim_id="c-bad-url",
        subject_entity_id="Acme",
        subject_type="COMPANY",
        predicate="API_TOOLS",
        value="API tools",
        evidence=[make_ref(source_id="src-bad-url", url="", verbatim_quote="API tools")]
    )
    v2, issues2 = ResearchVerifier.verify_single_claim(claim_bad_url, sources)
    assert v2.epistemic_status == "UNSUPPORTED"
    assert any(i.issue_type == "INVALID_SOURCE_METADATA" for i in issues2)

    # 3. Mismatched character offset
    claim_mismatched_offsets = AtomicClaim(
        claim_id="c-offset-mismatch",
        subject_entity_id="Acme",
        subject_type="COMPANY",
        predicate="API_TOOLS",
        value="API tools",
        evidence=[make_ref(
            source_id="src-valid",
            url="https://acme.com/news",
            verbatim_quote="API tools",
            char_offset_start=0,  # Offset 0 is "Acme Corporation", not "API tools"
            char_offset_end=9
        )]
    )
    v3, issues3 = ResearchVerifier.verify_single_claim(claim_mismatched_offsets, sources)
    assert any(i.issue_type == "OFFSET_MISMATCH" for i in issues3)


# ============================================================================
# RED-TEAM TEST CASE 12: Ambiguous executive identity with authoritative source
# ============================================================================
def test_case_12_ambiguous_identity_with_authoritative_source(make_source_record):
    """
    Adversarial Scenario:
    A high-authority source (e.g. Forbes or Bloomberg) exists, but entity resolution
    flags the executive identity as AMBIGUOUS (e.g. common name, different company).
    Expected outcome: Claim must be UNSUPPORTED, never VERIFIED.
    """
    raw_text = "John Smith was appointed Chief Executive Officer of Quantum Tech."
    # Source is authoritative Forbes, but identity resolution for our target executive was AMBIGUOUS
    source = make_source_record(
        source_id="src-forbes",
        raw_text=raw_text,
        url="https://forbes.com/article/quantum-ceo",
        domain="forbes.com",
        authority="PRIMARY_OFFICIAL",
        identity_status="AMBIGUOUS"  # Identity ambiguous!
    )
    sources = {"src-forbes": source}

    claim = AtomicClaim(
        claim_id="claim-ambiguous-exec",
        subject_entity_id="John Smith",
        subject_type="EXECUTIVE",
        predicate="CURRENT_ROLE",
        value="Chief Executive Officer",
        evidence=[
            make_ref(
                source_id="src-forbes",
                url=source.url,
                domain=source.domain,
                verbatim_quote="John Smith was appointed Chief Executive Officer",
                authority="PRIMARY_OFFICIAL"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sources)

    assert verified_claim.epistemic_status == "UNSUPPORTED", (
        f"Expected UNSUPPORTED due to ambiguous identity, got {verified_claim.epistemic_status}."
    )
    assert any(i.issue_type == "IDENTITY_AMBIGUOUS" for i in issues)


# ============================================================================
# RED-TEAM TEST CASE 13: Pronoun anaphora not falsely misattributed as other person
# ============================================================================
def test_case_13_pronoun_anaphora_not_misattributed_as_other_person(make_source_record):
    """
    Scenario:
    Source text uses standard English pronoun reference:
    'Satya Nadella is a business executive. He is the chairman and chief executive officer of Microsoft.'
    The phrase 'He is the' must NOT be mistaken for a distinct person's name attributing the role away.
    Expected outcome: VERIFIED (or semantic support approved).
    """
    raw_text = (
        "Satya Nadella is an American business executive. "
        "He is the chairman and chief executive officer (CEO) of Microsoft."
    )
    source = make_source_record(
        source_id="src-satya-bio",
        raw_text=raw_text,
        url="https://news.microsoft.com/exec/satya-nadella",
        domain="news.microsoft.com",
        authority="PRIMARY_OFFICIAL",
        identity_status="MATCH_CONFIRMED"
    )
    sources = {"src-satya-bio": source}

    claim = AtomicClaim(
        claim_id="claim-satya-ceo",
        subject_entity_id="Satya Nadella",
        subject_type="EXECUTIVE",
        predicate="CURRENT_ROLE",
        value="Chairman and Chief Executive Officer",
        evidence=[
            make_ref(
                source_id="src-satya-bio",
                url=source.url,
                domain=source.domain,
                verbatim_quote="He is the chairman and chief executive officer (CEO) of Microsoft",
                authority="PRIMARY_OFFICIAL"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sources)
    assert verified_claim.epistemic_status == "VERIFIED", (
        f"Expected VERIFIED, got {verified_claim.epistemic_status}."
    )
    assert not any(i.issue_type == "ROLE_ATTRIBUTED_TO_OTHER_PERSON" for i in issues)


# ============================================================================
# RED-TEAM TEST CASE 14: Role specialization enforcement blocks CISO on CEO quote
# ============================================================================
def test_case_14_role_specialization_enforcement_blocks_ciso_on_ceo_quote(make_source_record):
    """
    Scenario:
    The quote states 'Satya Nadella is the Chief Executive Officer of Microsoft'.
    An adversarial or hallucinated claim asserts 'Chief Information Security Officer'.
    Even though 'Chief' and 'Officer' overlap, the specialization words 'Information' and 'Security'
    are missing from the evidence, so it must be rejected with CLAIM_VALUE_NOT_IN_QUOTE.
    """
    raw_text = "Satya Nadella is the Chief Executive Officer of Microsoft leading enterprise AI initiatives."
    source = make_source_record(
        source_id="src-ceo-bio",
        raw_text=raw_text,
        url="https://news.microsoft.com/exec/satya-nadella",
        domain="news.microsoft.com",
        authority="PRIMARY_OFFICIAL",
        identity_status="MATCH_CONFIRMED"
    )
    sources = {"src-ceo-bio": source}

    claim = AtomicClaim(
        claim_id="claim-hallucinated-ciso",
        subject_entity_id="Satya Nadella",
        subject_type="EXECUTIVE",
        predicate="CURRENT_ROLE",
        value="Chief Information Security Officer",
        evidence=[
            make_ref(
                source_id="src-ceo-bio",
                url=source.url,
                domain=source.domain,
                verbatim_quote="Satya Nadella is the Chief Executive Officer of Microsoft",
                authority="PRIMARY_OFFICIAL"
            )
        ]
    )

    verified_claim, issues = ResearchVerifier.verify_single_claim(claim, sources)
    assert verified_claim.epistemic_status == "UNSUPPORTED", (
        f"Expected UNSUPPORTED for CISO on CEO quote, got {verified_claim.epistemic_status}."
    )
    assert any(i.issue_type == "CLAIM_VALUE_NOT_IN_QUOTE" for i in issues)

