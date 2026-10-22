import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from app.models.opportunity import Opportunity
from app.models.scraped_job import ScrapedJob
from app.services.scraping.ports import ScrapedJobRecord, IngestionStatus
from app.services.scraping.normalizer import (
    clean_html_to_text,
    canonicalize_url,
    normalize_company_name,
    normalize_job_title,
    compute_content_hash,
    compute_cross_source_hash
)
from app.services.scraping.collectors.remotive import RemotiveCollector
from app.services.scraping.collectors.arbeitnow import ArbeitnowCollector
from app.services.scraping.collectors.jobicy import JobicyCollector
from app.services.scraping.collectors.wwr_rss import WeWorkRemotelyCollector
from app.services.scraping.ingestion_service import JobIngestionService

def test_normalizer_functions():
    # 1. HTML stripping
    html = "<p>Join our team as a <strong>Senior Engineer</strong>.<script>alert('xss')</script></p>"
    clean = clean_html_to_text(html)
    assert clean == "Join our team as a Senior Engineer."

    # 2. URL canonicalization
    dirty_url = "https://www.company.com/jobs/123/?utm_source=linkedin&utm_medium=cpc&ref=jobboard#apply"
    canonical = canonicalize_url(dirty_url)
    assert canonical == "https://company.com/jobs/123"

    # 3. Company normalization
    assert normalize_company_name("Acme Corp, Inc.") == "acme"
    assert normalize_company_name("Google LLC") == "google"

    # 4. Job title normalization
    assert normalize_job_title("Senior Python Engineer (Remote) (m/f/d)") == "senior python engineer"

    # 5. Hashes
    h1 = compute_content_hash("Senior Engineer", "Acme Corp", "Build systems")
    h2 = compute_content_hash("Senior Engineer (Remote)", "Acme, Inc.", "Build systems")
    assert h1 == h2

@pytest.mark.asyncio
async def test_live_collectors():
    """Live verification of the four permitted collectors against actual endpoints."""
    # 1. Remotive
    remotive = RemotiveCollector()
    res_remotive = await remotive.scrape(limit=3)
    assert res_remotive.success, f"Remotive failed: {res_remotive.error_message}"
    assert len(res_remotive.records) > 0
    assert res_remotive.records[0].source == "remotive"

    # 2. Arbeitnow
    arbeitnow = ArbeitnowCollector()
    res_arbeitnow = await arbeitnow.scrape(limit=3)
    assert res_arbeitnow.success, f"Arbeitnow failed: {res_arbeitnow.error_message}"
    assert len(res_arbeitnow.records) > 0
    assert res_arbeitnow.records[0].source == "arbeitnow"

    # 3. Jobicy
    jobicy = JobicyCollector()
    res_jobicy = await jobicy.scrape(limit=3)
    assert res_jobicy.success, f"Jobicy failed: {res_jobicy.error_message}"
    assert len(res_jobicy.records) > 0
    assert res_jobicy.records[0].source == "jobicy"

    # 4. We Work Remotely RSS
    wwr = WeWorkRemotelyCollector()
    res_wwr = await wwr.scrape(limit=3)
    assert res_wwr.success, f"WWR failed: {res_wwr.error_message}"
    assert len(res_wwr.records) > 0
    assert res_wwr.records[0].source == "weworkremotely"

@pytest.mark.asyncio
async def test_idempotent_ingestion_and_cross_source_dedup():
    """Verifies single-record ingestion, idempotence (repeat runs), and cross-source deduplication."""
    test_org = "org-test-scraping"

    rec1 = ScrapedJobRecord(
        source="test_source_a",
        external_id="test-job-001",
        title="Staff AI Platform Engineer (Remote)",
        company_name="Apex Technologies, Inc.",
        apply_url="https://apextech.com/careers/ai-platform?utm_source=test",
        description_raw="<p>Seeking Staff AI Platform Engineer with FastAPI and Kubernetes expertise.</p>",
        location="Remote",
        salary="$180,000 - $220,000",
        tags=["Python", "FastAPI", "AI"]
    )

    # Cross-source twin job (from test_source_b with different URL formatting)
    rec2_twin = ScrapedJobRecord(
        source="test_source_b",
        external_id="twin-job-999",
        title="Staff AI Platform Engineer",
        company_name="Apex Technologies",
        apply_url="https://apextech.com/careers/ai-platform/",
        description_raw="<p>Seeking Staff AI Platform Engineer with FastAPI and Kubernetes expertise.</p>",
        location="Worldwide Remote",
        salary="$180,000 - $220,000",
        tags=["Python", "FastAPI"]
    )

    async with AsyncSessionLocal() as session:
        # Clean up any leftover test data
        await session.execute(text("DELETE FROM scraped_jobs WHERE source LIKE 'test_source%'"))
        await session.execute(text("DELETE FROM opportunities WHERE organization_id = :org"), {"org": test_org})
        await session.commit()

    # 1. Ingest first job
    async with AsyncSessionLocal() as session:
        status1, opp_id1, err1 = await JobIngestionService.ingest_single_record(session, rec1, organization_id=test_org)
        assert status1 == IngestionStatus.NEW
        assert opp_id1 is not None

    # 2. Ingest duplicate from same source (Idempotence test)
    async with AsyncSessionLocal() as session:
        status2, opp_id2, err2 = await JobIngestionService.ingest_single_record(session, rec1, organization_id=test_org)
        assert status2 == IngestionStatus.UNCHANGED
        assert opp_id2 == opp_id1

    # 3. Ingest modified description from same source (Update test)
    rec1_modified = rec1.model_copy(update={
        "description_raw": "<p>Updated: Seeking Staff AI Engineer with LLM orchestration and FastAPI.</p>"
    })
    async with AsyncSessionLocal() as session:
        status3, opp_id3, err3 = await JobIngestionService.ingest_single_record(session, rec1_modified, organization_id=test_org)
        assert status3 == IngestionStatus.UPDATED
        assert opp_id3 == opp_id1

    # 4. Ingest cross-source twin job (Cross-source deduplication test)
    async with AsyncSessionLocal() as session:
        status4, opp_id4, err4 = await JobIngestionService.ingest_single_record(session, rec2_twin, organization_id=test_org)
        assert status4 == IngestionStatus.NEW
        # Crucial check: Must link to the SAME opportunity ID!
        assert opp_id4 == opp_id1

    # 5. Verify database integrity
    async with AsyncSessionLocal() as session:
        # There should be 2 scraped_jobs records (one per source)
        sj_res = await session.execute(text("SELECT count(*) FROM scraped_jobs WHERE source LIKE 'test_source%'"))
        sj_count = sj_res.scalar()
        assert sj_count == 2, f"Expected 2 scraped_jobs records, found {sj_count}"

        # But only 1 canonical Opportunity created for this position!
        opp_res = await session.execute(text("SELECT count(*) FROM opportunities WHERE id = :opp_id"), {"opp_id": opp_id1})
        opp_count = opp_res.scalar()
        assert opp_count == 1, f"Expected exactly 1 Opportunity, found {opp_count}"

        # Clean up test rows
        await session.execute(text("DELETE FROM scraped_jobs WHERE source LIKE 'test_source%'"))
        await session.execute(text("DELETE FROM opportunities WHERE organization_id = :org"), {"org": test_org})
        await session.commit()

if __name__ == "__main__":
    test_normalizer_functions()
    print("Normalizer test passed.")
    asyncio.run(test_live_collectors())
    print("Live collectors test passed.")
    asyncio.run(test_idempotent_ingestion_and_cross_source_dedup())
    print("Idempotence & Cross-source Deduplication test passed.")
