"""add_interview_templates

Revision ID: 7abdc0ccb307
Revises: 001
Create Date: 2026-03-15 20:55:20.003250

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '7abdc0ccb307'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('interview_templates',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('target_role', sa.String(length=100), nullable=False),
    sa.Column('questions', postgresql.JSON(astext_type=sa.Text()), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('interviews', sa.Column('template_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_interviews_template_id', 'interviews', 'interview_templates',
        ['template_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_interviews_template_id', 'interviews', type_='foreignkey')
    op.drop_column('interviews', 'template_id')
    op.drop_table('interview_templates')
