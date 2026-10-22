import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal

async def verify():
    async with AsyncSessionLocal() as session:
        # 1. Alembic revision
        res = await session.execute(text("SELECT version_num FROM alembic_version"))
        version = res.scalar()
        print(f"ALEMBIC_VERSION: {version}")
        assert version == "005_scraped_jobs", f"Expected '005_scraped_jobs', got '{version}'"

        # 2. Check scraped_jobs table columns
        cols_res = await session.execute(text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'scraped_jobs' ORDER BY ordinal_position"
        ))
        cols = [dict(r._mapping) for r in cols_res.fetchall()]
        print(f"SCRAPED_JOBS_COLUMNS ({len(cols)} columns):")
        for c in cols:
            print(f"  - {c['column_name']} ({c['data_type']}) nullable={c['is_nullable']}")
        assert len(cols) == 24, f"Expected 24 columns in scraped_jobs, found {len(cols)}"

        # 3. Check scraped_jobs indexes
        idx_res = await session.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'scraped_jobs'"
        ))
        indexes = [dict(r._mapping) for r in idx_res.fetchall()]
        print(f"SCRAPED_JOBS_INDEXES ({len(indexes)} indexes):")
        for idx in indexes:
            print(f"  - {idx['indexname']}")
        index_names = {idx['indexname'] for idx in indexes}
        expected_indexes = {
            'scraped_jobs_pkey',
            'uq_scraped_jobs_source_external_id',
            'ix_scraped_jobs_id',
            'ix_scraped_jobs_organization_id',
            'ix_scraped_jobs_opportunity_id',
            'ix_scraped_jobs_content_hash',
            'ix_scraped_jobs_cross_source_hash',
            'ix_scraped_jobs_canonical_apply_url',
            'ix_scraped_jobs_status',
            'ix_scraped_jobs_last_scraped_at'
        }
        missing = expected_indexes - index_names
        assert not missing, f"Missing indexes: {missing}"

        # 4. Check Opportunities table count and verify records remain 100% identical
        opp_res = await session.execute(text("SELECT * FROM opportunities ORDER BY id"))
        current_rows = [dict(r._mapping) for r in opp_res.fetchall()]
        print(f"CURRENT_OPPORTUNITIES_COUNT: {len(current_rows)}")
        assert len(current_rows) == 2, f"Expected 2 rows in opportunities, found {len(current_rows)}"

        # Compare with pre-migration backup
        backup_path = os.path.join(os.path.dirname(__file__), "backup_opportunities_pre_005.json")
        with open(backup_path, "r") as f:
            backup_rows = json.load(f)

        backup_map = {r['id']: r for r in backup_rows}
        for cur in current_rows:
            opp_id = cur['id']
            assert opp_id in backup_map, f"Unexpected opportunity ID: {opp_id}"
            b = backup_map[opp_id]
            # Verify core fields
            for key in ['id', 'organization_id', 'title', 'company_name', 'problem', 'requirement', 'status']:
                assert str(cur[key]) == str(b[key]), f"Field mismatch in {opp_id} for '{key}': current={cur[key]} vs backup={b[key]}"
            print(f"Opportunity verified unchanged: {opp_id} ('{cur['title']}')")

        print("ALL POST-MIGRATION CHECKS PASSED WITH 100% SUCCESS.")

if __name__ == "__main__":
    asyncio.run(verify())
