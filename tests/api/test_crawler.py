import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.main import app
from app.services.web.crawler import CrawlerService

@pytest.mark.asyncio
async def test_crawler_service_scrape_page_mock():
    mock_res = {
        "success": True,
        "url": "https://example.com",
        "title": "Example Domain",
        "markdown": "# Example Domain\nThis domain is for use in illustrative examples.",
        "html": "<html><body><h1>Example Domain</h1></body></html>",
        "links": ["https://www.iana.org/domains/example"],
        "media": [],
        "status_code": 200
    }

    with patch.object(CrawlerService, "scrape_page", new=AsyncMock(return_value=mock_res)):
        res = await CrawlerService.scrape_page("https://example.com")
        assert res["success"] is True
        assert res["title"] == "Example Domain"
        assert "illustrative examples" in res["markdown"]
        assert len(res["links"]) == 1

@pytest.mark.asyncio
async def test_scrape_endpoint_success():
    mock_res = {
        "success": True,
        "url": "https://example.com",
        "title": "Example Domain",
        "markdown": "# Example Domain\nClean markdown content.",
        "html": "<html>...</html>",
        "links": ["https://iana.org"],
        "media": []
    }

    with patch.object(CrawlerService, "scrape_page", new=AsyncMock(return_value=mock_res)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/scrape", params={"url": "https://example.com"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["title"] == "Example Domain"
            assert data["markdown"] == "# Example Domain\nClean markdown content."
            assert "https://iana.org" in data["links"]

@pytest.mark.asyncio
async def test_scrape_endpoint_error_handling():
    with patch.object(CrawlerService, "scrape_page", new=AsyncMock(side_effect=RuntimeError("Crawl failed: Timeout"))):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/scrape", params={"url": "https://invalid-url.com"})
            assert resp.status_code == 500
            assert "Crawl failed" in resp.json()["detail"]
