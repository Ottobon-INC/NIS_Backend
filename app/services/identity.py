import logging
import uuid
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.identity import Contact, ExternalIdentity, ContactStatus
from app.models.evidence import SourceResult, Evidence, EvidenceType

logger = logging.getLogger("networkos")

def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text.strip().lower())

def tokens_match(str_a: str, str_b: str) -> bool:
    """Checks if substantial tokens overlap between two strings."""
    tokens_a = set(re.findall(r'\b\w{3,}\b', normalize_text(str_a)))
    tokens_b = set(re.findall(r'\b\w{3,}\b', normalize_text(str_b)))
    if not tokens_a or not tokens_b:
        return False
    return len(tokens_a.intersection(tokens_b)) > 0

def canonicalize_linkedin_url(url: str) -> str:
    """
    Validates and canonicalizes a LinkedIn profile URL to canonical form:
    https://www.linkedin.com/in/<username>
    Strips trailing slashes, query parameters, anchors, and standardizes subdomains.
    Raises ValueError on invalid or non-LinkedIn URLs.
    """
    if not url or not isinstance(url, str):
        raise ValueError("LinkedIn URL is required")

    cleaned = url.strip()
    if not cleaned:
        raise ValueError("LinkedIn URL is required")

    from urllib.parse import urlparse
    parsed_input = cleaned if "://" in cleaned else f"https://{cleaned}"
    parsed = urlparse(parsed_input)

    netloc = parsed.netloc.lower()
    if not (netloc == "linkedin.com" or netloc.endswith(".linkedin.com")):
        raise ValueError("URL host must be linkedin.com or a valid subdomain")

    path = parsed.path.rstrip('/')
    match = re.search(r'^/in/([a-zA-Z0-9_-]+)$', path, re.IGNORECASE)
    if not match:
        raise ValueError("Invalid LinkedIn URL format. Must be like https://www.linkedin.com/in/username")

    slug = match.group(1).lower()
    return f"https://www.linkedin.com/in/{slug}"

def extract_linkedin_slug(url_or_slug: Optional[str]) -> Optional[str]:
    """Extracts lowercase profile slug from a LinkedIn URL or slug string."""
    if not url_or_slug:
        return None
    url_clean = str(url_or_slug).strip().lower()
    m = re.search(r'linkedin\.com/in/([a-zA-Z0-9_-]+)', url_clean)
    if m:
        return m.group(1).rstrip('/')
    m2 = re.search(r'(?:^|/)in/([a-zA-Z0-9_-]+)', url_clean)
    if m2:
        return m2.group(1).rstrip('/')
    if re.match(r'^[a-zA-Z0-9_-]{3,60}$', url_clean) and url_clean not in ["in", "pub", "profile"]:
        return url_clean
    return None

def extract_name_from_linkedin_slug(url_or_slug: str) -> str:
    """Extracts a human-readable candidate name from a LinkedIn URL or slug."""
    if not url_or_slug:
        return "New Contact"
    m = re.search(r'in/([^/?#]+)', url_or_slug)
    slug = m.group(1) if m else url_or_slug.strip()
    clean_parts = [p for p in slug.split('-') if not any(c.isdigit() for c in p) and p.strip()]
    if len(clean_parts) > 1:
        return " ".join(p.capitalize() for p in clean_parts)
    elif len(clean_parts) == 1:
        single = clean_parts[0]
        if len(single) > 7:
            try:
                from langchain_openai import ChatOpenAI
                from app.core.config import settings
                llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, api_key=settings.OPENAI_API_KEY)
                res = llm.invoke(f"Segment this concatenated username into properly capitalized separate words (return ONLY the person name, nothing else): {single}").content.strip()
                if res and len(res.split()) > 1:
                    return res
            except Exception as e:
                logger.warning(f"Fast slug segmentation failed: {e}")
        return single.capitalize()
    return "New Contact"

def parse_date_safe(date_val: Any) -> Optional[datetime]:
    if not date_val:
        return None
    if isinstance(date_val, datetime):
        return date_val if date_val.tzinfo else date_val.replace(tzinfo=timezone.utc)
    s = str(date_val).strip()
    try:
        if len(s) == 4 and s.isdigit():
            return datetime(int(s), 1, 1, tzinfo=timezone.utc)
        clean = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

class IdentityResolver:
    @staticmethod
    async def process_source_result(db: AsyncSession, contact_id: str, source_result: SourceResult) -> Dict[str, Any]:
        """
        Processes a raw SourceResult, assesses identity match confidence,
        generates normalized claims, records conflicts, and persists Evidence rows.
        """
        if source_result.status != "SUCCESS":
            return {"match_status": "SKIPPED", "claims": []}

        c_res = await db.execute(select(Contact).where(Contact.id == contact_id))
        contact = c_res.scalars().first()
        if not contact:
            return {"match_status": "ERROR", "error": "Contact not found"}

        extracted = source_result.extracted_data or {}
        raw_text = extracted.get("text") or extracted.get("text_content") or ""
        source_id = source_result.source_id
        source_ref = source_result.raw_reference or source_result.query or ""

        target_name = contact.full_name or ""
        target_company = contact.current_company or ""
        if target_company.lower() in ["pending research", "independent", "unknown"]:
            target_company = ""

        match_status = "UNCERTAIN"  # CONFIRMED, PROBABLE, UNCERTAIN
        match_confidence = 50
        match_rationale = "General web mention"
        claims: List[Dict[str, Any]] = []

        # ==========================================================
        # 1. PROVIDER-SPECIFIC IDENTITY RESOLUTION & CLAIM PARSING
        # ==========================================================

        if source_id == "github":
            gh_data = extracted
            gh_name = gh_data.get("name") or gh_data.get("username") or ""
            gh_company = gh_data.get("company") or ""
            gh_bio = gh_data.get("bio") or ""

            # Check matching quality
            if target_name and tokens_match(target_name, gh_name):
                if target_company and tokens_match(target_company, gh_company):
                    match_status = "CONFIRMED"
                    match_confidence = 100
                    match_rationale = f"Exact name match '{gh_name}' and company match '{gh_company}'"
                elif gh_bio and target_company and tokens_match(target_company, gh_bio):
                    match_status = "CONFIRMED"
                    match_confidence = 95
                    match_rationale = f"Name match with company reference in bio: '{gh_company}'"
                else:
                    match_status = "PROBABLE"
                    match_confidence = 75
                    match_rationale = f"Matching name '{gh_name}' on GitHub; affiliation unverified"
            else:
                match_status = "UNCERTAIN"
                match_confidence = 40
                match_rationale = "GitHub handle match without confirmed real name overlap"

            if gh_data.get("profile_url"):
                claims.append({
                    "claim_type": "GITHUB_PROFILE",
                    "claim_value": f"GitHub @{gh_data.get('username')}: {gh_data.get('public_repos', 0)} public repos",
                    "confidence": match_confidence,
                    "excerpt": f"Bio: {gh_bio} | Company: {gh_company} | Location: {gh_data.get('location', '')}",
                    "observed_date": None
                })

            for repo in gh_data.get("repositories", [])[:3]:
                repo_date = parse_date_safe(repo.get("updated_at") or repo.get("created_at"))
                claims.append({
                    "claim_type": "PUBLIC_PROJECT",
                    "claim_value": f"Repository: {repo.get('name')} ({repo.get('language') or 'General'}) - {repo.get('stars', 0)} stars",
                    "confidence": match_confidence,
                    "excerpt": f"{repo.get('description')} ({repo.get('html_url')})",
                    "observed_date": repo_date
                })

        elif source_id == "academic_openalex":
            authors = extracted.get("authors", [])
            publications = extracted.get("publications", [])

            if authors:
                top_author = authors[0]
                auth_name = top_author.get("display_name", "")
                insts = top_author.get("institutions", [])

                # Check institutional match
                if target_company and any(tokens_match(target_company, inst) for inst in insts):
                    match_status = "CONFIRMED"
                    match_confidence = 100
                    match_rationale = f"Author '{auth_name}' matches name and affiliated institution"
                elif target_company:
                    # Institutional conflict: person belongs to a different known company
                    match_status = "UNCERTAIN"
                    match_confidence = 25
                    match_rationale = f"Author '{auth_name}' affiliated with '{', '.join(insts)}' conflicts with target company '{target_company}'"
                elif top_author.get("orcid"):
                    match_status = "UNCERTAIN"
                    match_confidence = 45
                    match_rationale = f"Scholar record with ORCID for '{auth_name}', but unanchored to professional company"
                else:
                    match_status = "UNCERTAIN"
                    match_confidence = 35
                    match_rationale = f"Unanchored scholar name collision for '{auth_name}'"

                claims.append({
                    "claim_type": "ACADEMIC_RECORD",
                    "claim_value": f"Scholar: {auth_name} ({top_author.get('works_count', 0)} publications, {top_author.get('cited_by_count', 0)} citations)",
                    "confidence": match_confidence,
                    "excerpt": f"Institutions: {', '.join(insts)} | Topics: {', '.join(top_author.get('topics', []))}",
                    "observed_date": None
                })

                for pub in publications[:3]:
                    pub_date = parse_date_safe(pub.get("year"))
                    claims.append({
                        "claim_type": "PUBLICATION",
                        "claim_value": f"Publication: \"{pub.get('title')}\" ({pub.get('year', 'N/A')})",
                        "confidence": match_confidence,
                        "excerpt": f"Citations: {pub.get('citations', 0)} | DOI: {pub.get('doi', 'N/A')}",
                        "observed_date": pub_date
                    })
            else:
                match_status = "SKIPPED"
                match_confidence = 0
                match_rationale = "No academic publications found"

        elif source_id == "company_web":
            comp_data = extracted
            title_text = comp_data.get("title", "")
            snippet_text = comp_data.get("snippet", "")

            if target_name and (tokens_match(target_name, title_text) or tokens_match(target_name, snippet_text) or tokens_match(target_name, raw_text)):
                match_status = "CONFIRMED"
                match_confidence = 100 if target_company and (tokens_match(target_company, title_text) or tokens_match(target_company, snippet_text) or tokens_match(target_company, raw_text)) else 90
                match_rationale = f"Official corporate webpage matches name '{target_name}'"
            else:
                match_status = "PROBABLE"
                match_confidence = 65
                match_rationale = "Company web search returned related organizational mentions"

            if snippet_text:
                claims.append({
                    "claim_type": "COMPANY_AFFILIATION",
                    "claim_value": f"Corporate Page: {title_text}",
                    "confidence": match_confidence,
                    "excerpt": snippet_text[:400],
                    "observed_date": None
                })

        elif source_id == "news_public":
            news_items = extracted.get("news", [])
            wikidata_items = extracted.get("wikidata", [])

            if wikidata_items:
                w_item = wikidata_items[0]
                claims.append({
                    "claim_type": "WIKIDATA_ENTITY",
                    "claim_value": f"Entity: {w_item.get('label')} ({w_item.get('id')}) - {w_item.get('description')}",
                    "confidence": 75,
                    "excerpt": f"Wikidata URL: {w_item.get('url')}",
                    "observed_date": None
                })

            for n in news_items[:3]:
                news_date = parse_date_safe(n.get("date"))
                claims.append({
                    "claim_type": "NEWS_MENTION",
                    "claim_value": f"Media: \"{n.get('title')}\" [{n.get('source', 'News')}]",
                    "confidence": 70,
                    "excerpt": f"{n.get('body')} (Date: {n.get('date', 'Recent')})",
                    "observed_date": news_date
                })

            match_status = "CONFIRMED" if (wikidata_items or news_items) else "PROBABLE"
            match_confidence = 75 if (wikidata_items or news_items) else 60
            match_rationale = "Public news index and Wikidata entities evaluated"

        elif source_id in ["general_web", "duckduckgo", "agent_reach"]:
            target_slug = extract_linkedin_slug(contact.profile_url)
            cand_slug = extract_linkedin_slug(source_ref) or extract_linkedin_slug(source_result.query)

            # Strict guard against LinkedIn profile slug collision / homonyms:
            if target_slug and cand_slug and target_slug != cand_slug:
                match_status = "UNCERTAIN"
                match_confidence = 10
                match_rationale = f"Disqualified: candidate LinkedIn slug '{cand_slug}' conflicts with target profile slug '{target_slug}'"
            elif "linkedin.com/in/" in source_ref or "site:linkedin.com/in/" in source_result.query:
                if target_slug and cand_slug and target_slug == cand_slug:
                    match_status = "CONFIRMED"
                    match_confidence = 100
                    match_rationale = f"Direct verified LinkedIn profile match (slug: {target_slug})"
                elif not target_slug:
                    if target_name and tokens_match(target_name, raw_text):
                        match_status = "PROBABLE"
                        match_confidence = 75
                        match_rationale = "Public LinkedIn profile name match without anchor slug verification"
                    else:
                        match_status = "UNCERTAIN"
                        match_confidence = 30
                        match_rationale = "Unverified LinkedIn profile reference"
                else:
                    match_status = "UNCERTAIN"
                    match_confidence = 30
                    match_rationale = "LinkedIn mention without matching profile slug"
            else:
                match_status = "PROBABLE"
                match_confidence = 70
                match_rationale = "Web search indexing for executive profile"

            meta_desc = extracted.get("meta_description") or ""
            title_text = extracted.get("title") or ""

            if meta_desc:
                claims.append({
                    "claim_type": "WEB_PROFILE",
                    "claim_value": f"Profile Summary: {title_text} | {meta_desc}"[:255],
                    "confidence": match_confidence,
                    "excerpt": f"Title: {title_text}\nSummary: {meta_desc}\n\n{raw_text[:1500]}",
                    "observed_date": None
                })
            elif raw_text:
                clean_raw = re.sub(r'Sign in to view.*?Cookie Policy \.', '', raw_text, flags=re.DOTALL).strip()
                first_line = clean_raw.split("\n")[0][:250] if clean_raw else raw_text[:250]
                claims.append({
                    "claim_type": "WEB_PROFILE",
                    "claim_value": f"Indexed Summary: {first_line}",
                    "confidence": match_confidence,
                    "excerpt": clean_raw[:1500] if clean_raw else raw_text[:1500],
                    "observed_date": None
                })

            # Run deterministic CompanyEntityVerifier on headline and snippet to verify authentic companies
            try:
                from app.services.research.company_verifier import CompanyEntityVerifier
                verified_comps = CompanyEntityVerifier.extract_and_verify_career_history([title_text, meta_desc])
                for vc in verified_comps:
                    comp_conf = 95 if vc.verification_tier in ["TIER_1_GLOBAL", "TIER_2_DATABASE"] else 80
                    claims.append({
                        "claim_type": "CAREER_HISTORY",
                        "claim_value": f"Verified Career Affiliation: {vc.name} ({vc.tenure_type})",
                        "confidence": comp_conf if match_status == "CONFIRMED" else min(comp_conf, 75),
                        "excerpt": f"Company '{vc.name}' verified via {vc.verification_tier}. Mention: '{vc.raw_mention}' in headline context: '{vc.source_context}'",
                        "observed_date": None
                    })
            except Exception as cv_err:
                logger.warning(f"CompanyEntityVerifier error in IdentityResolver: {cv_err}")


        # ==========================================================
        # 2. PERSIST ATOMIC EVIDENCE RECORDS
        # ==========================================================
        for c in claims:
            ev_id = str(uuid.uuid4())
            ev = Evidence(
                id=ev_id,
                evidence_type=EvidenceType.FACT if (c.get("confidence", 0) >= 85 and match_status == "CONFIRMED") else EvidenceType.SIGNAL,
                claim=c.get("claim_value", "")[:255],
                source_id=source_id,
                source_reference=source_ref,
                observed_date=c.get("observed_date"),  # None if missing, NOT replaced with now()
                retrieved_date=datetime.now(timezone.utc),
                confidence=c.get("confidence", 50),
                source_result_id=source_result.id,
                related_entity_id=contact_id
            )
            db.add(ev)
            c["evidence_id"] = ev_id

        # Update metadata on source_result
        curr_meta = dict(source_result.metadata_ or {})
        curr_meta.update({
            "identity_match_status": match_status,
            "identity_match_confidence": match_confidence,
            "identity_match_rationale": match_rationale,
            "claims_count": len(claims)
        })
        source_result.metadata_ = curr_meta

        # ==========================================================
        # 3. CONTACT PROGRESSION IF CONFIRMED ATTRIBUTES FOUND
        # ==========================================================
        if contact.status in [ContactStatus.NEW, ContactStatus.RESEARCHING]:
            contact.status = ContactStatus.RESEARCHING

        await db.commit()
        return {
            "match_status": match_status,
            "confidence": match_confidence,
            "rationale": match_rationale,
            "claims": claims
        }
