"""Baseline schema for JobMatch Agent."""

from typing import Sequence, Union

from alembic import op

revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_match_results_job_id ON match_results (job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_resume_versions_job_id ON resume_versions (job_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_match_results_job_id")
    op.execute("DROP INDEX IF EXISTS ix_resume_versions_job_id")
