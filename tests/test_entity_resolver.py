import pytest
from app.services.research.entity_resolver import (
    EntityResolver,
    TargetExecutiveAnchor,
    TargetCompanyAnchor
)

def test_executive_exact_linkedin_slug_match():
    anchor = TargetExecutiveAnchor(
        full_name="Gaurav Khatana",
        current_company="Ottobon",
        profile_url="https://www.linkedin.com/in/gaurav-khatana-dev"
    )
    result = EntityResolver.resolve_executive(
        anchor=anchor,
        candidate_url="https://www.linkedin.com/in/gaurav-khatana-dev/",
        candidate_title="Gaurav Khatana - Founder - Ottobon | LinkedIn",
        candidate_text="Gaurav Khatana is building intelligent autonomous workflows at Ottobon."
    )
    assert result.status == "MATCH_CONFIRMED"
    assert result.is_eligible_for_factual_claims is True
    assert "exact_linkedin_slug" in result.matched_anchors

def test_executive_wrong_linkedin_slug_rejection():
    anchor = TargetExecutiveAnchor(
        full_name="Gaurav Khatana",
        current_company="Ottobon",
        profile_url="https://www.linkedin.com/in/gaurav-khatana-target"
    )
    result = EntityResolver.resolve_executive(
        anchor=anchor,
        candidate_url="https://www.linkedin.com/in/gaurav-khatana-unrelated-person",
        candidate_title="Gaurav Khatana - Senior Architect - Microsoft | LinkedIn",
        candidate_text="Gaurav Khatana has 15 years experience at Microsoft Redmond."
    )
    assert result.status == "UNMATCHED"
    assert result.is_eligible_for_factual_claims is False

def test_executive_ambiguous_different_company():
    """Guards against attributing a person with the same name working at another company."""
    anchor = TargetExecutiveAnchor(
        full_name="Gaurav Khatana",
        current_company="Ottobon",
        current_title="Founder"
    )
    # Search snippet found for an unrelated Gaurav Khatana at Siemens
    result = EntityResolver.resolve_executive(
        anchor=anchor,
        candidate_url="https://example.com/team/gaurav",
        candidate_title="Gaurav Khatana at Siemens Energy",
        candidate_text="Gaurav Khatana leads regional turbine sales for Siemens Energy in Germany."
    )
    assert result.status == "AMBIGUOUS"
    assert result.is_eligible_for_factual_claims is False
    assert any("Siemens" in flag for flag in result.conflict_flags)

def test_executive_noise_baby_name_directory_filtered():
    anchor = TargetExecutiveAnchor(
        full_name="Gaurav Khatana",
        current_company="Ottobon"
    )
    result = EntityResolver.resolve_executive(
        anchor=anchor,
        candidate_url="https://www.momjunction.com/baby-names/gaurav/",
        candidate_title="Gaurav - Meaning, Origin, and Numerology",
        candidate_text="Gaurav is a popular Indian masculine name meaning honor, pride, or respect."
    )
    assert result.status == "UNMATCHED"
    assert result.is_eligible_for_factual_claims is False
    assert any("momjunction" in flag for flag in result.conflict_flags)

def test_executive_name_only_without_anchors_is_ambiguous():
    """A bare name with zero company or title overlap must not be accepted for factual attribution."""
    anchor = TargetExecutiveAnchor(
        full_name="John Smith",
        current_company="Acme Aerospace",
        current_title="Director of Guidance"
    )
    result = EntityResolver.resolve_executive(
        anchor=anchor,
        candidate_url="https://blog.example.com/recent-podcast",
        candidate_title="Podcast Episode 42: Building High Performance Teams",
        candidate_text="We were joined by John Smith who discussed modern software management."
    )
    assert result.status == "AMBIGUOUS"
    assert result.is_eligible_for_factual_claims is False

def test_company_canonical_domain_match():
    anchor = TargetCompanyAnchor(
        company_name="Ottobon",
        website_domain="ottobon.com"
    )
    result = EntityResolver.resolve_company(
        anchor=anchor,
        candidate_url="https://ottobon.com/about",
        candidate_title="About Us - Ottobon",
        candidate_text="Ottobon builds autonomous relationship intelligence for founders."
    )
    assert result.status == "MATCH_CONFIRMED"
    assert result.is_eligible_for_factual_claims is True

def test_company_verified_job_portal():
    anchor = TargetCompanyAnchor(
        company_name="Ottobon",
        website_domain="ottobon.com"
    )
    result = EntityResolver.resolve_company(
        anchor=anchor,
        candidate_url="https://boards.greenhouse.io/ottobon/jobs/123456",
        candidate_title="Senior Platform Engineer at Ottobon",
        candidate_text="Ottobon is hiring a Senior Platform Engineer in San Francisco."
    )
    assert result.status == "MATCH_CONFIRMED"
    assert result.is_eligible_for_factual_claims is True

def test_company_short_generic_word_ambiguous():
    """Short words like 'Apex' or 'Stripe' without domain or industry proof must be marked ambiguous."""
    anchor = TargetCompanyAnchor(
        company_name="Apex"
    )
    result = EntityResolver.resolve_company(
        anchor=anchor,
        candidate_url="https://apex-plumbing.com",
        candidate_title="Apex Residential Services",
        candidate_text="Apex provides fast heating and plumbing repairs."
    )
    assert result.status == "AMBIGUOUS"
    assert result.is_eligible_for_factual_claims is False
