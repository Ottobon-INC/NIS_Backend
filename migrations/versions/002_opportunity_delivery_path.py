"""add delivery_path and selected_solution_id to opportunities

Revision ID: 002_opportunity_delivery_path
Revises: 001_v1_contacts_extension
Create Date: 2026-10-21

"""
from alembic import op
import sqlalchemy as sa

revision = '002_opportunity_delivery_path'
down_revision = '001_v1_contacts_extension'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('opportunities', sa.Column('delivery_path', sa.String(), nullable=True))
    op.add_column('opportunities', sa.Column('selected_solution_id', sa.String(), nullable=True))
    op.create_index('ix_opportunities_delivery_path', 'opportunities', ['delivery_path'])


def downgrade() -> None:
    op.drop_index('ix_opportunities_delivery_path', table_name='opportunities')
    op.drop_column('opportunities', 'selected_solution_id')
    op.drop_column('opportunities', 'delivery_path')
