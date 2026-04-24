"""add platform settings

Revision ID: u1v2w3x4y5z6
Revises: d1e2f3a4b5c6
Create Date: 2026-04-15 13:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "u1v2w3x4y5z6"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_registration_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("company_registration_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("employee_invites_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("maintenance_mode_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("proctoring_policy_mode", sa.String(length=64), nullable=True),
        sa.Column("interviewer_model_preference", sa.String(length=120), nullable=True),
        sa.Column("assessor_model_preference", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        """
        INSERT INTO platform_settings (
            id,
            candidate_registration_enabled,
            company_registration_enabled,
            employee_invites_enabled,
            maintenance_mode_enabled,
            proctoring_policy_mode,
            interviewer_model_preference,
            assessor_model_preference,
            created_at,
            updated_at
        )
        VALUES (
            1, true, true, true, false, 'observe_only', NULL, NULL, NOW(), NOW()
        )
        """
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
