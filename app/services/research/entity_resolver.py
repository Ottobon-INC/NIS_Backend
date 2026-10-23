import re
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from app.schemas.epistemic_evidence import IdentityMatchStatus


class TargetExecutiveAnchor(BaseModel):
    """Known anchor attributes for an executive being researched."""
    full_name: str
    current_company: Optional[str] = None
    current_title: Optional[str] = None
    location: Optional[str] = None
    profile_url: Optional[str] = None           # e.g., "https://www.linkedin.com/in/gaurav-khatana-1234"
    company_domain: Optional[str] = None        # e.g., "ottobon.com"


class TargetCompanyAnchor(BaseModel):
    """Known anchor attributes for a company being researched."""
    company_name: str
    website_domain: Optional[str] = None        # e.g., "ottobon.com"
    industry: Optional[str] = None


class EntityResolutionResult(BaseModel):
    """Audit result of verifying whether a source or candidate document refers to the intended entity."""
    status: IdentityMatchStatus
    matched_anchors: List[str] = Field(default_factory=list)
    conflict_flags: List[str] = Field(default_factory=list)
    resolution_notes: str
    is_eligible_for_factual_claims: bool = False


class EntityResolver:
    """
    Deterministically resolves candidate documents, search snippets, and URLs against
    target entity anchors BEFORE any factual claims may be extracted or attributed.
    """

    @staticmethod
    def _extract_domain(url: Optional[str]) -> str:
        if not url:
            return ""
        u = url.strip().lower()
        if not (u.startswith("http://") or u.startswith("https://") or u.startswith("//")):
            u = "https://" + u
        try:
            parsed = urlparse(u)
            netloc = parsed.netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            return netloc
        except Exception:
            return ""

    @staticmethod
    def _extract_linkedin_slug(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        match = re.search(r'linkedin\.com/in/([a-zA-Z0-9_-]+)', url.lower())
        if match:
            slug = match.group(1).rstrip('/')
            return slug
        return None

    @classmethod
    def resolve_executive(
        cls,
        anchor: TargetExecutiveAnchor,
        candidate_url: Optional[str],
        candidate_title: Optional[str],
        candidate_text: str
    ) -> EntityResolutionResult:
        """
        Determines whether a candidate source refers to the intended executive.
        Enforces strict disambiguation between individuals sharing identical names.
        """
        norm_name = anchor.full_name.strip().lower()
        if not norm_name:
            return EntityResolutionResult(
                status="UNMATCHED",
                resolution_notes="Target full name is empty. Cannot perform identity resolution.",
                is_eligible_for_factual_claims=False
            )

        cand_domain = cls._extract_domain(candidate_url)
        matched_anchors: List[str] = []
        conflict_flags: List[str] = []

        # 0. Early Filter: Exclude known noise / baby name / nursery domains
        junk_domains = ["momjunction.com", "kidpaw.com", "babynames.com", "names.org", "behindthename.com"]
        if any(j in cand_domain for j in junk_domains):
            conflict_flags.append(f"Excluded noise domain: {cand_domain}")
            return EntityResolutionResult(
                status="UNMATCHED",
                matched_anchors=[],
                conflict_flags=conflict_flags,
                resolution_notes="Disqualified: Source is an etymology / baby name dictionary, not an executive source.",
                is_eligible_for_factual_claims=False
            )

        # 1. LinkedIn Slug Direct Anchor Check
        target_slug = cls._extract_linkedin_slug(anchor.profile_url)
        candidate_slug = cls._extract_linkedin_slug(candidate_url)
        if target_slug and candidate_slug:
            if target_slug == candidate_slug:
                matched_anchors.append("exact_linkedin_slug")
                return EntityResolutionResult(
                    status="MATCH_CONFIRMED",
                    matched_anchors=matched_anchors,
                    resolution_notes=f"Confirmed direct identity match via verified LinkedIn profile slug: {candidate_slug}",
                    is_eligible_for_factual_claims=True
                )
            else:
                conflict_flags.append(f"Target slug '{target_slug}' does not match candidate slug '{candidate_slug}'")
                return EntityResolutionResult(
                    status="UNMATCHED",
                    matched_anchors=[],
                    conflict_flags=conflict_flags,
                    resolution_notes="Candidate is a distinct LinkedIn profile for a different individual.",
                    is_eligible_for_factual_claims=False
                )

        norm_title = (candidate_title or "").lower()
        norm_text = candidate_text.lower()

        # 2. Name Presence Check
        name_in_title = norm_name in norm_title
        name_in_text = norm_name in norm_text

        if not (name_in_title or name_in_text):
            return EntityResolutionResult(
                status="UNMATCHED",
                matched_anchors=[],
                conflict_flags=["Target full name not found in title or text corpus."],
                resolution_notes=f"Source does not mention '{anchor.full_name}'.",
                is_eligible_for_factual_claims=False
            )

        matched_anchors.append("full_name_found")

        # 3. Company Domain & Name Alignment
        generic_companies = {"pending research", "unknown", "n/a", "none", "independent", "self-employed", "analyzing profile...", ""}
        has_company_anchor = bool(anchor.current_company and anchor.current_company.strip() and anchor.current_company.strip().lower() not in generic_companies)
        company_matched = False
        target_company_clean = (anchor.current_company or "").strip().lower()

        if has_company_anchor and target_company_clean:
            if target_company_clean in norm_text or target_company_clean in norm_title:
                matched_anchors.append(f"company_name_match:{target_company_clean}")
                company_matched = True

        target_domain = cls._extract_domain(anchor.company_domain)
        if target_domain and cand_domain and (target_domain in cand_domain or cand_domain in target_domain):
            matched_anchors.append(f"company_domain_match:{cand_domain}")
            company_matched = True

        # 4. Job Title / Role Alignment
        generic_titles = {"professional", "analyzing profile...", "unknown", "n/a", "none", "pending research", "executive", "team member", "practitioner", ""}
        has_title_anchor = bool(anchor.current_title and anchor.current_title.strip() and anchor.current_title.strip().lower() not in generic_titles)
        title_matched = False
        if has_title_anchor:
            target_title_clean = anchor.current_title.strip().lower()
            t_tokens = set(re.findall(r'\b\w{3,}\b', target_title_clean))
            corpus_tokens = set(re.findall(r'\b\w{3,}\b', norm_title + " " + norm_text[:1000]))
            overlap = t_tokens.intersection(corpus_tokens)
            if len(overlap) >= max(1, len(t_tokens) // 2):
                matched_anchors.append("title_role_alignment")
                title_matched = True

        # 5. Conflict & Disambiguation Rules
        # If the target has a known company, and candidate explicitly introduces person with this name
        # working at a completely different, unrelated company without mentioning target company:
        if has_company_anchor and not company_matched:
            alt_company_pattern = re.search(r'([\w\s]{3,30})\s*(?:at|@|,)\s*([A-Z][\w\s]{2,25})', candidate_title or "")
            if alt_company_pattern:
                alt_org = alt_company_pattern.group(2).strip()
                if alt_org.lower() != target_company_clean:
                    conflict_flags.append(f"Source associates '{anchor.full_name}' with '{alt_org}' rather than target company '{anchor.current_company}'.")
                    return EntityResolutionResult(
                        status="AMBIGUOUS",
                        matched_anchors=matched_anchors,
                        conflict_flags=conflict_flags,
                        resolution_notes=(
                            f"Ambiguous identity: Found individual with name '{anchor.full_name}', "
                            f"but affiliated with '{alt_org}' instead of target company '{anchor.current_company}'."
                        ),
                        is_eligible_for_factual_claims=False
                    )

        # 6. Synthesize Final Resolution Status
        if company_matched and (title_matched or "company_domain_match" in str(matched_anchors)):
            return EntityResolutionResult(
                status="MATCH_CONFIRMED",
                matched_anchors=matched_anchors,
                conflict_flags=conflict_flags,
                resolution_notes=f"Confirmed identity: Full name and company/domain anchors strongly aligned for '{anchor.full_name}'.",
                is_eligible_for_factual_claims=True
            )
        elif company_matched or title_matched:
            return EntityResolutionResult(
                status="PROBABLE",
                matched_anchors=matched_anchors,
                conflict_flags=conflict_flags,
                resolution_notes="Probable identity: Name match corroborated by partial company or title signal.",
                is_eligible_for_factual_claims=True
            )
        else:
            conflict_flags.append("No corroborating company, domain, or role anchors found to distinguish person.")
            return EntityResolutionResult(
                status="AMBIGUOUS",
                matched_anchors=matched_anchors,
                conflict_flags=conflict_flags,
                resolution_notes=(
                    f"Ambiguous identity: '{anchor.full_name}' was found in text, but has zero corroborating "
                    f"company or title anchors. Excluded from factual claim attribution to prevent wrong-person hallucination."
                ),
                is_eligible_for_factual_claims=False
            )

    LEGAL_AND_GEO_MODIFIERS = {
        'inc', 'incorporated', 'corp', 'corporation', 'llc', 'ltd', 'limited', 'co', 'company',
        'holdings', 'group', 'services', 'technologies', 'solutions', 'consulting', 'partners',
        'russia', 'russian', 'usa', 'us', 'uk', 'india', 'indian', 'germany', 'german',
        'france', 'french', 'singapore', 'australia', 'canada', 'global', 'international',
        'emea', 'apac', 'latam', 'na'
    }

    @classmethod
    def resolve_company(
        cls,
        anchor: TargetCompanyAnchor,
        candidate_url: Optional[str],
        candidate_title: Optional[str],
        candidate_text: str
    ) -> EntityResolutionResult:
        """
        Determines whether a candidate source refers to the intended company entity.
        Protects against homonyms, unrelated brands, and generic keyword collisions,
        while accurately associating regional subsidiaries and core parent organizations.
        """
        norm_company = anchor.company_name.strip().lower()
        if not norm_company:
            return EntityResolutionResult(
                status="UNMATCHED",
                resolution_notes="Target company name is empty.",
                is_eligible_for_factual_claims=False
            )

        # Handle parenthesized acronyms (e.g., "Amazon Web Services (AWS)")
        acronym_match = re.search(r'\(([a-z0-9]{2,10})\)', norm_company)
        acronym = acronym_match.group(1) if acronym_match else ""
        name_no_parens = re.sub(r'\s*\([^)]*\)', '', norm_company).strip()

        core_tokens = [t for t in re.findall(r'\b\w+\b', name_no_parens) if t not in cls.LEGAL_AND_GEO_MODIFIERS]
        core_company = " ".join(core_tokens) if core_tokens else name_no_parens

        cand_domain = cls._extract_domain(candidate_url)
        target_domain = cls._extract_domain(anchor.website_domain)
        matched_anchors: List[str] = []
        conflict_flags: List[str] = []

        # Disqualify generic third-party search engines and aggregators that are not official company portals
        generic_noise_domains = ["google.", "search.google", "bing.com", "duckduckgo.com", "yahoo.com", "youtube.com"]
        if any(g in cand_domain for g in generic_noise_domains):
            return EntityResolutionResult(
                status="UNMATCHED",
                conflict_flags=[f"Domain '{cand_domain}' is a generic public platform/search engine."],
                resolution_notes=f"Source domain '{cand_domain}' is not an authorized organizational repository for '{anchor.company_name}'.",
                is_eligible_for_factual_claims=False
            )

        # 1. Canonical Domain Exact Match or Core Brand Domain Match
        if target_domain and cand_domain:
            if target_domain == cand_domain or cand_domain.endswith(f".{target_domain}"):
                matched_anchors.append(f"exact_domain:{cand_domain}")
                return EntityResolutionResult(
                    status="MATCH_CONFIRMED",
                    matched_anchors=matched_anchors,
                    resolution_notes=f"Confirmed direct company identity via official domain: {cand_domain}",
                    is_eligible_for_factual_claims=True
                )

        if cand_domain and (core_company or acronym):
            clean_dom = cand_domain[4:] if cand_domain.startswith("www.") else cand_domain
            compact_core = core_company.replace(" ", "")
            is_brand_domain = False
            if len(core_company) >= 3 and (
                clean_dom == f"{core_company}.com" or clean_dom.endswith(f".{core_company}.com") or clean_dom.startswith(f"{core_company}.")
                or (compact_core and (clean_dom == f"{compact_core}.com" or clean_dom.endswith(f".{compact_core}.com") or clean_dom.startswith(f"{compact_core}.")))
            ):
                is_brand_domain = True
            elif acronym and len(acronym) >= 2 and (
                clean_dom == f"{acronym}.com" or clean_dom.startswith(f"{acronym}.") or clean_dom.endswith(f".{acronym}.com")
            ):
                is_brand_domain = True

            if is_brand_domain:
                matched_anchors.append(f"official_brand_domain:{cand_domain}")
                return EntityResolutionResult(
                    status="MATCH_CONFIRMED",
                    matched_anchors=matched_anchors,
                    resolution_notes=f"Confirmed organization identity via primary brand domain: {cand_domain}",
                    is_eligible_for_factual_claims=True
                )

        norm_title = (candidate_title or "").lower()
        norm_text = candidate_text.lower()

        # 2. Known Official Aggregator / Knowledge Base / Job Board matching
        reputable_platforms = ["greenhouse.io", "lever.co", "workday.com", "jobs.ashbyhq.com", "linkedin.com", "wikipedia.org", "en.wikipedia.org"]
        if any(p in cand_domain for p in reputable_platforms):
            slug_match = (
                norm_company in (candidate_url or "").lower()
                or name_no_parens in (candidate_url or "").lower()
                or (core_company and core_company in (candidate_url or "").lower())
                or (acronym and f"/{acronym}" in (candidate_url or "").lower())
            )
            title_match = (
                norm_company in norm_title
                or name_no_parens in norm_title
                or (core_company and core_company in norm_title)
                or (acronym and f"({acronym})" in norm_title)
            )
            if slug_match or title_match:
                matched_anchors.append(f"verified_platform_slug:{cand_domain}")
                return EntityResolutionResult(
                    status="MATCH_CONFIRMED",
                    matched_anchors=matched_anchors,
                    resolution_notes=f"Confirmed company identity via verified organizational knowledge portal: {cand_domain}",
                    is_eligible_for_factual_claims=True
                )

        # 3. Company Name or Core Brand Mention
        company_in_title = (
            norm_company in norm_title
            or name_no_parens in norm_title
            or (core_company and core_company in norm_title)
            or (acronym and f"({acronym})" in norm_title)
        )
        company_in_text = (
            norm_company in norm_text
            or name_no_parens in norm_text
            or (core_company and core_company in norm_text)
            or (acronym and (f"({acronym})" in norm_text or f" {acronym} " in norm_text))
        )

        if not (company_in_title or company_in_text):
            return EntityResolutionResult(
                status="UNMATCHED",
                matched_anchors=[],
                conflict_flags=["Target company name not found in title or content."],
                resolution_notes=f"Source does not mention '{anchor.company_name}'.",
                is_eligible_for_factual_claims=False
            )

        matched_anchors.append("company_name_found")

        # 4. Industry Corroboration
        if anchor.industry:
            ind_tokens = set(re.findall(r'\b\w{4,}\b', anchor.industry.lower()))
            text_tokens = set(re.findall(r'\b\w{4,}\b', norm_title + " " + norm_text[:2000]))
            if ind_tokens.intersection(text_tokens):
                matched_anchors.append("industry_corroboration")
                return EntityResolutionResult(
                    status="PROBABLE",
                    matched_anchors=matched_anchors,
                    resolution_notes=f"Probable company match: '{anchor.company_name}' with industry signal alignment.",
                    is_eligible_for_factual_claims=True
                )

        # If name is a very short generic dictionary word without domain or industry proof
        if len(norm_company.split()) == 1 and len(norm_company) <= 5 and not target_domain:
            conflict_flags.append(f"Short generic word '{norm_company}' with no domain or industry corroboration.")
            return EntityResolutionResult(
                status="AMBIGUOUS",
                matched_anchors=matched_anchors,
                conflict_flags=conflict_flags,
                resolution_notes=f"Ambiguous company reference: '{anchor.company_name}' is a short generic brand without domain proof.",
                is_eligible_for_factual_claims=False
            )

        return EntityResolutionResult(
            status="PROBABLE",
            matched_anchors=matched_anchors,
            conflict_flags=conflict_flags,
            resolution_notes=f"Probable company mention of '{anchor.company_name}' in public web context.",
            is_eligible_for_factual_claims=True
        )
