"""add tagline and missing fields to products table

Revision ID: 006_products_tagline_and_metadata
Revises: 005_scraped_jobs
Create Date: 2026-11-11

This migration is completely non-destructive:
- Checks column existence before attempting to add.
- Only uses ADD COLUMN IF NOT EXISTS.
- Preserves all existing records and schema structure.
"""
from alembic import op
import sqlalchemy as sa

revision = '006_products_tagline_and_metadata'
down_revision = '005_scraped_jobs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Safely and non-destructively ensure all columns required by the SQLAlchemy Product model exist
    # using raw SQL IF NOT EXISTS to guarantee idempotency across existing databases.
    op.execute(
        """
        DO $$
        BEGIN
            -- 1. tagline
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'products' AND column_name = 'tagline'
            ) THEN
                ALTER TABLE products ADD COLUMN tagline VARCHAR;
            END IF;

            -- 2. category
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'products' AND column_name = 'category'
            ) THEN
                ALTER TABLE products ADD COLUMN category VARCHAR;
            END IF;

            -- 3. features
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'products' AND column_name = 'features'
            ) THEN
                ALTER TABLE products ADD COLUMN features TEXT;
            END IF;

            -- 4. target_audience
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'products' AND column_name = 'target_audience'
            ) THEN
                ALTER TABLE products ADD COLUMN target_audience VARCHAR;
            END IF;

            -- 5. business_model
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'products' AND column_name = 'business_model'
            ) THEN
                ALTER TABLE products ADD COLUMN business_model VARCHAR;
            END IF;

            -- 6. status
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'products' AND column_name = 'status'
            ) THEN
                ALTER TABLE products ADD COLUMN status VARCHAR DEFAULT 'ACTIVE';
            END IF;

            -- 7. created_at
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'products' AND column_name = 'created_at'
            ) THEN
                ALTER TABLE products ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT now();
            END IF;

            -- 8. updated_at
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'products' AND column_name = 'updated_at'
            ) THEN
                ALTER TABLE products ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Non-destructive downgrade: remove columns if needed
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'updated_at') THEN
                ALTER TABLE products DROP COLUMN updated_at;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'created_at') THEN
                ALTER TABLE products DROP COLUMN created_at;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'status') THEN
                ALTER TABLE products DROP COLUMN status;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'business_model') THEN
                ALTER TABLE products DROP COLUMN business_model;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'target_audience') THEN
                ALTER TABLE products DROP COLUMN target_audience;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'features') THEN
                ALTER TABLE products DROP COLUMN features;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'category') THEN
                ALTER TABLE products DROP COLUMN category;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'products' AND column_name = 'tagline') THEN
                ALTER TABLE products DROP COLUMN tagline;
            END IF;
        END $$;
        """
    )

