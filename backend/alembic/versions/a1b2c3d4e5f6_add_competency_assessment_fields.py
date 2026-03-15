"""add competency assessment fields

Revision ID: a1b2c3d4e5f6
Revises: 7abdc0ccb307
Create Date: 2026-03-16 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '7abdc0ccb307'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New columns on assessment_reports
    op.add_column('assessment_reports', sa.Column('problem_solving_score', sa.Float(), nullable=True))
    op.add_column('assessment_reports', sa.Column('competency_scores', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('assessment_reports', sa.Column('per_question_analysis', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('assessment_reports', sa.Column('skill_tags', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('assessment_reports', sa.Column('red_flags', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('assessment_reports', sa.Column('response_consistency', sa.Float(), nullable=True))

    # New candidate_skills table
    op.create_table('candidate_skills',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('candidate_id', sa.UUID(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.Column('skill_name', sa.String(length=200), nullable=False),
        sa.Column('proficiency', sa.String(length=50), nullable=False),
        sa.Column('evidence_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['report_id'], ['assessment_reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('candidate_skills')
    op.drop_column('assessment_reports', 'response_consistency')
    op.drop_column('assessment_reports', 'red_flags')
    op.drop_column('assessment_reports', 'skill_tags')
    op.drop_column('assessment_reports', 'per_question_analysis')
    op.drop_column('assessment_reports', 'competency_scores')
    op.drop_column('assessment_reports', 'problem_solving_score')
