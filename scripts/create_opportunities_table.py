import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import asyncio
from sqlalchemy import text
from app.db.session import AsyncSessionLocal

EXPECTED_COLUMNS = {
    "id": "character varying",
    "organization_id": "character varying",
    "owner_user_id": "character varying",
    "contact_id": "character varying",
    "company_name": "character varying",
    "company_id": "character varying",
    "title": "character varying",
    "description": "text",
    "problem": "text",
    "requirement": "text",
    "opportunity_type": "character varying",
    "status": "character varying",
    "confidence": "integer",
    "timeline": "character varying",
    "budget_signal": "character varying",
    "matched_product_id": "character varying",
    "matched_product_name": "character varying",
    "match_score": "integer",
    "match_rationale": "text",
    "supporting_evidence_ids": "json",
    "trusted_context_ids": "json",
    "review_notes": "text",
    "reviewed_by": "character varying",
    "reviewed_at": "timestamp with time zone",
    "valid_until": "timestamp with time zone",
    "created_at": "timestamp with time zone",
    "updated_at": "timestamp with time zone"
}

CREATE_TABLE_SQL = """
CREATE TABLE opportunities (
    id VARCHAR NOT NULL,
    organization_id VARCHAR NOT NULL,
    owner_user_id VARCHAR,
    contact_id VARCHAR,
    company_name VARCHAR NOT NULL,
    company_id VARCHAR,
    title VARCHAR NOT NULL,
    description TEXT,
    problem TEXT NOT NULL,
    requirement TEXT NOT NULL,
    opportunity_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'DISCOVERED',
    confidence INTEGER NOT NULL DEFAULT 50,
    timeline VARCHAR,
    budget_signal VARCHAR,
    matched_product_id VARCHAR,
    matched_product_name VARCHAR,
    match_score INTEGER,
    match_rationale TEXT,
    supporting_evidence_ids JSON,
    trusted_context_ids JSON,
    review_notes TEXT,
    reviewed_by VARCHAR,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    valid_until TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT check_opportunity_confidence_range CHECK (confidence >= 0 AND confidence <= 100),
    FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE SET NULL,
    FOREIGN KEY (company_id) REFERENCES company_profiles (id) ON DELETE SET NULL,
    FOREIGN KEY (matched_product_id) REFERENCES products (id) ON DELETE SET NULL
);

CREATE INDEX ix_opportunities_id ON opportunities (id);
CREATE INDEX ix_opportunities_organization_id ON opportunities (organization_id);
CREATE INDEX ix_opportunities_contact_id ON opportunities (contact_id);
CREATE INDEX ix_opportunities_status ON opportunities (status);
"""

async def create_opportunities_table():
    print("Connecting to database...")
    async with AsyncSessionLocal() as session:
        # 1. Check if table already exists
        check_table_sql = text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name='opportunities'"
        )
        res = await session.execute(check_table_sql)
        exists = res.scalar() is not None

        if exists:
            print("Table 'opportunities' already exists. Inspecting schema compatibility...")
            cols_res = await session.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='opportunities'"
                )
            )
            existing_columns = {row[0]: row[1].lower() for row in cols_res.fetchall()}

            missing_columns = set(EXPECTED_COLUMNS.keys()) - set(existing_columns.keys())
            if missing_columns:
                raise RuntimeError(
                    f"Incompatible schema detected: 'opportunities' table is missing columns: {sorted(list(missing_columns))}. "
                    "Manual migration required."
                )

            # Check JSON/JSONB compatibility
            type_mismatches = []
            for col_name, expected_type in EXPECTED_COLUMNS.items():
                actual_type = existing_columns.get(col_name)
                # Allow json/jsonb variance
                if expected_type == "json" and actual_type in ["json", "jsonb"]:
                    continue
                if actual_type != expected_type:
                    type_mismatches.append(f"{col_name} (expected {expected_type}, found {actual_type})")

            if type_mismatches:
                raise RuntimeError(
                    f"Incompatible column data types detected in 'opportunities': {', '.join(type_mismatches)}."
                )

            print("Schema verification passed: 'opportunities' table is present and fully compatible.")
            return

        # 2. Table does not exist, create it idempotently
        print("Creating 'opportunities' table and indexes...")
        for statement in CREATE_TABLE_SQL.strip().split(";"):
            cleaned = statement.strip()
            if cleaned:
                await session.execute(text(cleaned))

        await session.commit()
        print("Table 'opportunities', constraints, and indexes created successfully.")

        # 3. Verify creation
        verify_res = await session.execute(check_table_sql)
        if verify_res.scalar() == "opportunities":
            print("Verification successful: 'opportunities' table confirmed in database.")
        else:
            raise RuntimeError("Verification failed: 'opportunities' table was not found after execution.")

if __name__ == "__main__":
    asyncio.run(create_opportunities_table())
