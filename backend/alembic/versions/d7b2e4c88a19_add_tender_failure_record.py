"""Add the tender failure record (failed_stage, error_detail, failed_at).

Backs the Processing page's error log. `progress_message` already holds the
failure sentence, but every stage overwrites it, so it cannot say which stage
died and it does not survive a retry as a record of the previous attempt.

Nullable with no default and no backfill: a tender that failed before this
migration has no stage or detail recorded, and the log renders that honestly as
"no detail recorded" rather than inventing one. New failures fill all three.

Revision ID: d7b2e4c88a19
Revises: c3f8a1d95b74
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7b2e4c88a19"
down_revision: Union[str, None] = "c3f8a1d95b74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenders", sa.Column("failed_stage", sa.String(length=50), nullable=True))
    op.add_column("tenders", sa.Column("error_detail", sa.Text(), nullable=True))
    op.add_column(
        "tenders",
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenders", "failed_at")
    op.drop_column("tenders", "error_detail")
    op.drop_column("tenders", "failed_stage")
