from typing import List, Dict, Any, Set
import re
from app.models.identity import Contact, ExternalIdentity
from app.models.research import ResearchSource

class DiscoveryAdapter:
    def can_handle(self, source: ResearchSource) -> bool:
        return False

    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        """Returns a list of target_metadata dicts for ResearchTask"""
        return []

def extract_profile_slug_and_name(contact: Contact, identities: List[ExternalIdentity]) -> tuple[str, str, str]:
    """Helper to extract best clean name and username slug from contact and identities."""
    name = (contact.full_name or "").strip()
    slug = ""
    linkedin_url = contact.profile_url or ""

    for ident in identities:
        if ident.provider == "linkedin" or ident.identifier_type in ["profile_url", "linkedin_url"]:
            linkedin_url = ident.identifier
            break

    if linkedin_url:
        match = re.search(r'in/([^/?#]+)', linkedin_url)
        if match:
            slug = match.group(1).strip()
            if not name or name in ["Unknown", "New Contact", "Pending research", "Analyzing profile..."] or len(name.split()) <= 1:
                try:
                    from app.services.identity import extract_name_from_linkedin_slug
                    extracted_name = extract_name_from_linkedin_slug(linkedin_url)
                    if extracted_name and extracted_name != "New Contact":
                        name = extracted_name
                except Exception:
                    pass

    company = (contact.current_company or "").strip()
    if company.lower() in ["pending research", "independent", "unknown", "[unverified]", "none", ""]:
        company = ""

    return name or "Target Contact", slug, company

class GeneralWebAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "general_web" or source.provider_type == "INTERNAL_HTTP"

    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        tasks = []
        seen = set()
        for ident in identities:
            if ident.identifier and ident.identifier.startswith("http") and ident.identifier not in seen:
                seen.add(ident.identifier)
                tasks.append({
                    "target_url": ident.identifier,
                    "search_terms": [contact.full_name or ""],
                    "entity_identifiers": [ident.identifier]
                })
        if not tasks and contact.profile_url:
            tasks.append({
                "target_url": contact.profile_url,
                "search_terms": [contact.full_name or ""],
                "entity_identifiers": [contact.profile_url]
            })
        return tasks

class SearchDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "duckduckgo"

    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        name, slug, company = extract_profile_slug_and_name(contact, identities)
        if not name or name == "Target Contact":
            return []

        clean_name = re.sub(r'\b[0-9a-f]{6,}\b', '', name).strip()
        clean_name = re.sub(r'\s+', ' ', clean_name)

        queries = []
        # Priority 1: Exact Name + LinkedIn (highest quality hit for professional cards)
        queries.append(f'"{clean_name}" linkedin')

        # Priority 2: Exact Name + Company (if company is known)
        if company:
            queries.append(f'"{clean_name}" "{company}"')

        # Priority 3: Unique profile slug (e.g. "dianadedkova" or "naveen-vallabhani")
        if slug and re.match(r'^[a-zA-Z0-9\-]{3,40}$', slug) and slug.lower() not in ["in", "pub", "profile"]:
            queries.append(f'"{slug}"')

        # Priority 4: Exact Name + professional leadership signals
        queries.append(f'"{clean_name}" (executive OR director OR officer OR founder OR leader OR engineer)')
        queries.append(f'"{clean_name}"')

        # Deduplicate while preserving order
        unique_queries = []
        for q in queries:
            if q not in unique_queries:
                unique_queries.append(q)

        tasks = []
        for q in unique_queries[:3]:  # Top 3 most precise queries
            tasks.append({
                "target_url": q,
                "query": q,
                "search_terms": [name],
                "entity_identifiers": [name]
            })
        return tasks

class GitHubDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "github"

    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        name, slug, company = extract_profile_slug_and_name(contact, identities)
        search_query = slug if slug else name
        if not search_query or search_query == "Target Contact":
            return []

        return [{
            "target_url": search_query,
            "query": search_query,
            "search_terms": [name, slug] if slug else [name],
            "entity_identifiers": [name]
        }]

class AcademicDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "academic_openalex"

    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        name, slug, company = extract_profile_slug_and_name(contact, identities)
        if not name or name == "Target Contact":
            return []

        return [{
            "target_url": name,
            "query": name,
            "search_terms": [name],
            "entity_identifiers": [name]
        }]

class CompanyWebDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "company_web"

    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        name, slug, company = extract_profile_slug_and_name(contact, identities)
        if not name or name == "Target Contact":
            return []

        if company:
            target = f'"{name}" "{company}"'
        elif slug and len(slug) >= 3:
            target = f'"{slug}"'
        else:
            target = f'"{name}"'

        return [{
            "target_url": target,
            "query": target,
            "search_terms": [name, company] if company else [name],
            "entity_identifiers": [name, company] if company else [name]
        }]

class NewsPublicDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "news_public"

    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        name, slug, company = extract_profile_slug_and_name(contact, identities)
        if not name or name == "Target Contact":
            return []

        # Strictly quote name to prevent fuzzy celebrity matching (e.g. Princess Diana)
        query = f'"{name}"'
        return [{
            "target_url": query,
            "query": query,
            "search_terms": [name],
            "entity_identifiers": [name]
        }]

class AgentReachDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "agent_reach"

    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        name, slug, company = extract_profile_slug_and_name(contact, identities)
        if not name or name == "Target Contact":
            return []

        query = f'"{name}"'
        return [{
            "target_url": query,
            "agent_reach_target": "web",
            "search_terms": [name],
            "entity_identifiers": [name]
        }]

class SourceDiscoveryService:
    def __init__(self):
        self.adapters: List[DiscoveryAdapter] = [
            GeneralWebAdapter(),
            SearchDiscoveryAdapter(),
            GitHubDiscoveryAdapter(),
            AcademicDiscoveryAdapter(),
            CompanyWebDiscoveryAdapter(),
            NewsPublicDiscoveryAdapter(),
            AgentReachDiscoveryAdapter(),
        ]

    def generate_queries(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        for adapter in self.adapters:
            if adapter.can_handle(source):
                return adapter.generate_tasks(source, contact, identities)
        return []
