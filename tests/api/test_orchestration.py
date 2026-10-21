import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.evidence import ExecutiveSnapshot

def make_mock_snapshot():
    return ExecutiveSnapshot(
        name="Test User",
        current_role="Staff Engineer",
        current_organization="Acme Inc",
        location="Remote",
        provenance_status="VERIFIED CURRENT",
        domain_name="Engineering",
        proven_domain_expertise="Distributed systems.",
        customer_knowledge_level="Technical Lead",
        is_domain_sme="Practitioner",
        operating_in_own_domain=True,
        opportunity_category="Small Service Engagement",
        opportunity_nature="Direct",
        broad_business_problem="Systems scaling",
        smallest_solvable_problem="Architecture review",
        why_now="Recent architecture transition",
        ottobon_capability_match="Development",
        delivery_risk_level="LOW",
        estimated_effort_hours="80 hours",
        cost_pricing_estimate="$10,000 sprint",
        proposed_first_engagement="System review",
        relationship_path="Direct",
        pipeline_stage="PROPOSED",
        next_action_step="Review technical specifications",
        full_markdown_report=(
            "# Commercial Opportunity Intelligence Report\n\n"
            "## 1. Executive & Domain Intelligence\n"
            "- **Current Role & Org**: Staff Engineer at Acme Inc [E1] `[VERIFIED CURRENT]`\n\n"
            "## 2. Opportunity Discovery & Classification\n"
            "- **Identified Business Context**: Systems engineering [E1]\n\n"
            "## 3. The Smallest Worthwhile Solvable Problem\n"
            "- **Broad Business Challenge**: Systems scaling\n\n"
            "## 4. Feasibility, Capability Matching & Commercial Scenarios\n"
            "- **Ottobon Capability Match**: Development\n\n"
            "## 5. Tentative Proposal & Action Plan\n"
            "- **Proposed First Engagement**: Architecture review\n"
        )
    )

@pytest.mark.asyncio
async def test_contact_creation_and_research(client: AsyncClient):
    headers = {"Authorization": "Bearer mock-token"}
    mock_snap = make_mock_snapshot()

    with patch("app.services.evidence.ChatOpenAI") as mock_openai, \
         patch("langchain_core.runnables.base.RunnableSequence.ainvoke", new=AsyncMock(return_value=mock_snap)):
        mock_llm_instance = MagicMock()
        mock_openai.return_value = mock_llm_instance
        mock_llm_instance.with_structured_output.return_value = MagicMock()

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
        assert data["status"] in ["QUEUED", "RUNNING", "PARTIAL", "COMPLETED"]
        assert "total_tasks" in data
        assert "completed_tasks" in data
        assert "tasks" in data
