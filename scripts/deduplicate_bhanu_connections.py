import asyncio
import logging
from sqlalchemy import text
from app.db.session import AsyncSessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deduplicate")

async def run_deduplication():
    async with AsyncSessionLocal() as db:
        logger.info("Checking pre-deduplication counts...")
        total_before = (await db.execute(text("SELECT COUNT(*) FROM contacts WHERE contact_type = 'BHANU_CONNECTION'"))).scalar()
        logger.info(f"Total BHANU_CONNECTION records before: {total_before}")

        # Delete duplicates keeping 1 unique record per (full_name, current_company)
        # Prioritize keeping records that are scored, earliest created_at, or lowest id
        delete_query = text("""
            DELETE FROM contacts
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY full_name, current_company
                               ORDER BY is_scored DESC, created_at ASC, id ASC
                           ) as rnum
                    FROM contacts
                    WHERE contact_type = 'BHANU_CONNECTION'
                ) t
                WHERE t.rnum > 1
            )
        """)

        res = await db.execute(delete_query)
        await db.commit()
        logger.info(f"Deleted duplicate rows: {res.rowcount}")

        total_after = (await db.execute(text("SELECT COUNT(*) FROM contacts WHERE contact_type = 'BHANU_CONNECTION'"))).scalar()
        logger.info(f"Total BHANU_CONNECTION records after deduplication: {total_after}")

        unique_check = (await db.execute(text("""
            SELECT COUNT(DISTINCT (full_name, current_company)) 
            FROM contacts 
            WHERE contact_type = 'BHANU_CONNECTION'
        """))).scalar()
        logger.info(f"Unique (full_name, current_company) pairs remaining: {unique_check}")

if __name__ == "__main__":
    asyncio.run(run_deduplication())
