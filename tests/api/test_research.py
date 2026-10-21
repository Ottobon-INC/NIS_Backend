import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient):
    resp = await client.get("/api/v1/research/sources")
    assert resp.status_code == 403
    data = resp.json()
    error_code = data.get("detail", {}).get("error", {}).get("code") or data.get("error", {}).get("code")
    assert error_code == "FORBIDDEN"

@pytest.mark.asyncio
async def test_crud_source(client: AsyncClient):
    headers = {"Authorization": "Bearer mock-admin-token"}
    source_id = "test_custom_source"
    # Delete if exists from previous test
    await client.delete(f"/api/v1/research/sources/{source_id}", headers=headers)

    # Create
    resp = await client.post("/api/v1/research/sources", json={
        "id": source_id,
        "name": "Custom Test Source",
        "source_type": "Technical",
        "priority": "P0",
        "status": "ENABLED",
        "provider_type": "api",
        "requires_api_key": True
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == source_id
    assert data["priority"] == "P0"

    # Get
    resp = await client.get(f"/api/v1/research/sources/{source_id}", headers=headers)
    assert resp.status_code == 200

    # Update
    resp = await client.put(f"/api/v1/research/sources/{source_id}", json={
        "status": "DISABLED",
        "priority": "P1"
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "DISABLED"
    assert resp.json()["priority"] == "P1"

    # Clean up
    await client.delete(f"/api/v1/research/sources/{source_id}", headers=headers)
