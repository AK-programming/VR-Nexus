"""widen requirement responsibility-matrix columns to text

Revision ID: f4b8e21a7c36
Revises: e2a7c4f18b95
Create Date: 2026-09-15 00:00:00.000000

Fixes a real production failure: requirements.responsibility was
VARCHAR(500), and a tender whose responsibility-matrix text ran past 500
characters for one requirement failed the whole batch INSERT for that
tender's chunk with psycopg.errors.StringDataRightTruncation - the tender
died at the "extracting" stage with nothing saved, not because the document
was unreadable but because one column was too narrow for a legitimate,
verbatim-copied value.

Widens all five responsibility-matrix columns (responsibility, dpl, prime,
the_t, joint_responsibility) to unbounded TEXT, matching `description` and
`evidence_description` on the same table, which were already TEXT and never
hit this. Postgres's ALTER COLUMN ... TYPE text is a fast, in-place
metadata-only change for VARCHAR -> TEXT (no table rewrite, no data loss -
existing values are valid TEXT as-is).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f4b8e21a7c36'
down_revision: Union[str, None] = 'e2a7c4f18b95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WIDENED_COLUMNS = ["responsibility", "dpl", "prime", "the_t", "joint_responsibility"]


def upgrade() -> None:
    for column_name in _WIDENED_COLUMNS:
        op.alter_column(
            "requirements",
            column_name,
            existing_type=sa.String(500 if column_name == "responsibility" else 255),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Reverting TEXT -> VARCHAR(n) is a real truncation risk if any row grew
    # past the old limit while this was TEXT (exactly the scenario this
    # migration exists to prevent) - Postgres will refuse the ALTER outright
    # if any existing value no longer fits, which is the right failure mode
    # for a downgrade rather than silently truncating production data.
    op.alter_column(
        "requirements", "responsibility",
        existing_type=sa.Text(), type_=sa.String(500), existing_nullable=True,
    )
    for column_name in ["dpl", "prime", "the_t", "joint_responsibility"]:
        op.alter_column(
            "requirements", column_name,
            existing_type=sa.Text(), type_=sa.String(255), existing_nullable=True,
        )
