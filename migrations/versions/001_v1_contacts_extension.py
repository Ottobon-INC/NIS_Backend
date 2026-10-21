"""extend contacts for v1 - bhanu connections, card review, route

Revision ID: 001_v1_contacts_extension
Revises: 
Create Date: 2026-10-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001_v1_contacts_extension'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('contact_type', sa.String(), nullable=False, server_default='TARGET'))
    op.add_column('contacts', sa.Column('company_website', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('card_status', sa.String(), nullable=True, server_default='PROCESSING'))
    op.add_column('contacts', sa.Column('admin_notes', sa.Text(), nullable=True))
    op.add_column('contacts', sa.Column('reviewed_by', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('founder_reviewed', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('contacts', sa.Column('founder_notes', sa.Text(), nullable=True))
    op.add_column('contacts', sa.Column('founder_reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('contacts', sa.Column('best_route', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('contacts', sa.Column('relationship_strength', sa.Integer(), nullable=True))
    op.add_column('contacts', sa.Column('reachability', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('best_channel', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('relationship_notes', sa.Text(), nullable=True))
    op.add_column('contacts', sa.Column('connected_since', sa.Date(), nullable=True))
    op.add_column('contacts', sa.Column('is_scored', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('contacts', sa.Column('import_batch_id', sa.String(), nullable=True))
    op.create_index('ix_contacts_contact_type', 'contacts', ['contact_type'])
    op.create_index('ix_contacts_card_status', 'contacts', ['card_status'])
    op.create_index('ix_contacts_is_scored', 'contacts', ['is_scored'])
    op.create_index('ix_contacts_import_batch_id', 'contacts', ['import_batch_id'])


def downgrade() -> None:
    op.drop_index('ix_contacts_import_batch_id', table_name='contacts')
    op.drop_index('ix_contacts_is_scored', table_name='contacts')
    op.drop_index('ix_contacts_card_status', table_name='contacts')
    op.drop_index('ix_contacts_contact_type', table_name='contacts')
    cols = [
        'import_batch_id', 'is_scored', 'connected_since', 'relationship_notes',
        'best_channel', 'reachability', 'relationship_strength', 'best_route',
        'founder_reviewed_at', 'founder_notes', 'founder_reviewed', 'reviewed_by',
        'admin_notes', 'card_status', 'company_website', 'contact_type'
    ]
    for col in cols:
        op.drop_column('contacts', col)
