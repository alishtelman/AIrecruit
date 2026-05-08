"""add marketplace search indexes

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-05-08 16:00:00.000000
"""

from alembic import op


revision = "x3y4z5a6b7c8"
down_revision = "w2x3y4z5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_assessment_reports_candidate_created_id_desc
        ON assessment_reports (candidate_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_interviews_marketplace_snapshot
        ON interviews (company_assessment_id, target_role, completed_at DESC, candidate_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_candidates_profile_visibility_id
        ON candidates (profile_visibility, id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_candidate_skills_candidate_created
        ON candidate_skills (candidate_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_company_shortlists_company_id
        ON company_shortlists (company_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_company_shortlist_candidates_candidate_id
        ON company_shortlist_candidates (candidate_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_company_shortlist_candidates_candidate_id")
    op.execute("DROP INDEX IF EXISTS ix_company_shortlists_company_id")
    op.execute("DROP INDEX IF EXISTS ix_candidate_skills_candidate_created")
    op.execute("DROP INDEX IF EXISTS ix_candidates_profile_visibility_id")
    op.execute("DROP INDEX IF EXISTS ix_interviews_marketplace_snapshot")
    op.execute("DROP INDEX IF EXISTS ix_assessment_reports_candidate_created_id_desc")
