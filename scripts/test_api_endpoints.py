import httpx
import json

client = httpx.Client(base_url="http://localhost:8080", headers={"Authorization": "Bearer mock-token"}, timeout=15.0)

# 1. Test status endpoint
res = client.get("/api/v1/opportunities/scrape-jobs/status")
print(f"Status endpoint HTTP: {res.status_code}")
print("Status data:")
print(json.dumps(res.json(), indent=2))

# 2. Test opportunities list
opp_res = client.get("/api/v1/opportunities?limit=8")
print(f"Opportunities endpoint HTTP: {opp_res.status_code}")
opps = opp_res.json().get("opportunities", [])
print(f"Total retrieved opportunities: {len(opps)}")
for opp in opps:
    print(f"  - [{opp['opportunityType']}] {opp['title']} ({opp['companyName']}) | Status: {opp['status']}")

# 3. Test unauthenticated request rejection (Safeguard check)
unauth_res = httpx.get("http://localhost:8080/api/v1/opportunities/scrape-jobs/status")
print(f"Unauthenticated request status: {unauth_res.status_code} (Expected 401)")
assert unauth_res.status_code == 401, f"Expected 401, got {unauth_res.status_code}"
