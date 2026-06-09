"""migrate_platform_settings_to_openai

Revision ID: 4619989a2198
Revises: d94697265921
Create Date: 2026-06-02 17:01:29.850409

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4619989a2198'
down_revision = 'd94697265921'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE platform_settings
        SET
            llm_provider = 'openai',
            interviewer_model = 'gpt-5.4-mini',
            interviewer_model_preference = 'gpt-5.4-mini',
            assessor_model = 'gpt-5.4-mini',
            assessor_model_preference = 'gpt-5.4-mini'
        WHERE llm_provider IS NULL OR llm_provider != 'openai'
        """
    )


def downgrade() -> None:
    pass
