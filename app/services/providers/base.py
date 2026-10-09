from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class ResearchProvider(ABC):
    @abstractmethod
    def get_provider_metadata(self) -> Dict[str, Any]:
        pass

    def search_person(self, query: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("search_person not supported by this provider")

    def search_company(self, query: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("search_company not supported by this provider")

    def fetch_person(self, identifier: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("fetch_person not supported by this provider")

    def fetch_company(self, identifier: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("fetch_company not supported by this provider")

    def fetch_signals(self, query: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("fetch_signals not supported by this provider")
