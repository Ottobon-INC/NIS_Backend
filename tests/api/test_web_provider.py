import pytest
import os
from app.services.web.url_security import validate_url_security, SSRError
from app.services.providers.web import GeneralWebProvider

def test_url_security_valid():
    os.environ["ENV"] = "test"
    assert validate_url_security("https://example.com/about") == "https://example.com/about"

def test_url_security_invalid_protocol():
    with pytest.raises(SSRError):
        validate_url_security("ftp://example.com")

def test_url_security_localhost():
    with pytest.raises(SSRError):
        validate_url_security("http://localhost:8080")

@pytest.mark.asyncio
async def test_general_web_provider_404():
    import respx
    import httpx
    provider = GeneralWebProvider()
    with respx.mock:
        respx.get("https://example.com/404").mock(return_value=httpx.Response(404))
        result = await provider.fetch_public_webpage("https://example.com/404")
        assert result["status"] == "NOT_FOUND"

@pytest.mark.asyncio
async def test_general_web_provider_success():
    import respx
    import httpx
    provider = GeneralWebProvider()
    html = "<html><head><title>Test</title></head><body><p>Hello World</p><script>alert(1);</script></body></html>"
    with respx.mock:
        respx.get("https://example.com").mock(return_value=httpx.Response(200, text=html))
        result = await provider.fetch_public_webpage("https://example.com")
        assert result["status"] == "SUCCESS"
        assert result["title"] == "Test"
        assert "Hello World" in result["text_content"]
        assert "alert" not in result["text_content"]
