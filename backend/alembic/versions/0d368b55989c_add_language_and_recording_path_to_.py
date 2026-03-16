"""add language and recording_path to interviews

Revision ID: 0d368b55989c
Revises: a1b2c3d4e5f6
Create Date: 2026-03-16 16:41:37.103847

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0d368b55989c'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('interviews', sa.Column('language', sa.String(length=10), server_default='ru', nullable=False))
    op.add_column('interviews', sa.Column('recording_path', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('interviews', 'recording_path')
    op.drop_column('interviews', 'language')
