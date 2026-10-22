import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal

async def verify_and_backup():
    async with AsyncSessionLocal() as session:
        # 1. Alembic version
        ver_res = await session.execute(text("SELECT version_num FROM alembic_version"))
        current_version = [r[0] for r in ver_res.fetchall()]
        print(f"CURRENT_ALEMBIC_VERSION: {current_version}")

        # 2. Opportunities schema
        col_res = await session.execute(text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'opportunities' "
            "ORDER BY ordinal_position"
        ))
        cols = [dict(r._mapping) for r in col_res.fetchall()]
        print(f"OPPORTUNITIES_COLUMNS_COUNT: {len(cols)}")
        for c in cols:
            print(f"  - {c['column_name']} ({c['data_type']}) default={c['column_default']}")

        # 3. Opportunities backup snapshot
        opp_res = await session.execute(text("SELECT * FROM opportunities"))
        rows = [dict(r._mapping) for r in opp_res.fetchall()]
        print(f"OPPORTUNITIES_ROW_COUNT: {len(rows)}")
        
        # Serialize datetime and json objects for backup
        serializable_rows = []
        for r in rows:
            sr = {}
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    sr[k] = v.isoformat()
                else:
                    sr[k] = v
            serializable_rows.append(sr)

        backup_path = os.path.join(os.path.dirname(__file__), "backup_opportunities_pre_005.json")
        with open(backup_path, "w") as f:
            json.dump(serializable_rows, f, indent=2)
        print(f"BACKUP_SAVED: {backup_path} ({len(serializable_rows)} records backed up)")

if __name__ == "__main__":
    asyncio.run(verify_and_backup())
