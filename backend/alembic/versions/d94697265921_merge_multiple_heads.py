"""Merge multiple heads

Revision ID: d94697265921
Revises: w1x2y3z4a5b6, x3y4z5a6b7c8
Create Date: 2026-05-17 14:33:59.770552

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd94697265921'
down_revision = ('w1x2y3z4a5b6', 'x3y4z5a6b7c8')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
