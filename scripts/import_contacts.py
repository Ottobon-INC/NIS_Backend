import asyncio
import asyncpg
import urllib.parse
import csv
import json
import os

async def run_import():
    conn = await asyncpg.connect(
        host="aws-0-ap-northeast-1.pooler.supabase.com",
        port=6543,
        user="postgres.czgaluszcaedowkqbzne",
        password=urllib.parse.unquote("Abhi%40128925"),
        database="postgres",
        ssl="require",
        statement_cache_size=0
    )
    
    csv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Cleaned_Connections.csv"))
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append((
                r["id"],
                r["organization_id"],
                r["first_name"],
                r["last_name"],
                r["full_name"],
                r["current_title"],
                r["current_company"],
                r["email"] if r["email"] else None,
                r["profile_url"] if r["profile_url"] else None,
                "READY",
                r["contact_type"],
                r["card_status"],
                r["admin_notes"]
            ))
    
    print(f"Parsed {len(rows)} records from Cleaned_Connections.csv")
    
    insert_sql = """
        INSERT INTO public.contacts (
            id, organization_id, first_name, last_name, full_name,
            current_title, current_company, email, profile_url,
            status, contact_type, card_status, admin_notes
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10::public.contactstatus, $11, $12, $13
        ) ON CONFLICT (id) DO NOTHING;
    """
    
    await conn.executemany(insert_sql, rows)
    print("Insertion completed successfully!")
    
    total = await conn.fetchval("SELECT count(id) FROM public.contacts")
    bhanu_total = await conn.fetchval("SELECT count(id) FROM public.contacts WHERE contact_type = 'BHANU_CONNECTION'")
    print(f"Total contacts now in DB: {total} (Bhanu network connections: {bhanu_total})")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(run_import())
