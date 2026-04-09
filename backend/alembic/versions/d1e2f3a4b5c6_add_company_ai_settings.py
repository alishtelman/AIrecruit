"""add company ai settings

Revision ID: d1e2f3a4b5c6
Revises: 5f6a7b8c9d0e
Create Date: 2026-04-09 18:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "5f6a7b8c9d0e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("ai_settings", postgresql.JSON(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "ai_settings")
