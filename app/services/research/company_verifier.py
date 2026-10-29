import re
import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from pydantic import BaseModel, Field

logger = logging.getLogger("networkos")

# -----------------------------------------------------------------------------
# 1. KNOWN ENTERPRISE CATALOG (Tier 1 Global Companies)
# -----------------------------------------------------------------------------
KNOWN_ENTERPRISES: Set[str] = {
    # Tech Giants & Big Tech
    "google", "alphabet", "microsoft", "meta", "facebook", "apple", "amazon", "aws",
    "netflix", "uber", "stripe", "airbnb", "snowflake", "databricks", "oracle", "sap",
    "salesforce", "cisco", "intel", "nvidia", "ibm", "palantir", "twitter", "x", "linkedin",
    "spotify", "adobe", "twilio", "atlassian", "figma", "canva", "zoom", "shopify",
    "square", "block", "paypal", "doordash", "instacart", "lyft", "dropbox", "github",
    "reddit", "openai", "anthropic", "deepmind", "box", "workday", "servicenow", "splunk",
    "vmware", "dell", "hp", "samsung", "sony", "tencent", "alibaba", "bytedance",
    "cloudflare", "elastic", "mongodb", "datadog", "confluent", "hashicorp", "gitlab",
    "robinhood", "coinbase", "plaid", "brex", "ramp", "gusto", "notion", "airtable",
    
    # Global Consulting & Professional Services
    "mckinsey", "mckinsey & company", "bcg", "boston consulting group", "bain",
    "bain & company", "deloitte", "pwc", "pricewaterhousecoopers", "ey", "ernst & young",
    "kpmg", "accenture", "infosys", "tcs", "tata consultancy services", "wipro",
    "cognizant", "capgemini", "hcltech", "hcl",
    
    # Financial Services & Banking
    "jpmorgan", "jpmorgan chase", "goldman sachs", "morgan stanley", "citigroup", "citi",
    "bank of america", "wells fargo", "barclays", "hsbc", "ubs", "blackrock", "fidelity",
    "sequoia", "sequoia capital", "andreessen horowitz", "a16z", "y combinator", "yc",
    
    # Healthcare, Retail, Enterprise
    "walmart", "target", "costco", "johnson & johnson", "pfizer", "moderna", "unitedhealth",
    "cvs health", "ge", "general electric", "siemens", "boeing", "tesla", "spacex"
}

# -----------------------------------------------------------------------------
# 2. BUZZWORDS, ROLES & NOISE BLOCKLIST
# -----------------------------------------------------------------------------
NON_COMPANY_BUZZWORDS: Set[str] = {
    # LinkedIn Catchphrases & Statuses
    "top voice", "linkedin top voice", "open to work", "opentowork", "hiring",
    "we are hiring", "actively hiring", "looking for new opportunities", "seeking opportunities",
    "available for hire", "available for advisory", "open for collaborations",
    
    # Non-Company Functional Identifiers
    "angel investor", "investor", "advisor", "adviser", "board member", "board advisor",
    "mentor", "consultant", "keynote speaker", "speaker", "author", "tedx speaker",
    "bestselling author", "writer", "blogger", "podcaster", "creator", "content creator",
    "personal branding", "personal brand", "storyteller", "solopreneur", "freelancer",
    "builder", "indie hacker", "tech enthusiast", "evangelist", "advocate", "influencer",
    
    # Personal / Family / Community
    "father", "mother", "husband", "wife", "parent", "runner", "marathoner", "proud dad",
    "proud mom", "dog lover", "coffee lover", "book lover", "traveler", "alumnus", "alumna",
    "alum", "alumni", "fellow", "member", "volunteer", "community lead",
    
    # Generic Industry Buzzwords
    "stealth", "stealth startup", "stealth mode", "stealth ai", "stealth venture",
    "passionate about ai", "ai enthusiast", "future of work", "web3 enthusiast",
    "building the future", "transforming enterprise", "digital transformation",
    "growth hacker", "visionary", "thought leader", "problem solver",
    
    # Standard Job Titles (when appearing standalone without company)
    "founder", "co-founder", "founding engineer", "ceo", "chief executive officer",
    "cto", "chief technology officer", "coo", "chief operating officer", "cfo", "cmo", "cpo",
    "vp", "vice president", "director", "senior director", "managing director",
    "head of engineering", "head of product", "head of growth", "head of sales",
    "software engineer", "senior software engineer", "staff engineer", "principal engineer",
    "product manager", "lead architect", "solutions architect", "engineering manager"
}

# Corporate legal and organizational indicators
CORPORATE_INDICATORS: Set[str] = {
    "inc", "inc.", "corp", "corp.", "corporation", "ltd", "ltd.", "limited",
    "llc", "llp", "gmbh", "ag", "pvt", "pvt.", "private limited", "co", "co.",
    "company", "technologies", "tech", "software", "labs", "systems", "solutions",
    "health", "therapeutics", "pharma", "biotech", "capital", "ventures", "partners",
    "group", "holdings", "media", "networks", "security", "data", "cloud"
}


class VerifiedCompany(BaseModel):
    name: str = Field(description="Normalized official company name")
    tenure_type: str = Field(default="PAST", description="'PAST', 'CURRENT', or 'AFFILIATION'")
    is_verified: bool = Field(default=False, description="True if proven to be a legitimate corporate entity")
    verification_tier: str = Field(default="UNVERIFIED", description="TIER_1_GLOBAL, TIER_2_DATABASE, TIER_3_CORPORATE_SIGNALS, or UNVERIFIED")
    raw_mention: Optional[str] = Field(default=None, description="Original raw snippet or headline token")
    source_context: Optional[str] = Field(default=None, description="Context excerpt supporting this affiliation")


class CompanyEntityVerifier:
    """
    Parses messy LinkedIn and web headlines containing separators (| , / @ • -)
    and verifies whether candidate strings represent authentic companies or noise.
    """

    @staticmethod
    def clean_token(token: str) -> str:
        """Cleans whitespace, quotes, and common punctuation from a candidate token."""
        if not token:
            return ""
        # Remove markdown, quotes, brackets
        t = re.sub(r'[\"\'`\[\]\(\)\{\}]', '', token).strip()
        # Remove trailing periods, commas, dashes
        t = re.sub(r'^[,\.\-\–\—\:\s]+|[,\.\-\–\—\:\s]+$', '', t)
        # Collapse multiple spaces
        return re.sub(r'\s+', ' ', t)

    @classmethod
    def extract_candidates_from_headline(cls, headline: str) -> List[Dict[str, Any]]:
        """
        Splits a headline or bio string across common separators:
        |, •, ·, /, @, –, —, -, \n, comma (when separating companies)
        Detects 'ex-', 'former', 'previously at' prefixes.
        """
        if not headline or not isinstance(headline, str):
            return []

        candidates: List[Dict[str, Any]] = []

        # 1. Normalize linebreaks and primary separators
        # Replace bullets, pipes, slashes, em-dashes with pipe
        normalized = re.sub(r'[\r\n\t]+', ' | ', headline)
        normalized = re.sub(r'[\•\·\|\/]+', ' | ', normalized)
        normalized = re.sub(r'\s+[\–\—\-]\s+', ' | ', normalized)

        # 2. Split on pipes
        segments = [s.strip() for s in normalized.split('|') if s.strip()]

        for seg in segments:
            # Check for '@ Company' pattern
            at_matches = re.findall(r'@\s*([A-Za-z0-9\.\&\s\-\'\’]+)', seg)
            has_specific_match = False

            for m in at_matches:
                cand = cls.clean_token(m)
                if cand:
                    has_specific_match = True
                    candidates.append({
                        "raw_token": cand,
                        "is_past": False,
                        "original_segment": seg
                    })

            # Check for 'ex-Company' or 'ex Company' or 'formerly at Company'
            ex_matches = re.finditer(
                r'(?:\b(?:ex[\-\s]|former(?:ly)?\s+(?:at\s+)?|previously\s+(?:at\s+)?|past:\s*|alumn(?:i|us)\s+(?:of\s+)?))\s*([A-Za-z0-9\.\&\s\-\'\’]+)',
                seg,
                re.IGNORECASE
            )
            for em in ex_matches:
                cand_str = em.group(1).strip()
                # If there are sub-commas (e.g. "ex-Google, Meta, Stripe"), split by comma
                sub_parts = [p.strip() for p in cand_str.split(',') if p.strip()]
                for sp in sub_parts:
                    cand = cls.clean_token(sp)
                    # Strip any residual prefixes
                    cand = re.sub(r'^(?:ex[\-\s]|former(?:ly)?\s+(?:at\s+)?|previously\s+(?:at\s+)?)', '', cand, flags=re.IGNORECASE).strip()
                    if cand:
                        has_specific_match = True
                        candidates.append({
                            "raw_token": cand,
                            "is_past": True,
                            "original_segment": seg
                        })

            # If no specific pattern matched, inspect clean standalone segment
            if not has_specific_match:
                seg_cleaned = cls.clean_token(seg)
                # Strip leading title/role keywords
                cleaned_standalone = re.sub(r'^(?:founder|ceo|cto|coo|vp|director|head|lead)\s+(?:of|at|@)?\s*', '', seg_cleaned, flags=re.IGNORECASE).strip()
                # Strip ex- prefix if present
                is_past_seg = bool(re.search(r'\b(?:ex[\-\s]|former|previously)\b', cleaned_standalone, re.IGNORECASE))
                cleaned_standalone = re.sub(r'^(?:ex[\-\s]|former(?:ly)?\s+(?:at\s+)?|previously\s+(?:at\s+)?)', '', cleaned_standalone, flags=re.IGNORECASE).strip()

                if cleaned_standalone and 2 <= len(cleaned_standalone) <= 45:
                    candidates.append({
                        "raw_token": cleaned_standalone,
                        "is_past": is_past_seg,
                        "original_segment": seg
                    })

        return candidates

    @classmethod
    def verify_company_entity(
        cls,
        candidate_name: str,
        supporting_text: Optional[str] = None,
        db_known_companies: Optional[Set[str]] = None
    ) -> Tuple[bool, str, str]:
        """
        Verifies whether candidate_name is an authentic company entity.
        Returns: (is_verified: bool, tier: str, normalized_name: str)
        """
        cleaned = cls.clean_token(candidate_name)
        norm = cleaned.lower()

        # Step 0: Immediate rejection of noise, stopwords, and buzzwords
        if not norm or len(norm) < 2:
            return False, "UNVERIFIED", cleaned

        if norm in NON_COMPANY_BUZZWORDS:
            return False, "REJECTED_BUZZWORD", cleaned

        # Check if candidate is purely a role or title (e.g. "Senior Software Engineer")
        if any(norm == bw or norm.startswith(f"{bw} ") or norm.endswith(f" {bw}") for bw in [
            "engineer", "manager", "developer", "architect", "consultant", "analyst", "specialist"
        ]) and not any(ind in norm.split() for ind in CORPORATE_INDICATORS):
            return False, "REJECTED_ROLE_TITLE", cleaned

        # Step 1: Tier 1 Global Enterprise Catalog
        if norm in KNOWN_ENTERPRISES:
            return True, "TIER_1_GLOBAL", cleaned.title()

        # Check token match against Big Tech with prefix/suffix (e.g. "Google Cloud" -> Google)
        for ke in KNOWN_ENTERPRISES:
            if re.search(rf'\b{re.escape(ke)}\b', norm):
                return True, "TIER_1_GLOBAL", cleaned.title()

        # Step 2: Tier 2 Database Known Companies
        if db_known_companies and norm in db_known_companies:
            return True, "TIER_2_DATABASE", cleaned.title()

        # Step 3: Tier 3 Corporate Entity Signals
        # 3a. Check for corporate legal indicators (Inc, Ltd, Corp, LLC, Technologies, Labs)
        words = norm.split()
        if any(w.rstrip('.') in CORPORATE_INDICATORS for w in words):
            return True, "TIER_3_CORPORATE_INDICATOR", cleaned.title()

        # 3b. Check supporting evidence snippet for employer / corporate phrasing
        if supporting_text:
            text_norm = supporting_text.lower()
            escaped_cand = re.escape(norm)
            patterns = [
                rf'(?:worked\s+at|employed\s+at|engineer\s+at|lead\s+at|role\s+at|team\s+at)\s+{escaped_cand}\b',
                rf'\b{escaped_cand}\s+(?:inc|corp|corporation|ltd|limited|llc|technologies|solutions|labs)\b',
                rf'(?:founded|co-founded|started)\s+{escaped_cand}\b',
                rf'\b{escaped_cand}\s+(?:headquarters|office|raised|acquired|announced|platform)\b',
            ]
            for pat in patterns:
                if re.search(pat, text_norm):
                    return True, "TIER_3_SNIPPET_VERIFIED", cleaned.title()

        # Single word without indicators (e.g. "Builder", "Strategy", "Impact") is rejected
        if len(words) == 1 and norm not in KNOWN_ENTERPRISES:
            return False, "UNVERIFIED_GENERIC_WORD", cleaned

        return False, "UNVERIFIED", cleaned

    @classmethod
    def extract_and_verify_career_history(
        cls,
        text_samples: List[str],
        db_known_companies: Optional[Set[str]] = None
    ) -> List[VerifiedCompany]:
        """
        Takes raw text snippets / search hits, extracts candidate company mentions,
        runs 3-tier entity verification, and returns deduplicated verified companies.
        """
        verified_companies: List[VerifiedCompany] = []
        seen_names: Set[str] = set()

        for text in text_samples:
            if not text:
                continue

            candidates = cls.extract_candidates_from_headline(text)
            for c in candidates:
                raw_token = c["raw_token"]
                is_past = c["is_past"]

                is_valid, tier, norm_name = cls.verify_company_entity(
                    candidate_name=raw_token,
                    supporting_text=text,
                    db_known_companies=db_known_companies
                )

                if is_valid:
                    key = norm_name.lower()
                    if key not in seen_names:
                        seen_names.add(key)
                        verified_companies.append(
                            VerifiedCompany(
                                name=norm_name,
                                tenure_type="PAST" if is_past else "CURRENT",
                                is_verified=True,
                                verification_tier=tier,
                                raw_mention=raw_token,
                                source_context=c.get("original_segment")
                            )
                        )

        return verified_companies
