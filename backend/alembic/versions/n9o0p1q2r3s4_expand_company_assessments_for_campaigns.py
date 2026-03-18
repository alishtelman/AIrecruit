"""expand company assessments for campaigns

Revision ID: n9o0p1q2r3s4
Revises: h8i9j0k1l2m3
Create Date: 2026-03-18 19:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "n9o0p1q2r3s4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_assessments",
        sa.Column("assessment_type", sa.String(length=50), nullable=False, server_default="employee_internal"),
    )
    op.add_column(
        "company_assessments",
        sa.Column("template_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "company_assessments",
        sa.Column("deadline_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "company_assessments",
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "company_assessments",
        sa.Column("opened_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "company_assessments",
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "company_assessments",
        sa.Column("branding_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "company_assessments",
        sa.Column("branding_logo_url", sa.String(length=500), nullable=True),
    )
    op.create_foreign_key(
        "fk_company_assessments_template_id",
        "company_assessments",
        "interview_templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_company_assessments_template_id", "company_assessments", type_="foreignkey")
    op.drop_column("company_assessments", "branding_logo_url")
    op.drop_column("company_assessments", "branding_name")
    op.drop_column("company_assessments", "completed_at")
    op.drop_column("company_assessments", "opened_at")
    op.drop_column("company_assessments", "expires_at")
    op.drop_column("company_assessments", "deadline_at")
    op.drop_column("company_assessments", "template_id")
    op.drop_column("company_assessments", "assessment_type")
