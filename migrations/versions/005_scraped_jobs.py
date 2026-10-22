"""create scraped_jobs table for job scraping pipeline

Revision ID: 005_scraped_jobs
Revises: 004_meeting_intelligence
Create Date: 2026-10-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '005_scraped_jobs'
down_revision = '004_meeting_intelligence'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create scraped_jobs table
    op.create_table(
        'scraped_jobs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('organization_id', sa.String(), nullable=False, server_default='org-1'),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('opportunity_id', sa.String(), sa.ForeignKey('opportunities.id', ondelete='SET NULL'), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('cross_source_hash', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('company_name', sa.String(), nullable=False),
        sa.Column('normalized_company', sa.String(), nullable=False),
        sa.Column('normalized_title', sa.String(), nullable=False),
        sa.Column('apply_url', sa.String(), nullable=False),
        sa.Column('canonical_apply_url', sa.String(), nullable=False),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('salary', sa.String(), nullable=True),
        sa.Column('description_raw', sa.Text(), nullable=True),
        sa.Column('description_clean', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='ACTIVE'),
        sa.Column('consecutive_missing_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_scraped_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('raw_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('source', 'external_id', name='uq_scraped_jobs_source_external_id')
    )

    # 2. Create indexes for performance and deduplication
    op.create_index('ix_scraped_jobs_id', 'scraped_jobs', ['id'])
    op.create_index('ix_scraped_jobs_organization_id', 'scraped_jobs', ['organization_id'])
    op.create_index('ix_scraped_jobs_opportunity_id', 'scraped_jobs', ['opportunity_id'])
    op.create_index('ix_scraped_jobs_content_hash', 'scraped_jobs', ['content_hash'])
    op.create_index('ix_scraped_jobs_cross_source_hash', 'scraped_jobs', ['cross_source_hash'])
    op.create_index('ix_scraped_jobs_canonical_apply_url', 'scraped_jobs', ['canonical_apply_url'])
    op.create_index('ix_scraped_jobs_status', 'scraped_jobs', ['status'])
    op.create_index('ix_scraped_jobs_last_scraped_at', 'scraped_jobs', ['last_scraped_at'])


def downgrade() -> None:
    op.drop_index('ix_scraped_jobs_last_scraped_at', table_name='scraped_jobs')
    op.drop_index('ix_scraped_jobs_status', table_name='scraped_jobs')
    op.drop_index('ix_scraped_jobs_canonical_apply_url', table_name='scraped_jobs')
    op.drop_index('ix_scraped_jobs_cross_source_hash', table_name='scraped_jobs')
    op.drop_index('ix_scraped_jobs_content_hash', table_name='scraped_jobs')
    op.drop_index('ix_scraped_jobs_opportunity_id', table_name='scraped_jobs')
    op.drop_index('ix_scraped_jobs_organization_id', table_name='scraped_jobs')
    op.drop_index('ix_scraped_jobs_id', table_name='scraped_jobs')
    op.drop_table('scraped_jobs')
