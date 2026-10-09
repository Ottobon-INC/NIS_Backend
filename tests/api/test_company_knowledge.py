import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_crud_services(client: AsyncClient):
    headers = {"Authorization": "Bearer mock-admin-token"}
    # Create
    resp = await client.post("/api/v1/knowledge/services/", json={
        "name": "Cloud Migration",
        "description": "Migrating to AWS"
    }, headers=headers)
    assert resp.status_code == 200
    item_id = resp.json()["id"]
    
    # Get
    resp = await client.get(f"/api/v1/knowledge/services/{item_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Cloud Migration"
    
    # Update
    resp = await client.put(f"/api/v1/knowledge/services/{item_id}", json={
        "name": "Cloud Strategy"
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Cloud Strategy"
    
    # Delete
    resp = await client.delete(f"/api/v1/knowledge/services/{item_id}", headers=headers)
    assert resp.status_code == 200
