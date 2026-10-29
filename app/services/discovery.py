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

        tasks: List[Dict[str, Any]] = []

        # -------------------------------------------------------------
        # Angle 1: Identity & Professional Anchor
        # -------------------------------------------------------------
        if slug and re.match(r'^[a-zA-Z0-9\-]{3,60}$', slug) and slug.lower() not in ["in", "pub", "profile"]:
            id_query = f"site:linkedin.com/in/{slug}"
        elif company:
            id_query = f'"{clean_name}" "{company}" linkedin'
        else:
            id_query = f'"{clean_name}" linkedin'

        tasks.append({
            "target_url": id_query,
            "query": id_query,
            "angle": "IDENTITY",
            "search_terms": [clean_name],
            "entity_identifiers": [clean_name]
        })

        # -------------------------------------------------------------
        # Angle 2: Career History & Past Experiences (Ex-companies, formerly at)
        # -------------------------------------------------------------
        career_query = f'"{clean_name}" ("formerly at" OR "previous role" OR "worked at" OR "career" OR "experience" OR "ex-")'
        tasks.append({
            "target_url": career_query,
            "query": career_query,
            "angle": "CAREER_HISTORY",
            "search_terms": [clean_name, "career"],
            "entity_identifiers": [clean_name]
        })

        # -------------------------------------------------------------
        # Angle 3: Technical Projects & Architectures Built
        # -------------------------------------------------------------
        projects_query = f'"{clean_name}" ("built" OR "architected" OR "developed" OR "system" OR "platform" OR "lead engineer")'
        tasks.append({
            "target_url": projects_query,
            "query": projects_query,
            "angle": "PROJECTS_BUILT",
            "search_terms": [clean_name, "projects"],
            "entity_identifiers": [clean_name]
        })

        # -------------------------------------------------------------
        # Angle 4: Summits, Conferences, Keynotes & Podcasts
        # -------------------------------------------------------------
        talks_query = f'"{clean_name}" ("speaker" OR "summit" OR "keynote" OR "conference" OR "podcast" OR "interview")'
        tasks.append({
            "target_url": talks_query,
            "query": talks_query,
            "angle": "SUMMITS_AND_TALKS",
            "search_terms": [clean_name, "speaker"],
            "entity_identifiers": [clean_name]
        })

        # -------------------------------------------------------------
        # Angle 5: Writings, Research, Articles & Substack
        # -------------------------------------------------------------
        writings_query = f'"{clean_name}" ("author" OR "article" OR "paper" OR "published" OR "substack" OR "medium" OR "patent")'
        tasks.append({
            "target_url": writings_query,
            "query": writings_query,
            "angle": "WRITINGS_AND_RESEARCH",
            "search_terms": [clean_name, "publications"],
            "entity_identifiers": [clean_name]
        })

        # -------------------------------------------------------------
        # Angle 6: LinkedIn Posts & Pulse Articles
        # -------------------------------------------------------------
        posts_query = f'site:linkedin.com/posts/ "{clean_name}" OR site:linkedin.com/pulse/ "{clean_name}"'

        tasks.append({
            "target_url": posts_query,
            "query": posts_query,
            "angle": "POSTS_AND_ARTICLES",
            "search_terms": [clean_name, "posts"],
            "entity_identifiers": [clean_name]
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

        query = f'"{name}" "{company}"' if company else name
        return [{
            "target_url": query,
            "query": query,
            "search_terms": [name, company] if company else [name],
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
