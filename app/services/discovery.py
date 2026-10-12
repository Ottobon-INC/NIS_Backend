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
        # If we have a name, use it, else guess from url
        query = contact.full_name
        if not query or query == "Unknown":
            for ident in identities:
                if ident.identifier_type == "profile_url":
                    # Simple heuristic to extract name from linkedin.com/in/john-doe
                    match = re.search(r'in/([^/]+)', ident.identifier)
                    if match:
                        query = match.group(1).replace('-', ' ')
                        break
        
        if not query:
            return []
            
        return [
            {
                "target_url": f'"{query}" (executive OR leader OR news OR interview)',
                "search_terms": [query],
                "entity_identifiers": []
            },
            {
                "target_url": f'site:linkedin.com/in/ "{query}"',
                "search_terms": [query],
                "entity_identifiers": []
            }
        ]

class AgentReachDiscoveryAdapter(DiscoveryAdapter):
    def can_handle(self, source: ResearchSource) -> bool:
        return source.id == "agent_reach"
        
    def generate_tasks(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        query = contact.full_name
        if not query or query == "Unknown":
            for ident in identities:
                if ident.identifier_type == "profile_url":
                    match = re.search(r'in/([^/]+)', ident.identifier)
                    if match:
                        query = match.group(1).replace('-', ' ')
                        break
        
        if not query:
            return []
            
        tasks = []
        # Generate target tasks for agent-reach
        for target in ["github", "twitter"]:
            tasks.append({
                "target_url": query,
                "agent_reach_target": target,
                "search_terms": [query],
                "entity_identifiers": []
            })
        return tasks

class SourceDiscoveryService:
    def __init__(self):
        self.adapters: List[DiscoveryAdapter] = [
            GeneralWebAdapter(),
            SearchDiscoveryAdapter(),
            AgentReachDiscoveryAdapter(),
        ]
        
    def generate_queries(self, source: ResearchSource, contact: Contact, identities: List[ExternalIdentity]) -> List[Dict[str, Any]]:
        for adapter in self.adapters:
            if adapter.can_handle(source):
                return adapter.generate_tasks(source, contact, identities)
        return []
