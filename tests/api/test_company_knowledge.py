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

@pytest.mark.asyncio
async def test_crud_products(client: AsyncClient):
    headers = {"Authorization": "Bearer mock-admin-token"}
    # Create product with tagline and all metadata
    product_payload = {
        "name": "NetworkOS Pro",
        "tagline": "Autonomous enterprise intelligence",
        "category": "Enterprise Software",
        "description": "AI agent platform for enterprise networks",
        "features": "Deep research, public footprint analysis, live sync",
        "target_audience": "Enterprises, Sales Leaders",
        "business_model": "SaaS Subscription",
        "status": "ACTIVE"
    }
    resp = await client.post("/api/v1/knowledge/products/", json=product_payload, headers=headers)
    assert resp.status_code == 200, resp.text
    product_data = resp.json()
    product_id = product_data["id"]
    assert product_data["tagline"] == "Autonomous enterprise intelligence"
    assert product_data["category"] == "Enterprise Software"

    # Get single product
    resp = await client.get(f"/api/v1/knowledge/products/{product_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["tagline"] == "Autonomous enterprise intelligence"

    # List products
    resp = await client.get("/api/v1/knowledge/products/", headers=headers)
    assert resp.status_code == 200
    assert any(p["id"] == product_id for p in resp.json())

    # Update product
    update_payload = {"tagline": "Next-gen enterprise intelligence"}
    resp = await client.put(f"/api/v1/knowledge/products/{product_id}", json=update_payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["tagline"] == "Next-gen enterprise intelligence"

    # Delete product
    resp = await client.delete(f"/api/v1/knowledge/products/{product_id}", headers=headers)
    assert resp.status_code == 200

