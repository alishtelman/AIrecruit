"""features 7 8 9 10: anti-cheat, salary, hire outcomes, replay

Revision ID: g2h3i4j5k6l7
Revises: bc183245d27d
Create Date: 2026-03-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'g2h3i4j5k6l7'
down_revision = 'bc183245d27d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Feature 7: behavioral signals on interviews
    op.add_column('interviews',
        sa.Column('behavioral_signals', postgresql.JSON(astext_type=sa.Text()), nullable=True))

    # Feature 7: cheat risk on assessment_reports
    op.add_column('assessment_reports',
        sa.Column('cheat_risk_score', sa.Float(), nullable=True))
    op.add_column('assessment_reports',
        sa.Column('cheat_flags', postgresql.JSON(astext_type=sa.Text()), nullable=True))

    # Feature 8: salary on candidates
    op.add_column('candidates',
        sa.Column('salary_min', sa.Integer(), nullable=True))
    op.add_column('candidates',
        sa.Column('salary_max', sa.Integer(), nullable=True))
    op.add_column('candidates',
        sa.Column('salary_currency', sa.String(length=10), server_default='USD', nullable=False))

    # Feature 9: hire_outcomes table
    op.create_table('hire_outcomes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('candidate_id', sa.UUID(), nullable=False),
        sa.Column('interview_id', sa.UUID(), nullable=True),
        sa.Column('outcome', sa.String(length=50), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['interview_id'], ['interviews.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'candidate_id', name='uq_hire_outcome_company_candidate'),
    )


def downgrade() -> None:
    op.drop_table('hire_outcomes')
    op.drop_column('candidates', 'salary_currency')
    op.drop_column('candidates', 'salary_max')
    op.drop_column('candidates', 'salary_min')
    op.drop_column('assessment_reports', 'cheat_flags')
    op.drop_column('assessment_reports', 'cheat_risk_score')
    op.drop_column('interviews', 'behavioral_signals')
