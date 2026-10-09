import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient):
    resp = await client.get("/api/v1/research/sources")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

@pytest.mark.asyncio
async def test_crud_source(client: AsyncClient):
    headers = {"Authorization": "Bearer mock-admin-token"}
    # Create
    resp = await client.post("/api/v1/research/sources", json={
        "id": "github",
        "name": "GitHub",
        "source_type": "Technical",
        "priority": "P0",
        "status": "ENABLED",
        "provider_type": "api",
        "requires_api_key": True
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "github"
    assert data["priority"] == "P0"
    
    # Get
    resp = await client.get("/api/v1/research/sources/github", headers=headers)
    assert resp.status_code == 200
    
    # Update
    resp = await client.put("/api/v1/research/sources/github", json={
        "status": "DISABLED",
        "priority": "P1"
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "DISABLED"
    assert resp.json()["priority"] == "P1"
