"""add module plan to company assessments

Revision ID: 5f6a7b8c9d0e
Revises: f1936ae5a32d
Create Date: 2026-04-08 18:10:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "5f6a7b8c9d0e"
down_revision = "f1936ae5a32d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_assessments",
        sa.Column("module_plan", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "company_assessments",
        sa.Column("current_module_index", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("company_assessments", "current_module_index")
    op.drop_column("company_assessments", "module_plan")
