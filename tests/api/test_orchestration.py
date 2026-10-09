import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_contact_creation_and_research(client: AsyncClient):
    headers = {"Authorization": "Bearer mock-token"}
    
    resp = await client.post("/api/v1/contacts/", json={
        "linkedin_url": "https://linkedin.com/in/testuser/"
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    contact_id = data["id"]
    
    resp2 = await client.post("/api/v1/contacts/", json={
        "linkedin_url": "https://www.linkedin.com/in/testuser"
    }, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] == contact_id
    
    resp = await client.post(f"/api/v1/contacts/{contact_id}/research", headers=headers)
    assert resp.status_code == 200
    run_id = resp.json()["research_run_id"]
    
    resp = await client.get(f"/api/v1/research/runs/{run_id}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "QUEUED"
    assert "progress" in data
