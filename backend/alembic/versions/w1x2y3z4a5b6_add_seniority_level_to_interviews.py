"""add_seniority_level_to_interviews

Revision ID: w1x2y3z4a5b6
Revises: v7w8x9y0z1a2
Create Date: 2026-04-27 12:05:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "w1x2y3z4a5b6"
down_revision = "v7w8x9y0z1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interviews", sa.Column("seniority_level", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("interviews", "seniority_level")
