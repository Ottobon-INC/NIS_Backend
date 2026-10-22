import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal

async def restore_backup():
    backup_path = os.path.join(os.path.dirname(__file__), "backup_opportunities_pre_005.json")
    if not os.path.exists(backup_path):
        print(f"Error: Backup file {backup_path} not found.")
        return

    with open(backup_path, "r") as f:
        records = json.load(f)

    print(f"Loaded {len(records)} records from backup.")
    async with AsyncSessionLocal() as session:
        for r in records:
            # Upsert into opportunities
            cols = list(r.keys())
            params = {k: r[k] for k in cols}
            update_clause = ", ".join([f"{k} = EXCLUDED.{k}" for k in cols if k != "id"])
            col_names = ", ".join(cols)
            val_names = ", ".join([f":{k}" for k in cols])
            
            stmt = text(f"""
                INSERT INTO opportunities ({col_names})
                VALUES ({val_names})
                ON CONFLICT (id) DO UPDATE SET {update_clause};
            """)
            await session.execute(stmt, params)
        await session.commit()
        print("Opportunities backup successfully verified/restored.")

if __name__ == "__main__":
    asyncio.run(restore_backup())
