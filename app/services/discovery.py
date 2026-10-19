from typing import List, Dict, Any
import re
from app.models.identity import Contact, ExternalIdentity
from app.models.research import ResearchSource

class DiscoveryAdapter:
    def can_handle(self, source: ResearchSource) -> bool:
        return False
    
    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        """Returns a list of target_metadata dicts for ResearchTask"""
        return []

def extract_identity_anchors(contact: Contact, identities: List[ExternalIdentity]):
    profile_url = contact.profile_url or ""
    if not profile_url:
        for ident in identities:
            if ident.identifier_type == "profile_url" or ident.provider == "linkedin":
                profile_url = ident.identifier
                break

    slug = ""
    if profile_url:
        m = re.search(r'in/([^/?#]+)', profile_url)
        if m:
            slug = m.group(1).strip()

    name = contact.full_name
    if not name or name in ("Unknown", "New Contact", "Pending research"):
        if slug:
            clean_parts = [p for p in slug.split('-') if not (p.isdigit() or (len(p) > 10 and any(c.isdigit() for c in p)))]
            if clean_parts:
                name = " ".join(p.capitalize() for p in clean_parts)
    
    clean_name = name or ""
    return slug, clean_name

class GeneralWebAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.provider_type == "INTERNAL_HTTP" or source.id == "general_web"
        
    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        tasks = []
        for ident in identities:
            if ident.identifier_type == "profile_url" and ident.identifier:
                tasks.append({
                    "target_url": ident.identifier,
                    "search_terms": [],
                    "entity_identifiers": [ident.identifier]
                })
        return tasks

class SearchDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "duckduckgo"
        
    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        slug, query = extract_identity_anchors(contact, identities)
        if not query:
            return []
            
        tasks = []
        if slug:
            tasks.append({
                "target_url": f'"{query}" "{slug}"',
                "search_terms": [query, slug],
                "entity_identifiers": [slug]
            })
            tasks.append({
                "target_url": f'"{query}" linkedin',
                "search_terms": [query],
                "entity_identifiers": []
            })
            tasks.append({
                "target_url": f'"{query}"',
                "search_terms": [query],
                "entity_identifiers": []
            })
        else:
            tasks.append({
                "target_url": f'"{query}"',
                "search_terms": [query],
                "entity_identifiers": []
            })
            tasks.append({
                "target_url": f'"{query}" linkedin',
                "search_terms": [query],
                "entity_identifiers": []
            })
        return tasks

class AgentReachDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "agent_reach"
        
    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        slug, query = extract_identity_anchors(contact, identities)
        if not query:
            return []
            
        tasks = []
        for target in ["github", "web"]:
            tasks.append({
                "target_url": query,
                "agent_reach_target": target,
                "search_terms": [query],
                "entity_identifiers": [slug] if slug else []
            })
        return tasks

class GithubDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "github"
        
    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        slug, query = extract_identity_anchors(contact, identities)
        if not query:
            return []
        return [{
            "target_url": query,
            "query": query,
            "search_terms": [query],
            "entity_identifiers": [query]
        }]

class CompanyWebDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "company_web"
        
    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        slug, query = extract_identity_anchors(contact, identities)
        company = contact.current_company if contact.current_company and contact.current_company not in ("Pending research", "Independent", "Unknown") else ""
        if not query:
            return []
        search_target = f'"{query}" "{company}"' if company else f'"{query}"'
        return [{
            "target_url": search_target,
            "query": search_target,
            "search_terms": [query, company] if company else [query],
            "entity_identifiers": [query]
        }]

class NewsPublicDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "news_public"
        
    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        slug, query = extract_identity_anchors(contact, identities)
        if not query:
            return []
        search_target = f'"{query}"'
        return [{
            "target_url": search_target,
            "query": search_target,
            "search_terms": [query],
            "entity_identifiers": [query]
        }]

class AcademicDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "academic_openalex"
        
    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        slug, query = extract_identity_anchors(contact, identities)
        if not query:
            return []
        search_target = f'"{query}"'
        return [{
            "target_url": search_target,
            "query": search_target,
            "search_terms": [query],
            "entity_identifiers": [query]
        }]

class SourceDiscoveryService:
    def __init__(self):
        self.adapters: List[DiscoveryAdapter] = [
            GeneralWebAdapter(),
            SearchDiscoveryAdapter(),
            AgentReachDiscoveryAdapter(),
            GithubDiscoveryAdapter(),
            CompanyWebDiscoveryAdapter(),
            NewsPublicDiscoveryAdapter(),
            AcademicDiscoveryAdapter(),
        ]
        
    def generate_queries(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        for adapter in self.adapters:
            if adapter.can_handle(source):
                return adapter.generate_tasks(source, contact, identities)
        return []
