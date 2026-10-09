import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_root_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "Go to /api/v1/health for detailed status."}

@pytest.mark.asyncio
async def test_api_v1_health(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
