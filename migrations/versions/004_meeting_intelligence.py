"""create meetings and meeting_findings tables

Revision ID: 004_meeting_intelligence
Revises: 003_trusted_context
Create Date: 2026-10-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '004_meeting_intelligence'
down_revision = '003_trusted_context'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create meetings table
    op.create_table(
        'meetings',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('organization_id', sa.String(), nullable=False, server_default='ottobon'),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('contact_id', sa.String(), sa.ForeignKey('contacts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('meeting_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='SCHEDULED'),
        sa.Column('raw_transcript', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('objectives', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('suggested_topics', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('recent_signals', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('relationship_context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('extracted_needs', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('action_items', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_meetings_id', 'meetings', ['id'])
    op.create_index('ix_meetings_organization_id', 'meetings', ['organization_id'])
    op.create_index('ix_meetings_contact_id', 'meetings', ['contact_id'])
    op.create_index('ix_meetings_status', 'meetings', ['status'])

    # 2. Create meeting_findings table
    op.create_table(
        'meeting_findings',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('organization_id', sa.String(), nullable=False, server_default='ottobon'),
        sa.Column('meeting_id', sa.String(), sa.ForeignKey('meetings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('contact_id', sa.String(), sa.ForeignKey('contacts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('finding_type', sa.String(), nullable=False, server_default='PROBLEM'),
        sa.Column('claim', sa.Text(), nullable=False),
        sa.Column('evidence_quote', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Integer(), nullable=False, server_default='80'),
        sa.Column('status', sa.String(), nullable=False, server_default='AWAITING_VALIDATION'),
        sa.Column('validated_by', sa.String(), nullable=True),
        sa.Column('validated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('opportunity_id', sa.String(), sa.ForeignKey('opportunities.id', ondelete='SET NULL'), nullable=True),
        sa.Column('trusted_context_id', sa.String(), sa.ForeignKey('trusted_contexts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_meeting_findings_id', 'meeting_findings', ['id'])
    op.create_index('ix_meeting_findings_organization_id', 'meeting_findings', ['organization_id'])
    op.create_index('ix_meeting_findings_meeting_id', 'meeting_findings', ['meeting_id'])
    op.create_index('ix_meeting_findings_contact_id', 'meeting_findings', ['contact_id'])
    op.create_index('ix_meeting_findings_finding_type', 'meeting_findings', ['finding_type'])
    op.create_index('ix_meeting_findings_status', 'meeting_findings', ['status'])
    op.create_index('ix_meeting_findings_opportunity_id', 'meeting_findings', ['opportunity_id'])
    op.create_index('ix_meeting_findings_trusted_context_id', 'meeting_findings', ['trusted_context_id'])


def downgrade() -> None:
    op.drop_index('ix_meeting_findings_trusted_context_id', table_name='meeting_findings')
    op.drop_index('ix_meeting_findings_opportunity_id', table_name='meeting_findings')
    op.drop_index('ix_meeting_findings_status', table_name='meeting_findings')
    op.drop_index('ix_meeting_findings_finding_type', table_name='meeting_findings')
    op.drop_index('ix_meeting_findings_contact_id', table_name='meeting_findings')
    op.drop_index('ix_meeting_findings_meeting_id', table_name='meeting_findings')
    op.drop_index('ix_meeting_findings_organization_id', table_name='meeting_findings')
    op.drop_index('ix_meeting_findings_id', table_name='meeting_findings')
    op.drop_table('meeting_findings')

    op.drop_index('ix_meetings_status', table_name='meetings')
    op.drop_index('ix_meetings_contact_id', table_name='meetings')
    op.drop_index('ix_meetings_organization_id', table_name='meetings')
    op.drop_index('ix_meetings_id', table_name='meetings')
    op.drop_table('meetings')
