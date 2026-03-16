"""deduplicate templates and add unique constraint on company_id+name

Revision ID: f1e2d3c4b5a6
Revises: 0d368b55989c
Create Date: 2026-03-16 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "f1e2d3c4b5a6"
down_revision = "0d368b55989c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete duplicate templates, keeping only the oldest (first created) per (company_id, name)
    op.execute("""
        DELETE FROM interview_templates
        WHERE id NOT IN (
            SELECT DISTINCT ON (company_id, name) id
            FROM interview_templates
            ORDER BY company_id, name, created_at ASC
        )
    """)

    op.create_unique_constraint(
        "uq_template_company_name",
        "interview_templates",
        ["company_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_template_company_name", "interview_templates", type_="unique")
