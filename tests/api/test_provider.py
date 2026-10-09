import pytest
from app.services.providers.base import ResearchProvider

class MockProvider(ResearchProvider):
    def get_provider_metadata(self):
        return {"id": "mock"}

def test_provider_interface_unsupported_methods():
    provider = MockProvider()
    with pytest.raises(NotImplementedError):
        provider.search_person("John")
