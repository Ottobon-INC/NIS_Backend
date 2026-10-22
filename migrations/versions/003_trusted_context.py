"""create trusted_contexts table

Revision ID: 003_trusted_context
Revises: 002_opportunity_delivery_path
Create Date: 2026-10-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003_trusted_context'
down_revision = '002_opportunity_delivery_path'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'trusted_contexts',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('organization_id', sa.String(), nullable=False, server_default='ottobon'),
        sa.Column('contact_id', sa.String(), sa.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(), nullable=False, server_default='PROBLEM'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('evidence_id', sa.String(), nullable=True),
        sa.Column('source_meeting_id', sa.String(), nullable=True),
        sa.Column('current_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('history', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('is_confirmed', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('confirmed_by', sa.String(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('confidence', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_trusted_contexts_id', 'trusted_contexts', ['id'])
    op.create_index('ix_trusted_contexts_organization_id', 'trusted_contexts', ['organization_id'])
    op.create_index('ix_trusted_contexts_contact_id', 'trusted_contexts', ['contact_id'])
    op.create_index('ix_trusted_contexts_type', 'trusted_contexts', ['type'])


def downgrade() -> None:
    op.drop_index('ix_trusted_contexts_type', table_name='trusted_contexts')
    op.drop_index('ix_trusted_contexts_contact_id', table_name='trusted_contexts')
    op.drop_index('ix_trusted_contexts_organization_id', table_name='trusted_contexts')
    op.drop_index('ix_trusted_contexts_id', table_name='trusted_contexts')
    op.drop_table('trusted_contexts')
