"""Add tenders.support_requested_at (the support-handoff timestamp).

Set when a user pressed "Contact technical support" on a failed tender and the
error was emailed to the support team. Its presence flips the error log entry
from the technical error + Retry to the calm "reported, please wait" message a
non-technical user should see. Cleared again on reprocess.

Nullable, no default: a tender that never had support requested has NULL here,
which is exactly "no request made".

Revision ID: a2e9f4c11d63
Revises: f1a6c07d3e58
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2e9f4c11d63"
down_revision: Union[str, None] = "f1a6c07d3e58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenders",
        sa.Column("support_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenders", "support_requested_at")
