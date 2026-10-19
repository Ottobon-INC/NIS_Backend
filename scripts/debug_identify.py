import asyncio
import asyncpg
import urllib.parse
import json

async def check():
    conn = await asyncpg.connect(
        host="aws-0-ap-northeast-1.pooler.supabase.com",
        port=5432,
        user="postgres.czgaluszcaedowkqbzne",
        password=urllib.parse.unquote("Abhi%40128925"),
        database="postgres",
        ssl="require"
    )
    
    print("--- CONTACT e43e37be-53d7-4fc9-bb14-f1dd18e36e92 ---")
    c = await conn.fetchrow("SELECT * FROM contacts WHERE id = 'e43e37be-53d7-4fc9-bb14-f1dd18e36e92'")
    print("CONTACT:", dict(c) if c else "NOT FOUND")
    
    identities = await conn.fetch("SELECT * FROM external_identities WHERE contact_id = 'e43e37be-53d7-4fc9-bb14-f1dd18e36e92'")
    print("IDENTITIES:", [dict(i) for i in identities])
    
    tasks = await conn.fetch("SELECT id, source_id, status, target_metadata FROM research_tasks WHERE research_run_id = '356d3901-a4b8-4e56-80bb-d8c0b2ac4362'")
    for t in tasks:
        print("TASK:", t["id"], t["source_id"], t["status"], t["target_metadata"])
        
    srs = await conn.fetch("""
        SELECT id, research_task_id, source_id, query, raw_reference, status, extracted_data 
        FROM source_results 
        WHERE research_task_id IN (SELECT id FROM research_tasks WHERE research_run_id = '356d3901-a4b8-4e56-80bb-d8c0b2ac4362')
    """)
    for s in srs:
        print("SOURCE RESULT:", s["id"], s["source_id"], s["query"], s["status"])
        if s["extracted_data"]:
            ed = s["extracted_data"]
            if isinstance(ed, str):
                try:
                    ed = json.loads(ed)
                except Exception:
                    pass
            print("  Title:", ed.get("title") if isinstance(ed, dict) else "")
            text_snip = (ed.get("text") or ed.get("text_content") or "")[:400] if isinstance(ed, dict) else ""
            print("  Text snippet:", text_snip)

    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
