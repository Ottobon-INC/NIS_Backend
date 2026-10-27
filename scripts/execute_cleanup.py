import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cleanup")

async def run_cleanup():
    async with AsyncSessionLocal() as session:
        # Step 1: Identify test / dummy contacts
        test_ids_res = await session.execute(text("""
            SELECT id, full_name, contact_type
            FROM contacts
            WHERE id LIKE 'test-%'
               OR id LIKE 'contact-a-%'
               OR id LIKE 'contact-b-%'
               OR id LIKE 'contact-other-%'
               OR id LIKE 'contact-test-%'
               OR id LIKE 'c-foreign-%'
               OR id LIKE 'c-err-meet-%'
               OR id = 'a4adfc6d-44b0-47c9-8a00-98d4dd0bf37e'
               OR full_name IN (
                    'Conflict Lead', 'Contact A', 'Contact B', 'Placeholder Test Contact',
                    'Empty Run Candidate', 'Date Test Candidate', 'Null Test', 'Direct Lookup User',
                    'Valid Contact', 'Foreign Corp Executive', 'Low Confidence Candidate',
                    'Plan Test Candidate', 'Test Unres Slug', 'Uncertain Lead', 'Unknown Profile',
                    'Assumptions Lead', 'Competitor Contact', 'Confirmed Executive',
                    'Confidence Test', 'Compat Test Candidate', 'Alice Candidate',
                    'Morgan Stark', 'Dr. Elena Rostova', 'Error Handling User',
                    'Auth Failure Test User'
               )
        """))
        test_contacts = test_ids_res.fetchall()
        test_ids = [r[0] for r in test_contacts]
        logger.info(f"Identified {len(test_ids)} test/dummy contacts to purge.")

        if test_ids:
            # Find research_runs
            runs_res = await session.execute(text("""
                SELECT id FROM research_runs WHERE contact_id = ANY(:test_ids)
            """), {"test_ids": test_ids})
            run_ids = [r[0] for r in runs_res.fetchall()]
            logger.info(f"Found {len(run_ids)} test research_runs.")

            # Find research_tasks
            task_ids = []
            if run_ids:
                tasks_res = await session.execute(text("""
                    SELECT id FROM research_tasks WHERE research_run_id = ANY(:run_ids)
                """), {"run_ids": run_ids})
                task_ids = [r[0] for r in tasks_res.fetchall()]
                logger.info(f"Found {len(task_ids)} test research_tasks.")

            # Find source_results
            sr_ids = []
            if task_ids:
                sr_res = await session.execute(text("""
                    SELECT id FROM source_results WHERE research_task_id = ANY(:task_ids)
                """), {"task_ids": task_ids})
                sr_ids = [r[0] for r in sr_res.fetchall()]
                logger.info(f"Found {len(sr_ids)} test source_results.")

            # 1. Delete evidence linked to test_ids or test source_results
            ev_del = await session.execute(text("""
                DELETE FROM evidence 
                WHERE related_entity_id = ANY(:test_ids)
                   OR source_result_id = ANY(:sr_ids)
            """), {"test_ids": test_ids, "sr_ids": sr_ids if sr_ids else ['dummy-uuid']})
            logger.info(f"Deleted {ev_del.rowcount} test evidence rows.")

            # 2. Delete source_results
            if sr_ids:
                sr_del = await session.execute(text("""
                    DELETE FROM source_results WHERE id = ANY(:sr_ids)
                """), {"sr_ids": sr_ids})
                logger.info(f"Deleted {sr_del.rowcount} test source_results rows.")

            # 3. Delete research_tasks
            if task_ids:
                rt_del = await session.execute(text("""
                    DELETE FROM research_tasks WHERE id = ANY(:task_ids)
                """), {"task_ids": task_ids})
                logger.info(f"Deleted {rt_del.rowcount} test research_tasks rows.")

            # 4. Delete research_runs
            if run_ids:
                rr_del = await session.execute(text("""
                    DELETE FROM research_runs WHERE id = ANY(:run_ids)
                """), {"run_ids": run_ids})
                logger.info(f"Deleted {rr_del.rowcount} test research_runs rows.")

            # 5. Delete other dependent tables
            for tbl, col in [
                ('external_identities', 'contact_id'),
                ('trusted_contexts', 'contact_id'),
                ('company_intelligence', 'contact_id'),
                ('opportunities', 'contact_id'),
                ('meetings', 'contact_id'),
                ('meeting_findings', 'contact_id'),
                ('deleted_contacts', 'contact_id')
            ]:
                del_res = await session.execute(text(f"""
                    DELETE FROM {tbl} WHERE {col} = ANY(:test_ids)
                """), {"test_ids": test_ids})
                logger.info(f"Deleted {del_res.rowcount} from {tbl}.")

            # 6. Delete contacts
            c_del = await session.execute(text("""
                DELETE FROM contacts WHERE id = ANY(:test_ids)
            """), {"test_ids": test_ids})
            logger.info(f"Deleted {c_del.rowcount} test contacts.")

        # Step 2: Merge the 6 cross-duplicate contacts (TARGET + BHANU_CONNECTION)
        # 1) Harshitha Kosana: keep 041201c5-e5cd-4989-8125-bbd030520586 (TARGET), purge duplicate e22b1031-92dc-4df6-a031-4c8c2afb111d
        await session.execute(text("""
            UPDATE research_runs SET contact_id = '041201c5-e5cd-4989-8125-bbd030520586'
            WHERE contact_id = 'e22b1031-92dc-4df6-a031-4c8c2afb111d'
        """))
        await session.execute(text("""
            UPDATE evidence SET related_entity_id = '041201c5-e5cd-4989-8125-bbd030520586'
            WHERE related_entity_id = 'e22b1031-92dc-4df6-a031-4c8c2afb111d'
        """))
        await session.execute(text("""
            DELETE FROM external_identities WHERE contact_id = 'e22b1031-92dc-4df6-a031-4c8c2afb111d'
        """))
        await session.execute(text("""
            DELETE FROM contacts WHERE id = 'e22b1031-92dc-4df6-a031-4c8c2afb111d'
        """))
        await session.execute(text("""
            UPDATE contacts SET contact_type = 'BHANU_CONNECTION', relationship_strength = 3
            WHERE id = '041201c5-e5cd-4989-8125-bbd030520586'
        """))
        logger.info("Merged Harshitha Kosana into single BHANU_CONNECTION contact.")

        # 2) Veeresh Hawalkhod: keep af1e5e21-966b-4baf-8191-59d19e25b655, purge 01edae07-07f7-4f92-8dd9-106b7882480e
        await session.execute(text("""
            DELETE FROM external_identities WHERE contact_id = '01edae07-07f7-4f92-8dd9-106b7882480e'
        """))
        await session.execute(text("""
            DELETE FROM contacts WHERE id = '01edae07-07f7-4f92-8dd9-106b7882480e'
        """))
        await session.execute(text("""
            UPDATE contacts SET contact_type = 'BHANU_CONNECTION', relationship_strength = 3
            WHERE id = 'af1e5e21-966b-4baf-8191-59d19e25b655'
        """))
        logger.info("Merged Veeresh Hawalkhod into single BHANU_CONNECTION contact.")

        # 3) Viktor Zhuchkov: keep 13666a26-94a1-4add-9c2b-736f0e9d7cc9, purge 9e184434-5b3a-438f-9a18-97c63f32dc36
        await session.execute(text("""
            DELETE FROM external_identities WHERE contact_id = '9e184434-5b3a-438f-9a18-97c63f32dc36'
        """))
        await session.execute(text("""
            DELETE FROM contacts WHERE id = '9e184434-5b3a-438f-9a18-97c63f32dc36'
        """))
        await session.execute(text("""
            UPDATE contacts SET contact_type = 'BHANU_CONNECTION', relationship_strength = 3
            WHERE id = '13666a26-94a1-4add-9c2b-736f0e9d7cc9'
        """))
        logger.info("Merged Viktor Zhuchkov into single BHANU_CONNECTION contact.")

        # 4) Stephen Staszewski: keep 131a8729-f5bd-4bc2-962f-00a5befb1d86, purge 2c4cd194-20fb-4531-98bb-0557ebacfcf9
        await session.execute(text("""
            DELETE FROM external_identities WHERE contact_id = '2c4cd194-20fb-4531-98bb-0557ebacfcf9'
        """))
        await session.execute(text("""
            DELETE FROM contacts WHERE id = '2c4cd194-20fb-4531-98bb-0557ebacfcf9'
        """))
        await session.execute(text("""
            UPDATE contacts SET contact_type = 'BHANU_CONNECTION', relationship_strength = 3
            WHERE id = '131a8729-f5bd-4bc2-962f-00a5befb1d86'
        """))
        logger.info("Merged Stephen Staszewski into single BHANU_CONNECTION contact.")

        # 5) Diana Dedkova: keep d3c7861f-e5ad-421a-a62b-e6aa780755e5, purge c64ad278-40b3-482c-b455-51d15cfdbeeb
        await session.execute(text("""
            DELETE FROM external_identities WHERE contact_id = 'c64ad278-40b3-482c-b455-51d15cfdbeeb'
        """))
        await session.execute(text("""
            DELETE FROM contacts WHERE id = 'c64ad278-40b3-482c-b455-51d15cfdbeeb'
        """))
        await session.execute(text("""
            UPDATE contacts SET contact_type = 'BHANU_CONNECTION', relationship_strength = 3
            WHERE id = 'd3c7861f-e5ad-421a-a62b-e6aa780755e5'
        """))
        logger.info("Merged Diana Dedkova into single BHANU_CONNECTION contact.")

        # 6) Alon Laor: keep 1bab5edc-f7ac-4534-8791-5ed04af9f74f, purge 89ab719c-36a6-437b-a211-7e66e3720ba9
        await session.execute(text("""
            DELETE FROM external_identities WHERE contact_id = '89ab719c-36a6-437b-a211-7e66e3720ba9'
        """))
        await session.execute(text("""
            DELETE FROM contacts WHERE id = '89ab719c-36a6-437b-a211-7e66e3720ba9'
        """))
        await session.execute(text("""
            UPDATE contacts SET 
                full_name = 'Alon Laor',
                current_company = 'CXP Consulting',
                current_title = 'Co-Founder',
                contact_type = 'BHANU_CONNECTION', 
                relationship_strength = 3
            WHERE id = '1bab5edc-f7ac-4534-8791-5ed04af9f74f'
        """))
        logger.info("Merged Alon Laor into single BHANU_CONNECTION contact.")

        # Step 3: Run deduplication across any remaining duplicate pairs of (full_name, current_company)
        # Keeping record with research runs, highest score, or earliest created
        dup_query = text("""
            DELETE FROM contacts
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY LOWER(TRIM(full_name)), LOWER(TRIM(COALESCE(current_company, '')))
                               ORDER BY (SELECT count(*) FROM research_runs WHERE contact_id = contacts.id) DESC,
                                        is_scored DESC,
                                        created_at ASC
                           ) as rnum
                    FROM contacts
                    WHERE current_company IS NOT NULL AND current_company != ''
                ) t
                WHERE t.rnum > 1
            )
        """)
        dup_del = await session.execute(dup_query)
        logger.info(f"Deduplicated remaining name/company collisions: {dup_del.rowcount} removed.")

        await session.commit()
        logger.info("Successfully committed all database cleanups and deduplications!")

if __name__ == "__main__":
    asyncio.run(run_cleanup())
