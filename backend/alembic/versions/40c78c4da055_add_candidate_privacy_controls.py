"""add candidate privacy controls

Revision ID: 40c78c4da055
Revises: t4u5v6w7x8y9
Create Date: 2026-03-18 13:54:13.565691

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '40c78c4da055'
down_revision = 't4u5v6w7x8y9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('candidates', sa.Column('profile_visibility', sa.String(length=32), server_default='marketplace', nullable=False))
    op.add_column('candidates', sa.Column('public_share_token', sa.String(length=128), nullable=True))
    op.create_unique_constraint('uq_candidates_public_share_token', 'candidates', ['public_share_token'])


def downgrade() -> None:
    op.drop_constraint('uq_candidates_public_share_token', 'candidates', type_='unique')
    op.drop_column('candidates', 'public_share_token')
    op.drop_column('candidates', 'profile_visibility')
