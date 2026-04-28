"""add llm runtime platform settings

Revision ID: w2x3y4z5a6b7
Revises: v7w8x9y0z1a2
Create Date: 2026-04-27 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "w2x3y4z5a6b7"
down_revision = "v7w8x9y0z1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_settings", sa.Column("llm_provider", sa.String(length=32), nullable=True))
    op.add_column("platform_settings", sa.Column("interviewer_model", sa.String(length=160), nullable=True))
    op.add_column("platform_settings", sa.Column("assessor_model", sa.String(length=160), nullable=True))
    op.add_column("platform_settings", sa.Column("interviewer_prompt_override", sa.Text(), nullable=True))
    op.add_column("platform_settings", sa.Column("assessor_prompt_override", sa.Text(), nullable=True))
    op.add_column("platform_settings", sa.Column("llm_timeout_seconds", sa.Integer(), nullable=True))
    op.add_column("platform_settings", sa.Column("llm_max_retries", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE platform_settings
        SET
            llm_provider = COALESCE(llm_provider, 'groq'),
            interviewer_model = COALESCE(interviewer_model, interviewer_model_preference, 'llama-3.3-70b-versatile'),
            assessor_model = COALESCE(assessor_model, assessor_model_preference, 'llama-3.3-70b-versatile'),
            llm_timeout_seconds = COALESCE(llm_timeout_seconds, 30),
            llm_max_retries = COALESCE(llm_max_retries, 1)
        WHERE id = 1
        """
    )


def downgrade() -> None:
    op.drop_column("platform_settings", "llm_max_retries")
    op.drop_column("platform_settings", "llm_timeout_seconds")
    op.drop_column("platform_settings", "assessor_prompt_override")
    op.drop_column("platform_settings", "interviewer_prompt_override")
    op.drop_column("platform_settings", "assessor_model")
    op.drop_column("platform_settings", "interviewer_model")
    op.drop_column("platform_settings", "llm_provider")
